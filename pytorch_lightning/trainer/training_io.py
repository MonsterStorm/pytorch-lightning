import logging as log
import os
import re
import signal
import warnings
from abc import ABC
from subprocess import call
from typing import Union
from copy import deepcopy

import torch
import torch.distributed as dist

from pytorch_lightning.core.lightning import LightningModule
from pytorch_lightning.loggers import LightningLoggerBase
from pytorch_lightning.overrides.data_parallel import (
    LightningDistributedDataParallel,
    LightningDataParallel,
)

try:
    import torch_xla
    import torch_xla.core.xla_model as xm
    import torch_xla.distributed.xla_multiprocessing as xmp
except ImportError:
    XLA_AVAILABLE = False
else:
    XLA_AVAILABLE = True


class TrainerIOMixin(ABC):

    # this is just a summary on variables used in this abstract class,
    #  the proper values/initialisation should be done in child class
    model: LightningModule
    on_gpu: bool
    root_gpu: ...
    resume_from_checkpoint: ...
    use_ddp: bool
    use_ddp2: bool
    checkpoint_callback: ...
    proc_rank: int
    weights_save_path: str
    logger: Union[LightningLoggerBase, bool]
    early_stop_callback: ...
    lr_schedulers: ...
    optimizers: ...
    on_tpu: bool
    num_training_batches: int
    accumulate_grad_batches: int

    def get_model(self):
        is_dp_module = isinstance(self.model, (LightningDistributedDataParallel,
                                               LightningDataParallel))
        model = self.model.module if is_dp_module else self.model
        return model

    # --------------------
    # CHECK-POINTING
    # --------------------
    def restore_weights(self, model):
        """
        We attempt to restore weights in this order:
        1. HPC weights.
        2. if no HPC weights restore checkpoint_path weights
        3. otherwise don't restore weights

        :param model:
        :return:
        """
        # clear cache before restore
        if self.on_gpu:
            torch.cuda.empty_cache()

        # if script called from hpc resubmit, load weights
        did_restore_hpc_weights = self.restore_hpc_weights_if_needed(model)

        # clear cache after restore
        if self.on_gpu:
            torch.cuda.empty_cache()

        if not did_restore_hpc_weights:
            if self.resume_from_checkpoint is not None:
                self.restore(self.resume_from_checkpoint, on_gpu=self.on_gpu)

        # wait for all models to restore weights
        if self.use_ddp or self.use_ddp2:
            # wait for all processes to catch up
            dist.barrier()

        # wait for all models to restore weights
        if self.on_tpu and XLA_AVAILABLE:
            # wait for all processes to catch up
            torch_xla.core.xla_model.rendezvous("pl.TrainerIOMixin.restore_weights")

        # clear cache after restore
        if self.on_gpu:
            torch.cuda.empty_cache()

    # --------------------
    # HPC SIGNAL HANDLING
    # --------------------
    def register_slurm_signal_handlers(self):
        # see if we're using slurm (not interactive)
        on_slurm = False
        try:
            job_name = os.environ['SLURM_JOB_NAME']
            if job_name != 'bash':
                on_slurm = True
        except Exception as e:
            pass

        if on_slurm:
            log.info('Set SLURM handle signals.')
            signal.signal(signal.SIGUSR1, self.sig_handler)
            signal.signal(signal.SIGTERM, self.term_handler)

    def sig_handler(self, signum, frame):
        if self.proc_rank == 0:
            # save weights
            log.info('handling SIGUSR1')
            self.hpc_save(self.weights_save_path, self.logger)

            # find job id
            job_id = os.environ['SLURM_JOB_ID']
            cmd = 'scontrol requeue {}'.format(job_id)

            # requeue job
            log.info(f'requeing job {job_id}...')
            result = call(cmd, shell=True)

            # print result text
            if result == 0:
                log.info(f'requeued exp {job_id}')
            else:
                log.info('requeue failed...')

            # close experiment to avoid issues
            self.logger.close()

    def term_handler(self, signum, frame):
        # save
        log.info("bypassing sigterm")

    # --------------------
    # MODEL SAVE CHECKPOINT
    # --------------------
    def _atomic_save(self, checkpoint, filepath):
        """Saves a checkpoint atomically, avoiding the creation of incomplete checkpoints.

        This will create a temporary checkpoint with a suffix of ``.part``, then copy it to the final location once
        saving is finished.

        Args:
            checkpoint (object): The object to save.
                Built to be used with the ``dump_checkpoint`` method, but can deal with anything which ``torch.save``
                accepts.
            filepath (str|pathlib.Path): The path to which the checkpoint will be saved.
                This points to the file that the checkpoint will be stored in.
        """
        tmp_path = str(filepath) + ".part"
        torch.save(checkpoint, tmp_path)
        os.replace(tmp_path, filepath)

    def save_checkpoint(self, filepath):
        checkpoint = self.dump_checkpoint()

        # do the actual save
        try:
            self._atomic_save(checkpoint, filepath)
        except AttributeError:
            if 'hparams' in checkpoint:
                del checkpoint['hparams']

            self._atomic_save(checkpoint, filepath)

    def restore(self, checkpoint_path, on_gpu):
        """
        Restore training state from checkpoint.
        Also restores all training state like:
        - epoch
        - callbacks
        - schedulers
        - optimizer
        :param checkpoint_path:
        :param on_gpu:

        :return:
        """

        # if on_gpu:
        #     checkpoint = torch.load(checkpoint_path)
        # else:
        # load on CPU first
        checkpoint = torch.load(checkpoint_path, map_location=lambda storage, loc: storage)

        # load model state
        model = self.get_model()

        # load the state_dict on the model automatically
        model.load_state_dict(checkpoint['state_dict'])
        if on_gpu:
            model.cuda(self.root_gpu)

        # load training state (affects trainer only)
        self.restore_training_state(checkpoint)

    def dump_checkpoint(self):
        checkpoint = {
            'epoch': self.current_epoch + 1,
            'global_step': self.global_step + 1,
        }

        if self.checkpoint_callback is not None and self.checkpoint_callback is not False:
            checkpoint['checkpoint_callback_best'] = self.checkpoint_callback.best

        if self.early_stop_callback is not None and self.checkpoint_callback is not False:
            checkpoint['early_stop_callback_wait'] = self.early_stop_callback.wait
            checkpoint['early_stop_callback_patience'] = self.early_stop_callback.patience

        # save optimizers
        optimizer_states = []
        for i, optimizer in enumerate(self.optimizers):
            optimizer_states.append(optimizer.state_dict())

        checkpoint['optimizer_states'] = optimizer_states

        # save lr schedulers
        lr_schedulers = []
        for i, scheduler in enumerate(self.lr_schedulers):
            lr_schedulers.append(scheduler.state_dict())

        checkpoint['lr_schedulers'] = lr_schedulers

        # add the hparams and state_dict from the model
        model = self.get_model()

        checkpoint['state_dict'] = model.state_dict()

        if hasattr(model, "hparams"):
            checkpoint['hparams'] = vars(model.hparams)
        else:
            warnings.warn(
                "Did not find hyperparameters at model.hparams. Saving checkpoint without"
                " hyperparameters"
            )

        # give the model a chance to add a few things
        model.on_save_checkpoint(checkpoint)

        return checkpoint

    # --------------------
    # HPC IO
    # --------------------
    def restore_hpc_weights_if_needed(self, model):
        """
        If there is a set of hpc weights, use as signal to restore model
        :param model:
        :return:
        """
        did_restore = False

        # look for hpc weights
        folderpath = self.weights_save_path
        if os.path.exists(folderpath):
            files = os.listdir(folderpath)
            hpc_weight_paths = [x for x in files if 'hpc_ckpt' in x]

            # if hpc weights exist restore model
            if len(hpc_weight_paths) > 0:
                self.hpc_load(folderpath, self.on_gpu)
                did_restore = True
        return did_restore

    def restore_training_state(self, checkpoint):
        """
        Restore trainer state.
        Model will get its change to update
        :param checkpoint:
        :return:
        """
        if self.checkpoint_callback is not None and self.checkpoint_callback is not False:
            self.checkpoint_callback.best = checkpoint['checkpoint_callback_best']

        if self.early_stop_callback is not None and self.early_stop_callback is not False:
            self.early_stop_callback.wait = checkpoint['early_stop_callback_wait']
            self.early_stop_callback.patience = checkpoint['early_stop_callback_patience']

        self.global_step = checkpoint['global_step']
        self.current_epoch = checkpoint['epoch']

        # Division deals with global step stepping once per accumulated batch
        # Inequality deals with different global step for odd vs even num_training_batches
        n_accum = 1 if self.accumulate_grad_batches is None else self.accumulate_grad_batches
        expected_steps = self.num_training_batches / n_accum
        if self.num_training_batches != 0 and self.global_step % expected_steps > 1:
            warnings.warn(
                "You're resuming from a checkpoint that ended mid-epoch. "
                "This can cause unreliable results if further training is done, "
                "consider using an end of epoch checkpoint. "
            )

        # restore the optimizers
        optimizer_states = checkpoint['optimizer_states']
        for optimizer, opt_state in zip(self.optimizers, optimizer_states):
            optimizer.load_state_dict(opt_state)

            # move optimizer to GPU 1 weight at a time
            # avoids OOM
            if self.root_gpu is not None:
                for state in optimizer.state.values():
                    for k, v in state.items():
                        if isinstance(v, torch.Tensor):
                            state[k] = v.cuda(self.root_gpu)

        # restore the lr schedulers
        lr_schedulers = checkpoint['lr_schedulers']
        for scheduler, lrs_state in zip(self.lr_schedulers, lr_schedulers):
            scheduler.load_state_dict(lrs_state)

    # ----------------------------------
    # PRIVATE OPS
    # ----------------------------------
    def hpc_save(self, folderpath, logger):
        # make sure the checkpoint folder exists
        os.makedirs(folderpath, exist_ok=True)

        # save logger to make sure we get all the metrics
        logger.save()

        ckpt_number = self.max_ckpt_in_folder(folderpath) + 1

        if not os.path.exists(folderpath):
            os.makedirs(folderpath, exist_ok=True)
        filepath = '{}/hpc_ckpt_{}.ckpt'.format(folderpath, ckpt_number)

        # give model a chance to do something on hpc_save
        model = self.get_model()
        checkpoint = self.dump_checkpoint()

        model.on_hpc_save(checkpoint)

        # do the actual save
        # TODO: fix for anything with multiprocess DP, DDP, DDP2
        try:
            self._atomic_save(checkpoint, filepath)
        except AttributeError:
            if 'hparams' in checkpoint:
                del checkpoint['hparams']

            self._atomic_save(checkpoint, filepath)

        return filepath

    def hpc_load(self, folderpath, on_gpu):
        filepath = '{}/hpc_ckpt_{}.ckpt'.format(folderpath, self.max_ckpt_in_folder(folderpath))

        # load on CPU first
        checkpoint = torch.load(filepath, map_location=lambda storage, loc: storage)

        # load model state
        model = self.get_model()

        # load the state_dict on the model automatically
        model.load_state_dict(checkpoint['state_dict'])

        if self.root_gpu is not None:
            model.cuda(self.root_gpu)

        # load training state (affects trainer only)
        self.restore_training_state(checkpoint)

        # call model hook
        model.on_hpc_load(checkpoint)

        log.info(f'restored hpc model from: {filepath}')

    def max_ckpt_in_folder(self, path, name_key='ckpt_'):
        files = os.listdir(path)
        files = [x for x in files if name_key in x]
        if len(files) == 0:
            return 0

        ckpt_vs = []
        for name in files:
            name = name.split(name_key)[-1]
            name = re.sub('[^0-9]', '', name)
            ckpt_vs.append(int(name))

        return max(ckpt_vs)

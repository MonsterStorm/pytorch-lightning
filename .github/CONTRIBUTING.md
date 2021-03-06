# Contributing    
Welcome to the PyTorch Lightning community! We're building the most advanced research platform on the planet to implement the latest, best practices that the amazing PyTorch team rolls out!   

## Main Core Value: One less thing to remember

Simplify the API as much as possible from the user perspective.
 Any additions or improvements should minimize things the user needs to remember.   

For example: One benefit of the validation_step is that the user doesn't have to remember to set the model to .eval().
 This avoids all sorts of subtle errors the user could make.  

## Lightning Design Principles
We encourage all sorts of contributions you're interested in adding! When coding for lightning, please follow these principles.   
 
#### No PyTorch Interference
We don't want to add any abstractions on top of pure PyTorch.
 This gives researchers all the control they need without having to learn yet another framework.    

#### Simple Internal Code
It's useful for users to look at the code and understand very quickly what's happening.
 Many users won't be engineers. Thus we need to value clear, simple code over condensed ninja moves.
 While that's super cool, this isn't the project for that :)      

#### Force User Decisions To Best Practices
There are 1,000 ways to do something. However, something eventually becomes standard practice that everyone does.
 Thus we pick one way of doing it and force everyone to do it this way.
 A good example is accumulated gradients.
 There are many ways to implement, we just pick one and force users to use that one.
 A bad forced decision would be to make users use a specific library to do something.    

When something becomes a best practice, we add it to the framework. This likely looks like code in utils or in the model file that everyone keeps adding over and over again across projects. When this happens, bring that code inside the trainer and add a flag for it.

#### Simple External API
What makes sense to you may not make sense to others. Create an issue with an API change suggestion and validate that it makes sense for others.
 Treat code changes how you treat a startup: validate that it's a needed feature, then add if it makes sense for many people.

#### Backward-compatible API
We all hate updating our deep learning packages because we don't want to refactor a bunch of stuff. In Lightning, we make sure every change we make which could break an API is backwards compatible with good deprecation warnings.

**You shouldn't be afraid to upgrade Lightning :)**

#### Gain User Trust
As a researcher you can't have any part of your code going wrong. So, make thorough tests that ensure an implementation of a new trick or subbtle change is correct.

#### Interoperability
Have a favorite feature from other libraries like fast.ai or transformers? Those should just work with lightning as well. Grab your favorite model or learning rate scheduler from your favorite library and run it in Lightning.

---

## Contribution Types
Currently looking for help implementing new features or adding bug fixes.

A lot of good work has already been done in project mechanics (requirements.txt, setup.py, pep8, badges, ci, etc...) we're in a good state there thanks to all the early contributors (even pre-beta release)!

### Bug Fixes:
1. Submit a github issue - try to decried what happen so other can reproduce it too.
2. Try to ix it or recommend a solution...
3. Submit a PR!


### New Features:
1. Submit a github issue - describe what is motivation of such feature (plus an use-case).
2. Let's discuss to agree on the feature scope.
3. Submit a PR! (with updated docs and tests 🙃).

---

## Guidelines

### Coding Style

1. Use f-strings for output formation (except logging when we stay with lazy `logging.info("Hello %s!`, name).
2. Test the code with flake8, run locally PEP8 fixes:
    ```
    autopep8 -v -r --max-line-length 120 --in-place .
    ```
3. Documentation is using [Napoleon formatting with Google style](https://sphinxcontrib-napoleon.readthedocs.io/en/latest/example_google.html)

### Testing

Test your work locally to speed up your work since so you can focus only in particular (failing) test-cases.
 To setup a local development environment, install both local and test dependecies:
```bash
pip install -r requirements.txt
pip install -r tests/requirements.txt
``` 

You can run the full test-case in your terminal via this bash script: 

```bash
bash .run_local_tests.sh
```

Note: if your computer does not have multi-GPU nor TPU these tests are skipped.

For convenience, you can use also your own CircleCI building which will be triggered with each commit.
This is useful if you do not test against all required dependencies version.
To do so, login to [CircleCI](https://app.circleci.com/) and enable your forked project in the dashboard. It will just work after that.

### Pull Request

We welcome any useful contribution! For convinece here's a recommended workflow:

0. Think about what you want to do - fix a bug, repair docs, etc. 
1. Start your work locally (usually until you need our CI testing)
    - create a branch and prepare your changes
    - hint: do not work with your master directly, it may become complicated when you need to rebase
    - hint: give your PR a good name! it will be useful later when you may work on multiple tasks/PRs
2. Create a "Draft PR" which is clearly marked which lets us know you don't need feedback yet.
3. When you feel like you are ready for integrating your work, turn your PR to "Ready for review".
4. Use tags in PR name for following cases:
    - **[blocked by #<number>]** if you work is depending on others changes
    - **[wip]** when you start to re-edit your work, mark it so no one will accidentally merge it in meantime

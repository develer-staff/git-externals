Usage without options:

  $ git externals
  Usage: git-externals [OPTIONS] COMMAND [ARGS]...
  
    Utility to manage git externals, meant to be used as a drop-in replacement
    to svn externals
  
    This script works by cloning externals found in the `git_externals.json`
    file into `.git/externals` and symlinks them to recreate the wanted
    directory layout.
  
  Options:
    --version                  Show the version and exit.
    --with-color / --no-color  Enable/disable colored output
    -h, --help                 Show this message and exit.
  
  Commands:
    add      Add a git external to the current repo.
    diff     Call git diff on the given externals
    foreach  Evaluates an arbitrary shell command in each...
    freeze   Freeze the externals revision
    info     Print some info about the externals.
    list     Print just a list of all externals used
    remove   Remove the externals at the given repository...
    status   Call git status on the given externals
    update   Update the working copy cloning externals if...
\n+ (re)

[![Build Status](https://travis-ci.org/develersrl/git-externals.svg?branch=master)](https://travis-ci.org/develersrl/git-externals)

Git Externals
-------------

`git-externals` is a command line tool that helps you throw **SVN** away and
migrate to **Git** for projects that make heavy use of *svn:externals*. In some
cases it's just impossible to use *Git submodules* or *subtrees* to emulate *SVN
externals*, because they aren't as flexible as SVN externals. For example **SVN**
lets you handle a *single file dependency* through *SVN external*, whereas **Git**
doesn't.

On Windows this requires **ADMIN PRIVILEGES**, because under the hood it uses
symlinks. For the same reason this script is not meant to be used with the old 
Windows XP.

## How to Install

```sh
$ pip install https://github.com/develersrl/git-externals/archive/master.zip
```

## Usage:

### Content of `git_externals.json`

Once your main project repository is handled by Git, `git-externals` expects to
find a file called `git_externals.json` at the project root. Here is how to fill
it:

Let's take an hypothetical project **A**, under Subversion, having 2
dependencies, **B** and **C**, declared as `svn:externals` as
follows. 

```sh
$ svn propget svn:externals .
^/svn/libraries/B lib/B
^/svn/libraries/C src/C
```

```
A
├── lib
│   └── B
└── src
    └── C
```

Once **A**, **B** and **C** have all been migrated over different Git
repositories, fill `git_externals.json` by running the following commands.
They describe, for each dependency, its remote location, and the destination 
directory, relative to the project root. Check out all the possibilities by 
running `git externals add --help`.

```sh
$ git externals add --branch=master git@github.com:username/libB.git . lib/B
$ git externals add --branch=master git@github.com:username/libC.git . src/C
```

This is now the content of `git_externals.json`:

```json
{
    "git@github.com:username/libB.git": {
        "branch": "master",
        "ref": null,
        "targets": {
            "./": [
                "lib/B"
            ]
        }
    },
    "git@github.com:username/libC.git": {
        "branch": "master",
        "ref": null,
        "targets": {
            "./": [
                "src/C"
            ]
        }
    }
}
```


### Git externals update

If you want to:

- download the externals of a freshly cloned Git repository and creates their 
  symlinks, in order to have the wanted directory layout.
- checkout the latest version of all externals (as defined in
    `git_externals.json` file)

Run:

```sh
$ git externals update
```

### Git externals status

```sh
$ git externals status [--porcelain|--verbose]
$ git externals status [--porcelain|--verbose] [external1 [external2] ...]
```

Shows the working tree status of one, multiple, or all externals:

 - add `--verbose` if you are also interested to see the externals that haven't
   been modified
 - add `--porcelain` if you want the output easily parsable (for non-humans).

```sh
$ git externals status
$ git externals status deploy
$ git externals status deploy qtwidgets
```

### Git externals foreach

```sh
$ git externals foreach [--] cmd [arg1 [arg2] ...]
```

Evaluates an arbitrary shell command in each checked out external.
```sh
$ git externals foreach git fetch
```

**Note**: If some arguments of the shell command starts with `--`, like in 
`git rev-parse --all`, you must pass `--` after `foreach` in order to stop 
git externals argument processing, example:

```sh
$ git externals foreach -- git rev-parse --all
```

### Example usage

```sh
$ git externals add --branch=master https://github.com/username/projectA.git shared/ foo
$ git externals add --branch=master https://github.com/username/projectB.git shared/ bar
$ git externals add --branch=master https://github.com/username/projectC.git README.md baz/README.md
$ git externals add --tag=v4.4 https://github.com/torvalds/linux.git Makefile Makefile
$ git add git_externals.json
$ git commit -m "Let git-externals handle our externals ;-)"
$ git externals update
$ git externals diff
$ git externals info
$ git externals list
$ git externals foreach -- git diff HEAD~1
```

**Note**: Append `/` to the source path if it represents a directory.

### Bash command-line completion

See installation instructions in [gitext.completion.bash](./git_externals/gitext.completion.bash).

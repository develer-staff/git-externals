# Git Externals
Couple of scripts to throw away SVN and migrate to Git. These scripts are particularly
useful when the SVN repos make heavy use of externals. In some cases it's just impossible
to use submodules or subtrees to emulate SVN externals, because they aren't as flexible as
SVN externals. For instance it's impossible to use submodules to include just a single file in an
arbitrary directory.

Basically what you need to do is launch gittify to slowly migrate all the given SVN repos
and related externals and then you can use git-externals to manage them.

On Windows this requires **ADMIN PRIVILEGES**, because under the hood it uses symlinks. Moreover for the same
reason this script is not meant to be used with the old Windows XP.

## How to Install
```bash
$ pip install git+ssh://gitlab.com/develer/svn-migration-tools.git
```

## Gittify
This tool tries to do the best to convert SVN repos to Git repos. Under the hood it uses
`git-svn` to clone repos and does some extra work to handle externals and removed tags and branches.

If (hopefully) doesn't crash, a dump named "git\_externals.json" will be created in every branch
and tag containing various info about the externals.
In case different revisions, branches or tags are used for the same external "mismatched\_externals.json" is
created with a bit of info.

This script can work in 3 modes:
- Clone: clone the desired svn repos and all their externals into .gitsvn repos;
- Fetch: it's possible to simply fetch new revisions from svn without cloning everythin again;
- Finalization: when everything is ready convert all the git-svn repos into bare git repos;

Usage:
```bash
$ gittify -A authors-file.txt file:///var/lib/svn/foo file:///var/lib/svn/bar &> clone_log
$ gittify -A authors-file.txt --fetch &> fetch_log
$ gittify --finalize --git-server=https://git.foo.com/ &> conversion_log
```

However ```gittify --help``` is useful as well.

## Git-Externals

### Git externals update

If you want to:
* download the externals of a freshly cloned Git repository and creates their 
symlinks, in order to have the wanted directory layout.
* checkout the latest version of all externals (as defined in `git_externals.json` 
file)

Run:
```bash
$ git externals update
```

### Git externals status

```bash
$ git externals status [--porcelain|--verbose]
$ git externals status [--porcelain|--verbose] [external1 [external2] ...]
```

Shows the working tree status of one, multiple, or all externals:
 - add `--verbose` if you are also interested to see the externals that haven't
been modified
 - add `--porcelain` if you want the output easily parsable (for non-humans).

```bash
$ git externals status
$ git externals status deploy
$ git externals status deploy qtwidgets
```

### Git externals foreach

```bash
$ git externals foreach [--] cmd [arg1 [arg2] ...]
```

Evaluates an arbitrary shell command in each checked out external.
```bash
$ git externals foreach git fetch
```

**Note**: If some arguments of the shell command starts with `--`, like in 
`git rev-parse --all`, you must pass `--` after `foreach` in order to stop 
git externals argument processing, example:

```bash
$ git externals foreach -- git rev-parse --all
```


### Example usage
```bash
$ git externals add --branch=master https://gitlab.com/gitlab-org/gitlab-ce.git shared/ foo
$ git externals add --branch=master https://gitlab.com/gitlab-org/gitlab-ce.git shared/ bar
$ git externals add --branch=master https://gitlab.com/gitlab-org/gitlab-ce.git README.md baz/README.md
$ git externals add --tag=v4.4 https://github.com/torvalds/linux.git Makefile Makefile
$ git add git_externals.json
$ git commit -m "DO NOT FORGET TO COMMIT THE EXTERNALS!!!"
$ git externals update
$ git externals diff
$ git externals info
$ git externals list
```



Please be careful to include / if the source is a directory!


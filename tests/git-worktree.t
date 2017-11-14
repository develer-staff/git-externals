Svn external in a git worktree:

  $ mkdir master
  $ cd master
  $ git init .
  Initialized empty Git repository in /tmp/cramtests-*/git-worktree.t/master/.git/ (glob)
  $ git config user.email "externals@test.com"
  $ git config user.name "Git Externals"
  $ git externals add -b trunk -c svn https://svn.riouxsvn.com/svn-test-repo/trunk ./ test-repo-svn > /dev/null 2>&1
  $ git externals update > /dev/null 2>&1
  $ ls . | grep test-repo-svn
  test-repo-svn
  $ git add git_externals.json
  $ git commit -m"Add git_externals.json" git_externals.json | grep "create mode"
   create mode 100644 git_externals.json

Now we create a worktree ad try to update the externals there too

  $ git worktree add ../test-worktree > /dev/null
  Preparing ../test-worktree (identifier test-worktree)
  $ cd ../test-worktree
  $ ls . | grep test-repo-svn
  [1]
  $ git externals update > /dev/null 2>&1
  $ ls . | grep test-repo-svn
  test-repo-svn

Test the upgrade to the new storage folder `.git_externals/`

  $ cd ../master
  $ readlink -f test-repo-svn
  /tmp/cramtests-*/git-worktree.t/master/.git_externals/trunk (glob)
  $ mv .git_externals/ .git/externals
  $ rm test-repo-svn
  $ ln -s .git/externals/trunk ./test-repo-svn
  $ readlink -f test-repo-svn  # check we restored the old version location
  /tmp/cramtests-*/git-worktree.t/master/.git/externals/trunk (glob)

  $ git externals update
  Moving old externals path to new location
  externals sanity check passed!
  External trunk
  Retrieving changes from server:  trunk
  *-*-* *:*:* INFO[git-svn-clone-externals]: git svn rebase . (glob)
  Current branch HEAD is up to date.
  Checking out commit git-svn

  $ readlink -f test-repo-svn  # check we updated the link too
  /tmp/cramtests-*/git-worktree.t/master/.git_externals/trunk (glob)

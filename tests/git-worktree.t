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

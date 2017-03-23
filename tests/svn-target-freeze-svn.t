Svn external freeze (with --vcs and --no-gitsvn):

  $ git init .
  Initialized empty Git repository in /tmp/cramtests-*/svn-target-freeze-svn.t/.git/ (glob)
  $ git externals add -b trunk -c svn -r svn:r10 https://svn.riouxsvn.com/svn-test-repo/trunk ./ test-repo-svn
  Repo:   https://svn.riouxsvn.com/svn-test-repo/trunk
  Branch: trunk
  Ref:    svn:r10
    ./ -> ./test-repo-svn
  
  $ git externals update --no-gitsvn
  externals sanity check passed!
  External trunk
  Cloning external trunk
  Retrieving changes from server:  trunk
  Updating to commit 10

  $ (cd test-repo-svn && svn log --limit 1)
  ------------------------------------------------------------------------
  r10 | naufraghi | 2017-02-02 23:06:36 +0000 (Thu, 02 Feb 2017) | 1 line
  
  Add citation
  ------------------------------------------------------------------------

Test version bump:

  $ (cd test-repo-svn && svnversion -c)
  5:10

  $ (cd test-repo-svn && svn update -rHEAD)
  Updating '.':
  A    docs
  A    docs/docs.md
  U    README.md
   U   .
  Updated to revision 15.

  $ (cd test-repo-svn && svnversion -c)
  5:15

  $ git externals freeze
  Freeze https://svn.riouxsvn.com/svn-test-repo/trunk at svn:r15
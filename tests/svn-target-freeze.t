Svn external (with --vcs):

  $ git init .
  Initialized empty Git repository in /tmp/cramtests-*/svn-target-freeze.t/.git/ (glob)
  $ git externals add -b trunk -c svn -r svn:r10 https://svn.riouxsvn.com/svn-test-repo/trunk ./ test-repo-svn
  Repo:   https://svn.riouxsvn.com/svn-test-repo/trunk
  Branch: trunk
  Ref:    svn:r10
    ./ -> ./test-repo-svn
  
  $ git externals update 2>&1 | grep -v "svn:mergeinfo"
  externals sanity check passed!
  External trunk
  Cloning external trunk
  Initialized empty Git repository in /tmp/cramtests-*/svn-target-freeze.t/.git*externals/trunk/.git/ (glob)
  \tA\t*.* (esc) (glob)
  \tA\t*.* (esc) (glob)
  r10 = e05cc85567e5e18004ba1fc55ed7599ba94d2b5a (refs/remotes/git-svn)
  Checked out HEAD:
    https://svn.riouxsvn.com/svn-test-repo/trunk r10
  Retrieving changes from server:  trunk
  *-*-* *:*:* INFO[git-svn-clone-externals]: git svn rebase . (glob)
  \tM\tREADME.md (esc)
  r11 = 2c875802afea7d5cb498b902af94eeb3b42bbe73 (refs/remotes/git-svn)
  \tM\tREADME.md (esc)
  Couldn't find revmap for https://svn.riouxsvn.com/svn-test-repo/trunk/branches/issue-1
  r13 = 6d4767de6645e6bd59e3437036e8a0e3137203ef (refs/remotes/git-svn)
  \tA\tdocs/docs.md (esc)
  r15 = fbe3da492ad7013e779968d7d7183cce742e501a (refs/remotes/git-svn)
  First, rewinding head to replay your work on top of it...
  Fast-forwarded master to refs/remotes/git-svn.
  Checking out commit e05cc85567e5e18004ba1fc55ed7599ba94d2b5a

  $ cd test-repo-svn && git log -1
  commit e05cc85567e5e18004ba1fc55ed7599ba94d2b5a
  Author: naufraghi <naufraghi@fa4e49d6-2000-40a9-909b-e7fe548600ae>
  Date:   Thu Feb 2 23:06:36 2017 +0000
  
      Add citation
      
      git-svn-id: https://svn.riouxsvn.com/svn-test-repo/trunk@10 fa4e49d6-2000-40a9-909b-e7fe548600ae

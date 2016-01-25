#!/usr/bin/env python

from __future__ import print_function

import subprocess
import os

from contextlib import contextmanager


class ProgError(Exception):
    def __init__(self, prog='', errcode=1, errmsg=''):
        super(ProgError, self).__init__(prog + ' ' + errmsg)
        self.prog = prog
        self.errcode = errcode

    def __str__(self):
        name = '{}Error'.format(self.prog.title())
        msg = super(ProgError, self).__str__()
        return '<{}: {} {}>'.format(name, self.errcode, msg)


class GitError(ProgError):
    def __init__(self, **kwargs):
        super(GitError, self).__init__(prog='git', **kwargs)


class SVNError(ProgError):
    def __init__(self, **kwargs):
        super(SVNError, self).__init__(prog='svn', **kwargs)


def svn(*args):
    p = subprocess.Popen(['svn'] + list(args), stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    output, err = p.communicate()

    if p.returncode != 0:
        raise SVNError(errcode=p.returncode, errmsg=err)

    return output


def git(*args):
    p = subprocess.Popen(['git'] + list(args), stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    output, err = p.communicate()

    if p.returncode != 0:
        raise GitError(errcode=p.returncode, errmsg=err)

    return output


def branches():
    refs = git('for-each-ref', 'refs/heads', "--format=%(refname)")
    return [line.split('/')[2] for line in refs.splitlines()]


def tags():
    refs = git('for-each-ref', 'refs/tags', "--format=%(refname)")
    return [line.split('/')[2] for line in refs.splitlines()]


@contextmanager
def checkout(branch, remote=None):
    brs = set(branches())

    # if remote is not None -> create local branch from remote
    if remote is not None and branch not in brs:
        git('checkout', '-b', branch, remote)
    else:
        git('checkout', branch)
    yield
    git('checkout', 'master')


@contextmanager
def chdir(path):
    cwd = os.path.abspath(os.getcwd())

    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(cwd)

def header(msg):
    banner = '=' * 78

    print('')
    print(banner)
    print('{:^78}'.format(msg))
    print(banner)

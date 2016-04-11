#!/usr/bin/env python

from __future__ import print_function

import subprocess
import os
import sys
import logging
import re

from subprocess import check_call
from contextlib import contextmanager


class ProgError(Exception):
    def __init__(self, prog='', errcode=1, errmsg=''):
        super(ProgError, self).__init__(u'{} {}'.format(prog, errmsg))
        self.prog = prog
        self.errcode = errcode

    def __str__(self):
        name = u'{}Error'.format(self.prog.title())
        msg = super(ProgError, self).__str__()
        return u'<{}: {} {}>'.format(name, self.errcode, msg)


class GitError(ProgError):
    def __init__(self, **kwargs):
        super(GitError, self).__init__(prog='git', **kwargs)


class SVNError(ProgError):
    def __init__(self, **kwargs):
        super(SVNError, self).__init__(prog='svn', **kwargs)

class CommandError(ProgError):
    def __init__(self, cmd, **kwargs):
        super(CommandError, self).__init__(prog=cmd, **kwargs)


def svn(*args, **kwargs):
    universal_newlines = kwargs.get('universal_newlines', True)
    p = subprocess.Popen(['svn'] + list(args),
                         stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE,
                         universal_newlines=universal_newlines)
    output, err = p.communicate()

    if p.returncode != 0:
        raise SVNError(errcode=p.returncode, errmsg=err)

    return output


def git(*args, **kwargs):
    capture = kwargs.get('capture', True)
    if capture:
         stdout = subprocess.PIPE
         stderr = subprocess.PIPE
    else:
         stdout = None
         stderr = None
    p = subprocess.Popen(['git'] + list(args),
                         stdout=stdout,
                         stderr=stderr,
                         universal_newlines=True)
    output, err = p.communicate()

    if p.returncode != 0:
        raise GitError(errcode=p.returncode, errmsg=err)

    return output


def command(cmd, *args):
    p = subprocess.Popen([cmd] + list(args),
                         stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE,
                         universal_newlines=True)
    output, err = p.communicate()

    if p.returncode != 0:
        raise CommandError(cmd, errcode=p.returncode, errmsg=err)

    return output


def current_branch():
    return git('name-rev', '--name-only', 'HEAD').strip()


def branches():
    refs = git('for-each-ref', 'refs/heads', "--format=%(refname)")
    return [line.split('/')[2] for line in refs.splitlines()]


def tags():
    refs = git('for-each-ref', 'refs/tags', "--format=%(refname)")
    return [line.split('/')[2] for line in refs.splitlines()]


TAGS_RE = re.compile('.+/tags/(.+)')

def git_remote_branches_and_tags():
    output = git('branch', '-r')

    _branches, _tags = [], []

    for line in output.splitlines():
        line = line.strip()
        m = TAGS_RE.match(line)

        t = _tags if m is not None else _branches
        t.append(line)

    return _branches, _tags


@contextmanager
def checkout(branch, remote=None, back_to='master', force=False):
    brs = set(branches())

    cmd = ['git', 'checkout']
    if force:
        cmd += ['--force']
    # if remote is not None -> create local branch from remote
    if remote is not None and branch not in brs:
        check_call(cmd + ['-b', branch, remote])
    else:
        check_call(cmd + [branch])
    yield
    check_call(cmd + [back_to])


@contextmanager
def chdir(path):
    cwd = os.path.abspath(os.getcwd())

    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(cwd)


def mkdir_p(path):
    if path != '' and not os.path.exists(path):
        os.makedirs(path)


def header(msg):
    banner = '=' * 78

    print('')
    print(banner)
    print(u'{:^78}'.format(msg))
    print(banner)


def print_msg(msg):
    print(u'  {}'.format(msg))


if not sys.platform.startswith('win32'):
    link = os.symlink
    rm_link = os.remove

# following works but it requires admin privileges
else:

    def link(src, dst):
        import ctypes
        csl = ctypes.windll.kernel32.CreateSymbolicLinkW
        csl.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32)
        csl.restype = ctypes.c_ubyte
        if os.path.isdir(src):
            # use directory junctions (fix for python 2.6)
            ret = subprocess.call(['mklink', '/J', src, dst])
        else:
            if csl(dst, src, 1) == 0:
                raise ctypes.WinError()

    def rm_link(path):
        if os.path.isfile(path):
            os.remove(path)
        else:
            os.rmdir(path)


class IndentedLoggerAdapter(logging.LoggerAdapter):
    def __init__(self, logger, indent_val=4):
        super(IndentedLoggerAdapter, self).__init__(logger, {})
        self.indent_level = 0
        self.indent_val = 4

    def process(self, msg, kwargs):
        return (' ' * self.indent_level + msg, kwargs)

    @contextmanager
    def indent(self):
        self.indent_level += self.indent_val
        yield
        self.indent_level -= self.indent_val

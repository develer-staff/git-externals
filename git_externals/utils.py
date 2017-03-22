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
    def __init__(self, prog='', errcode=1, errmsg='', args=''):
        if isinstance(args, tuple):
            args = u' '.join(args)
        super(ProgError, self).__init__(u'\"{} {}\" {}'.format(prog, args, errmsg))
        self.prog = prog
        self.errcode = errcode

    def __str__(self):
        name = u'{}Error'.format(self.prog.title())
        msg = super(ProgError, self).__str__()
        return u'<{}: {} {}>'.format(name, self.errcode, msg)


class GitError(ProgError):
    def __init__(self, **kwargs):
        super(GitError, self).__init__(prog='git', **kwargs)


class SvnError(ProgError):
    def __init__(self, **kwargs):
        super(SvnError, self).__init__(prog='svn', **kwargs)


class GitSvnError(ProgError):
    def __init__(self, **kwargs):
        super(GitSvnError, self).__init__(prog='git-svn', **kwargs)


class CommandError(ProgError):
    def __init__(self, cmd, **kwargs):
        super(CommandError, self).__init__(prog=cmd, **kwargs)


def svn(*args, **kwargs):
    universal_newlines = kwargs.get('universal_newlines', True)
    output, err, errcode = _command('svn', *args, capture=True, universal_newlines=universal_newlines)
    if errcode != 0:
        print("running svn ", args)
        raise SvnError(errcode=errcode, errmsg=err)
    return output


def git(*args, **kwargs):
    capture = kwargs.get('capture', True)
    output, err, errcode = _command('git', *args, capture=capture, universal_newlines=True)
    if errcode != 0:
        raise GitError(errcode=errcode, errmsg=err, args=args)
    return output


def gitsvn(*args, **kwargs):
    capture = kwargs.get('capture', True)
    output, err, errcode = _command('git', 'svn', *args, capture=capture, universal_newlines=True)
    if errcode != 0:
        raise GitSvnError(errcode=errcode, errmsg=err, args=args)
    return output


def gitsvnrebase(*args, **kwargs):
    capture = kwargs.get('capture', True)
    output, err, errcode = _command('git-svn-rebase', *args, capture=capture, universal_newlines=True)
    if errcode != 0:
        raise GitSvnError(errcode=errcode, errmsg=err, args=args)
    return output


def command(cmd, *args, **kwargs):
    universal_newlines = kwargs.get('universal_newlines', True)
    capture = kwargs.get('capture', True)
    output, err, errcode = _command(cmd, *args, universal_newlines=universal_newlines, capture=capture)
    if errcode != 0:
        raise CommandError(cmd, errcode=errcode, errmsg=err, args=args)
    return output


def _command(cmd, *args, **kwargs):
    env = kwargs.get('env', dict(os.environ))
    env.setdefault('LC_MESSAGES', 'C')
    universal_newlines = kwargs.get('universal_newlines', True)
    capture = kwargs.get('capture', True)
    if capture:
        stdout, stderr = subprocess.PIPE, subprocess.PIPE
    else:
        stdout, stderr = None, None

    p = subprocess.Popen([cmd] + list(args),
                         stdout=stdout,
                         stderr=stderr,
                         universal_newlines=universal_newlines,
                         env=env)
    output, err = p.communicate()
    return output, err, p.returncode


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


def decode_utf8(msg):
    """
    Py2 / Py3 decode
    """
    try:
        return msg.decode('utf8')
    except AttributeError:
        return msg


if not sys.platform.startswith('win32'):
    link = os.symlink
    rm_link = os.remove

# following works but it requires admin privileges
else:
    if sys.getwindowsversion()[0] >= 6:
        def link(src, dst):
            import ctypes
            csl = ctypes.windll.kernel32.CreateSymbolicLinkW
            csl.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32)
            csl.restype = ctypes.c_ubyte
            if csl(dst, src, 0 if os.path.isfile(src) else 1) == 0:
                print("Error in CreateSymbolicLinkW(%s, %s)" % (dst, src))
                raise ctypes.WinError()
    else:
        import shutil
        def link(src, dst):
            if os.path.isfile(src):
                print_msg("WARNING: Unsupported SymLink on Windows before Vista, single files will be copied")
                shutil.copy2(src, dst)
            else:
                try:
                    subprocess.check_call(['junction', dst, src], shell=True)
                except:
                    print_msg("ERROR: Is http://live.sysinternals.com/junction.exe in your PATH?")
                    raise

    def rm_link(path):
        if os.path.isfile(path):
            os.remove(path)
        else:
            os.rmdir(path)


class IndentedLoggerAdapter(logging.LoggerAdapter):
    def __init__(self, logger, indent_val=4):
        super(IndentedLoggerAdapter, self).__init__(logger, {})
        self.indent_level = 0
        self.indent_val = indent_val

    def process(self, msg, kwargs):
        return (' ' * self.indent_level + msg, kwargs)

    @contextmanager
    def indent(self):
        self.indent_level += self.indent_val
        yield
        self.indent_level -= self.indent_val

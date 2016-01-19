#!/usr/bin/env python

import subprocess
import os.path
import sys
import re

from contextlib import contextmanager

TAGS_RE = re.compile('.+/tags/(.+)')


def git(*args):
    p = subprocess.Popen(['git'] + list(args), stdout=subprocess.PIPE)
    output = p.communicate()[0]

    if p.returncode != 0:
        raise Exception('git failed, err code {}'.format(p.returncode))

    return output


@contextmanager
def chdir(path):
    cwd = os.path.abspath(os.getcwd())

    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(cwd)


def name_of(remote):
    if remote.endswith('/'):
        remote = remote[:-1]
    return os.path.basename(remote)


def get_branches_and_tags():
    output = git('branch', '-r')

    branches, tags = [], []

    for line in output.splitlines():
        line = line.strip()
        m = TAGS_RE.match(line)

        t = tags if m is not None else branches
        t.append(line)

    return branches, tags


@contextmanager
def checkout(branch, remote=None):
    # if remote is not None -> create local branch from remote
    if remote is not None:
        git('checkout', '-b', branch, remote)
    else:
        git('checkout', branch)
    yield
    git('checkout', 'master')


def branchtag_to_tag(tag_name, remote_tag):
    with checkout(tag_name, remote_tag):
        pass

    git('tag', tag_name, tag_name)
    git('branch', '-D', tag_name)


def cleanup(repo):
    with chdir(repo):
        branches, tags = get_branches_and_tags()

        revbound_brach_re = re.compile('.+@\d+')
        for branch in branches:
            # trunk is automatically remapped to master by git svn
            branch_name = name_of(branch)
            is_revbound = revbound_brach_re.match(branch_name) is not None
            if branch_name == 'trunk' or is_revbound:
                continue

            with checkout(branch_name, branch):
                pass

        for tag in tags:
            branchtag_to_tag(name_of(tag), tag)


if __name__ == '__main__':
    cleanup(sys.argv[1])

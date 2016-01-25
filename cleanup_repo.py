#!/usr/bin/env python

import os.path
import re
import argparse

from utils import svn, git, SVNError, checkout, chdir

TAGS_RE = re.compile('.+/tags/(.+)')

def get_branches_and_tags():
    output = git('branch', '-r')

    branches, tags = [], []

    for line in output.splitlines():
        line = line.strip()
        m = TAGS_RE.match(line)

        t = tags if m is not None else branches
        t.append(line)

    return branches, tags


def name_of(remote):
    if remote.endswith('/'):
        remote = remote[:-1]
    return os.path.basename(remote)


def branchtag_to_tag(tag_name, remote_tag):
    with checkout(tag_name, remote_tag):
        pass

    git('tag', tag_name, tag_name)
    git('branch', '-D', tag_name)


def get_merged_branches(repo):
    try:
        entries = svn('ls', os.path.join(repo, 'branches')).splitlines()
    except SVNError:
        return set()
    return set([b[:-1] for b in entries])


def get_removed_tags(repo):
    try:
        entries = svn('ls', os.path.join(repo, 'tags')).splitlines()
    except SVNError:
        return set()
    return set([t[:-1] for t in entries])


def cleanup(repo, with_revbound=False, remote=None):
    with chdir(repo):
        if remote is not None:
            remote_branches = get_merged_branches(remote)
            remote_tags = get_removed_tags(remote)

        branches, tags = get_branches_and_tags()

        revbound_re = re.compile(r'.+@\d+')
        for branch in branches:
            branch_name = name_of(branch)
            is_revbound = revbound_re.match(branch_name) is not None

            # trunk is automatically remapped to master by git svn
            if branch_name in ('trunk', 'git-svn'):
                continue

            if not with_revbound and is_revbound:
                continue

            if remote is not None and branch_name not in remote_branches:
                continue

            with checkout(branch_name, branch):
                pass

        for tag in tags:
            if remote is not None and tag not in remote_tags:
                continue

            if with_revbound or revbound_re.match(tag) is None:
                branchtag_to_tag(name_of(tag), tag)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('repo', help='path to local repo to cleanup')
    parser.add_argument('--remote', default=None,
        help='remote repo containing all the branches and tags')
    parser.add_argument('--with-revbound', default=False, action='store_true',
        help='keep both revision bounded branches and tags')

    args = parser.parse_args()

    cleanup(args.repo, args.with_revbound, args.remote)

if __name__ == '__main__':
    main()

#!/usr/bin/env python

import posixpath
import re
import argparse

import logging
from .utils import svn, git, SVNError, checkout, chdir, tags, git_remote_branches_and_tags


def name_of(remote):
    return posixpath.basename(remote.strip('/'))


def branchtag_to_tag(tag_name, remote_tag):
    with checkout(tag_name, remote_tag):
        pass

    if tag_name in tags():
        git('tag', '-d', tag_name)

    git('tag', tag_name, tag_name)
    git('branch', '-D', tag_name)


def svn_remote_branches(repo):
    try:
        entries = svn('ls', posixpath.join(repo, 'branches')).splitlines()
    except SVNError:
        return set()
    return set([b[:-1] for b in entries])


def svn_remote_tags(repo):
    try:
        entries = svn('ls', posixpath.join(repo, 'tags')).splitlines()
    except SVNError:
        return set()
    return set([t[:-1] for t in entries])


def cleanup(repo, with_revbound=False, remote=None, log=None):
    if log is None:
        logging.basicConfig()
        log = logging.getLogger(__name__)
        log.setLevel(logging.INFO)

    with chdir(repo):
        if remote is not None:
            remote_branches = svn_remote_branches(remote)
            remote_tags = svn_remote_tags(remote)
        else:
            remote_branches = []
            remote_tags = []

        repo_name, _ = posixpath.splitext(name_of(repo))

        branches, tags = git_remote_branches_and_tags()

        revbound_re = re.compile(r'.+@(\d+)')

        log.info('Cleaning up branches...')
        for branch in branches:
            branch_name = name_of(branch)

            match = revbound_re.match(branch_name)
            is_revbound = match is not None
            rev = match.group(1) if is_revbound else None

            # trunk is automatically remapped to master by git svn
            if branch_name in ('trunk', 'git-svn'):
                continue

            if not with_revbound and is_revbound:
                log.warning('Skipping cleanup of {} because it is bound to rev {}'
                            .format(branch_name, rev))
                continue

            if branch_name not in remote_branches and not branch_name.startswith(repo_name):
                log.warning('Skipping cleanup of {} because it has been deleted (maybe after a merge?)'
                            .format(branch_name))
                continue

            log.info('Cleaning up branch {}'.format(branch_name))
            with checkout(branch_name, branch):
                pass

        log.info('Cleaning up tags')
        for tag in tags:
            match = revbound_re.match(tag)
            is_revbound = match is not None
            rev = match.group(1) if is_revbound else None

            tag_name = name_of(tag)

            if tag_name not in remote_tags:
                log.warning('Skipping tag {} because it has been deleted'
                            .format(tag))
                continue

            if not with_revbound and is_revbound:
                log.warning('Skipping tag {} because it is bound to rev {}'
                            .format(tag, rev))
                continue

            log.info('Cleaning up tag {}'.format(tag))
            branchtag_to_tag(tag_name, tag)


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

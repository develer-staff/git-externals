#!/usr/bin/env python

from __future__ import unicode_literals

import os
import os.path
import shutil
import json
import sys
import glob
import re

try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse

try:
    from lxml import etree as ET
except ImportError:
    from xml.etree import ElementTree as ET

from cleanup_repo import cleanup
from utils import git, svn, chdir, checkout, SVNError, branches, tags, header,\
    print_msg
from process_externals import unique_externals

GITSVN_EXT = '.gitsvn'
GIT_EXT = '.git'


def get_externals(repo):
    data = svn('propget', '--xml', '-R', 'svn:externals', repo)

    targets = ET.fromstring(data).findall('target')

    return unique_externals(targets)

BRANCH_RE = re.compile(r'branches/(.+)')
TAG_RE = re.compile(r'tags/(.+)')


def svnext_to_gitext(ext, git_server):
    gitext = {}

    path = urlparse(ext['target']).path

    repo_name = extract_repo_name(path)
    remote_dir = extract_repo_path(path, repo_name)

    gitext['destination'] = os.path.join(remote_dir, ext['path'])

    ext_repo = os.path.basename(extract_repo_name(ext['location']))
    if ext_repo.startswith('..'):
        # assume for simplicity it's the current repo(e.g. multiple .. not allowed)
        ext_repo = repo_name

    gitext['source'] = extract_repo_path(ext['location'], ext_repo)
    gitext['repo'] = os.path.join(git_server, ext_repo)

    gitext['branch'] = 'master'
    match = BRANCH_RE.match(ext['location'])
    if match is not None:
        gitext['branch'] = match.group(1).split('/')[0]

    gitext['ref'] = None
    if ext['rev'] is not None:
        # svn rev -> git sha
        rev = 'r' + ext['rev'] if ext['rev'][0] != 'r' else ext['rev']

        with chdir(os.path.join('..', ext_repo + GITSVN_EXT)):
            gitext['ref'] = git('svn', 'find-rev', rev).strip()
    else:
        match = TAG_RE.match(ext['location'])
        if match is not None:
            gitext['ref'] = match.group(1)

    return gitext


def write_extfile(exts, filename='git_externals.json', git_server='yourserver'):
    exts = [svnext_to_gitext(e, git_server) for e in exts]

    with open(filename, 'wt') as fd:
        json.dump(exts, fd, indent=4)


def extract_repo_name(remote_name):
    if remote_name[0] == '/':
        remote_name = remote_name[1:]

    if remote_name.startswith('svn/'):
        remote_name = remote_name[len('svn/'):]

    # a svn super repo is a container of other repos
    super_repos = set(['packages/', 'vendor/'])

    for super_repo in super_repos:
        if remote_name.startswith(super_repo):
            i = len(super_repo) - 1
            return super_repo + extract_repo_name(remote_name[i:])

    j = remote_name.find('/')
    if j < 0:
        return remote_name
    return remote_name[:j]


def extract_repo_root(repo):
    output = svn('info', '--xml', repo)

    rootnode = ET.fromstring(output)
    return rootnode.find('./entry/repository/root').text


def extract_repo_path(path, repo_name):
    if path[0] == '/':
        path = path[1:]

    remote_dir = []
    for subpath in path.split('/')[::-1]:
        if subpath in set(['trunk', 'branches', 'tags', repo_name]):
            # remove tag/branch name
            if subpath == 'branches' or subpath == 'tags':
                remote_dir = remote_dir[:-1]
            break
        remote_dir.append(subpath)

    if len(remote_dir) > 0:
        remote_dir = '/'.join(remote_dir[::-1])
    else:
        remote_dir = '.'

    return remote_dir


def get_layout_opts(repo):
    entries = set(svn('ls', repo).splitlines())

    opts = []

    if 'trunk/' in entries:
        opts.append(
            '--trunk=trunk'
        )

    if 'branches/' in entries:
        opts.append(
            '--branches=branches'
        )

    if 'tags/' in entries:
        opts.append(
            '--tags=tags'
        )

    return opts


def remote_rm(remote):
    remotes = set(git('remote').splitlines())
    if remote in remotes:
        git('remote', 'rm', remote)


def gittify_branch(repo, branch_name, obj, svn_server):
    print_msg('Gittifying branch {}'.format(branch_name))
    gittified = set()

    with checkout(branch_name, obj):
        externals = get_externals(os.path.join(svn_server, repo))

        if len(externals) > 0:
            print_msg('Gittifying externals...')
            ext_to_write = []
            with chdir('..'):
                for ext in externals:
                    # should be true only for externals of picking_assistant
                    if ext['location'].startswith('..'):
                        continue
                    repo_name = extract_repo_name(ext['location'])
                    gittified_externals = gittify(repo_name, svn_server)
                    gittified.update(gittified_externals)

                    gittified_name = os.path.basename(repo_name)
                    if gittified_name not in gittified_externals:
                        print_msg('{} is a SVN external, however it has not been found!'.format(gittified_name))
                        continue
                    ext_to_write.append(ext)

            write_extfile(ext_to_write)
            git('add', 'git_externals.json')
            git('commit', '-m', 'gittify: create svn_externals file',
                '--author="gittify <>"')

    return gittified


def gittify(repo, svn_server, basename_only=True, ignore_not_found=True):
    repo_name = repo
    if basename_only:
        repo_name = os.path.basename(repo)

    git_repo = repo_name + GIT_EXT
    gittified = set([repo_name])

    if os.path.exists(git_repo):
        print_msg('{} already gittified'.format(repo_name))
        return gittified

    gitsvn_repo = repo_name + GITSVN_EXT

    remote_repo = os.path.join(svn_server, repo)
    try:
        layout_opts = get_layout_opts(remote_repo)
    except SVNError as err:
        if ignore_not_found:
            print_msg('Ignoring error {}'.format(err))
            return set()
        raise

    is_std = len(layout_opts) == 3

    if not os.path.exists(gitsvn_repo):

        # FIXME: handle authors file for mapping SVN users to Git users
        args = ['svn', 'clone', '--prefix=origin/'] + layout_opts + [remote_repo, gitsvn_repo]

        header('Cloning {}'.format(remote_repo))
        print_msg('standard layout: {}'.format(is_std))
        print_msg(' '.join(args))

        git(*args)
        cleanup(gitsvn_repo, False, remote_repo)

        with chdir(gitsvn_repo):
            print_msg('Gittifying branches...')
            for branch in branches():
                if not is_std:
                    subrepo = repo
                elif branch != 'master':
                    subrepo = os.path.join(repo, 'branches', branch)
                else:
                    subrepo = os.path.join(repo, 'trunk')

                # we've already created a local branch for each
                # origin branch with cleanup
                external_gittified = gittify_branch(subrepo, branch, None, svn_server)
                gittified.update(external_gittified)

            print_msg('Gittifying tags...')
            for tag in tags():
                subrepo = os.path.join(repo, 'tags', tag)
                external_gittified = gittify_branch(subrepo, tag, tag, svn_server)

                if len(external_gittified) > 0:
                    gittified.update(external_gittified)
                    git('tag', '-d', tag)
                    git('tag', tag, tag)

                git('branch', '-D', tag)

        # avoid cycles, because it could be created by a previous call
        # from an external
        if not os.path.exists(git_repo):
            print_msg('Cloning into final git repo')
            git('clone', '--bare', gitsvn_repo, git_repo)
            with chdir(git_repo):
                remote_rm('origin')

    return gittified


def remove_gitsvn_repos():
    for tmp_repo in glob.iglob('*' + GITSVN_EXT):
        shutil.rmtree(tmp_repo)


if __name__ == '__main__':
    for r in sys.argv[1:]:
        root = extract_repo_root(r)
        repo = r[len(root) + 1:]
        gittify(repo, root)

    remove_gitsvn_repos()

#!/usr/bin/env python

from __future__ import unicode_literals

import subprocess
import os
import os.path
import shutil
import json
import sys

try:
    from lxml import etree as ET
except ImportError:
    from xml.etree import ElementTree as ET

from cleanup_repo import git, cleanup, chdir, checkout
from process_externals import unique_externals


def svn(*args):
    p = subprocess.Popen(['svn'] + list(args), stdout=subprocess.PIPE)
    output = p.communicate()[0]

    if p.returncode != 0:
        raise Exception('svn failed, err code {}'.format(p.returncode))

    return output


def get_externals(repo):
    data = svn('propget', '--xml', '-R', 'svn:externals', repo)

    targets = ET.fromstring(data).findall('target')

    return unique_externals(targets)


def write_extfile(exts, filename='svn_externals'):
    with open(filename, 'wt') as fd:
        json.dump(exts, fd, indent=4)


def extract_repo_name(remote_name):
    return remote_name[1:remote_name.index('/', 1)]


def extract_repo_root(repo):
    output = svn('info', '--xml', repo)

    rootnode = ET.fromstring(output)
    return rootnode.find('./entry/repository/root').text


def branches():
    refs = git('for-each-ref', 'refs/heads', "--format=%(refname)")
    return [line.split('/')[2] for line in refs.splitlines()]


def tags():
    refs = git('for-each-ref', 'refs/tags', "--format=%(refname)")
    return [line.split('/')[2] for line in refs.splitlines()]


def has_stdlayout(repo):
    stdlayout_entries = set(['trunk/', 'branches/', 'tags/'])
    entries = set(svn('ls', repo).splitlines())

    return entries == stdlayout_entries


def gittify_branch(repo, branch_name, obj, svn_server):
    gittified = set()

    with checkout(branch_name, obj):
        externals = get_externals(os.path.join(svn_server, repo))

        if len(externals) > 0:
            with chdir('..'):
                for ext in externals:
                    # FIXME: convert blocked externals revision to commit sha with git svn find-rev
                    repo_name = extract_repo_name(ext['location'])
                    gittified_externals = gittify(repo_name, svn_server)
                    gittified.update(gittified_externals)

            write_extfile(externals)
            git('add', 'svn_externals')
            git('commit', '-m', 'gittify: create svn_externals file')

    return gittified


def gittify(repo, svn_server, basename_only=True):
    gittified = set([repo])

    # check if already gittified
    if os.path.exists(repo):
        return gittified

    repo_name = repo
    if basename_only:
        repo_name = os.path.basename(repo)

    tmprepo = '{}.tmp'.format(repo_name)

    remote_repo = os.path.join(svn_server, repo)
    is_std = has_stdlayout(remote_repo)

    if not os.path.exists(tmprepo):
        # FIXME: handle authors file for mapping SVN users to Git users
        layout_opt = '--stdlayout' if is_std else '--trunk=.'

        git('svn', 'clone', layout_opt, '--prefix=origin/',
            remote_repo, tmprepo)
        cleanup(tmprepo)

    with chdir(tmprepo):
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

        for tag in tags():
            subrepo = os.path.join(repo, 'tags', tag)
            external_gittified = gittify_branch(subrepo, tag, tag, svn_server)

            # following should work, but not properly tested yet :)
            if len(external_gittified) > 0:
                gittified.update(gittify_branch)
                git('tag', '-d', tag)
                git('tag', tag, tag)

            git('branch', '-D', tag)

    git('clone', '--bare', tmprepo, repo_name)
    with chdir(repo_name):
        git('remote', 'rm', 'origin')

    shutil.rmtree(tmprepo)

    return gittified


if __name__ == '__main__':
    for r in sys.argv[1:]:
        root = extract_repo_root(r)
        repo = r[len(root) + 1:]
        gittify(repo, root)

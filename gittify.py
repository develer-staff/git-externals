#!/usr/bin/env python

from __future__ import unicode_literals

import subprocess
import os
import os.path
import shutil
import json
import sys

from lxml import etree
from cleanup_repo import git, cleanup, chdir, checkout, name_of
from process_externals import unique_externals


def svn(*args):
    p = subprocess.Popen(['svn'] + list(args), stdout=subprocess.PIPE)
    output = p.communicate()[0]

    if p.returncode != 0:
        raise Exception('svn failed, err code {}'.format(p.returncode))

    return output


def get_externals(repo):
    data = svn('propget', '--xml', '-R', 'svn:externals', repo)

    targets = etree.fromstring(data).findall('target')

    return unique_externals(targets)


def write_extfile(exts, filename='svn_externals'):
    with open(filename, 'wt') as fd:
        json.dump(exts, fd, indent=4)


def extract_repo_name(remote_name):
    return remote_name[1:remote_name.index('/', 1)]


def extract_repo_root(repo):
    output = svn('info', '--xml', repo)

    rootnode = etree.fromstring(output)
    return rootnode.find('./entry/repository/root').text


def branches():
    refs = git('for-each-ref', 'refs/heads', "--format=%(refname)")
    return [line.split('/')[2] for line in refs.splitlines()]


def tags():
    refs = git('for-each-ref', 'refs/tags', "--format=%(refname)")
    return [line.split('/')[2] for line in refs.splitlines()]


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


def gittify(repo, svn_server):
    gittified = set([repo])

    # check if already gittified
    if os.path.exists(repo):
        return gittified

    tmprepo = '{}.tmp'.format(repo)

    if not os.path.exists(tmprepo):
        # FIXME: handle non stdlayout repos, as most of foosvn/packages
        # FIXME: handle authors file for mapping SVN users to Git users
        git('svn', 'clone', '--stdlayout', '--prefix=origin/',
            os.path.join(svn_server, repo), tmprepo)
        cleanup(tmprepo)

    with chdir(tmprepo):
        for branch in branches():
            if branch != 'master':
                subrepo = os.path.join(repo, 'branches', branch)
            else:
                subrepo = os.path.join(repo, 'trunk')

            # we've already created a local branch for each
            # origin branch with cleanup
            external_gittified = gittify_branch(subrepo, branch, None, svn_server)
            gittified.update(external_gittified)

        # should work, but not tested yet :)
        for tag in tags():
            subrepo = os.path.join(svn_server, 'tags', tag)
            external_gittified = gittify_branch(subrepo, tag, tag, svn_server)
            if len(external_gittified) > 0:
                gittified.update(gittify_branch)
                git('tag', '-d', tag)
                git('tag', tag, tag)
            git('branch', '-D', tag)

    git('clone', '--bare', tmprepo, repo)
    with chdir(repo):
        git('remote', 'rm', 'origin')

    shutil.rmtree(tmprepo)

    return gittified


if __name__ == '__main__':
    for r in sys.argv[1:]:
        root = extract_repo_root(r)
        gittify(r[len(root)+1:], root)

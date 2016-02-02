#!/usr/bin/env python

from __future__ import unicode_literals

import os
import os.path
import posixpath
import shutil
import json
import glob
import re
import argparse
import logging

try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse

try:
    from lxml import etree as ET
except ImportError:
    from xml.etree import ElementTree as ET

from cleanup_repo import cleanup
from utils import git, svn, chdir, checkout, SVNError, branches, tags, \
    IndentedLoggerAdapter
from process_externals import parsed_externals

GITSVN_EXT = '.gitsvn'
GIT_EXT = '.git'

logging.basicConfig(format='%(levelname)8s %(asctime)s: %(message)s',
                    level=logging.INFO, datefmt='%Y-%m-%d %I:%m:%S')
log = IndentedLoggerAdapter(logging.getLogger(__name__))


def get_externals(repo):
    data = svn('propget', '--xml', '-R', 'svn:externals', repo)

    targets = ET.fromstring(data).findall('target')

    return list(parsed_externals(targets))

BRANCH_RE = re.compile(r'branches/(.+)')
TAG_RE = re.compile(r'tags/(.+)')


def last_changed_rev_from(rev, repo):
    data = svn('info', '--xml', '-' + rev, repo)

    rev = ET.fromstring(data).find('./entry/commit').get('revision')
    return 'r' + rev


def svnext_to_gitext(ext, config):
    gitext = {}

    path = urlparse(ext['target']).path

    repo_name = extract_repo_name(path, config['super_repos'])
    remote_dir = extract_repo_path(path, repo_name)

    gitext['destination'] = posixpath.join(remote_dir, ext['path'])

    complete_ext_repo = extract_repo_name(ext['location'], config['super_repos'])
    ext_repo = posixpath.basename(complete_ext_repo)
    if ext_repo.startswith('.'):
        source = posixpath.join(remote_dir, ext['location'])

        # assume for simplicity it's the current repo(e.g. multiple .. not allowed)
        ext_repo = repo_name
    else:
        source = extract_repo_path(ext['location'], ext_repo)

    gitext['source'] = source
    gitext['repo'] = posixpath.join(config['git_server'], ext_repo) + GIT_EXT

    gitext['branch'] = 'master'
    match = BRANCH_RE.match(ext['location'])
    if match is not None:
        gitext['branch'] = match.group(1).split('/')[0]

    gitext['ref'] = None
    if ext['rev'] is not None:
        # svn rev -> git sha
        rev = 'r' + ext['rev'] if ext['rev'][0] != 'r' else ext['rev']

        svn_repo = posixpath.join(config['svn_server'], complete_ext_repo)
        changed_rev = last_changed_rev_from(rev, svn_repo)

        with chdir(os.path.join('..', ext_repo + GITSVN_EXT)):
            gitext['ref'] = git('svn', 'find-rev', changed_rev).strip()
    else:
        match = TAG_RE.match(ext['location'])
        if match is not None:
            gitext['ref'] = match.group(1)

    return gitext


def group_gitexternals(exts):
    ret = {}
    for ext in exts:
        repo = ext['repo']
        src = ext['source']
        dst = ext['destination']

        if repo not in ret:
            ret[repo] = {
                'branch': ext['branch'],
                'ref': ext['ref'],
                'targets': {src: dst}
            }
        else:
            if ret[repo]['branch'] != ext['branch'] or ret[repo]['ref'] != ext['ref']:
                log.critical('Branch or ref mismatch across different dirs of git ext')
            ret[repo]['targets'][src] = dst

    return ret


def write_extfile(exts, config):
    gitexts = []
    for ext in exts:
        try:
            gitext = svnext_to_gitext(ext, config)
            gitexts.append(gitext)
        except SVNError:
            if not config['ignore_not_found']:
                raise
    gitexts = group_gitexternals(gitexts)
    with open(config['externals_filename'], 'wt') as fd:
        json.dump(gitexts, fd, indent=4)


def extract_repo_name(remote_name, super_repos):
    if remote_name[0] == '/':
        remote_name = remote_name[1:]

    if remote_name.startswith('svn/'):
        remote_name = remote_name[len('svn/'):]

    for super_repo in super_repos:
        if remote_name.startswith(super_repo):
            i = len(super_repo) - 1
            return super_repo + extract_repo_name(remote_name[i:], super_repos)

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


def gittify_branch(repo, branch_name, obj, config):
    log.info('Gittifying branch {}'.format(branch_name))
    gittified = set()

    with checkout(branch_name, obj):
        git_ignore = git('svn', 'show-ignore')
        with open('.gitignore', 'wt') as fp:
            fp.write(git_ignore)
        git('add', '.gitignore')
        git('commit', '-m', 'gittify: convert svn:ignore to .gitignore')

        externals = get_externals(posixpath.join(config['svn_server'], repo))

        if len(externals) > 0:
            log.info('Gittifying externals...')
            with log.indent():
                ext_to_write = []
                with chdir('..'):
                    for ext in externals:
                        # assume no multiple .., so it's a reference to the current repo
                        if not ext['location'].startswith('..'):
                            repo_name = extract_repo_name(ext['location'],
                                                          config['super_repos'])
                            gittified_externals = gittify(repo_name, config)
                            gittified.update(gittified_externals)

                            gittified_name = posixpath.basename(repo_name)
                            if gittified_name not in gittified_externals:
                                log.info('{} is a SVN external, however it has not been found!'.format(gittified_name))
                                continue
                        ext_to_write.append(ext)

                write_extfile(ext_to_write, config)
                git('add', config['externals_filename'])
                git('commit', '-m',
                    'gittify: create {} file'.format(config['externals_filename']),
                    '--author="gittify <>"')

    return gittified


def gittify(repo, config):
    repo_name = posixpath.basename(repo)

    git_repo = repo_name + GIT_EXT
    gittified = set([repo_name])

    if os.path.exists(git_repo):
        log.info('{} already gittified'.format(repo_name))
        return gittified

    gitsvn_repo = repo_name + GITSVN_EXT

    remote_repo = posixpath.join(config['svn_server'], repo)
    try:
        layout_opts = get_layout_opts(remote_repo)
    except SVNError as err:
        if config['ignore_not_found']:
            log.info('Ignoring error {}'.format(err))
            return set()
        raise

    is_std = len(layout_opts) == 3

    if not os.path.exists(gitsvn_repo):
        authors_file_opt = []
        if config['authors_file'] is not None:
            authors_file_opt = ['-A', config['authors_file']]
        args = ['svn', 'clone', '--prefix=origin/'] + authors_file_opt + \
                layout_opts + [remote_repo, gitsvn_repo]

        log.info('Cloning {}'.format(remote_repo))
        log.info('standard layout: {}'.format(is_std))
        log.info(' '.join(args))

        git(*args)
        cleanup(gitsvn_repo, False, remote_repo, log=log)

        with chdir(gitsvn_repo):
            log.info('Gittifying branches...')
            for branch in branches():
                if not is_std:
                    subrepo = repo
                elif branch != 'master':
                    subrepo = posixpath.join(repo, 'branches', branch)
                else:
                    subrepo = posixpath.join(repo, 'trunk')

                external_gittified = gittify_branch(subrepo, branch, None,
                                                    config)
                gittified.update(external_gittified)

            log.info('Gittifying tags...')
            for tag in tags():
                subrepo = posixpath.join(repo, 'tags', tag)
                external_gittified = gittify_branch(subrepo, tag, tag,
                                                    config)

                if len(external_gittified) > 0:
                    gittified.update(external_gittified)
                    git('tag', '-d', tag)
                    git('tag', tag, tag)

                git('branch', '-D', tag)

        if not os.path.exists(git_repo):
            log.info('Cloning into final git repo')
            git('clone', '--bare', gitsvn_repo, git_repo)
            with chdir(git_repo):
                remote_rm('origin')

    return gittified


def remove_gitsvn_repos():
    for tmp_repo in glob.iglob('*' + GITSVN_EXT):
        shutil.rmtree(tmp_repo)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('repos', nargs='+', help='SVN repos to migrate to Git')
    parser.add_argument('--git-server', default='yourserver',
                        help='Url to use as base url for the git server')
    parser.add_argument('--filename', default='git_externals.json',
                        help='Filename of the json dump of the svn externals')
    parser.add_argument('--crash-on-404', default=False, action='store_true',
                        help='Give error if an external has not been found')
    parser.add_argument('--rm-gitsvn', default=False, action='store_true',
                        help='Remove gitsvn temporaries repos')
    parser.add_argument('--super-repos', type=set, nargs='+',
                        default=set(['packages/', 'vendor/']),
                        help='A SVN super repo is not a real repo but it is a container of repos')
    parser.add_argument('-A', '--authors-file', default=None,
                        help='Authors file to map svn users to git')

    args = parser.parse_args()

    return args.repos, {
        'git_server': args.git_server,
        'externals_filename': args.filename,
        'ignore_not_found': not args.crash_on_404,
        'rm_gitsvn': args.rm_gitsvn,
        'super_repos': args.super_repos,
        'authors_file': args.authors_file,
    }


def main():
    repos, config = parse_args()

    for r in repos:
        root = extract_repo_root(r)
        repo = r[len(root) + 1:]
        config['svn_server'] = root
        gittify(repo, config)

    if config['rm_gitsvn']:
        remove_gitsvn_repos()

if __name__ == '__main__':
    main()

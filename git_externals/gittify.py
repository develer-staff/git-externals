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

from .cleanup_repo import cleanup, name_of
from .utils import git, svn, chdir, checkout, current_branch, SVNError, branches, \
    tags, IndentedLoggerAdapter, git_remote_branches_and_tags
from .process_externals import parsed_externals

GITSVN_EXT = '.gitsvn'
GIT_EXT = '.git'

logging.basicConfig(format='%(levelname)8s %(asctime)s: %(message)s',
                    level=logging.INFO, datefmt='%Y-%m-%d %I:%m:%S')
log = IndentedLoggerAdapter(logging.getLogger(__name__))


def get_externals(repo):
    data = svn('propget', '--xml', '-R', 'svn:externals', repo)

    targets = ET.fromstring(data).findall('target')

    return list(parsed_externals(targets))


def svn_path_type(repo):
    data = svn('info', '--xml', repo)
    return ET.fromstring(data).find('./entry').get('kind')


def last_changed_rev_from(rev, repo):
    data = svn('info', '--xml', '-' + rev, repo)

    rev = ET.fromstring(data).find('./entry/commit').get('revision')
    return 'r' + rev


def svnrev_to_gitsha(rev):
    # brute force :(
    gitsvn_id_re = re.compile(r'(\w+) .*git-svn-id: [^@]+@{}'.format(rev[1:]), re.S)

    data = git('log', '--format="%H %b"')

    return gitsvn_id_re.search(data).group(1)


def gitsvn_url():
    return git('svn', 'info', '--url').strip()


BRANCH_RE = re.compile(r'branches/([^/]+)')
TAG_RE = re.compile(r'tags/([^/]+)')


def svnext_to_gitext(ext, config):
    gitext = {}

    path = urlparse(ext['target']).path

    repo_name = extract_repo_name(path, config['super_repos'])
    remote_dir = extract_repo_path(path, repo_name)

    gitext['destination'] = posixpath.join(remote_dir, ext['path'])

    loc = ext['location'] if ext['location'][0] != '/' else ext['location'][1:]

    complete_ext_repo = extract_repo_name(ext['location'], config['super_repos'])
    ext_repo = posixpath.basename(complete_ext_repo)
    if ext_repo.startswith('.'):
        source = posixpath.join(remote_dir, ext['location'])
        gitext['source'] = source

        # assume for simplicity it's the current repo(e.g. multiple .. not allowed)
        ext_repo = repo_name
    else:
        source = extract_repo_path(ext['location'], complete_ext_repo)

        is_dir = svn_path_type(posixpath.join(config['svn_server'], loc)) == 'dir'
        gitext['source'] = source + '/' if is_dir else source

    gitext['repo'] = posixpath.join(config['git_server'], ext_repo) + GIT_EXT

    match = TAG_RE.search(ext['location'])
    if match is not None:
        gitext['tag'] = match.group(1)

    else:
        gitext['branch'] = 'master'
        match = BRANCH_RE.search(ext['location'])
        if match is not None:
            gitext['branch'] = match.group(1).split('/')[0]

        gitext['ref'] = None
        if ext['rev'] is not None:
            # svn rev -> git sha -> git tag
            rev = 'r' + ext['rev'] if ext['rev'][0] != 'r' else ext['rev']

            svn_ext_repo = loc[:-len(source)] if source != '.' else loc
            svn_repo = posixpath.join(config['svn_server'], svn_ext_repo)
            changed_rev = last_changed_rev_from(rev, svn_repo)

            with chdir(os.path.join('..', ext_repo + GITSVN_EXT)):
                with checkout(gitext['branch'], back_to=current_branch()):
                    ref = git('svn', 'find-rev', changed_rev).strip()
                    if ref == '':
                        ref = svnrev_to_gitsha(changed_rev)
                    if git('tag', '-l', rev).strip() == '':
                        git('tag', rev, ref)
                    gitext['ref'] = rev

    return gitext


def group_gitexternals(exts):
    ret = {}
    mismatched_refs = {}
    for ext in exts:
        repo = ext['repo']
        src = ext['source']
        dst = ext['destination']

        if repo not in ret:
            ret[repo] = {'targets': {src: [dst]}}
            if 'branch' in ext:
                ret[repo]['branch'] = ext['branch']
                ret[repo]['ref'] = ext['ref']
            else:
                ret[repo]['tag'] = ext['tag']
        else:
            def equal(lhs, rhs, field):
                return lhs.get(field, None) == rhs.get(field, None)

            if not equal(ret[repo], ext, 'branch') or \
                    not equal(ret[repo], ext, 'ref') or \
                    not equal(ret[repo], ext, 'tag'):
                mismatched_refs.setdefault(repo, [ret[repo]]).append(ext)
                log.critical('Branch or ref mismatch across different dirs of git ext')

            if dst not in ret[repo]['targets'].setdefault(src, []):
                ret[repo]['targets'][src].append(dst)

    return ret, mismatched_refs


def write_extfile(exts, config):
    gitexts = []
    for ext in exts:
        try:
            gitext = svnext_to_gitext(ext, config)
            gitexts.append(gitext)
        except SVNError:
            if not config['ignore_not_found']:
                raise
    gitexts, mismatched = group_gitexternals(gitexts)

    with open(config['externals_filename'], 'wt') as fd:
        json.dump(gitexts, fd, indent=4, sort_keys=True)

    if len(mismatched) > 0:
        with open(config['mismatched_refs_filename'], 'wt') as fp:
            json.dump(mismatched, fp, indent=4, sort_keys=True)


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

    path = path[len(repo_name)+1:]

    if len(path) == 0:
        return '.'

    remote_dir = path.split('/')

    def index(x):
        try:
            return remote_dir.index(x)
        except ValueError:
            return len(remote_dir)

    trunk_idx = index('trunk')
    branches_idx = index('branches')
    tags_idx = index('tags')

    first = min(trunk_idx, branches_idx, tags_idx)

    if first < len(remote_dir):
        if first == trunk_idx:
            remote_dir = remote_dir[first+1:]
        else:
            remote_dir = remote_dir[first+2:]

    if len(remote_dir) > 0:
        remote_dir = '/'.join(remote_dir)
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


def gittify_branch(gitsvn_repo, branch_name, obj, config):
    log.info('Gittifying branch {}'.format(branch_name))

    with chdir(os.path.join('..', gitsvn_repo)):
        with checkout(branch_name):
            git_ignore = git('svn', 'show-ignore')
            repo = gitsvn_url()

    with checkout(branch_name, obj):
        with open('.gitignore', 'wt') as fp:
            fp.write(git_ignore)
        git('add', '.gitignore')
        git('commit', '-m', 'gittify: convert svn:ignore to .gitignore',
            '--author="gittify <>"')

        externals = get_externals(repo)

        if len(externals) > 0:
            with log.indent():
                ext_to_write = []
                with chdir('..'):
                    for ext in externals:
                        # assume no multiple .., so it's a reference to the current repo
                        if not ext['location'].startswith('..'):
                            repo_name = extract_repo_name(ext['location'],
                                                          config['super_repos'])

                            gittified_externals = [os.path.splitext(os.path.basename(e))[0]
                                                   for e in gitsvn_cloned()]

                            gittified_name = posixpath.basename(repo_name)
                            if gittified_name not in gittified_externals:
                                log.info('{} is a SVN external, however it has not been found!'.format(gittified_name))
                                continue
                        ext_to_write.append(ext)

                write_extfile(ext_to_write, config)
                git('add', config['externals_filename'])
                if os.path.exists(config['mismatched_refs_filename']):
                    git('add', config['mismatched_refs_filename'])
                git('commit', '-m',
                    'gittify: create {} file'.format(config['externals_filename']),
                    '--author="gittify <>"')


def gittify(repo, config):
    repo_name = os.path.splitext(repo)[0]

    git_repo = repo_name + GIT_EXT
    gittified = set([repo_name])

    if os.path.exists(git_repo):
        log.info('{} already gittified'.format(repo_name))
        return gittified

    gitsvn_repo = repo_name + GITSVN_EXT

    # clone first in a working copy, because we need to perform checkouts, commit, etc...
    log.info('Cloning into final git repo {}'.format(git_repo))
    git('clone', gitsvn_repo, git_repo)

    with chdir(git_repo):
        for branch in git_remote_branches_and_tags()[0]:
            with checkout(name_of(branch), branch):
                pass

        log.info('Gittifying branches...')
        for branch in branches():
            gittify_branch(gitsvn_repo, branch, branch, config)

        log.info('Gittifying tags...')
        for tag in tags():
            gittify_branch(gitsvn_repo, tag, tag, config)

            # retag in case the dump was committed
            git('tag', '-d', tag)
            git('tag', tag, tag)

            git('branch', '-D', tag)

        remote_rm('origin')


def clone(repo, config):
    repo_name = posixpath.basename(repo)

    gitsvn_repo = repo_name + GITSVN_EXT

    if os.path.exists(gitsvn_repo):
        log.info('{} already cloned'.format(repo_name))
        return

    remote_repo = posixpath.join(config['svn_server'], repo)
    try:
        layout_opts = get_layout_opts(remote_repo)
    except SVNError as err:
        if config['ignore_not_found']:
            log.info('Ignoring error {}'.format(err))
            return
        raise

    authors_file_opt = []
    if config['authors_file'] is not None:
        authors_file_opt = ['-A', config['authors_file']]
    args = ['svn', 'clone', '--prefix=origin/'] + authors_file_opt + \
        layout_opts + [remote_repo, gitsvn_repo]

    log.info('Cloning {}'.format(remote_repo))
    log.info('Standard layout: {}'.format(len(layout_opts) == 3))
    log.info(' '.join(args))

    git(*args)
    cleanup(gitsvn_repo, False, remote_repo, log=log)

    with chdir(gitsvn_repo):
        log.info('Cloning externals in branches...')
        for branch in branches():
            clone_branch(branch, None, config)

        log.info('Cloning externals in tags...')
        for tag in tags():
            clone_branch(tag, tag, config)


def clone_branch(branch_name, obj, config):
    with checkout(branch_name, obj):
        externals = get_externals(gitsvn_url())

        if len(externals) > 0:
            log.info('Cloning externals...')
            with log.indent():
                with chdir('..'):
                    for ext in externals:
                        # assume no multiple .., so it's a reference to the current repo
                        if not ext['location'].startswith('..'):
                            repo_name = extract_repo_name(ext['location'], config['super_repos'])
                            clone(repo_name, config)


def gitsvn_cloned():
    return glob.iglob('*' + GITSVN_EXT)


def remove_gitsvn_repos():
    for tmp_repo in gitsvn_cloned():
        shutil.rmtree(tmp_repo)


def gitsvn_fetch_all(config):
    authors_file = config['authors_file']
    authors_file_opt = [] if authors_file is None else ['-A', authors_file]

    git('svn', 'fetch', '--all', *authors_file_opt)

    for branch in branches():
        log.info('Rebasing branch {}'.format(branch))
        with checkout(branch):
            git('svn', 'rebase', *authors_file_opt)

    url = gitsvn_url()
    root = extract_repo_root(url)
    repo_name = extract_repo_name(url[len(root):], config['super_repos'])

    remote_repo = posixpath.join(root, repo_name)

    cleanup('.', False, remote_repo, log=log)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('repos', nargs='*', help='SVN repos to migrate to Git')
    parser.add_argument('--git-server', default='/',
                        help='Url to use as base url for the git server')
    parser.add_argument('--filename', default='git_externals.json',
                        help='Filename of the json dump of the svn externals')
    parser.add_argument('--mismatched-filename', default='mismatched_ext.json',
                        help='Filename of the json dump of the svn externals those point to different revisions')
    parser.add_argument('--crash-on-404', default=False, action='store_true',
                        help='Give error if an external has not been found')
    parser.add_argument('--rm-gitsvn', default=False, action='store_true',
                        help='Remove gitsvn temporary repos')
    parser.add_argument('--finalize', default=False, action='store_true',
                        help='Clone into final git repos')
    parser.add_argument('--fetch', default=False, action='store_true',
                        help='Fetch from the svn repos')
    parser.add_argument('--super-repos', type=set, nargs='+',
                        default=set(['packages/', 'vendor/']),
                        help='A SVN super repo is not a real repo but it is a container of repos')
    parser.add_argument('-A', '--authors-file', default=None,
                        help='Authors file to map svn users to git')

    args = parser.parse_args()

    return args.repos, {
        'git_server': args.git_server,
        'externals_filename': args.filename,
        'mismatched_refs_filename': args.mismatched_filename,
        'ignore_not_found': not args.crash_on_404,
        'rm_gitsvn': args.rm_gitsvn,
        'finalize': args.finalize,
        'fetch': args.fetch,
        'super_repos': args.super_repos,
        'authors_file': None if args.authors_file is None else os.path.abspath(args.authors_file),
    }


def main():
    repos, config = parse_args()

    for r in repos:
        root = extract_repo_root(r)
        repo = r[len(root) + 1:]
        config['svn_server'] = root
        clone(repo, config)

    if config['fetch']:
        for gitsvn_repo in gitsvn_cloned():
            with chdir(gitsvn_repo):
                log.info('Fetching all in {}'.format(gitsvn_repo))
                gitsvn_fetch_all(config)

    if config['finalize']:
        for gitsvn_repo in gitsvn_cloned():
            with chdir(gitsvn_repo):
                config['svn_server'] = extract_repo_root(gitsvn_url())

            gittify(gitsvn_repo, config)

    if config['rm_gitsvn']:
        remove_gitsvn_repos()

if __name__ == '__main__':
    main()

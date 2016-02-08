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
from utils import git, svn, chdir, checkout, current_branch, SVNError, branches, \
    tags, IndentedLoggerAdapter
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
        source = extract_repo_path(ext['location'], ext_repo)

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
            # svn rev -> git sha
            rev = 'r' + ext['rev'] if ext['rev'][0] != 'r' else ext['rev']

            svn_ext_repo = loc[:-len(source)] if source != '.' else loc
            svn_repo = posixpath.join(config['svn_server'], svn_ext_repo)
            changed_rev = last_changed_rev_from(rev, svn_repo)

            with chdir(os.path.join('..', ext_repo + GITSVN_EXT)):
                with checkout(gitext['branch'], back_to=current_branch()):
                    gitext['ref'] = git('svn', 'find-rev', changed_rev).strip()
                    if gitext['ref'] == '':
                        gitext['ref'] = svnrev_to_gitsha(changed_rev)

    return gitext


def group_gitexternals(exts):
    ret = {}
    mismatched_refs = {}
    for ext in exts:
        repo = ext['repo']
        src = ext['source']
        dst = ext['destination']

        if repo not in ret:
            ret[repo] = {'targets' : {src: dst}}
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

            ret[repo]['targets'][src] = dst

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
        json.dump(gitexts, fd, indent=4)

    if len(mismatched) > 0:
        with open(config['mismatched_refs_filename'], 'wt') as fp:
            json.dump(mismatched, fp, indent=4)


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

    remote_dir = path.split('/')

    def index(x):
        try:
            return remote_dir.index(x)
        except ValueError:
            return -1

    i = index('trunk')
    if i >= 0:
        remote_dir = remote_dir[i+1:]
    else:
        i = index('branches')
        if i >= 0:
            remote_dir = remote_dir[i+2:]
        else:
            i = index('tags')
            if i >= 0:
                remote_dir = remote_dir[i+2:]
            else:
                i = index(repo_name)
                remote_dir = remote_dir[i+1:]

    if len(remote_dir) > 0:
        remote_dir = '/'.join(remote_dir)
    else:
        remote_dir = '.'

    return remote_dir


def get_layout_opts(repo):
    entries = set(svn('ls', repo).splitlines())

    opts = []
    has_trunk = has_branches = has_tags = False

    if 'trunk/' in entries:
        opts.append(
            '--trunk=trunk'
        )
        has_trunk = True

    if 'branches/' in entries:
        opts.append(
            '--branches=branches'
        )
        has_branches = True

    if 'tags/' in entries:
        opts.append(
            '--tags=tags'
        )
        has_tags = True

    return opts, has_trunk, has_branches, has_tags


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
        git('commit', '-m', 'gittify: convert svn:ignore to .gitignore',
            '--author="gittify <>"')

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
                if os.path.exists(config['mismatched_refs_filename']):
                    git('add', config['mismatched_refs_filename'])
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
        layout_opts, has_trunk, has_branches, _ = get_layout_opts(remote_repo)
    except SVNError as err:
        if config['ignore_not_found']:
            log.info('Ignoring error {}'.format(err))
            return set()
        raise

    if not os.path.exists(gitsvn_repo):
        authors_file_opt = []
        if config['authors_file'] is not None:
            authors_file_opt = ['-A', config['authors_file']]
        args = ['svn', 'clone', '--prefix=origin/'] + authors_file_opt + \
                layout_opts + [remote_repo, gitsvn_repo]

        log.info('Cloning {}'.format(remote_repo))
        log.info('standard layout: {}'.format(len(layout_opts) == 3))
        log.info(' '.join(args))

        git(*args)
        cleanup(gitsvn_repo, False, remote_repo, log=log)

        with chdir(gitsvn_repo):
            log.info('Gittifying branches...')
            for branch in branches():
                if branch != 'master' and has_branches:
                    subrepo = posixpath.join(repo, 'branches', branch)
                elif branch == 'master' and has_trunk:
                    subrepo = posixpath.join(repo, 'trunk')
                else:
                    subrepo = repo

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
    parser.add_argument('--mismatched-filename', default='mismatched_ext.json',
                        help='Filename of the json dump of the svn externals those point to different revisions')
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
        'mismatched_refs_filename': args.mismatched_filename,
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

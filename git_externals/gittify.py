#!/usr/bin/env python

from __future__ import division, print_function, absolute_import

import os
import os.path
import posixpath
import shutil
import json
import glob
import re
import sys
import argparse
import logging
from subprocess import check_call
from collections import defaultdict
from contextlib import contextmanager

try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse

try:
    from lxml import etree as ET
except ImportError:
    from xml.etree import ElementTree as ET

try:
    from pathlib2 import Path
except ImportError:
    from pathlib import Path

import click

from . import cleanup_repo
from .utils import git, svn, chdir, checkout, current_branch, SVNError, branches, \
    tags, IndentedLoggerAdapter, git_remote_branches_and_tags
from .process_externals import parsed_externals

GITSVN_EXT = '.gitsvn'
GIT_EXT = '.git'

logging.basicConfig(format='%(levelname)8s %(asctime)s: %(message)s',
                    level=logging.INFO, datefmt='%Y-%m-%d %I:%m:%S')
log = IndentedLoggerAdapter(logging.getLogger(__name__))


def echo(*args):
    click.echo(' '.join(args))


def info(*args):
    click.secho(' '.join(args), fg='blue')


def warn(*args):
    click.secho(' '.join(args), fg='red')


def error(*args, **kwargs):
    click.secho(' '.join(args), fg='red')
    exitcode = kwargs.get('exitcode', 1)
    if exitcode is not None:
        sys.exit(exitcode)

# Regexs
BRANCH_RE = re.compile(r'branches/([^/]+)')
TAG_RE = re.compile(r'tags/([^/]+)')


@click.group()
@click.option('--gitsvn-dir', type=click.Path(resolve_path=True), default='gitsvn')
@click.option('--gittify-dir', type=click.Path(resolve_path=True), default='gittify')
@click.pass_context
def cli(ctx, gitsvn_dir, gittify_dir):
    ctx.obj['gitsvn_dir'] = gitsvn_dir = Path(gitsvn_dir)
    if not gitsvn_dir.exists():
        gitsvn_dir.mkdir()
    ctx.obj['gittify_dir'] = gittify_dir = Path(gittify_dir)
    if not gittify_dir.exists():
        gittify_dir.mkdir()


def get_externals(repo, skip_relative=False):
    data = svn('propget', '--xml', '-R', 'svn:externals', repo, universal_newlines=False)

    targets = ET.fromstring(data).findall('target')

    externals = parsed_externals(targets)
    if skip_relative:
        externals = (e for e in externals if not e['location'].startswith('..'))
    return list(externals)


def svn_path_type(repo, revision=None, cache={}):
    if (repo, revision) in cache:
        return cache[(repo, revision)]
    args = ['info', '--xml']
    if revision is not None:
        args += ['-r', str(revision)]
    data = svn(*args + [repo], universal_newlines=False)
    cache[(repo, revision)] = res = ET.fromstring(data).find('./entry').get('kind')
    return res


def last_changed_rev_from(rev, repo):
    data = svn('info', '--xml', '-{}'.format(rev), repo, universal_newlines=False)

    rev = ET.fromstring(data).find('./entry/commit').get('revision')
    return 'r{}'.format(rev)


def svnrev_to_gitsha(repo, branch, rev, cache={}):

    def _svnrev_to_gitsha(rev):
        gitsvn_id_re = re.compile(r'(\w+) .*git-svn-id: [^@]+@{}'.format(rev[1:]), re.S)
        data = git('log', '--format="%H %b"')

        match = gitsvn_id_re.search(data)
        if match is not None:
            return match.group(1)
        else:
            log.error("Unable to find a valid sha for revision: %s in %s", rev, os.path.basename(os.getcwd()))
            return None

    if (repo, branch, rev) in cache:
        return cache[(repo, branch, rev)]
    else:
        cache[(repo, branch, rev)] = sha = _svnrev_to_gitsha(rev)
        return sha


def gitsvn_url():
    return git('svn', 'info', '--url').strip()


def svnext_to_gitext(ext, config, cache={}):
    key = '{}{}'.format(ext, config)
    if key in cache:
        return cache[key]

    gitext = {}

    path = urlparse(ext['target']).path

    repo_name = extract_repo_name(path, config['super_repos'])
    remote_dir = extract_repo_path(path, repo_name)

    gitext['destination'] = posixpath.join(remote_dir, ext['path'])

    loc = ext['location'].lstrip('/')

    complete_ext_repo = extract_repo_name(ext['location'], config['super_repos'])
    ext_repo = posixpath.basename(complete_ext_repo)
    if ext_repo.startswith('.'):
        source = posixpath.join(remote_dir, ext['location'])
        gitext['source'] = source

        # assume for simplicity it's the current repo(e.g. multiple .. not allowed)
        ext_repo = repo_name
    else:
        source = extract_repo_path(ext['location'], complete_ext_repo)
        try:
            is_dir = svn_path_type(posixpath.join(config['svn_server'], loc), revision=ext['rev']) == 'dir'
        except SVNError as err:
            warn(str(err))
            is_dir = True
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
            gitext['ref'] = 'svn:' + ext['rev'].strip('r')

    cache[key] = gitext
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


def write_extfile(gitexts, externals_filename, mismatched_refs_filename):
    gitexts, mismatched = group_gitexternals(gitexts)

    with open(externals_filename, 'wt') as fd:
        json.dump(gitexts, fd, indent=4, sort_keys=True)

    if len(mismatched) > 0:
        with open(mismatched_refs_filename, 'wt') as fp:
            json.dump(mismatched, fp, indent=4, sort_keys=True)


def extract_repo_name(remote_name, super_repos=None):
    super_repos = super_repos or []

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


def extract_repo_root(repo, cache={}):
    if repo in cache:
        return cache[repo]

    output = svn('info', '--xml', repo)

    rootnode = ET.fromstring(output)
    cache[repo] = root = rootnode.find('./entry/repository/root').text
    return root


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


def gittify_branch(gitsvn_repo, branch_name, obj, config, mode='branch', finalize=False):
    log.info('Gittifying {} {} [{}]'.format(mode, branch_name, 'finalizze' if finalize else 'prepare'))

    with chdir(os.path.join('..', gitsvn_repo)):
        with checkout(branch_name):
            git_ignore = git('svn', 'show-ignore')
            repo = gitsvn_url()

    with checkout(branch_name, obj):
        if finalize:
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
                        try:
                            gitext = svnext_to_gitext(ext, config)
                        except SVNError:
                            if not config['ignore_not_found']:
                                raise
                        ext_to_write.append(gitext)

                if finalize:
                    # If tagging, not ready to write
                    write_extfile(ext_to_write, config)
                    git('add', config['externals_filename'])
                    if os.path.exists(config['mismatched_refs_filename']):
                        git('add', config['mismatched_refs_filename'])
                    git('commit', '-m',
                        'gittify: create {} file'.format(config['externals_filename']),
                        '--author="gittify <>"')


def gittify(repo, config, checkout_branches=False, finalize=False):
    repo_name = os.path.splitext(repo)[0]

    git_repo = repo_name + GIT_EXT
    gittified = set([repo_name])
    gitsvn_repo = repo_name + GITSVN_EXT

    # clone first in a working copy, because we need to perform checkouts, commit, etc...
    if not os.path.exists(git_repo):
        log.info('Cloning into final git repo {}'.format(git_repo))
        git('clone', gitsvn_repo, git_repo)

    with chdir(git_repo):
        if checkout_branches:
            for branch in git_remote_branches_and_tags()[0]:
                with checkout(cleanup_repo.name_of(branch), branch):
                    pass

        log.info('Gittifying branches...')
        for branch in branches():
            gittify_branch(gitsvn_repo, branch, branch, config, finalize=finalize)

        log.info('Gittifying tags...')
        for tag in tags():
            gittify_branch(gitsvn_repo, tag, tag, config, mode='tag', finalize=finalize)

            if finalize:
                # retag in case the dump was committed
                git('tag', '-d', tag)
                git('tag', tag, tag)

                git('branch', '-D', tag)

        if finalize:
            remote_rm('origin')


@cli.command('clone')
@click.argument('root', metavar='SVNROOT')
@click.argument('path', metavar='REPOPATH')
@click.argument('authors-file', type=click.Path(exists=True, resolve_path=True),
                metavar='USERMAP')
@click.option('--dry-run', is_flag=True)
@click.pass_context
def clone(ctx, root, path, authors_file, dry_run):
    remote_repo = posixpath.join(root, path)
    info('Cloning {}'.format(remote_repo))
    repo_name = posixpath.basename(remote_repo)
    gitsvn_repo = ctx.obj['gitsvn_dir'] / (path + GITSVN_EXT)

    if not gitsvn_repo.parent.exists():
        if dry_run:
            echo('mkdir %s' % gitsvn_repo.parent)
        else:
            gitsvn_repo.parent.mkdir()

    if gitsvn_repo.exists():
        echo('{} already cloned'.format(repo_name))
        return

    args = ['git', 'svn', 'clone', '--prefix=origin/']

    if authors_file is not None:
        args += ['-A', authors_file]

    try:
        layout_opts = get_layout_opts(remote_repo)
        args += layout_opts
    except SVNError as err:
        error('Error {} in {}'.format(err, remote_repo))

    args += [remote_repo, str(gitsvn_repo)]

    echo(' '.join(map(str, args)))

    if not dry_run:
        check_call(args)

    """
    cleanup_repo.cleanup(gitsvn_repo, False, remote_repo, log=log)

    with chdir(gitsvn_repo):
        log.info('Cloning externals in branches...')
        for branch in branches():
            clone_branch(branch, None, config)

        log.info('Cloning externals in tags...')
        for tag in tags():
            clone_branch(tag, tag, config)
    """


@cli.command('fetch')
@click.argument('root', metavar='SVNROOT')
@click.argument('path', metavar='REPOPATH')
@click.argument('authors-file', type=click.Path(exists=True, resolve_path=True),
                metavar='USERMAP')
@click.option('--dry-run', is_flag=True)
@click.pass_context
def fetch(ctx, root, path, authors_file, dry_run, git=git, checkout=checkout, check_call=check_call):
    remote_repo = posixpath.join(root, path)
    info('Fetching {}'.format(remote_repo))
    repo_name = posixpath.basename(remote_repo)
    gitsvn_repo = ctx.obj['gitsvn_dir'] / (path + GITSVN_EXT)
    with chdir(str(gitsvn_repo)):
        if dry_run:
            git = echo
            check_call = echo
            @contextmanager
            def checkout(x):
                echo('checkout', x)
                yield
        check_call(['git','svn', 'fetch', '--all', '-A', authors_file])
        for branch in branches():
            with checkout(branch):
                check_call(['git', 'svn', 'rebase', '-A', authors_file])


@cli.command('cleanup')
@click.argument('root', metavar='SVNROOT')
@click.argument('path', metavar='REPOPATH')
@click.option('--dry-run', is_flag=True)
@click.pass_context
def cleanup(ctx, root, path, dry_run, git=git, checkout=checkout):
    remote_repo = posixpath.join(root, path)
    info('Cleaning {}'.format(remote_repo))
    repo_name = posixpath.basename(remote_repo)
    gitsvn_repo = ctx.obj['gitsvn_dir'] / (path + GITSVN_EXT)
    class log2click(object):
        @staticmethod
        def info(*args):
            echo(*args)
        @staticmethod
        def warning(*args):
            info(*args)
    if dry_run:
        echo('cleanup', str(gitsvn_repo), remote=remote_repo)
    else:
        cleanup_repo.cleanup(str(gitsvn_repo), remote=remote_repo, log=log2click)


@cli.command('finalize')
@click.argument('root', metavar='SVNROOT')
@click.argument('path', metavar='REPOPATH')
@click.option('--ignore-not-found', is_flag=True)
@click.option('--externals-filename', default='git_externals.json')
@click.option('--mismatched-refs-filename', default='mismatched_ext.json')
@click.option('--dry-run', is_flag=True)
@click.pass_context
def finalize(ctx, root, path, ignore_not_found, externals_filename, mismatched_refs_filename,
             dry_run, git=git, checkout=checkout, check_call=check_call):
    gitsvn_repo = ctx.obj['gitsvn_dir'] / (path + GITSVN_EXT)
    git_repo = ctx.obj['gittify_dir'] / (path + GIT_EXT)
    info('Finalize {}'.format(git_repo))

    if dry_run:
        git = echo
        check_call = echo
        @contextmanager
        def checkout(x, target=''):
            echo('checkout', x, target)
            yield
        def add_extfile(*args):
            echo('add_extfile')
        def add_ignores(*args):
            echo('add_ignores')

    config = {'super_repos': ['packages/', 'vendor/'],
              'svn_server': root,
              'git_server': 'foo',
              'basedir': str(ctx.obj['gitsvn_dir']),
              }

    def prefix(config, path):
        if path.startswith('/packages/'):
            git_server = 'packages/'
        elif path.startswith('/vendor/'):
            git_server = 'vendor/'
        else:
            git_server = 'foo'
        config = dict(config)
        config['git_server'] = git_server
        return config

    def add_ignores(git_ignore):
        with open('.gitignore', 'wt') as fp:
            fp.write(git_ignore)
        check_call(['git', 'add', '.gitignore'])
        check_call(['git', 'commit', '-m', 'gittify: convert svn:ignore to .gitignore',
                    '--author="gittify <>"'])

    def add_extfile(ext_to_write, tag=None):
        write_extfile(ext_to_write, externals_filename, mismatched_refs_filename)
        check_call(['git', 'add', externals_filename])
        if os.path.exists(mismatched_refs_filename):
            check_call(['git', 'add', mismatched_refs_filename])
        check_call(['git', 'commit', '-m', 'gittify: create {} file'.format(externals_filename),
                    '--author="gittify <>"'])
        if tag is not None:
            # retag in case the dump was committed
            check_call(['git', 'tag', '-d', tag])
            check_call(['git', 'tag', tag, tag])

    def _svn2git_metadata(gitsvn_repo, branch_name, tag=None):
        with chdir(str(gitsvn_repo)):
            with checkout(branch_name):
                git_ignore = git('svn', 'show-ignore')
                svn_url = gitsvn_url()

        externals = []
        check_call(['git', 'stash'])
        with checkout(branch_name, branch_name, force=True):
            for ext in get_externals(svn_url, skip_relative=True):
                echo('... processing external %s ...' % ext['location'])
                externals += [svnext_to_gitext(ext, prefix(config, ext['location']))]
            add_ignores(git_ignore)
            add_extfile(externals, tag=tag)

    with chdir(str(git_repo)):
        echo('Searching externals in branches...')
        for branch in branches():
            echo('.. searching in branch %s ...' % branch)
            _svn2git_metadata(gitsvn_repo, branch)

    with chdir(str(git_repo)):
        echo('Searching externals in tags...')
        for tag in tags():
            echo('.. searching in tag %s ...' % tag)
            _svn2git_metadata(gitsvn_repo, tag, tag=tag)


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

    check_call(['git', 'svn', 'fetch', '--all'] + authors_file_opt)

    for branch in branches():
        log.info('Rebasing branch {}'.format(branch))
        with checkout(branch):
            check_call(['git', 'svn', 'rebase'] + authors_file_opt)

    url = gitsvn_url()
    root = extract_repo_root(url)
    repo_name = extract_repo_name(url[len(root):], config['super_repos'])

    remote_repo = posixpath.join(root, repo_name)

    cleanup_repo.cleanup('.', False, remote_repo, log=log)


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
    parser.add_argument('-n', '--no-authors-file', default=False, action='store_true',
                        help='Continue without users mapping file')

    args = parser.parse_args()

    return args.repos, {
        'basedir': os.getcwd(),
        'git_server': args.git_server,
        'externals_filename': args.filename,
        'mismatched_refs_filename': args.mismatched_filename,
        'ignore_not_found': not args.crash_on_404,
        'rm_gitsvn': args.rm_gitsvn,
        'finalize': args.finalize,
        'fetch': args.fetch,
        'super_repos': args.super_repos,
        'authors_file': None if args.authors_file is None else os.path.abspath(args.authors_file),
        'no_authors_file': args.no_authors_file,
    }


def old_main():
    repos, config = parse_args()

    for r in repos:
        log.info("---- Cloning %s ----", r)
        root = extract_repo_root(r)
        repo = r[len(root) + 1:]
        config['svn_server'] = root
        clone(repo, config)

    if config['fetch']:
        if config['authors_file'] is None:
            log.warn('Fetching without authors-file')
            if not config['no_authors_file']:
                log.error('Provide --no-authors-file to continue without user mapping')
                sys.exit(2)
        for gitsvn_repo in gitsvn_cloned():
            with chdir(gitsvn_repo):
                log.info('---- Fetching all in {} ----'.format(gitsvn_repo))
                gitsvn_fetch_all(config)

    if config['finalize']:
        for gitsvn_repo in gitsvn_cloned():
            log.info("---- Pre-Finalize %s ----", gitsvn_repo)
            with chdir(gitsvn_repo):
                config['svn_server'] = extract_repo_root(gitsvn_url())

            gittify(gitsvn_repo, config)

        for gitsvn_repo in gitsvn_cloned():
            log.info("---- Finalize %s ----", gitsvn_repo)
            with chdir(gitsvn_repo):
                config['svn_server'] = extract_repo_root(gitsvn_url())

            gittify(gitsvn_repo, config, finalize=True)

    if config['rm_gitsvn']:
        remove_gitsvn_repos()


def main():
    cli(obj={})


if __name__ == '__main__':
    main()

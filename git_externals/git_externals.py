#!/usr/bin/env python

from __future__ import print_function, unicode_literals

if __package__ is None:
    import sys
    from os import path
    sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))

import json
import os
import os.path
import posixpath
from collections import defaultdict, namedtuple

try:
    from urllib.parse import urlparse, urlsplit, urlunsplit
except ImportError:
    from urlparse import urlparse, urlsplit, urlunsplit

import click

from .utils import (chdir, mkdir_p, link, rm_link, git, GitError, svn, gitsvn, gitsvnrebase, current_branch)
from .cli import echo, info, error


EXTERNALS_ROOT = os.path.join('.git', 'externals')
EXTERNALS_JSON = 'git_externals.json'

ExtItem = namedtuple('ExtItem', ['branch', 'ref', 'path', 'name'])


def get_repo_name(repo):
    externals = load_gitexts()
    if repo in externals and 'name' in externals[repo]:
        # echo ("for {} in pwd:{} returning {}".format(repo, os.getcwd(),
        #                                              externals[repo]['name']))
        return externals[repo]['name']

    if repo[-1] == '/':
        repo = repo[:-1]
    name = repo.split('/')[-1]
    if name.endswith('.git'):
        name = name[:-len('.git')]
    if not name:
        error("Invalid repository name: \"{}\"".format(repo), exitcode=1)
    return name


def externals_json_path():
    return os.path.join(root_path(), EXTERNALS_JSON)


def externals_root_path():
    return os.path.join(root_path(), EXTERNALS_ROOT)


def root_path():
    return git('rev-parse', '--show-toplevel').strip()


def is_git_repo(quiet=True):
    """Says if pwd is a Git working tree or not.
    If not quiet: says it also on standard output
    """
    try:
        return git('rev-parse', '--is-inside-work-tree').strip() == 'true'
    except GitError as err:
        if not quiet:
            print (str(err))


def normalize_gitext_url(url):
    # an absolute url is already normalized
    if urlparse(url).netloc != '' or url.startswith('git@'):
        return url

    # relative urls use the root url of the current origin
    remote_name = git('config', 'branch.%s.remote' % current_branch()).strip()
    remote_url = git('config', 'remote.%s.url' % remote_name).strip()

    if remote_url.startswith('git@'):
        prefix = remote_url[:remote_url.index(':')+1]
        remote_url = prefix + url.strip('/')
    else:
        remote_url = urlunsplit(urlsplit(remote_url)._replace(path=url))

    return remote_url


def get_entries():
    return [get_repo_name(e)
            for e in load_gitexts().keys()
            if os.path.exists(os.path.join(externals_root_path(), get_repo_name(e)))]


def load_gitexts(pwd=None):
    """Load the *externals definition file* present in given
    directory, or cwd
    """
    d = pwd if pwd is not None else '.'
    fn = os.path.join(d, EXTERNALS_JSON)
    if os.path.exists(fn):
        with open(fn) as f:
            gitext = json.load(f)
            for url, _ in gitext.items():
                # svn external url must be absolute
                gitext[url]['vcs'] = 'svn' if 'svn' in urlparse(url).scheme else 'git'
            return gitext
    return {}


def dump_gitexts(externals):
    """
    Dump externals dictionary as json in current working directory
    git_externals.json. Remove 'vcs' key that is only used at runtime.
    """
    with open(externals_json_path(), 'w') as f:
        # copy the externals dict (we want to keep the 'vcs')
        dump = {k: v for k,v in externals.items()}
        for v in dump.values():
            if 'vcs' in v:
                del v['vcs']
        json.dump(dump, f, sort_keys=True, indent=4, separators=(',', ': '))


def foreach_externals(pwd, callback, recursive=True, only=()):
    """
    Iterates over externals, starting from directory pwd, recursively or not
    callback is called for each externals with the following arguments:
        - relative url of current external repository
        - path to external working tree directory
        - refs: external as a dictionary (straight from json file)
    Iterates over all externals by default, or filter over the externals listed
    in only (filters on externals path, url or part of it)
    """
    externals = load_gitexts(pwd)
    def filter_ext():
        def take_external(url, path):
            return any((expr in url or expr in path) for expr in only)
        def take_all(*args):
            return True
        return take_external if len(only) else take_all

    for rel_url in externals:
        ext_path = os.path.join(pwd, EXTERNALS_ROOT, get_repo_name(rel_url))
        if filter_ext()(rel_url, ext_path):
            callback(rel_url, ext_path, externals[rel_url])
        if recursive:
            foreach_externals(ext_path, callback, recursive=recursive, only=only)


def foreach_externals_dir(pwd, callback, recursive=True, only=[]):
    """
    Same as foreach_externals, but place the callback in the directory
    context of the externals before calling it
    """
    def run_from_dir(rel_url, ext_path, refs):
        if os.path.exists(ext_path):
            with chdir(ext_path):
                callback(rel_url, ext_path, refs)
    foreach_externals(root_path(), run_from_dir, recursive=recursive, only=only)


def sparse_checkout(repo_name, repo, dirs):
    git('init', repo_name)

    with chdir(repo_name):
        git('remote', 'add', '-f', 'origin', repo)
        git('config', 'core.sparsecheckout', 'true')

        with open(os.path.join('.git', 'info', 'sparse-checkout'), 'wt') as fp:
            fp.write('{}\n'.format(externals_json_path()))
            for d in dirs:
                # assume directories are terminated with /
                fp.write(posixpath.normpath(d))
                if d[-1] == '/':
                    fp.write('/')
                fp.write('\n')

    return repo_name


def is_workingtree_clean(path, fail_on_empty=True):
    """
    Returns true if and only if there are no modifications to tracked files. By
    modifications it is intended additions, deletions, file removal or
    conflicts. If True is returned, that means that performing a
    `git reset --hard` would result in no loss of local modifications because:
    - tracked files are unchanged
    - untracked files are not modified anyway
    """
    if not os.path.exists(path):
        return not fail_on_empty
    if fail_on_empty and not os.path.exists(path):
        return False
    with chdir(path):
        try:
            return len([line.strip for line in git('status', '--untracked-files=no', '--porcelain').splitlines(True)]) == 0
        except GitError as err:
            echo('Couldn\'t retrieve Git status of', path)
            error(str(err), exitcode=err.errcode)


def link_entries(git_externals):
    entries = [(get_repo_name(repo), src, os.path.join(os.getcwd(), dst.replace('/', os.path.sep)))
               for (repo, repo_data) in git_externals.items()
               for (src, dsts) in repo_data['targets'].items()
               for dst in dsts]

    entries.sort(key=lambda x: x[2])

    # remove links starting from the deepest dst
    for _, __, dst in entries[::-1]:
        if os.path.lexists(dst):
            rm_link(dst)

    # link starting from the highest dst
    for repo_name, src, dst in entries:
        with chdir(os.path.join(externals_root_path(), repo_name)):
            mkdir_p(os.path.split(dst)[0])
            link(os.path.abspath(src), dst)


def externals_sanity_check():
    """Check that we are not trying to track various refs of the same external repo"""
    registry = defaultdict(set)
    root = root_path()

    def registry_add(url, path, ext):
        registry[url].add(ExtItem(ext['branch'], ext['ref'], path, ext.get('name', '')))

    foreach_externals(root, registry_add, recursive=True)
    errmsg = None
    for url, set_ in registry.items():
        # we are only interested to know if branch-ref pairs are duplicated
        if len({(s[0], s[1]) for s in set_}) > 1:
            if errmsg is None:
                errmsg = ["Error: one project can not refer to different branches/refs of the same git external repository,",
                          "however it appears to be the case for:"]
            errmsg.append('\t- {}, tracked as:'.format(url))
            for i in set_:
                errmsg.append("\t\t- external directory: '{0}'".format(os.path.relpath(i.path, root)))
                errmsg.append("\t\t  branch: '{0}', ref: '{1}'".format(i.branch, i.ref))
    if errmsg is not None:
        errmsg.append("Please correct the corresponding {0} before proceeding".format(EXTERNALS_JSON))
        error('\n'.join(errmsg), exitcode=1)
    info('externals sanity check passed!')

    # TODO: check if  we don't have duplicate entries under .git/externals


def filter_externals_not_needed(all_externals, entries):
    git_externals = {}
    for repo_name, repo_val in all_externals.items():
        filtered_targets = {}
        for src, dsts in repo_val['targets'].items():
            filtered_dsts = []
            for dst in dsts:
                inside_external = any([os.path.abspath(dst).startswith(e) for e in entries])
                if inside_external:
                    filtered_dsts.append(dst)

            if filtered_dsts:
                filtered_targets[src] = filtered_dsts

        if filtered_targets:
            git_externals[repo_name] = all_externals[repo_name]
            git_externals[repo_name]['targets'] = filtered_targets

    return git_externals


def gitext_up(recursive, entries=None, reset=False, use_gitsvn=False):

    if not os.path.exists(externals_json_path()):
        return

    all_externals = load_gitexts()
    git_externals = all_externals if entries is None else filter_externals_not_needed(all_externals, entries)

    def egit(command, *args):
        if command == 'checkout' and reset:
            args = ('--force',) + args
        git(command, *args, capture=False)

    def git_initial_checkout(repo_name, repo_url):
        """Perform the initial git clone (or sparse checkout)"""
        dirs = git_externals[ext_repo]['targets'].keys()
        if './' not in dirs:
            echo('Doing a sparse checkout of:', ', '.join(dirs))
            sparse_checkout(repo_name, repo_url, dirs)
        else:
            egit('clone', repo_url, repo_name)

    def git_update_checkout(reset):
        """Update an already existing git working tree"""
        if reset:
            egit('reset', '--hard')
            egit('clean', '-df')
        egit('fetch', '--all')
        egit('fetch', '--tags')
        if 'tag' in git_externals[ext_repo]:
            echo('Checking out tag', git_externals[ext_repo]['tag'])
            egit('checkout', git_externals[ext_repo]['tag'])
        else:
            echo('Checking out branch', git_externals[ext_repo]['branch'])
            egit('checkout', git_externals[ext_repo]['branch'])
            egit('pull', 'origin', git_externals[ext_repo]['branch'])

            if git_externals[ext_repo]['ref'] is not None:
                echo('Checking out commit', git_externals[ext_repo]['ref'])
                ref = git_externals[ext_repo]['ref']
                if git_externals[ext_repo]['ref'].startswith('svn:'):
                    ref = egit('log', '--grep', 'git-svn-id:.*@%s' % ref.strip('svn:r'), '--format=%H').strip()
                egit('checkout', ref)

    def gitsvn_initial_checkout(repo_name, repo_url):
        """Perform the initial git-svn clone (or sparse checkout)"""
        import re
        m = re.match(r'(?:svn:)?(?:r)?(\d+)', git_externals[ext_repo]['ref'])
        rev = m.groups()[0] if m is not None else 'HEAD'
        gitsvn('clone', normalized_ext_repo, repo_name, '-r'+rev, capture=False)

    def gitsvn_update_checkout(reset):
        """Update an already existing git-svn working tree"""
        # FIXME: seems this might be necessary sometimes (happened with
        # 'vectorfonts' for example that the following error: "Unable to
        # determine upstream SVN information from HEAD history" was fixed by
        # adding that, but breaks sometimes. (investigate)
        # git('rebase', '--onto', 'git-svn', '--root', 'master')
        # gitsvnrebase('.', capture=False)

    def svn_initial_checkout(repo_name, repo_url):
        """Perform the initial svn checkout"""
        svn('checkout', '--ignore-externals', normalized_ext_repo, repo_name, capture=False)

    def svn_update_checkout(reset):
        """Update an already existing svn working tree"""
        if reset:
            svn('revert', '-R', '.')
        svn('up', '--ignore-externals', capture=False)

    def autosvn_update_checkout(reset):
        if os.path.exists('.git'):
            gitsvn_update_checkout(reset)
        else:
            svn_update_checkout(reset)

    for ext_repo in git_externals.keys():
        normalized_ext_repo = normalize_gitext_url(ext_repo)

        if all_externals[ext_repo]['vcs'] == 'git':
            _initial_checkout = git_initial_checkout
            _update_checkout = git_update_checkout
        else:
            if use_gitsvn:
                _initial_checkout = gitsvn_initial_checkout
            else:
                _initial_checkout = svn_initial_checkout
            _update_checkout = autosvn_update_checkout

        mkdir_p(externals_root_path())
        with chdir(externals_root_path()):
            repo_name = get_repo_name(normalized_ext_repo)
            ext_name = git_externals[ext_repo].get('name', '')
            ext_name = ext_name if ext_name else repo_name

            info('External', ext_name)
            if not os.path.exists(ext_name):
                echo('Cloning external', ext_name)
                _initial_checkout(ext_name, normalized_ext_repo)

            with chdir(ext_name):
                echo('Retrieving changes from server: ', ext_name)
                _update_checkout(reset)

    link_entries(git_externals)

    if recursive:
        for ext_repo in git_externals.keys():
            entries = [os.path.realpath(d)
                       for t in git_externals[ext_repo]['targets'].values()
                       for d in t]
            with chdir(os.path.join(externals_root_path(), get_repo_name(ext_repo))):
                gitext_up(recursive, entries, reset=reset, use_gitsvn=use_gitsvn)


def gitext_recursive_info(root_dir):
    git_exts = load_gitexts()
    git_exts = {ext_repo: ext for ext_repo, ext in git_exts.items()
                if os.path.exists(os.path.join(externals_root_path(), get_repo_name(ext_repo)))}

    for ext_repo, ext in git_exts.items():
        print_gitext_info(ext_repo, ext, root_dir=root_dir)

    for ext_repo, ext in git_exts.items():
        entries = [os.path.realpath(d)
                   for t in git_exts[ext_repo]['targets'].values()
                   for d in t]

        cwd = os.getcwd()

        with chdir(os.path.join(externals_root_path(), get_repo_name(ext_repo))):
            filtered = filter_externals_not_needed(load_gitexts(), entries)

            for dsts in ext['targets'].values():
                for dst in dsts:
                    real_dst = os.path.realpath(os.path.join(cwd, dst))

                    has_deps = any([os.path.realpath(d).startswith(real_dst)
                                    for e in filtered.values()
                                    for ds in e['targets'].values()
                                    for d in ds])

                    if has_deps:
                        gitext_recursive_info(os.path.join(root_dir, dst))


def print_gitext_info(ext_repo, ext, root_dir):
    click.secho('Repo:   {}'.format(ext_repo), fg='blue')

    if 'tag' in ext:
        click.echo('Tag:    {}'.format(ext['tag']))
    else:
        click.echo('Branch: {}'.format(ext['branch']))
        click.echo('Ref:    {}'.format(ext['ref']))

    if 'name' in ext:
        click.echo('Name:    {}'.format(ext['name']))

    for src, dsts in ext['targets'].items():
        for dst in dsts:
            click.echo('  {} -> {}'.format(src, os.path.join(root_dir, dst)))

    click.echo('')


def iter_externals(externals, verbose=True):
    if not externals:
        externals = get_entries()

    for entry in externals:
        entry_path = os.path.join(externals_root_path(), entry)

        if not os.path.exists(entry_path):
            error('External {} not found'.format(entry), exitcode=None)
            continue

        with chdir(entry_path):
            if verbose:
                info('External {}'.format(entry))
            yield entry

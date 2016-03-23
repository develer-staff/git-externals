#!/usr/bin/env python

from __future__ import print_function, unicode_literals

from . import __version__
from .utils import chdir, mkdir_p, link, rm_link, git, GitError

import click
import json
import os
import os.path
import sys
import posixpath
from collections import defaultdict, namedtuple

try:
    from urllib.parse import urlparse, urlunparse, urlsplit, urlunsplit
except ImportError:
    from urlparse import urlparse, urlunparse, urlsplit, urlunsplit

EXTERNALS_ROOT = os.path.join('.git', 'externals')
EXTERNALS_JSON = 'git_externals.json'

click.disable_unicode_literals_warning = True


def echo(*args):
    click.echo(' '.join(args))


def info(*args):
    click.secho(' '.join(args), fg='blue')


def error(*args, **kwargs):
    click.secho(' '.join(args), fg='red')
    exitcode = kwargs.get('exitcode', 1)
    if exitcode is not None:
        sys.exit(exitcode)


def get_repo_name(repo):
    name = repo.split('/')[-1]
    if name.endswith('.git'):
        name = name[:-len('.git')]
    return name


def externals_json_path():
    repo_root = git('rev-parse', '--show-toplevel').strip()
    return os.path.join(repo_root, EXTERNALS_JSON)


def externals_root_path():
    repo_root = git('rev-parse', '--show-toplevel').strip()
    return os.path.join(repo_root, EXTERNALS_ROOT)


def normalize_gitext_url(url):
    # an absolute url is already normalized
    if urlparse(url).netloc != '' or url.startswith('git@'):
        return url

    # relative urls use the root url of the current origin
    remote_url = git('config', 'remote.origin.url').strip()

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


def load_gitexts():
    if os.path.exists(externals_json_path()):
        with open(externals_json_path()) as fp:
            return json.load(fp)
    return {}


def load_gitexts(pwd=None):
    """Load the *externals definition file* present in given
    directory, or cwd
    """
    d = pwd if pwd is not None else '.'
    fn = os.path.join(d, EXTERNALS_JSON)
    if os.path.exists(fn):
        with open(fn) as f:
            return json.load(f)
    return {}


def dump_gitexts(externals):
    with open(externals_json_path(), 'wt') as fp:
        json.dump(externals, fp, sort_keys=True, indent=4)


def foreach_externals(pwd, callback=None):
    """
    Iterates over given externals.
    """
    externals = load_gitexts(pwd)
    for rel_url in externals:
        ext_path = os.path.join(pwd, EXTERNALS_ROOT, get_repo_name(rel_url))
        if callback is not None:
            callback(rel_url, ext_path, externals[rel_url])
        foreach_externals(ext_path, callback=callback)


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


def clean_repo():
    git('reset', '--hard')
    try:
        git('clean', '-d', '-x', '-f')
    except GitError:
        # ignore errors mostly due to the fact it is skipping dirs
        pass


def link_entries(git_externals):
    entries = [(get_repo_name(repo), src, os.path.join(os.getcwd(), dst))
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


def untrack(paths):
    with open(os.path.join('.git', 'info', 'exclude'), 'wt') as fp:
        for p in paths:
            if p.startswith('./'):
                p = p[2:]
            fp.write(p + '\n')


@click.group(invoke_without_command=True)
@click.version_option(__version__)
@click.option('--with-color/--no-color',
              default=True,
              help='Enable/disable colored output')
@click.pass_context
def cli(ctx, with_color):
    """Utility to manage git externals, meant to be used as a drop-in replacement to svn externals

    This script works cloning externals found in the `git_externals.json` file into `.git/externals` and
    then it uses symlinks to create the wanted directory layout.
    """

    if ctx.invoked_subcommand != 'add' and not os.path.exists(externals_json_path()):
        error("Unable to find", externals_json_path(), exitcode=1)

    if not os.path.exists(externals_root_path()):
        if ctx.invoked_subcommand not in set(['update', 'add']):
            error('You must first run git-externals update/add', exitcode=2)
    else:
        if with_color:
            enable_colored_output()

        if ctx.invoked_subcommand is None:
            gitext_st(())


@cli.command('update')
@click.option(
    '--with-hooks/--no-hooks',
    default=False,
    help=
    'Install post-checkout hook used to automatically update the working copy')
@click.option('--recursive/--no-recursive', help='Do not call git-externals update recursively', default=True)
@click.option('--no-confirm', help='Do not ask for confirmation before updating, OVERWRITING LOCAL MODIFICATIONS', is_flag=True)
def gitext_update(with_hooks, recursive, no_confirm):
    """Update the working copy cloning externals if needed and create the desired layout using symlinks
    """
    if with_hooks:
        install_hooks(recursive)

    externals_sanity_check()
    gitext_up(recursive, prompt_confirm=not no_confirm)


def externals_sanity_check():
    """Check that we are not trying to track various refs of the same external repo"""
    ExtItem = namedtuple('ExtItem', ['branch', 'ref'])
    registry = defaultdict(set)

    def registry_add(url, path, ext):
        registry[url].add(ExtItem(ext['branch'], ext['ref']))

    foreach_externals('.', registry_add)
    errmsg = None
    for url, set_ in registry.iteritems():
        if len(set_) > 1:
            if errmsg is None:
                errmsg = ["Error: one project can not refer to different branches/refs of the same git external repository,",
                    "however it appear that it's the case for:"]
            errmsg.append('\t- {}, tracked as:'.format(url))
            for i in set_:
                errmsg.append("\t\t- branch: '{0}', ref: '{1}'".format(i.branch, i.ref))
    if errmsg is not None:
        errmsg.append("Please correct the corresponding {0} before proceeding".format(EXTERNALS_JSON))
        error('\n'.join(errmsg), exitcode=1)
    info('externals sanity check passed!')


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


def gitext_up(recursive, entries=None, prompt_confirm=True):

    if prompt_confirm:
        print("""git externals update is about to perform a hard reset of your working tree.
ALL MODIFICATIONS WILL BE LOST""")
        try:
            click.confirm('Do you confirm?', abort=True)
        except click.Abort:
            print ('Aborted!')
            return

    clean_repo()
    if not os.path.exists(externals_json_path()):
        return

    all_externals = load_gitexts()
    git_externals = all_externals if entries is None else filter_externals_not_needed(all_externals, entries)

    for ext_repo in git_externals.keys():
        normalized_ext_repo = normalize_gitext_url(ext_repo)

        mkdir_p(externals_root_path())
        with chdir(externals_root_path()):
            repo_name = get_repo_name(normalized_ext_repo)

            info('External', repo_name)
            if not os.path.exists(repo_name):
                echo('Cloning external', repo_name)

                dirs = git_externals[ext_repo]['targets'].keys()
                if './' not in dirs:
                    sparse_checkout(repo_name, normalized_ext_repo, dirs)
                else:
                    git('clone', normalized_ext_repo, repo_name)

            with chdir(repo_name):
                git('fetch', '--all')
                git('fetch', '--tags')

                if 'tag' in git_externals[ext_repo]:
                    echo('Checking out tag', git_externals[ext_repo]['tag'])
                    git('checkout', git_externals[ext_repo]['tag'])
                else:
                    echo('Checking out branch', git_externals[ext_repo]['branch'])
                    git('checkout', git_externals[ext_repo]['branch'])
                    git('pull', 'origin', git_externals[ext_repo]['branch'])

                    if git_externals[ext_repo]['ref'] is not None:
                        echo('Checking out commit', git_externals[ext_repo]['ref'])
                        git('checkout', git_externals[ext_repo]['ref'])

    link_entries(git_externals)

    if recursive:
        for ext_repo in git_externals.keys():
            entries = [os.path.realpath(d)
                       for t in git_externals[ext_repo]['targets'].values()
                       for d in t]
            with chdir(os.path.join(externals_root_path(), get_repo_name(ext_repo))):
                gitext_up(recursive, entries, prompt_confirm=False)

    to_untrack = []
    for ext in git_externals.values():
        to_untrack += [dst for dsts in ext['targets'].values() for dst in dsts]
    untrack(to_untrack)


@cli.command('status')
@click.argument('external', nargs=-1)
@click.option(
    '--porcelain',
    is_flag=True,
    help='Print output using the porcelain format, useful mostly for scripts')
def gitext_st(external, porcelain):
    """Call git status on the given externals"""
    for _ in iter_externals(external):
        click.echo(git('status', '--porcelain' if porcelain else ''))


@cli.command('diff')
@click.argument('external', nargs=-1)
def gitext_diff(external):
    """Call git status on the given externals"""
    for _ in iter_externals(external):
        click.echo(git('diff'))


@cli.command('list')
def gitext_ls():
    """Print just a list of all externals used"""
    for entry in iter_externals([], verbose=False):
        info(entry)


@cli.command('add')
@click.argument('external',
                metavar='URL')
@click.argument('src', metavar='PATH')
@click.argument('dst', metavar='PATH')
@click.option('--branch', '-b', default=None, help='Checkout the given branch')
@click.option('--tag', '-t', default=None, help='Checkout the given tag')
@click.option(
    '--ref',
    '-r',
    default=None,
    help='Checkout the given commit sha, it requires that a branch is given')
def gitext_add(external, src, dst, branch, tag, ref):
    """Add a git external to the current repo.

    Be sure to add '/' to `src` if it's a directory!
    It's possible to add multiple `dst` to the same `src`, however you cannot mix different branches, tags or refs
    for the same external.

    It's safe to use this command to add `src` to an already present external, as well as adding
    `dst` to an already present `src`.

    It requires one of --branch or --tag.
    """
    git_externals = load_gitexts()

    if branch is None and tag is None:
        error('Please specifiy at least a branch or a tag', exitcode=3)

    if external not in git_externals:
        git_externals[external] = {'targets': {src: [dst]}}
        if branch is not None:
            git_externals[external]['branch'] = branch
            git_externals[external]['ref'] = ref
        else:
            git_externals[external]['tag'] = tag

    else:
        if branch is not None:
            if 'branch' not in git_externals[external]:
                error(
                    '{} is bound to tag {}, cannot set it to branch {}'.format(
                        external, git_externals[external]['tag'], branch),
                    exitcode=4)

            if ref != git_externals[external]['ref']:
                error('{} is bound to ref {}, cannot set it to ref {}'.format(
                    external, git_externals[external]['ref'], ref),
                      exitcode=4)

        elif 'tag' not in git_externals[external]:
            error('{} is bound to branch {}, cannot set it to tag {}'.format(
                external, git_externals[external]['branch'], tag),
                  exitcode=4)

        if dst not in git_externals[external]['targets'].setdefault(src, []):
            git_externals[external]['targets'][src].append(dst)

    dump_gitexts(git_externals)


@cli.command('remove')
@click.argument('external', nargs=-1, metavar='URL')
def gitext_remove(external):
    """Remove the externals at the given repository URLs """
    git_externals = load_gitexts()

    for ext in external:
        if ext in git_externals:
            del git_externals[ext]

    dump_gitexts(git_externals)


@cli.command('info')
@click.argument('external', nargs=-1)
@click.option('--recursive/--no-recursive', default=True, help='Print info only for top level externals')
def gitext_info(external, recursive):
    """Print some info about the externals."""

    if recursive:
        gitext_recursive_info('.')
        return

    external = set(external)
    git_externals = load_gitexts()

    filtered = [(ext_repo, ext)
                for (ext_repo, ext) in git_externals.items()
                if get_repo_name(ext_repo) in external]
    filtered = filtered or git_externals.items()

    for ext_repo, ext in filtered:
        print_gitext_info(ext_repo, ext, root_dir='.')


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


def install_hooks(recursive):
    hook_filename = os.path.join('.git', 'hooks', 'post-checkout')
    with open(hook_filename, 'wt') as fp:
        fp.write('#!/bin/sh\n')
        fp.write(
            '# see http://article.gmane.org/gmane.comp.version-control.git/281960\n')
        fp.write('unset GIT_WORK_TREE\n')
        fp.write('if [ $3 -ne 0 ]; then git externals update {}; fi;'.format('--no-recursive' if not recursive else ''))
    os.chmod(hook_filename, 0o755)


def enable_colored_output():
    for entry in get_entries():
        with chdir(os.path.join(externals_root_path(), entry)):
            git('config', 'color.ui', 'always')

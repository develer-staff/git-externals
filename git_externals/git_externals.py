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

DEFAULT_DIR = os.path.join('.git', 'externals')
FILENAME = 'git_externals.json'

click.disable_unicode_literals_warning = True


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


def get_entries():
    return [get_repo_name(e)
            for e in load_gitexts().keys()
            if os.path.exists(os.path.join(DEFAULT_DIR, get_repo_name(e)))]


def load_gitexts():
    if os.path.exists(FILENAME):
        with open(FILENAME) as fp:
            return json.load(fp)
    return {}


def dump_gitexts(externals):
    with open(FILENAME, 'wt') as fp:
        json.dump(externals, fp, sort_keys=True, indent=4)


def sparse_checkout(repo_name, repo, dirs, branch):
    git('init', repo_name)

    with chdir(repo_name):
        git('remote', 'add', '-f', 'origin', repo)
        git('config', 'core.sparsecheckout', 'true')

        with open(os.path.join('.git', 'info', 'sparse-checkout'), 'wt') as fp:
            fp.write('{}\n'.format(FILENAME))
            for d in dirs:
                # assume directories are terminated with /
                fp.write(posixpath.normpath(d))
                if d[-1] == '/':
                    fp.write('/')
                fp.write('\n')

        git('pull', 'origin', branch)

    return repo_name


def clean_repo():
    git('reset', '--hard')
    try:
        git('clean', '-d', '-x', '-f')
    except GitError:
        # ignore errors mostly due to the fact it is skipping dirs
        pass


def link_targets(targets):
    for target in targets:
        dsts = target[1]
        for dst in dsts:
            mkdir_p(os.path.split(dst)[0])
            if os.path.lexists(dst):
                rm_link(dst)
            link(target[0], dst)


def untrack(paths):
    with open('.git/info/exclude', 'wt') as fp:
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

    if ctx.invoked_subcommand != 'add' and not os.path.exists(FILENAME):
        error("Unable to find", FILENAME, exitcode=1)

    if not os.path.exists(DEFAULT_DIR):
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
    default=True,
    help=
    'Install post-checkout hook used to automatically update the working copy')
@click.option('--recursive', help='Call git-externals update recursively')
def gitext_update(with_hooks, recursive):
    """Update the working copy cloning externals if needed and create the desired layout using symlinks
    """
    if with_hooks:
        install_hooks(recursive)
    gitext_up(recursive)


def gitext_up(recursive):
    clean_repo()
    if not os.path.exists(FILENAME):
        return

    git_externals = load_gitexts()

    for ext_repo in git_externals.keys():
        mkdir_p(DEFAULT_DIR)
        with chdir(DEFAULT_DIR):
            repo_name = get_repo_name(ext_repo)

            info('External', repo_name)
            if not os.path.exists(repo_name):
                info('Cloning external', repo_name)

                dirs = git_externals[ext_repo]['targets'].keys()
                if './' not in dirs:
                    sparse_checkout(repo_name, ext_repo, dirs,
                                    git_externals[ext_repo]['branch'])
                else:
                    git('clone', ext_repo, repo_name)

            with chdir(repo_name):
                git('fetch', '--all')

                if 'tag' in git_externals[ext_repo]:
                    info('Checking out tag', git_externals[ext_repo]['tag'])
                    git('checkout', git_externals[ext_repo]['tag'])
                else:
                    info('Checking out branch',
                         git_externals[ext_repo]['branch'])
                    git('checkout', git_externals[ext_repo]['branch'])
                    git('pull', 'origin', git_externals[ext_repo]['branch'])

                    if git_externals[ext_repo]['ref'] is not None:
                        info('Checking out commit',
                             git_externals[ext_repo]['ref'])
                        git('checkout', git_externals[ext_repo]['ref'])

                if recursive:
                    gitext_up(recursive)

        def absjoin(*args):
            return os.path.abspath(os.path.join(*args))

        targets = [(absjoin(DEFAULT_DIR, repo_name, t[0]), t[1])
                   for t in git_externals[ext_repo]['targets'].items()]

        link_targets(targets)

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
def gitext_info(external):
    """Print some info about the externals."""
    external = set(external)
    git_externals = load_gitexts()

    filtered = [(ext_repo, ext)
                for (ext_repo, ext) in git_externals.items()
                if get_repo_name(ext_repo) in external]
    filtered = filtered or git_externals.items()

    for ext_repo, ext in filtered:
        click.echo('Repo:   {}'.format(ext_repo))
        if 'tag' in ext:
            click.echo('Tag:    {}'.format(ext['tag']))
        else:
            click.echo('Branch: {}'.format(ext['branch']))
            click.echo('Ref:    {}'.format(ext['ref']))

        for src, dsts in ext['targets'].items():
            for dst in dsts:
                click.echo('  {} -> {}'.format(src, dst))

        click.echo('')


def iter_externals(externals, verbose=True):
    if not externals:
        externals = get_entries()

    for entry in externals:
        entry_path = os.path.join(DEFAULT_DIR, entry)

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
        fp.write('if [ $3 -ne 0 ]; then git externals update {}; fi;'.format('' if not recursive else '--recursive'))
    os.chmod(hook_filename, 0o755)


def enable_colored_output():
    for entry in get_entries():
        with chdir(os.path.join(DEFAULT_DIR, entry)):
            git('config', 'color.ui', 'always')

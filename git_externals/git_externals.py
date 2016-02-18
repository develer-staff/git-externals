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
        return name[:-len('.git')]


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
@click.option('--with-color/--no-color', default=True)
@click.option('--with-hooks/--no-hooks', default=True)
@click.pass_context
def cli(ctx, with_color, with_hooks):
    """Utility to manage git externals"""

    if ctx.invoked_subcommand != 'add' and not os.path.exists(FILENAME):
        error("Unable to find", FILENAME, exitcode=1)

    if not os.path.exists(DEFAULT_DIR):
        if ctx.invoked_subcommand not in set(['update', 'add']):
            error('You must first run git-externals update/add', exitcode=2)
    else:
        if with_color:
            enable_colored_output()

        if with_hooks:
            install_hooks()

        if ctx.invoked_subcommand is None:
            gitext_st(())


@cli.command('update')
def gitext_update():
    gitext_up()


def gitext_up():
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

                gitext_up()

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
@click.option('--porcelain', is_flag=True)
def gitext_st(external, porcelain):
    for _ in iter_externals(external):
        click.echo(git('status', '--porcelain' if porcelain else ''))


@cli.command('diff')
@click.argument('external', nargs=-1)
def gitext_diff(external):
    for _ in iter_externals(external):
        click.echo(git('diff'))


@cli.command('list')
def gitext_ls():
    for entry in iter_externals([], verbose=False):
        info(entry)


@cli.command('add')
@click.argument('external')
@click.argument('src')
@click.argument('dst')
@click.option('--branch', '-b', default=None)
@click.option('--tag', '-t', default=None)
@click.option('--ref', '-r', default=None)
def gitext_add(external, src, dst, branch, tag, ref):
    git_externals = load_gitexts()

    if branch is None and tag is None:
        click.secho('Please specifiy at least a branch or a tag', fg='red')
        sys.exit(3)

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
                click.secho(
                    '{} is bound to tag {}, cannot set it to branch {}'.format(
                        external, git_externals[external]['tag'], branch))
                sys.exit(4)

            if ref != git_externals[external]['ref']:
                click.secho(
                    '{} is bound to ref {}, cannot set it to ref {}'.format(
                        external, git_externals[external]['ref'], ref))
                sys.exit(4)
        elif 'tag' not in git_externals[external]:
            click.secho(
                '{} is bound to branch {}, cannot set it to tag {}'.format(
                    external, git_externals[external]['branch'], tag))
            sys.exit(4)

        if dst not in git_externals[external]['targets'].setdefault(src, []):
            git_externals[external]['targets'][src].append(dst)

    dump_gitexts(git_externals)


@cli.command('remove')
@click.argument('external', nargs=-1)
def gitext_remove(external):
    git_externals = load_gitexts()

    for ext in external:
        if ext in git_externals:
            del git_externals[ext]

    dump_gitexts(git_externals)


@cli.command('info')
@click.argument('external', nargs=-1)
def gitext_info(external):
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


def install_hooks():
    hook_filename = os.path.join('.git', 'hooks', 'post-checkout')
    with open(hook_filename, 'wt') as fp:
        fp.write('#!/bin/sh\n')
        fp.write('# see http://article.gmane.org/gmane.comp.version-control.git/281960')
        fp.write('unset GIT_WORK_TREE')
        fp.write('git externals update')
    os.chmod(hook_filename, 0o755)


def enable_colored_output():
    for entry in get_entries():
        with chdir(os.path.join(DEFAULT_DIR, entry)):
            git('config', 'color.ui', 'always')

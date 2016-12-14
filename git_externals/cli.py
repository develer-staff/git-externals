#!/usr/bin/env python

from __future__ import print_function, unicode_literals

if __package__ is None:
    from __init__ import __version__
    from utils import command, CommandError, chdir, git, ProgError
else:
    from . import __version__
    from .utils import command, CommandError, chdir, git, ProgError, decode_utf8

import click
import os
import sys

click.disable_unicode_literals_warning = True


def echo(*args):
    click.echo(u' '.join(args))


def info(*args):
    click.secho(u' '.join(args), fg='blue')


def error(*args, **kwargs):
    click.secho(u' '.join(args), fg='red')
    exitcode = kwargs.get('exitcode', 1)
    if exitcode is not None:
        sys.exit(exitcode)


@click.group(context_settings={
    'allow_extra_args': True,
    'ignore_unknown_options': True,
    'help_option_names':['-h','--help'],
})
@click.version_option(__version__)
@click.option('--with-color/--no-color',
              default=True,
              help='Enable/disable colored output')
@click.pass_context
def cli(ctx, with_color):
    """Utility to manage git externals, meant to be used as a drop-in
    replacement to svn externals

    This script works by cloning externals found in the `git_externals.json`
    file into `.git/externals` and symlinks them to recreate the wanted
    directory layout.
    """
    from git_externals import is_git_repo, externals_json_path, externals_root_path

    if not is_git_repo():
        error("{} is not a git repository!".format(os.getcwd()), exitcode=2)

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


@cli.command('foreach')
@click.option('--recursive/--no-recursive', help='If --recursive is specified, this command will recurse into nested externals', default=True)
@click.argument('subcommand', nargs=-1, required=True)
def gitext_foreach(recursive, subcommand):
    """Evaluates an arbitrary shell command in each checked out external
    """
    from git_externals import externals_sanity_check, get_repo_name, foreach_externals_dir, root_path

    externals_sanity_check()

    def run_command(rel_url, ext_path, targets):
        try:
            info("External {}".format(get_repo_name(rel_url)))
            output = decode_utf8(command(*subcommand))
            info("Ok: CWD: {}, cmd: {}".format(os.getcwd(), subcommand))
            echo(output)
        except CommandError as err:
            info("Command error {} CWD: {}, cmd: {}".format(err, os.getcwd(), subcommand))
            error(str(err), exitcode=err.errcode)

    foreach_externals_dir(root_path(), run_command, recursive=recursive)


@cli.command('update')
@click.option('--recursive/--no-recursive', help='Do not call git-externals update recursively', default=True)
@click.option('--gitsvn/--no-gitsvn', help='Do not call git-externals update recursively (used only for the first checkout)', default=True)
@click.option('--reset', help='Reset repo, overwrite local modifications', is_flag=True)
def gitext_update(recursive, gitsvn, reset):
    """Update the working copy cloning externals if needed and create the desired layout using symlinks
    """
    from git_externals import externals_sanity_check, root_path, is_workingtree_clean, foreach_externals, gitext_up

    externals_sanity_check()
    root = root_path()

    if reset:
        git('reset', '--hard')

    # Aggregate in a list the `clean flags` of all working trees (root + externals)
    clean = [is_workingtree_clean(root, fail_on_empty=False)]
    foreach_externals(root,
        lambda u, p, r: clean.append(is_workingtree_clean(p, fail_on_empty=False)),
        recursive=recursive)

    if reset or all(clean):
        # Proceed with update if everything is clean
        try:
            gitext_up(recursive, reset=reset, use_gitsvn=gitsvn)
        except ProgError as e:
            error(str(e), exitcode=e.errcode)
    else:
        echo("Cannot perform git externals update because one or more repositories contain some local modifications")
        echo("Run:\tgit externals status\tto have more information")


@cli.command('status')
@click.option(
    '--porcelain',
    is_flag=True,
    help='Print output using the porcelain format, useful mostly for scripts')
@click.option(
    '--verbose/--no-verbose',
    is_flag=True,
    help='Show the full output of git status, instead of showing only the modifications regarding tracked file')
@click.argument('externals', nargs=-1)
def gitext_st(porcelain, verbose, externals):
    """Call git status on the given externals"""
    from git_externals import foreach_externals_dir, root_path, \
                              is_workingtree_clean, get_repo_name

    def get_status(rel_url, ext_path, targets):
        try:
            if porcelain:
                echo(rel_url)
                click.echo(git('status', '--porcelain'))
            elif verbose or not is_workingtree_clean(ext_path):
                info("External {}".format(get_repo_name(rel_url)))
                echo(git('status', '--untracked-files=no' if not verbose else ''))
        except CommandError as err:
            error(str(err), exitcode=err.errcode)

    foreach_externals_dir(root_path(), get_status, recursive=True, only=externals)


@cli.command('diff')
@click.argument('external', nargs=-1)
def gitext_diff(external):
    """Call git diff on the given externals"""
    from git_externals import iter_externals
    for _ in iter_externals(external):
        click.echo(git('diff'))


@cli.command('list')
def gitext_ls():
    """Print just a list of all externals used"""
    from git_externals import iter_externals
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
    from git_externals import load_gitexts, dump_gitexts

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
    from git_externals import load_gitexts, dump_gitexts

    git_externals = load_gitexts()

    for ext in external:
        if ext in git_externals:
            del git_externals[ext]

    dump_gitexts(git_externals)


@cli.command('info')
@click.argument('external', nargs=-1)
@click.option('--recursive/--no-recursive', default=True,
              help='Print info only for top level externals')
def gitext_info(external, recursive):
    """Print some info about the externals."""
    from git_externals import print_gitext_info, get_repo_name, gitext_recursive_info, load_gitexts

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


def enable_colored_output():
    from git_externals import externals_root_path, get_entries

    for entry in get_entries():
        with chdir(os.path.join(externals_root_path(), entry)):
            git('config', 'color.ui', 'always')


def main():
    cli()


if __name__ == '__main__':
    main()

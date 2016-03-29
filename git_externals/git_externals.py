#!/usr/bin/env python

from __future__ import print_function, unicode_literals

from . import __version__
from .utils import chdir, mkdir_p, link, rm_link, git, GitError, command, CommandError

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


def foreach_externals(pwd, callback, recursive=True, only=[]):
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
            for expr in only:
                return expr in url or expr in path
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
    `git reset --hard` would result in no local modifications lost because:
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
            error(str(err), exitcode=err.errcode)


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
@click.argument('command_', nargs=-1, required=True, metavar="command")
def gitext_foreach(recursive, command_):
    """Evaluates an arbitrary shell command in each checked out external
    """

    externals_sanity_check()

    def run_command(rel_url, ext_path, targets):
        try:
            info("External {}".format(get_repo_name(rel_url)))
            output = command(command_[0], *command_[1:])
            echo(output)
        except CommandError as err:
            error(str(err), exitcode=err.errcode)

    foreach_externals_dir(root_path(), run_command, recursive=recursive)


@cli.command('update')
@click.option('--recursive/--no-recursive', help='Do not call git-externals update recursively', default=True)
def gitext_update(recursive):
    """Update the working copy cloning externals if needed and create the desired layout using symlinks
    """

    externals_sanity_check()
    root = root_path()

    # Aggregate in a list the `clean flags` of all working trees (root + externals)
    clean = [is_workingtree_clean(root, fail_on_empty=False)]
    foreach_externals(root,
        lambda u,p,r: clean.append(is_workingtree_clean(p, fail_on_empty=False)),
        recursive=recursive)

    if all(clean):
        # Proceed with update if everything is clean
        gitext_up(recursive)
    else:
        echo("Cannot perform git externals update because one or more repositories contain some local modifications")
        echo("Run:\tgit externals status\tto have more information")


def externals_sanity_check():
    """Check that we are not trying to track various refs of the same external repo"""
    ExtItem = namedtuple('ExtItem', ['branch', 'ref'])
    registry = defaultdict(set)

    def registry_add(url, path, ext):
        registry[url].add(ExtItem(ext['branch'], ext['ref']))

    foreach_externals(root_path(), registry_add, recursive=True)
    errmsg = None
    for url, set_ in registry.iteritems():
        if len(set_) > 1:
            if errmsg is None:
                errmsg = ["Error: one project can not refer to different branches/refs of the same git external repository,",
                    "however it appears to be the case for:"]
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


def gitext_up(recursive, entries=None):

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
                gitext_up(recursive, entries)

    to_untrack = []
    for ext in git_externals.values():
        to_untrack += [dst for dsts in ext['targets'].values() for dst in dsts]
    untrack(to_untrack)


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


def enable_colored_output():
    for entry in get_entries():
        with chdir(os.path.join(externals_root_path(), entry)):
            git('config', 'color.ui', 'always')

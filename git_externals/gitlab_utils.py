#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import time
import posixpath

import click
import gitlab


def _iter_paginated(source, per_page=10):
    page = 0
    while True:
        projects = source(page=page, per_page=per_page)
        if len(projects) == 0:
            break
        else:
            page = page + 1
        for project in projects:
            yield project


def iter_projects(gl):
    for prj in _iter_paginated(gl.projects.list):
        yield prj


def search_projects(gl, name):
    def source(page, per_page):
        return gl.projects.search(name, page=page, per_page=per_page)
    for prj in _iter_paginated(source):
        yield prj


@click.group()
@click.option('--gitlab-id', default=None)
@click.option('--config', default=None)
@click.pass_context
def cli(ctx, gitlab_id, config):
    if config is not None:
        config = [config]
    gl = gitlab.Gitlab.from_config(gitlab_id=gitlab_id, config_files=config)
    ctx.obj['api'] = gl


@cli.group()
@click.pass_context
def project(ctx):
    pass


def get_project_by_path(gl, path):
    name = posixpath.basename(path)
    with click.progressbar(search_projects(gl, name), label='Searching project...') as projects:
        for prj in projects:
            if prj.path_with_namespace == path:
                return prj


@project.command()
@click.argument('path')
@click.option('--sync', is_flag=True)
@click.pass_context
def delete(ctx, path, sync):
    gl = ctx.obj['api']
    prj = get_project_by_path(gl, path)
    if prj is None:
        click.echo('Unable to find a matching project for path %r' % path, err=True)
        return
    try:
        if not gl.delete(prj):
            raise click.UsegeError('Unable to delete project for path %r' % path)
    except gitlab.GitlabGetError:
        click.echo('The project %r seems to be already deleted' % path, err=True)
        return
    if sync:
        with click.progressbar(range(6*4), label='Waiting for deletion...') as waiting:
            def deleted():
                for step in waiting:
                    try:
                        gl.projects.get(prj.id)
                    except gitlab.GitlabGetError:
                        return True
                    time.sleep(10)
                return False
            if deleted():
                click.echo('Project %r deleted' % path)
            else:
                click.UsegeError('Timeout waiting for %r deletion' % path)
    else:
        click.echo('Project %r submitted for deletion' % path)


@project.command()
@click.pass_context
def list(ctx):
    gl = ctx.obj['api']
    for prj in iter_projects(gl):
        click.echo(prj.path_with_namespace)


def main():
    cli(obj={})


if __name__ == '__main__':
    main()

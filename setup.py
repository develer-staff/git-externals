#!/usr/bin/env python
# -*- coding: utf-8 -*-

try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup


with open('git_externals/__init__.py') as fp:
    exec(fp.read())


classifiers = [
    'Development Status :: 4 - Beta',
    'Programming Language :: Python',
    'Programming Language :: Python :: 2',
    'Programming Language :: Python :: 2.6',
    'Programming Language :: Python :: 2.7',
    'Programming Language :: Python :: 3',
    'Programming Language :: Python :: 3.4',
    'Programming Language :: Python :: 3.5',
    'Topic :: Software Development :: Libraries :: Python Modules',
]

setup(
    name='git-externals',
    version=__version__,
    description='cli tool to manage git externals',
    long_description='Ease the migration from Git to SVN by handling svn externals through a cli tool',
    packages=['git_externals'],
    install_requires=['click',
                      'git-svn-clone-externals'],
    entry_points={
        'console_scripts': [
            'git-externals = git_externals.cli:cli',
            'svn-externals-info = git_externals.process_externals:main',
        ],
    },
    author=__author__,
    author_email=__email__,
    license='MIT',
    classifiers=classifiers,
)

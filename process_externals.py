#!/usr/bin/env python

from __future__ import unicode_literals, print_function

import collections
import os
import os.path
import re

try:
    from lxml import etree as ET
except ImportError:
    from xml.etree import ElementTree as ET

from utils import header
from argparse import ArgumentParser, FileType

RE_REVISION = re.compile(r'(-r\s*|@)(\d+)')
SVNROOT = "file:///var/lib/svn"


def get_args():
    parser = ArgumentParser()
    parser.add_argument('ext', type=FileType('r'),
            help='XML file containing the SVN externals to parse')

    parser.add_argument('--to-print', nargs='+',
        choices=['all', 'dir', 'file', 'locked', 'unique'], default='all',
        help='print only specified externals')

    parser.add_argument('--tags', action='store_true', default=False,
        help='analyze externals only in tags')

    return parser.parse_args()


def main():
    args = get_args()

    # Essentials
    doc = ET.parse(args.ext)
    targets = doc.findall("target")

    filterfn = notags if not args.tags else withtags
    ranks = ranked_externals(targets, filterfn)

    # View data - support methods
    def print_ranked(externals):
        print('')
        print("Number of externals", len(externals))

        for rank, external in reversed(externals):
            print('')
            print('External {} referenced {} times by:'.format(external["location"], rank))

            for ref in sorted(ranks[external["location"]]):
                print("  " + ref)

    # View data
    def print_externals_to_dir():
        to_dir = sorted_by_rank(unique_externals(targets, onlydir), ranks)
        header("Externals to a directory")
        print_ranked(to_dir)

    def print_externals_to_file():
        to_file = sorted_by_rank(unique_externals(targets, onlyfile), ranks)
        header("Externals to a file")
        print_ranked(to_file)

    def print_locked_externals():
        to_rev = unique_externals(targets, onlylocked)
        header("Externals locked to a certain revision")
        for external in to_rev:
            print("r{0} {1}".format(external["rev"], external["location"]))

    def print_unique_externals():
        externals = [e['location'] for e in unique_externals(targets)]
        externals.sort()
        header("Unique externals")

        print('')
        print('Found {} unique externals'.format(len(externals)))
        print('')
        for external in externals:
            print(external)


    printers = [
        ('dir', print_externals_to_dir),
        ('file', print_externals_to_file),
        ('locked', print_locked_externals),
        ('unique', print_unique_externals),
    ]

    if 'all' in args.to_print:
        funcs = [p[1] for p in printers]
    else:
        funcs = []
        for tp in sorted(set(args.to_print)):
            fn = [p[1] for p in printers if p[0] == tp][0]
            funcs.append(fn)

    for fn in funcs:
        fn()


def ranked_externals(targets, filterf=lambda x: True):
    ret = collections.defaultdict(list)

    for external in parsed_externals(targets):
        if filterf(external):
            ret[external["location"]].append(external["target"])

    return ret


def sorted_by_rank(externals, ranks):
    ret = []

    for external in externals:
        ret.append((len(ranks[external["location"]]), external))

    return sorted(ret, key=lambda x: (x[0], x[1]['location']))


def unique_externals(targets, filterf=lambda x: True):
    return {v["location"]: v for v in parsed_externals(targets) if filterf(v)}.values()


def parsed_externals(targets):
    for target in targets:
        for item in get_externals_from_target(target):
            yield item


def get_externals_from_target(target):
    prop = target.find("property")

    for external in [l for l in prop.text.split("\n") if l.strip()]:
        ret = parse_external(external)
        ret["target"] = target.get("path").replace(SVNROOT, "")

        yield ret


def parse_external(external):
    normalized = RE_REVISION.sub("", external).strip()

    revision = RE_REVISION.search(external)
    revision = revision.group(2) if revision else None

    pieces = normalized.split(" ", 1)
    pieces = [p.strip() for p in pieces]

    # Determine whether the first or the second piece is a reference to another SVN repo/location.
    if pieces[0].startswith("^/") or pieces[0].startswith("/") or pieces[0].startswith("../"):
        location = pieces[0]
        localpath = pieces[1]
    else:
        location = pieces[1]
        localpath = pieces[0]

    # If the location starts with the "relative to svnroot" operator, normalize it.
    if location.startswith("^/"):
        location = location[1:]

    return {
        "location": location,
        "path": localpath,
        "rev": revision,
    }


#
# Filters
#


def notags(external):
    return "/tags/" not in external["target"]

def withtags(external):
    return '/tags/' in external['target']

def onlyfile(external):
    return os.path.splitext(external["location"])[1] != ""


def onlydir(external):
    return os.path.splitext(external["location"])[1] == ""


def onlylocked(external):
    return external["rev"] is not None

#
# Entry point
#

if __name__ == "__main__":
    main()

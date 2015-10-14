#!/usr/bin/env python

import collections
import os
import os.path
import re
import sys

from lxml import etree

RE_REVISION = re.compile(ur'(-r\s*|@)(\d+)')
SVNROOT = "file:///var/lib/svn"


def main():
    doc = etree.parse(sys.argv[1])
    targets = doc.findall("target")
    ranked = ranked_externals(targets)

    header("Externals to a directory:")
    process_externals(targets, only_dir_locations)

    header("Externals to a file:")
    process_externals(targets, only_file_locations)

    header("Externals locked to a certain revision:")
    process_externals(targets, only_locked)


def ranked_externals(targets, filterf=None):
    ret = collections.defaultdict(list)

    for ext in parsed_externals(targets):
        if filterf and not filterf(ext):
            continue

        ret[ext["location"]].append(ext["target"])

    return ret


def process_externals(targets, mapf):
    externals = unique_externals(targets, mapf)

    print "Found {0} unique externals".format(len(externals))

    for ext in sorted(externals):
        if ext:
            print ext


def unique_externals(targets, mapf=lambda x: x):
    return set([mapf(e) for e in parsed_externals(targets)])


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
# Utilities
#


def header(msg):
    print ""
    print msg

#
# Filters
#


def only_file_locations(external):
    _, ext = os.path.splitext(external["location"])
    if not ext:
        return None

    return external["location"]


def only_dir_locations(external):
    _, ext = os.path.splitext(external["location"])
    if ext:
        return None

    return external["location"]


def only_locked(external):
    if not external["rev"]:
        return None

    return "r{0} of {1}".format(external["rev"], external["location"], external["target"])


if __name__ == "__main__":
    main()

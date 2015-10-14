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
    # Essentials
    doc = etree.parse(sys.argv[1])
    targets = doc.findall("target")
    ranks = ranked_externals(targets, notags)

    # Extract
    to_dir = sorted_by_rank(unique_externals(targets, onlydir), ranks)
    to_file = sorted_by_rank(unique_externals(targets, onlyfile), ranks)
    to_rev = unique_externals(targets, onlylocked)

    # Present - support methods
    def print_ranked(externals):
        print "# of externals", len(externals)

        for rank, external in reversed(externals):
            print str(rank).ljust(5), external["location"]

            for ref in ranks[external["location"]]:
                print "  " + ref

    # Present
    header("Externals to a directory:")
    print_ranked(to_dir)

    header("Externals to a file:")
    print_ranked(to_file)

    header("Externals locked to a certain revision:")
    for external in to_rev:
        print "r{0} {1}".format(external["rev"], external["location"])


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

    return sorted(ret)


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
# Utilities
#


def header(msg):
    print ""
    print msg

#
# Filters
#


def notags(external):
    return "/tags/" not in external["target"]


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

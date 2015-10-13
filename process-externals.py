#!/usr/bin/env python

import re
import sys

from lxml import etree

RE_REVISION = re.compile(ur'(-r\s*\d+|@\d+)')
SVNROOT = "file:///var/lib/svn"


def main():
    doc = etree.parse(sys.argv[1])

    externals = unique_externals(doc.findall('target'))

    print "Found {0} unique externals".format(len(externals))

    for ext in sorted(externals):
        print ext


def unique_externals(targets):
    ext = []

    for target in targets:
        prop = target.find('property')
        externals = [l for l in prop.text.split("\n") if l.strip()]
        ext += [purify_external(e) for e in externals]

    return set(ext)


def purify_external(external):
    # Strip "@<rev>", "-r <rev>", "-r<rev>" and split into [external, checkout dir]
    pieces = RE_REVISION.sub("", external).strip().split(" ", 1)
    pieces = [p.strip() for p in pieces]

    # Determine whether the first or the second piece is a reference to another SVN repo/location.
    if pieces[0].startswith("^/") or pieces[0].startswith("/") or pieces[0].startswith("../"):
        location = pieces[0]
    else:
        location = pieces[1]

    # If the location starts with the "relative to svnroot" operator, normalize it.
    if location.startswith("^/"):
        return "/svn/" + location[2:]

    return location

if __name__ == "__main__":
    main()

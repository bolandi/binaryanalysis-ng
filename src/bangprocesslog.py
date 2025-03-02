#!/usr/bin/env python3

# Binary Analysis Next Generation (BANG!)
#
# This file is part of BANG.
#
# BANG is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License,
# version 3, as published by the Free Software Foundation.
#
# BANG is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public
# License, version 3, along with BANG.  If not, see
# <http://www.gnu.org/licenses/>
#
# Copyright 2018-2021 - Armijn Hemel
# Licensed under the terms of the GNU Affero General Public License
# version 3
# SPDX-License-Identifier: AGPL-3.0-only

'''Processes a BANG log file to see which errors were triggered the
most, as this is useful to find which checks to tighten and see
which checks possibly need to be inlined into the main program.'''

import os
import sys
import stat
import collections
import argparse
import pathlib

# import own modules
import bangsignatures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-f", "--file", action="store", dest="checkfile",
                        help="path to file to check", metavar="FILE")
    args = parser.parse_args()

    # sanity checks for the file to scan
    if args.checkfile is None:
        parser.error("No file to scan provided, exiting")

    # the file to scan should exist ...
    if not os.path.exists(args.checkfile):
        parser.error("File %s does not exist, exiting." % args.checkfile)

    # ... and should be a real file
    if not stat.S_ISREG(os.stat(args.checkfile).st_mode):
        parser.error("%s is not a regular file, exiting." % args.checkfile)

    filesize = os.stat(args.checkfile).st_size

    # Don't scan an empty file
    if filesize == 0:
        print("File to scan is empty, exiting", file=sys.stderr)
        sys.exit(1)

    bangerrors = collections.Counter()
    bangerrormessages = {}

    errorfiles = collections.Counter()
    totalerrors = 0

    extensions = collections.Counter()

    # open the file, assume for now that everything is in UTF-8
    # (famous last words).
    logfile = open(args.checkfile, 'r')
    extensions_tmp = []
    openfiles = set()
    opensignatures = set()
    for i in logfile:
        valid_line = False
        for j in ['FAIL', 'TRYING', 'SUCCESS']:
            if j in i:
                valid_line = True
                break
        if not valid_line:
            continue
        file_name = pathlib.Path(i[len(j):].strip().split(':', 1)[0].rsplit(' ', 3)[0])
        signature = i.strip().split(':', 1)[0].rsplit(' ', 3)[1]
        if j == 'TRYING':
            openfiles.add(file_name)
            opensignatures.add((file_name, signature))
        else:
            try:
                openfiles.remove(file_name)
                opensignatures.remove((file_name, signature))
            except:
                pass
        if 'FAIL' not in i:
            continue
        # ignore the 'known extension' entries
        if ' known extension ' in i:
            continue
        bangfails = i[5:].strip().rsplit(':', 1)
        bangfail = bangfails[1].strip()
        extension = file_name.suffix
        extensions_tmp.append(extension)
        for sig in bangsignatures.signatures:
            if " %s at offset" % sig in i.strip():
                bangerrors.update([sig])
                if sig not in bangerrormessages:
                    bangerrormessages[sig] = collections.Counter()
                bangerrormessages[sig].update([bangfail])
                filename = bangfails[0].rsplit(sig, 1)[0]
                errorfiles.update([filename])
                totalerrors += 1
                break
    extensions.update(extensions_tmp)
    logfile.close()

    print("Failures per signature")
    print("----------------------\n")

    # print the error messages in descending order
    for err in bangerrors.most_common():
        print("Signature %s: %d (%f%%)" % (err[0], err[1], err[1]/totalerrors*100))
        for msg in bangerrormessages[err[0]].most_common():
            print("%s: %d" % msg)
        print()

    # print the files with the most errors
    print("Failures per file")
    print("-----------------\n")
    for err in errorfiles.most_common():
        print("%s: %d failures\n" % err)

    # print the extension with the most errors
    print("Failures per extension")
    print("-----------------\n")
    for err in extensions.most_common():
        print("%s: %d failures\n" % err)


    print("Opened but not closed files")
    print("---------------------------\n")
    for o in openfiles:
        print(o)

    print()
    print("Opened but not closed signatures")
    print("---------------------------\n")
    for o in opensignatures:
        print(o)


if __name__ == "__main__":
    main()

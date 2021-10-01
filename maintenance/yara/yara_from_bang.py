#!/usr/bin/env python3

# Binary Analysis Next Generation (BANG!)
#
# Copyright 2021 - Armijn Hemel
# Licensed under the terms of the GNU Affero General Public License version 3
# SPDX-License-Identifier: AGPL-3.0-only

'''
This script processes BANG results and generates YARA rules for
dynamically linked ELF files.
'''

import sys
import os
import argparse
import pathlib
import tempfile
import datetime
import pickle
import re
import uuid
import multiprocessing
import queue

import packageurl

# import YAML module for the configuration
from yaml import load
from yaml import YAMLError
try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader

ESCAPE = str.maketrans({'"': '\\"',
                        '\\': '\\\\',
                        '\t': '\\t',
                        '\n': '\\n'})

def normalize_name(name):
    for i in ['.', '-']:
        if i in name:
            name = name.replace(i, '_')
    return name


def generate_yara(yara_directory, metadata, functions, variables, strings, tags):
    generate_date = datetime.datetime.utcnow().isoformat()
    rule_uuid = uuid.uuid4()
    meta = '''
    meta:
        description = "Rule for %s in %s"
        author = "Generated by BANG"
        date = "%s"
        uuid = "%s"
''' % (metadata['name'], metadata['package'], generate_date, rule_uuid)

    for m in sorted(metadata):
        meta += '        %s = "%s"\n' % (m, metadata[m])

    yara_file = yara_directory / ("%s-%s.yara" % (metadata['package'], metadata['name']))
    if tags == []:
        rule_name = 'rule rule_%s\n' % normalize_name(str(rule_uuid))
    else:
        rule_name = 'rule rule_%s: %s\n' % (normalize_name(str(rule_uuid)), " ".join(tags))

    with yara_file.open(mode='w') as p:
        p.write(rule_name)
        p.write('{')
        p.write(meta)
        p.write('\n    strings:\n')

        # write the strings
        p.write("\n        // Extracted strings\n\n")
        counter = 1
        for s in sorted(strings):
            p.write("        $string%d = \"%s\"\n" % (counter, s))
            counter += 1

        # write the functions
        p.write("\n        // Extracted functions\n\n")
        counter = 1
        for s in sorted(functions):
            p.write("        $function%d = \"%s\"\n" % (counter, s))
            counter += 1

        # write the variable names
        p.write("\n        // Extracted variables\n\n")
        counter = 1
        for s in sorted(variables):
            p.write("        $variable%d = \"%s\"\n" % (counter, s))
            counter += 1

        # TODO: find good heuristics of how many identifiers should be matched
        p.write('\n    condition:\n')
        p.write('        all of them\n')
        p.write('\n}')
    return yara_file.name


def process_directory(yaraqueue, yara_directory, yara_binary_directory,
                      processlock, processed_files, yara_env):

    generate_identifier_files = False
    while True:
        bang_directory = yaraqueue.get()
        bang_pickle = bang_directory / 'bang.pickle'
        functions_per_package = set()
        variables_per_package = set()
        strings_per_package = set()

        yara_files = []

        elf_to_identifiers = {}
        processed = False

        # open the top level pickle
        bang_data = pickle.load(open(bang_pickle, 'rb'))
        package_name = ''
        for bang_file in bang_data['scantree']:
            if 'root' in bang_data['scantree'][bang_file]['labels']:
                package_name = pathlib.Path(bang_file).name
                root_sha256 = bang_data['scantree'][bang_file]['hash']['sha256']

                processlock.acquire()

                # try to catch duplicates
                if root_sha256 in processed_files:
                    processed = True
                processlock.release()
                break

        if processed:
            yaraqueue.task_done()
            continue

        processlock.acquire()
        processed_files[root_sha256] = ''
        processlock.release()

        for bang_file in bang_data['scantree']:
            metadata = {}
            if 'elf' in bang_data['scantree'][bang_file]['labels']:
                sha256 = bang_data['scantree'][bang_file]['hash']['sha256']
                elf_name = pathlib.Path(bang_file).name
                suffix = pathlib.Path(bang_file).suffix

                if suffix in yara_env['ignored_suffixes']:
                    continue

                # TODO: name is actually not correct, as it assumes
                # there is only one binary with that particular name
                # inside a package. Counter example: apt-utils_2.2.4_amd64.deb
                metadata['name'] = elf_name
                metadata['sha256'] = sha256
                metadata['package'] = package_name

                # open the result pickle
                try:
                    results_data = pickle.load(open(bang_directory / 'results' / ("%s.pickle" % sha256), 'rb'))
                except:
                    continue
                if 'metadata' not in results_data:
                    # example: statically linked binaries currently
                    # have no associated metadata.
                    continue

                if 'tlsh' in results_data:
                    metadata['tlsh'] = results_data['tlsh']

                if 'telfhash' in results_data['metadata']:
                    metadata['telfhash'] = results_data['metadata']['telfhash']

                strings = set()
                functions = set()
                variables = set()
                if results_data['metadata']['strings'] != []:
                    for s in results_data['metadata']['strings']:
                        if len(s) < yara_env['string_cutoff']:
                            continue
                        # ignore whitespace-only strings
                        if re.match(r'^\s+$', s) is None:
                            strings.add(s.translate(ESCAPE))
                    strings_per_package.update(strings)
                if results_data['metadata']['symbols'] != []:
                    for s in results_data['metadata']['symbols']:
                        if s['section_index'] == 0:
                            continue
                        if yara_env['ignore_weak_symbols']:
                            if s['binding'] == 'weak':
                                continue
                        if len(s['name']) < yara_env['identifier_cutoff']:
                            continue
                        if '@@' in s['name']:
                            identifier_name = s['name'].rsplit('@@', 1)[0]
                        elif '@' in s['name']:
                            identifier_name = s['name'].rsplit('@', 1)[0]
                        else:
                            identifier_name = s['name']
                        if s['type'] == 'func':
                            if identifier_name in yara_env['lq_identifiers']['elf']['functions']:
                                continue
                            functions.add(identifier_name)
                        elif s['type'] == 'object':
                            if identifier_name in yara_env['lq_identifiers']['elf']['variables']:
                                continue
                            variables.add(identifier_name)
                    functions_per_package.update(functions)
                    variables_per_package.update(variables)
                if elf_name not in elf_to_identifiers:
                    elf_to_identifiers['strings'] = strings
                    elf_to_identifiers['variables'] = variables
                    elf_to_identifiers['functions'] = functions

                # do not generate a YARA file if there is no data
                if strings == set() and variables == set() and functions == set():
                    continue

                total_identifiers = len(functions) + len(variables) + len(strings)

                if total_identifiers > yara_env['max_identifiers']:
                    pass

                yara_tags = yara_env['tags'] + ['elf']
                yara_name = generate_yara(yara_binary_directory, metadata, functions, variables, strings, yara_tags)
                yara_files.append(yara_name)
            elif 'dex' in bang_data['scantree'][bang_file]['labels']:
                sha256 = bang_data['scantree'][bang_file]['hash']['sha256']
                dex_name = pathlib.Path(bang_file).name
                suffix = pathlib.Path(bang_file).suffix

                if suffix in yara_env['ignored_suffixes']:
                    continue

                # TODO: name is actually not correct, as it assumes
                # there is only one binary with that particular name
                # inside a package.
                metadata['name'] = dex_name
                metadata['sha256'] = sha256
                metadata['package'] = package_name

                # open the result pickle
                try:
                    results_data = pickle.load(open(bang_directory / 'results' / ("%s.pickle" % sha256), 'rb'))
                except:
                    continue
                if 'metadata' not in results_data:
                    continue

                if 'tlsh' in results_data:
                    metadata['tlsh'] = results_data['tlsh']

                strings = set()
                functions = set()
                variables = set()

                for c in results_data['metadata']['classes']:
                    for method in c['methods']:
                        # ignore whitespace-only methods
                        if len(method['name']) < yara_env['identifier_cutoff']:
                            continue
                        if re.match(r'^\s+$', method['name']) is not None:
                            continue
                        if method['name'] in ['<init>', '<clinit>']:
                            continue
                        if method['name'].startswith('access$'):
                            continue
                        if method['name'] in yara_env['lq_identifiers']['dex']['functions']:
                            continue
                        functions.add(method['name'])
                    for method in c['methods']:
                        for s in method['strings']:
                            if len(s) < yara_env['string_cutoff']:
                                continue
                            # ignore whitespace-only strings
                            if re.match(r'^\s+$', s) is None:
                                strings.add(s.translate(ESCAPE))

                    for field in c['fields']:
                        # ignore whitespace-only methods
                        if len(field['name']) < yara_env['identifier_cutoff']:
                            continue
                        if re.match(r'^\s+$', field['name']) is not None:
                            continue

                        if field['name'] in yara_env['lq_identifiers']['dex']['variables']:
                            continue
                        variables.add(field['name'])

                # do not generate a YARA file if there is no data
                if strings == set() and variables == set() and functions == set():
                    continue

                total_identifiers = len(functions) + len(variables) + len(strings)

                if total_identifiers > yara_env['max_identifiers']:
                    pass

                yara_tags = yara_env['tags'] + ['dex']
                yara_name = generate_yara(yara_binary_directory, metadata, functions, variables, strings, yara_tags)
                yara_files.append(yara_name)

        if yara_files != []:
            yara_file = yara_directory / ("%s.yara" % package_name)
            with yara_file.open(mode='w') as p:
                p.write("/*\nRules for %s\n*/\n" % package_name)
                #for y in yara_files:
                for y in sorted(set(yara_files)):
                    p.write("include \"./binary/%s\"\n" % y)
            if generate_identifier_files:
                if len(functions_per_package) != 0:
                    yara_file = yara_directory / ("%s.func" % package_name)
                    with yara_file.open(mode='w') as p:
                        for f in sorted(functions_per_package):
                            p.write(f)
                            p.write('\n')
                if len(variables_per_package) != 0:
                    yara_file = yara_directory / ("%s.var" % package_name)
                    with yara_file.open(mode='w') as p:
                        for f in sorted(variables_per_package):
                            p.write(f)
                            p.write('\n')
        yaraqueue.task_done()


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", action="store", dest="cfg",
                        help="path to configuration file", metavar="FILE")
    parser.add_argument("-r", "--result-directory", action="store", dest="result_directory",
                        help="path to BANG result directories", metavar="DIR")
    parser.add_argument("-i", "--identifiers", action="store", dest="identifiers",
                        help="path to pickle with low quality identifiers", metavar="FILE")
    args = parser.parse_args()

    # sanity checks for the configuration file
    if args.cfg is None:
        parser.error("No configuration file provided, exiting")

    cfg = pathlib.Path(args.cfg)

    # the configuration file should exist ...
    if not cfg.exists():
        parser.error("File %s does not exist, exiting." % args.cfg)

    # ... and should be a real file
    if not cfg.is_file():
        parser.error("%s is not a regular file, exiting." % args.cfg)

    # sanity checks for the result directory
    if args.result_directory is None:
        parser.error("No result directory provided, exiting")

    result_directory = pathlib.Path(args.result_directory)

    # the result directory should exist ...
    if not result_directory.exists():
        parser.error("File %s does not exist, exiting." % args.result_directory)

    # ... and should be a real directory
    if not result_directory.is_dir():
        parser.error("%s is not a directory, exiting." % args.result_directory)

    lq_identifiers = {'elf': {'functions': [], 'variables': []},
                      'dex': {'functions': [], 'variables': []}}

    # read the pickle with identifiers
    if args.identifiers is not None:
        try:
            lq_identifiers = pickle.load(open(args.identifiers, 'rb'))
        except:
            pass

    # read the configuration file. This is in YAML format
    try:
        configfile = open(args.cfg, 'r')
        config = load(configfile, Loader=Loader)
    except (YAMLError, PermissionError):
        print("Cannot open configuration file, exiting", file=sys.stderr)
        sys.exit(1)

    # some sanity checks:
    for i in ['general', 'yara']:
        if i not in config:
            print("Invalid configuration file, section %s missing, exiting" % i,
                  file=sys.stderr)
            sys.exit(1)

    verbose = False
    if 'verbose' in config['general']:
        if isinstance(config['general']['verbose'], bool):
            verbose = config['general']['verbose']

    threads = multiprocessing.cpu_count()
    if 'threads' in config['general']:
        if isinstance(config['general']['threads'], int):
            threads = config['general']['threads']

    if 'yara_directory' not in config['yara']:
        print("yara_directory not defined in configuration, exiting",
              file=sys.stderr)
        sys.exit(1)

    yara_directory = pathlib.Path(config['yara']['yara_directory'])
    if not yara_directory.exists():
        print("yara_directory does not exist, exiting",
              file=sys.stderr)
        sys.exit(1)

    if not yara_directory.is_dir():
        print("yara_directory is not a valid directory, exiting",
              file=sys.stderr)
        sys.exit(1)

    # check if the yara directory is writable
    try:
        temp_name = tempfile.NamedTemporaryFile(dir=yara_directory)
        temp_name.close()
    except:
        print("yara_directory is not writable, exiting",
              file=sys.stderr)
        sys.exit(1)

    yara_binary_directory = yara_directory / 'binary'

    yara_binary_directory.mkdir(exist_ok=True)

    string_cutoff = 8
    if 'string_cutoff' in config['yara']:
        if isinstance(config['yara']['string_cutoff'], int):
            string_cutoff = config['yara']['string_cutoff']

    identifier_cutoff = 2
    if 'identifier_cutoff' in config['yara']:
        if isinstance(config['yara']['identifier_cutoff'], int):
            identifier_cutoff = config['yara']['identifier_cutoff']

    max_identifiers = 10000
    if 'max_identifiers' in config['yara']:
        if isinstance(config['yara']['max_identifiers'], int):
            max_identifiers = config['yara']['max_identifiers']

    processmanager = multiprocessing.Manager()

    # ignore object files (regular and GHC specific)
    ignored_suffixes = ['.o', '.p_o']

    ignore_weak_symbols = False
    if 'ignore_weak_symbols' in config['yara']:
        if isinstance(config['yara']['ignore_weak_symbols'], bool):
            ignore_weak_symbols = config['yara']['ignore_weak_symbols']

    # create a lock to control access to any shared data structures
    processlock = multiprocessing.Lock()

    # create a shared dictionary
    processed_files = processmanager.dict()

    # create a queue for scanning files
    yaraqueue = processmanager.JoinableQueue(maxsize=0)
    processes = []

    # walk the results directory
    for bang_directory in result_directory.iterdir():
        bang_pickle = bang_directory / 'bang.pickle'
        if not bang_pickle.exists():
            continue

        yaraqueue.put(bang_directory)

    # tags = ['debian', 'debian11']
    tags = []

    yara_env = {'verbose': verbose, 'string_cutoff': string_cutoff,
                'identifier_cutoff': identifier_cutoff,
                'ignored_suffixes': ignored_suffixes,
                'ignore_weak_symbols': ignore_weak_symbols,
                'lq_identifiers': lq_identifiers, 'tags': tags,
                'max_identifiers': max_identifiers}

    # create processes for unpacking archives
    for i in range(0, threads):
        process = multiprocessing.Process(target=process_directory,
                                          args=(yaraqueue, yara_directory,
                                                yara_binary_directory, processlock,
                                                processed_files, yara_env))
        processes.append(process)

    # start all the processes
    for process in processes:
        process.start()

    yaraqueue.join()

    # Done processing, terminate processes
    for process in processes:
        process.terminate()


if __name__ == "__main__":
    main(sys.argv)

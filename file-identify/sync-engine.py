#!/usr/bin/env python3
"""Keep the engine a byte-for-byte copy of auto-sort's own.

    python3 file-identify/sync-engine.py --from ~/code/auto-sort
    python3 file-identify/sync-engine.py --check
    python3 file-identify/sync-engine.py --check --from ~/code/auto-sort

The identifier is auto-sort's, not a rewrite of it: `engine/` holds the
modules auto-sort itself uses to decide what a file is, copied unchanged,
with `engine/MANIFEST.json` naming the auto-sort commit they came from and
the hash of every file. A copy that is edited here drifts, and the next fix
in auto-sort does not reach it -- so the engine is never edited here. It is
fixed in auto-sort and copied again.

`--from` copies from an auto-sort checkout and rewrites the manifest.
`--check` fails if any engine file differs from its manifest entry, and,
given `--from` as well, if the checkout has moved on since the copy.
Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(HERE, "engine")
MANIFEST = os.path.join(ENGINE, "MANIFEST.json")

# What identify.py reaches, found by importing it alone and reading every
# file off sys.modules. owner and winapi are imported lazily -- the owner's
# name so a letter's heading is never taken to be the person it is addressed
# to, winapi for Windows download marks -- so a first run would miss them.
MODULES = ("identify", "bundles", "evidence", "folders", "hosts", "kinds",
           "names", "owner", "platform_support", "provenance", "signatures",
           "sites", "winapi")


def wanted(source):
    """Every file the engine is made of, as paths relative to its root."""
    files = ["%s.py" % name for name in MODULES]
    readers = os.path.join(source, "readers")
    files += sorted("readers/" + name for name in os.listdir(readers)
                    if name.endswith(".py"))
    return files


def digest(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def commit_of(source):
    try:
        done = subprocess.run(["git", "-C", source, "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=30)
        dirty = subprocess.run(["git", "-C", source, "status", "--porcelain",
                                "--", "*.py"],
                               capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip() + (" (with uncommitted changes)"
                                  if dirty.stdout.strip() else "")


def version_of(source):
    try:
        with open(os.path.join(source, "autosort.py"), encoding="utf-8") as h:
            for line in h:
                if line.startswith("VERSION"):
                    return line.split("=", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return None


def copy(source):
    if not os.path.isfile(os.path.join(source, "identify.py")):
        print("%s is not an auto-sort checkout" % source, file=sys.stderr)
        return 1
    files = wanted(source)
    if os.path.isdir(ENGINE):
        shutil.rmtree(ENGINE)
    os.makedirs(os.path.join(ENGINE, "readers"))
    for name in files:
        shutil.copyfile(os.path.join(source, name),
                        os.path.join(ENGINE, name))
    manifest = {
        "from": "https://github.com/snepssen/auto-sort",
        "version": version_of(source),
        "commit": commit_of(source),
        "files": dict((name, digest(os.path.join(ENGINE, name)))
                      for name in files),
    }
    with open(MANIFEST, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print("copied %d files from auto-sort %s (%s)"
          % (len(files), manifest["version"], manifest["commit"]))
    return 0


def check(source=None):
    try:
        with open(MANIFEST, encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError) as error:
        print("no readable manifest: %s" % error, file=sys.stderr)
        return 1
    problems = []
    listed = set(manifest["files"])
    for name, expected in sorted(manifest["files"].items()):
        path = os.path.join(ENGINE, name)
        if not os.path.isfile(path):
            problems.append("%s is missing" % name)
        elif digest(path) != expected:
            problems.append("%s was edited here; fix it in auto-sort and "
                            "copy again" % name)
    for folder, _dirs, names in os.walk(ENGINE):
        if "__pycache__" in folder:
            continue
        for name in names:
            relative = os.path.relpath(os.path.join(folder, name),
                                       ENGINE).replace(os.sep, "/")
            if name.endswith(".py") and relative not in listed:
                problems.append("%s is not auto-sort's" % relative)
    if source:
        for name in sorted(set(wanted(source)) | listed):
            there = os.path.join(source, name)
            if not os.path.isfile(there):
                problems.append("%s is no longer in auto-sort" % name)
            elif name not in listed:
                problems.append("%s is new in auto-sort" % name)
            elif digest(there) != manifest["files"][name]:
                problems.append("%s has changed in auto-sort" % name)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        if source:
            print("copy again with: python3 file-identify/sync-engine.py "
                  "--from %s" % source, file=sys.stderr)
        return 1
    print("engine matches auto-sort %s (%d files)"
          % (manifest.get("version"), len(listed)))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Copy auto-sort's identifier here, or check the copy.")
    parser.add_argument("--from", dest="source", metavar="AUTO_SORT",
                        help="an auto-sort checkout to copy from")
    parser.add_argument("--check", action="store_true",
                        help="change nothing; fail if the copy differs")
    options = parser.parse_args(argv)
    source = options.source and os.path.abspath(
        os.path.expanduser(options.source))
    if options.check:
        return check(source)
    if not source:
        parser.error("give --from AUTO_SORT, or --check")
    return copy(source)


if __name__ == "__main__":
    sys.exit(main())

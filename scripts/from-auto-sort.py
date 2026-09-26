#!/usr/bin/env python3
"""Keep the tools taken from auto-sort byte-for-byte copies of its code.

    python3 scripts/from-auto-sort.py --from ~/code/auto-sort
    python3 scripts/from-auto-sort.py --check
    python3 scripts/from-auto-sort.py --check --from ~/code/auto-sort
    python3 scripts/from-auto-sort.py --check --only tray-icon

These tools are auto-sort's code run on its own, not rewrites of it:
file-identify, tray-icon, exact-duplicates and bundle-list. Each
has an `engine/` holding auto-sort's modules, copied unchanged, with
`engine/MANIFEST.json` naming the auto-sort commit they came from and the
hash of every file. A copy that is edited here drifts, and the next fix in
auto-sort does not reach it -- so an engine is never edited here. It is
fixed in auto-sort and copied again.

`--from` copies from an auto-sort checkout and rewrites the manifests.
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Each tool, the auto-sort modules it is made of, and whether it takes the
# readers package whole.
ENGINES = {
    # What identify.py reaches, found by importing it alone and reading
    # every file off sys.modules. owner and winapi are imported lazily --
    # the owner's name so a letter's heading is never taken to be the person
    # it is addressed to, winapi for Windows download marks -- so a first
    # run would miss them.
    "file-identify": (("identify", "bundles", "evidence", "folders", "hosts",
                       "kinds", "names", "owner", "platform_support",
                       "provenance", "signatures", "sites", "winapi"), True),
    # The tray, the D-Bus wire protocol its Linux icon speaks, and the
    # declared Win32 signatures its Windows icon calls through.
    "tray-icon": (("tray", "dbuswire", "winapi"), False),
    "bundle-list": (("bundles", "kinds"), False),
    "exact-duplicates": (("duplicates", "bundles", "kinds", "mover",
                           "paths", "userdirs", "winapi"), False),
}


def engine_dir(tool):
    return os.path.join(ROOT, tool, "engine")


def manifest_path(tool):
    return os.path.join(engine_dir(tool), "MANIFEST.json")


def wanted(tool, source):
    """Every file an engine is made of, as paths relative to its root."""
    modules, with_readers = ENGINES[tool]
    files = ["%s.py" % name for name in modules]
    if with_readers:
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


def copy(tool, source):
    files = wanted(tool, source)
    engine = engine_dir(tool)
    if os.path.isdir(engine):
        shutil.rmtree(engine)
    for name in files:
        target = os.path.join(engine, name)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(os.path.join(source, name), target)
    manifest = {
        "from": "https://github.com/snepssen/auto-sort",
        "version": version_of(source),
        "commit": commit_of(source),
        "files": dict((name, digest(os.path.join(engine, name)))
                      for name in files),
    }
    with open(manifest_path(tool), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print("%s: copied %d files from auto-sort %s (%s)"
          % (tool, len(files), manifest["version"], manifest["commit"]))
    return 0


def check(tool, source=None):
    try:
        with open(manifest_path(tool), encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError) as error:
        print("%s: no readable manifest: %s" % (tool, error), file=sys.stderr)
        return 1
    engine = engine_dir(tool)
    problems = []
    listed = set(manifest["files"])
    for name, expected in sorted(manifest["files"].items()):
        path = os.path.join(engine, name)
        if not os.path.isfile(path):
            problems.append("%s is missing" % name)
        elif digest(path) != expected:
            problems.append("%s was edited here; fix it in auto-sort and "
                            "copy again" % name)
    for folder, _dirs, names in os.walk(engine):
        if "__pycache__" in folder:
            continue
        for name in names:
            relative = os.path.relpath(os.path.join(folder, name),
                                       engine).replace(os.sep, "/")
            if name.endswith(".py") and relative not in listed:
                problems.append("%s is not auto-sort's" % relative)
    if source:
        for name in sorted(set(wanted(tool, source)) | listed):
            there = os.path.join(source, name)
            if not os.path.isfile(there):
                problems.append("%s is no longer in auto-sort" % name)
            elif name not in listed:
                problems.append("%s is new in auto-sort" % name)
            elif digest(there) != manifest["files"][name]:
                problems.append("%s has changed in auto-sort" % name)
    for problem in problems:
        print("%s: %s" % (tool, problem), file=sys.stderr)
    if problems:
        if source:
            print("copy again with: python3 scripts/from-auto-sort.py "
                  "--from %s" % source, file=sys.stderr)
        return 1
    print("%s: engine matches auto-sort %s (%d files)"
          % (tool, manifest.get("version"), len(listed)))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Copy auto-sort's code into the tools made of it, or "
                    "check the copies.")
    parser.add_argument("--from", dest="source", metavar="AUTO_SORT",
                        help="an auto-sort checkout to copy from")
    parser.add_argument("--check", action="store_true",
                        help="change nothing; fail if a copy differs")
    parser.add_argument("--only", choices=sorted(ENGINES), action="append",
                        help="just this tool (may be repeated)")
    options = parser.parse_args(argv)
    source = options.source and os.path.abspath(
        os.path.expanduser(options.source))
    tools = options.only or sorted(ENGINES)
    if options.check:
        return max(check(tool, source) for tool in tools)
    if not source:
        parser.error("give --from AUTO_SORT, or --check")
    if not os.path.isfile(os.path.join(source, "tray.py")):
        print("%s is not an auto-sort checkout" % source, file=sys.stderr)
        return 1
    return max(copy(tool, source) for tool in tools)


if __name__ == "__main__":
    sys.exit(main())

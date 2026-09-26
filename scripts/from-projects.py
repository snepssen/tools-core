#!/usr/bin/env python3
"""Copy and verify the engines extracted from Media Preflight and siphon.

Auto Sort extractions continue to use from-auto-sort.py.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ENGINES = {
    "caption-check": ("media-preflight", ("captions.py", "platform_support.py")),
    "remux": ("siphon", ("formats.py", "platform_support.py",
                         "engines/__init__.py", "engines/ffmpeg.py")),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(tool, source=None):
    project, names = ENGINES[tool]
    engine = ROOT / tool / "engine"
    problems = []
    try:
        manifest = json.loads((engine / "MANIFEST.json").read_text())
        if set(manifest["files"]) != set(names):
            problems.append("manifest does not match the extraction's file list")
        if manifest.get("from") != "https://github.com/snepssen/" + project:
            problems.append("manifest names the wrong upstream project")
        for name in names:
            expected = manifest["files"].get(name)
            if digest(engine / name) != expected:
                problems.append(name + " differs; fix it upstream and copy again")
            if source and digest(source / name) != expected:
                problems.append(name + " has changed upstream")
        actual = {p.relative_to(engine).as_posix() for p in engine.rglob("*.py")}
        if actual != set(names):
            problems.append("unexpected or missing engine modules")
    except (OSError, ValueError, KeyError) as error:
        problems.append(str(error))
    for problem in problems:
        print(tool + ": " + problem, file=sys.stderr)
    if not problems:
        print(tool + ": engine matches its upstream manifest")
    return bool(problems)


def copy(tool, source):
    project, names = ENGINES[tool]
    # Read everything before touching the existing copy.
    contents = {name: (source / name).read_bytes() for name in names}
    version = (source / "VERSION").read_text().strip()
    commit = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(source), "status", "--porcelain", "--",
         *names, "VERSION"], text=True).strip()
    if dirty:
        commit += " (with uncommitted changes)"
    engine = ROOT / tool / "engine"
    if engine.exists():
        shutil.rmtree(engine)
    for name, data in contents.items():
        target = engine / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    manifest = {"from": "https://github.com/snepssen/" + project,
                "version": version, "commit": commit,
                "files": {name: digest(engine / name) for name in names}}
    (engine / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(tool + ": copied from " + project + " " + version)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="source", type=Path)
    parser.add_argument("--project", choices=sorted({p for p, _ in ENGINES.values()}))
    parser.add_argument("--only", choices=sorted(ENGINES), action="append")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.source and not args.project:
        parser.error("--from needs --project")
    if not args.check and not args.source:
        parser.error("give --check or --project PROJECT --from CHECKOUT")
    selected = args.only or sorted(ENGINES)
    if args.project:
        if args.only and any(ENGINES[t][0] != args.project for t in selected):
            parser.error("--only must belong to --project")
        selected = [t for t in selected if ENGINES[t][0] == args.project]
    source = args.source.expanduser().resolve() if args.source else None
    try:
        results = [(check(t, source) if args.check else copy(t, source))
                   for t in selected]
    except (OSError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return int(any(results))


if __name__ == "__main__":
    sys.exit(main())

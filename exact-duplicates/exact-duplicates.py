#!/usr/bin/env python3
"""Report exact file duplicates. Nothing is deleted, renamed or moved."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / "engine"))
import bundles
import duplicates


def minimum(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1 byte")
    return number


def roots_for(folders):
    roots = []
    for folder in folders:
        root = folder.expanduser().resolve()
        if not root.is_dir():
            raise OSError("Not a directory: " + str(root))
        if bundles.is_package(str(root)):
            raise OSError("Choose a folder outside the package: " + str(root))
        next(root.iterdir(), None)  # Check that the root can actually be read.
        if any(root == old or old in root.parents for old in roots):
            continue
        roots = [old for old in roots if root not in old.parents]
        roots.append(root)
    return [str(root) for root in roots]


def report_groups(groups):
    rows = []
    for group in groups:
        # Overlapping inputs and hard links must never inflate the space count.
        inodes = {}
        for path in sorted(set(group.paths)):
            try:
                status = os.stat(path, follow_symlinks=False)
            except OSError:
                continue
            if status.st_size != group.size:
                continue
            key = (status.st_dev, status.st_ino) if status.st_ino else path
            inodes.setdefault(key, []).append(path)
        if len(inodes) < 2:
            continue
        copies = list(inodes.values())
        rows.append({"sha256": group.digest, "size": group.size,
                     "paths": [paths[0] for paths in copies],
                     "hardlink_aliases": {paths[0]: paths[1:] for paths in copies if len(paths) > 1},
                     "duplicate_bytes": group.size * (len(copies) - 1)})
    rows.sort(key=lambda row: (-row["duplicate_bytes"], row["paths"]))
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folders", nargs="+", type=Path)
    parser.add_argument("--min-size", type=minimum, default=1, metavar="BYTES")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        roots = roots_for(args.folders)
        groups = duplicates.scan(roots, min_size=args.min_size, limit=sys.maxsize)
        rows = report_groups(groups)
    except OSError as error:
        print(str(error), file=sys.stderr)
        return 1
    report = {"roots": roots, "groups": rows,
              "duplicate_bytes": sum(row["duplicate_bytes"] for row in rows)}
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for row in rows:
            print("%d copies of %d bytes  SHA-256 %s" %
                  (len(row["paths"]), row["size"], row["sha256"]))
            for path in row["paths"]:
                print("  " + path)
                for alias in row["hardlink_aliases"].get(path, []):
                    print("    hard link: " + alias)
        print("%d duplicate groups; %d duplicate bytes (logical size, not guaranteed disk savings)"
              % (len(rows), report["duplicate_bytes"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""List files that belong together, without moving or changing them."""
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / "engine"))
import bundles


def depth(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--depth", type=depth, default=3,
                        help="maximum descent with --recursive (default: 3)")
    parser.add_argument("--groups-only", action="store_true",
                        help="omit ordinary single files")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = args.folder.expanduser().absolute()
    try:
        if not root.is_dir():
            raise OSError("Not a directory: " + str(root))
        # Fail on an unreadable root, instead of reporting an empty listing.
        names = [p.name for p in root.iterdir()]
        if bundles.is_package(str(root)):
            items = [bundles.Item(str(root), reason="package directory")]
        elif args.recursive:
            items = bundles.walk(str(root), max_depth=args.depth)
        else:
            items = bundles.group(str(root), names)
        rows = []
        for item in items:
            if args.groups_only and len(item.members) == 1 and not item.is_dir:
                continue
            rows.append({"primary": item.primary, "members": sorted(item.members),
                         "reason": item.reason or "single file", "directory": item.is_dir,
                         "sequence": item.sequence})
        rows.sort(key=lambda row: row["primary"])
    except OSError as error:
        print(str(error), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    else:
        for row in rows:
            print("%s  [%s]" % (row["primary"], row["reason"]))
            if len(row["members"]) > 1:
                for member in row["members"]:
                    print("  " + member)
        print("%d items" % len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())

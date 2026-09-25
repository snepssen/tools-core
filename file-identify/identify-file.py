#!/usr/bin/env python3
"""What a file is, from its bytes rather than its name.

    python3 file-identify/identify-file.py invoice.pdf
    python3 file-identify/identify-file.py --facts photo.jpg
    python3 file-identify/identify-file.py --json ~/Downloads/*
    python3 file-identify/identify-file.py --no-programs scan.tiff

For each path: what it really is (and whether its extension says otherwise),
the heading a document gives itself, when it happened as best that can be
told, and where it came from if the system kept a note of the download.
`--facts` prints everything that was found, each with the reader that found
it and how sure that reader is; `--json` prints the same for a program.

This is auto-sort's identifier, run on its own. The engine in `engine/` is
a copy of auto-sort's modules, never edited here (see sync-engine.py).

It reads and never writes: nothing is moved, renamed, cached or sent. The
readers are standard-library Python. ffprobe, exiftool and, for scans,
the Mac's own text recognition or tesseract are used when they are installed
and a file still has a gap they could fill; `--no-programs` starts none of
them.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "engine"))
sys.dont_write_bytecode = True

import bundles                                           # noqa: E402
import evidence                                          # noqa: E402
import identify                                          # noqa: E402
import kinds                                             # noqa: E402

TIERS = {"stat": identify.TIER_STAT, "signature": identify.TIER_SIGNATURE,
         "header": identify.TIER_HEADER, "all": identify.TIER_ALL}

# The facts worth a line in the short form, in the order they are read. The
# rest -- and every source and confidence -- is one `--facts` away.
SUMMARY = (
    ("heading", "Heading"),
    ("title", "Title"),
    ("title_drawn", "Title"),
    ("doc_title", "Title"),
    ("song_title", "Song"),
    ("artist", "Artist"),
    ("album", "Album"),
    ("author", "Author"),
    ("camera", "Camera"),
    ("scanner", "Scanner"),
    ("capture", "Made as"),
    ("project", "Project"),
    ("from_host", "Downloaded from"),
    ("from_app", "Downloaded by"),
)
# Where the date came from, said plainly: a photo's own clock and the day
# it landed in Downloads are very different kinds of evidence.
DATED_BY = {
    "taken": "when the photo was taken",
    "created": "when the file says it was made",
    "content_created": "when the file says it was made",
    "digitised": "when it was scanned",
    "name_date": "the date in its name",
    "added": "when it arrived on this disk",
}
FLAGS = (
    ("needs_password", "locked with a password"),
    ("encryption_unread", "encrypted in a way that is not read"),
    ("encrypted", "encrypted, opens without a password"),
    ("needs_ocr", "a scan with no text layer"),
    ("empty", "empty"),
    ("dataless", "in the cloud, not on this disk"),
)


def target_for(path):
    """The item a path belongs to: a photo with its sidecar is one thing."""
    path = os.path.abspath(path)
    directory = os.path.dirname(path) or "."
    try:
        for item in bundles.group(directory):
            if path in (os.path.abspath(member) for member in item.members):
                return item
    except OSError:
        pass
    return bundles.Item(path)


def size_text(count):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if count < 1024 or unit == "TB":
            return "%.0f %s" % (count, unit) if unit == "B" \
                else "%.1f %s" % (count, unit)
        count /= 1024.0
    return str(count)


def duration_text(seconds):
    seconds = int(round(float(seconds)))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return ("%d:%02d:%02d" % (hours, minutes, seconds) if hours
            else "%d:%02d" % (minutes, seconds))


def as_data(record, item):
    return {
        "path": record.path,
        "members": list(item.members),
        "facts": dict((name, {"value": fact.value, "source": fact.source,
                              "confidence": round(fact.confidence, 3),
                              "agreed_by": fact.corroborated_by})
                      for name, fact in record.items()),
        "read_by": [{"reader": name, "result": detail}
                    for name, detail in record.readers],
        "notes": list(record.notes),
        "conflicts": [str(conflict) for conflict in record.conflicts],
    }


def summary(record, item):
    value = record.value
    lines = ["", "  %s" % value("name", os.path.basename(record.path))]
    what = "/".join(str(part) for part in (value("kind"), value("format"))
                    if part)
    details = [what or "unknown"]
    if value("size") is not None:
        details.append(size_text(value("size")))
    if value("duration"):
        details.append(duration_text(value("duration")))
    if value("width") and value("height"):
        details.append("%s x %s" % (value("width"), value("height")))
    if len(item.members) > 1:
        details.append("%d files, read as one" % len(item.members))
    lines.append("  " + "  ·  ".join(details))

    rows = []
    happened = record.fact("happened")
    if happened:
        how = happened.source.split(":", 1)[-1]
        rows.append(("Happened", "%s  (%s)" % (happened.value,
                                               DATED_BY.get(how, how))))
    shown = set()
    for name, label in SUMMARY:
        if label in shown or not record.has(name):
            continue
        shown.add(label)
        rows.append((label, str(value(name))))
    for name, label in FLAGS:
        if value(name):
            rows.append(("Note", label))
            break
    if value("extension_lies"):
        claim = kinds.classify_extension(value("ext"))
        if claim:
            rows.append(("Note", "named .%s, which would be %s/%s"
                         % (value("ext"), claim[0], claim[1])))
    if rows:
        lines.append("")
        width = max(len(label) for label, _ in rows)
        lines += ["  %-*s  %s" % (width, label, text) for label, text in rows]
    return lines


def every_fact(record):
    lines = []
    if record.readers:
        lines += ["", "  Read by"]
        lines += ["    %-16s %s" % (name, detail)
                  for name, detail in record.readers]
    lines += ["", "  What is known"]
    for name, fact in record.items():
        if name in ("path", "dir"):
            continue
        agreed = ""
        if fact.corroborated_by:
            agreed = "  agreed by " + ", ".join(fact.corroborated_by)
        text = str(fact.value)
        if len(text) > 40:
            text = text[:39] + "…"
        lines.append("    %-20s %-40s %-8s %s%s" % (
            name, text, evidence.band(fact.confidence), fact.source, agreed))
    if record.conflicts:
        lines += ["", "  Disagreements"]
        lines += ["    %s" % conflict for conflict in record.conflicts]
    if record.notes:
        lines += ["", "  Notes"]
        lines += ["    - %s" % note for note in record.notes]
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="What a file is, from its bytes rather than its name.")
    parser.add_argument("paths", nargs="+", metavar="PATH")
    shape = parser.add_mutually_exclusive_group()
    shape.add_argument("--facts", action="store_true",
                       help="every fact, with its reader and confidence")
    shape.add_argument("--json", action="store_true",
                       help="every fact, as JSON")
    parser.add_argument("--tier", choices=sorted(TIERS), default="all",
                        help="how far to read: stat (the name and the disk "
                             "only), signature, header, all (default)")
    parser.add_argument("--no-programs", action="store_true",
                        help="read with Python alone; start no other "
                             "program (the same as --tier header)")
    options = parser.parse_args(argv)
    tier = TIERS[options.tier]
    if options.no_programs:
        tier = min(tier, identify.TIER_HEADER)

    found, missing = [], 0
    for path in options.paths:
        if not os.path.lexists(path):
            print("No such file: %s" % path, file=sys.stderr)
            missing += 1
            continue
        item = target_for(path)
        record = identify.identify(item, tier=tier)
        if options.json:
            found.append(as_data(record, item))
            continue
        lines = summary(record, item)
        if options.facts:
            lines += every_fact(record)
        print("\n".join(lines))
    if options.json:
        print(json.dumps(found if len(options.paths) > 1 else
                         (found[0] if found else None),
                         indent=2, default=str, ensure_ascii=False))
    elif len(options.paths) > missing:
        print()
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())

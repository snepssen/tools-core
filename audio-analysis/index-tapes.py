#!/usr/bin/env python3
"""Assign levels to tape transcripts from evidence, not assumption.

A track's title is authoritative when it names a Focus level ("Intro Focus 27").
Otherwise the body decides: a level mentioned repeatedly is what the track
works in, a level mentioned once in passing is not. Whichever way it was
decided is recorded in the frontmatter, so an inferred level never looks like
a stated one.

    index-tapes.py GATEWAY_ROOT [--dry-run]
"""
import pathlib, re, sys, collections

args = [a for a in sys.argv[1:] if not a.startswith("--")]
if len(args) != 1:
    raise SystemExit(__doc__)
DRY = "--dry-run" in sys.argv
ROOT = pathlib.Path(args[0]).resolve()
SRC = ROOT / "library/sources"

# A level named this many times or more is a level the track actually works in.
THRESHOLD = 3

def levels_in(text):
    hits = re.findall(r"[Ff]ocus\s+(\d{1,2})", text)
    return collections.Counter("F" + h for h in hits)

changed = 0
for md in sorted(SRC.rglob("*.md")):
    raw = md.read_text()
    if not raw.startswith("---"):
        continue
    _, fm, body = raw.split("---", 2)
    fm_lines = [l for l in fm.strip().split("\n") if l.strip()]
    meta = {}
    for l in fm_lines:
        if ":" in l:
            k, v = l.split(":", 1)
            meta[k.strip()] = v.strip()

    title_levels = sorted(set(re.findall(r"[Ff]ocus\s+(\d{1,2})", meta.get("title", ""))),
                          key=int)
    # Every tape counts up through F10 and F12 on its way somewhere, so raw
    # mentions say where a track *goes*, not what it is *about*. The
    # destination -- the highest level it actually works in -- is the subject;
    # the rest are passed through.
    if title_levels:
        levels = ["F" + n for n in title_levels]
        visits = levels
        basis = "title"
    else:
        counts = levels_in(body)
        visits = sorted((l for l, n in counts.items() if n >= THRESHOLD),
                        key=lambda l: int(l[1:]))
        levels = visits[-1:]        # destination only
        basis = f"body: destination of {', '.join(visits)}" if visits else "none"

    if not levels:
        continue

    meta["levels"] = ", ".join(levels)
    if visits != levels:
        meta["levels-visits"] = ", ".join(visits)
    meta["levels-basis"] = basis
    order = ["kind", "title", "source", "levels", "levels-visits", "levels-basis", "transcribed"]
    out = "---\n" + "\n".join(f"{k}: {meta[k]}" for k in order if k in meta)
    for k, v in meta.items():
        if k not in order:
            out += f"\n{k}: {v}"
    out += "\n---\n" + body.lstrip("\n").rstrip() + "\n"
    if not DRY and out != raw:
        md.write_text(out)
    changed += 1
    print(f"{md.relative_to(ROOT)}  ->  {meta['levels']}  [{basis}]")

print(f"{'would index' if DRY else 'indexed'} {changed} transcripts")

#!/usr/bin/env python3
"""Seed provisional briefings for levels no source describes.

Two rules, both the user's:

1. **Curiosity, not assertion.** These levels have no Monroe source and no
   recorded experience. A briefing that told the listener what is there would
   be inventing it. So each one names the level, says where it sits by what
   comes before and after, and invites noticing.
2. **Position by neighbours.** "Look what's before and what's after… draw a
   line or a curve from 1 to 3 and see where 2 would fit."

Every file is @provisional: written to be voiced and compiled now, replaced
when experience supplies something truer. Existing files are never overwritten.
"""
import pathlib, json, sys

args = [a for a in sys.argv[1:] if not a.startswith("--")]
if len(args) != 1:
    raise SystemExit("usage: seed-briefings.py GATEWAY_ROOT [--dry-run]")
ROOT = pathlib.Path(args[0]).resolve()
DRY_RUN = "--dry-run" in sys.argv
SEG = ROOT / "library/segments"
levels = json.loads((ROOT / "library/levels.json").read_text())
by_key = {l["key"]: l for l in levels}

# level: (what you came from, what lies beyond, the one thread published
# material offers — used as an invitation, never as a statement of fact)
CONTEXT = {
    "F11": ("the ten state, body asleep and mind awake", "the expanded awareness of Focus 12",
            "a channel that reaches every level of awareness"),
    "F18": ("the timelessness of Focus 15", "the bridge at Focus 21",
            "unconditional acceptance"),
    "F22": ("the bridge you crossed at Focus 21", "the new arrivals of Focus 23",
            "the border of time and space, where some are only partly present"),
    "F24": ("the new arrivals of Focus 23", "the organised beliefs of Focus 25",
            "the simplest belief systems, built by those who hold them"),
    "F34": ("the Park at Focus 27", "the further reaches of Focus 35",
            "a gathering of many, come to witness"),
    "F35": ("the gathering at Focus 34", "the clusters of Focus 42",
            "the same gathering, seen from further out"),
    "F42": ("the gathering you passed", "the sea of clusters at Focus 49",
            "many voices that are one"),
    "F49": ("the cluster consciousness of Focus 42", "whatever lies past the edge of the map",
            "clusters beyond counting"),
}

written, skipped = 0, 0
for key, (behind, ahead, thread) in CONTEXT.items():
    path = SEG / f"briefing-{key.lower()}.gws"
    if path.exists():
        skipped += 1
        continue
    lv = by_key.get(key)
    n = key[1:]
    name = lv["name"] if lv else key
    src = f"""# PROVISIONAL. No Monroe tape and no manual describes Focus {n}; this was
# written to be voiced and compiled while the level is still unknown. It names
# the level, places it between its neighbours, and invites noticing. It does
# not say what is there, because nobody has written that down yet.
#
# Replace it the moment experience supplies something truer.

@segment     briefing-{key.lower()}
@title       Focus {n} — {name} (provisional)
@levels      {key}
@verbosity   2
@provisional
@protected   Focus {n}
@duration    ~50s

say You are now in Focus {n}.
pause 5
say Behind you, {behind}. Ahead, {ahead}.
pause 6
say What is published of this place speaks of {thread}. Hold that lightly. It may be so, and it may not.
pause 8
say Nothing here has been described to you, so there is nothing you are meant to find.
pause 6
say Look around. Let whatever is here show itself, in its own time.
pause 12
say Whatever you notice, remember it. It will be the first account of this place.
pause 10
"""
    if not DRY_RUN:
        path.write_text(src)
    written += 1
    print(f"seeded {path.name}")
verb = "would be written" if DRY_RUN else "written"
print(f"{written} provisional briefings {verb}, {skipped} left alone")

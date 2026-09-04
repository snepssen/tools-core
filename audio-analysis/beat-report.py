#!/usr/bin/env python3
"""Turn the per-tape beat measurements into a per-level picture.

Each tape is indexed to the level it works in (from the transcript frontmatter,
`index-tapes.py`), so the measured beats can be grouped by level and set
against what levels.json claims.
"""
import json, pathlib, re, sys, collections

if len(sys.argv) != 3:
    raise SystemExit("usage: beat-report.py GATEWAY_ROOT BEAT_ANALYSIS_DIR")
ROOT = pathlib.Path(sys.argv[1]).resolve()
BEATS = pathlib.Path(sys.argv[2]).resolve()
levels = {l["key"]: l for l in json.loads((ROOT / "library/levels.json").read_text())}

# tape stem -> level, from the transcripts' own frontmatter
tape_level = {}
for md in (ROOT / "library/sources/gateway-experience").rglob("*.md"):
    fm = md.read_text().split("---")[1] if md.read_text().startswith("---") else ""
    title = lvl = None
    for line in fm.strip().split("\n"):
        if line.startswith("title:"): title = line.split(":", 1)[1].strip()
        if line.startswith("levels:"): lvl = line.split(":", 1)[1].strip()
    if title and lvl:
        tape_level[re.sub(r"[^a-z0-9]+", "", title.lower())] = lvl.split(",")[0].strip()

by_level = collections.defaultdict(list)
rows = []
for j in sorted(BEATS.glob("*.json")):
    try:
        d = json.loads(j.read_text())
    except json.JSONDecodeError:
        continue          # still being written by a running batch

    stem = pathlib.Path(d["file"]).stem
    lvl = tape_level.get(re.sub(r"[^a-z0-9]+", "", stem.lower()))
    rows.append((stem, lvl, d))
    if lvl and d.get("layers"):
        by_level[lvl].append((stem, d.get("dominant"), d))

# Two tones only slightly detuned -- stereo-widened music, say -- read as a
# very low "beat" that nobody is entraining to. Report them, but do not let
# them decide a level's frequency.
FLOOR = 1.8

print(f"{'level':6} {'claimed':>8} {'measured':>9} {'tapes':>6}  holds by time held")
for key in sorted(by_level, key=lambda k: int(k[1:])):
    entries = by_level[key]
    claimed = levels.get(key, {}).get("beatHz")
    # Weight each layer by how much of the tape it is present for, times how
    # loud it is -- the primary layer is the one you are entraining to.
    holds = collections.Counter()
    carriers = collections.Counter()
    for _, _, d in entries:
        for l in d.get("layers", []):
            if l["share"] < 4.0 or l["amp"] < 0.25:
                continue
            if l["carrier"] < 40:      # below any Hemi-Sync carrier
                continue
            holds[round(l["beat"] * 10) / 10] += l["share"] * l["amp"]
            carriers[round(l["carrier"])] += l["share"] * l["amp"]
    total = sum(holds.values()) or 1
    ranked = holds.most_common()
    real = [(b, w) for b, w in ranked if b >= FLOOR]
    measured = real[0][0] if real else None
    top = "  ".join(f"{b:g}Hz {100*w/total:.0f}%" + ("*" if b < FLOOR else "")
                    for b, w in ranked[:4])
    if carriers:
        top += "   carriers " + "/".join(str(c) for c, _ in carriers.most_common(3))
    flag = ""
    if claimed and measured and abs(claimed - measured) > 0.6:
        flag = f"   <-- claimed {claimed:g}"
    m = f"{measured:9.2f}" if measured else f"{'—':>9}"
    print(f"{key:6} {claimed if claimed is not None else '—':>8} {m} {len(entries):6}  {top}{flag}")
print("\n* below 1.8 Hz: likely detuned stereo content, not an entrainment tone")

unmapped = [s for s, l, _ in rows if not l]
print(f"\n{len(rows)} tapes analysed, {len(rows)-len(unmapped)} mapped to a level")
if unmapped:
    print("not mapped to any level:", ", ".join(unmapped[:6]), "…" if len(unmapped) > 6 else "")

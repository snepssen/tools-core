#!/usr/bin/env python3
"""Save each tape's measured Hemi-Sync signal as a profile the app can
regenerate from.

The analysis JSON is a measurement log; a profile is a playable description.
Confidence comes from the measurement itself: how steady the tone held and how
long it ran. Harmonics are folded to their fundamental, because a 50/50.75 Hz
pair and its 100/101.5 Hz image are one signal.
"""
import json, pathlib, re, sys

if len(sys.argv) != 3:
    raise SystemExit("usage: save-signals.py GATEWAY_ROOT BEAT_ANALYSIS_DIR")
ROOT = pathlib.Path(sys.argv[1]).resolve()
BEATS = pathlib.Path(sys.argv[2]).resolve()
OUT = ROOT / "library/signals/measured"
OUT.mkdir(parents=True, exist_ok=True)

# tape title -> level, from the transcripts the tapes were indexed by
tape_level = {}
for md in (ROOT / "library/sources/gateway-experience").rglob("*.md"):
    txt = md.read_text()
    if not txt.startswith("---"):
        continue
    fm = txt.split("---")[1]
    title = lvl = None
    for line in fm.strip().split("\n"):
        if line.startswith("title:"): title = line.split(":", 1)[1].strip()
        if line.startswith("levels:"): lvl = line.split(":", 1)[1].strip()
    if title and lvl:
        tape_level[re.sub(r"[^a-z0-9]+", "", title.lower())] = lvl.split(",")[0].strip()

def slug(x): return re.sub(r"[^a-z0-9]+", "-", x.lower()).strip("-")

written = 0
for j in sorted(BEATS.glob("*.json")):
    try:
        d = json.loads(j.read_text())
    except json.JSONDecodeError:
        continue
    # Faint pairs survive the balance test but are not tones anybody hears;
    # a real layer measured 1.00, 0.67, 0.38 while noise sat near 0.15.
    layers = [l for l in (d.get("layers") or [])
              if l["share"] >= 4.0 and l["amp"] >= 0.25]
    if not layers:
        continue
    stem = pathlib.Path(d["file"]).stem
    level = tape_level.get(re.sub(r"[^a-z0-9]+", "", stem.lower()))

    # One hold per contiguous span of a layer. Layers overlap in time -- that
    # is the point: Hemi-Sync sounds several pairs at once.
    holds = []
    for l in layers:
        for span in l["spans"]:
            if span["to"] - span["from"] < 30:      # too brief to be a hold
                continue
            steady = max(0.0, 1.0 - l["spread"] / 0.5)
            weight = min(1.0, l["windows"] / 20)
            holds.append({
                "start": span["from"], "end": span["to"],
                "carrier": round(l["carrier"], 2), "beat": round(l["beat"], 3),
                "gain": round(l["amp"], 3),
                "confidence": round(0.5 * steady + 0.5 * weight, 2),
            })
    if not holds:
        continue
    holds.sort(key=lambda h: (h["start"], -h["gain"]))

    profile = {
        "id": slug(stem),
        "provenance": "measured",
        "tape": d["file"].split("The Gateway Experience/")[-1],
        "duration": round(d["minutes"] * 60, 1),
        "holds": holds,
        "notes": (f"FFT of the tape, 20 s windows (0.05 Hz), {d['windows']} windows. "
                  f"{len(layers)} simultaneous binaural layers above 4% presence. "
                  "Pairs required near-equal level in both ears; layers overlap "
                  "in time because Hemi-Sync sounds several at once."),
    }
    if level:
        profile["level"] = level
    (OUT / f"{slug(stem)}.json").write_text(json.dumps(profile, indent=2) + "\n")
    written += 1

print(f"{written} measured profiles written to {OUT.relative_to(ROOT)}")

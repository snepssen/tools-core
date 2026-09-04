#!/usr/bin/env python3
"""Does the speech accelerate across a line?

    mw transcribe --model parakeet-pro:nvidia_parakeet-v3 --format json x.wav > x.json
    analyse-pace.py x.json

Reads MacWhisper's word timestamps and reports words/second over the first,
middle and last third of each continuous run. A render whose last third is much
faster than its first is the acceleration artefact. Lives outside the project
tree, like every other Python tool here.
"""
import json, sys

def runs_from(path):
    d = json.load(open(path))
    words = []
    if isinstance(d, list):                       # flat "text"/"timestamp" form
        for w in d:
            a, b = w["timestamp"].split("-")
            f = lambda t: int(t.split(":")[0]) * 60 + float(t.split(":")[1])
            words.append((w["text"].strip(), f(a), f(b)))
    else:                                          # mw json: milliseconds
        for seg in d.get("segments", []):
            for w in seg.get("words", []):
                words.append((w.get("word", w.get("text", "")).strip(),
                              w["start"] / 1000.0, w["end"] / 1000.0))
    runs, cur = [], []
    for w in words:
        if cur and w[1] - cur[-1][2] > 1.5:
            runs.append(cur); cur = []
        cur.append(w)
    if cur: runs.append(cur)
    return runs

for path in sys.argv[1:]:
    print(f"\n=== {path.split('/')[-1]} ===")
    for i, r in enumerate(runs_from(path)):
        n = len(r)
        if n < 6:
            continue
        rates = []
        for sl in (slice(0, n//3), slice(n//3, 2*n//3), slice(2*n//3, n)):
            part = r[sl]
            span = part[-1][2] - part[0][1]
            rates.append(len(part) / span if span > 0 else 0)
        drift = rates[2] / rates[0] if rates[0] else 0
        flag = "  <== ACCELERATES" if drift > 1.4 else ""
        print(f"  run {i}: {n:2d} words, {r[0][1]:5.1f}-{r[-1][2]:5.1f}s | "
              f"{rates[0]:4.2f} -> {rates[1]:4.2f} -> {rates[2]:4.2f} w/s | "
              f"x{drift:.2f}{flag}")

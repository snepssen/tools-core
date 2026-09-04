#!/usr/bin/env python
"""Measure the binaural beat in a Hemi-Sync tape, and whether it moves.

A binaural beat is not in the audio -- it is the *difference* between a steady
tone in one ear and a slightly different steady tone in the other. So the
method is: find the narrow, persistent tones in each channel separately, pair
them, and take the difference. Voice and surf are broadband and unsteady, so
they wash out of a median spectrum while a sustained sine does not.

    analyse-beat.py <file.flac> [--window 20] [--hop 10]
"""
import sys, pathlib
import numpy as np
import soundfile as sf
from scipy.signal import find_peaks

path = sys.argv[1]
AS_JSON = "--json" in sys.argv
win_s = float(sys.argv[sys.argv.index("--window") + 1]) if "--window" in sys.argv else 20.0
hop_s = float(sys.argv[sys.argv.index("--hop") + 1]) if "--hop" in sys.argv else 10.0
FMIN, FMAX = 20.0, 400.0          # Hemi-Sync carriers live low

data, sr = sf.read(path, always_2d=True)
if data.shape[1] < 2:
    sys.exit("mono file: a binaural beat needs two channels")
L, R = data[:, 0], data[:, 1]
n = int(win_s * sr)
hop = int(hop_s * sr)
win = np.hanning(n)
freqs = np.fft.rfftfreq(n, 1 / sr)
band = (freqs >= FMIN) & (freqs <= FMAX)
fb = freqs[band]
res = sr / n
if not AS_JSON:
    print(f"{pathlib.Path(path).name}")
    print(f"{len(L)/sr/60:.1f} min · window {win_s:g}s · resolution {res:.3f} Hz\n")

def peaks(spec, floor=0.10):
    """Narrow peaks in the carrier band, each refined by parabolic
    interpolation so the answer is not quantised to the FFT bin."""
    s = spec[band]
    if s.max() <= 0:
        return []
    med = np.median(s) + 1e-12
    idx, _ = find_peaks(s, height=s.max() * floor, distance=max(1, int(1.0 / res)))
    out = []
    for i in idx:
        if 0 < i < len(s) - 1:
            a, b, c = s[i - 1], s[i], s[i + 1]
            denom = a - 2 * b + c
            delta = 0.5 * (a - c) / denom if denom != 0 else 0.0
        else:
            delta = 0.0
        out.append((fb[i] + delta * res, s[i], s[i] / med))
    return out


def binaural_pairs(pl, pr, lo=0.2, hi=15.0, floor=0.10, balance=0.6):
    """**All** genuine tone pairs in a window, not just the loudest.

    Hemi-Sync stacks several binaural pairs at once: a window of Introduction
    to Focus 12 carries 99.25/100.75 (1.5 Hz), 50.00/50.50 (0.5 Hz) and
    198/202 (4 Hz) together. Reporting only the strongest reduces the stack to
    whichever layer won, and made every level look like 4 Hz.

    Two rules keep noise out, both learned by getting it wrong:

    - **Balance.** A real pair is one tone offset between the ears, so its two
      peaks are near-equal in level. 120.10(0.25) against 100.75(1.00) is two
      unrelated peaks, not a pair.
    - **Range.** A binaural beat is low. Allowing up to 25 Hz let distant noise
      peaks pair off and produced thousands of phantom layers at ~24.8 Hz.

    Each tone is consumed once, strongest first, so one peak cannot feed
    several pairs.
    """
    if not pl or not pr:
        return []
    ampL = max(a for _, a, _ in pl) or 1.0
    ampR = max(a for _, a, _ in pr) or 1.0
    cands = []
    for iL, (fL, aL, _) in enumerate(pl):
        for iR, (fR, aR, _) in enumerate(pr):
            d = abs(fL - fR)
            if not (lo <= d <= hi):
                continue
            rl, rr = aL / ampL, aR / ampR
            if min(rl, rr) < floor:
                continue
            if min(rl, rr) / max(rl, rr) < balance:
                continue
            cands.append((min(rl, rr), d, fL, fR, iL, iR))
    cands.sort(reverse=True)
    usedL, usedR, out = set(), set(), []
    for rel, d, fL, fR, iL, iR in cands:
        if iL in usedL or iR in usedR:
            continue
        usedL.add(iL); usedR.add(iR)
        out.append({"beat": d, "carrier": min(fL, fR), "amp": rel})
    return out


rows = []          # (time, [pairs])
for start in range(0, len(L) - n, hop):
    segL = L[start:start + n] * win
    segR = R[start:start + n] * win
    pairs = binaural_pairs(peaks(np.abs(np.fft.rfft(segL))),
                           peaks(np.abs(np.fft.rfft(segR))))
    rows.append((start / sr, pairs))

# Group pairs into layers: a beat that keeps recurring at the same carrier is
# one continuous tone, whatever else is playing over it.
layers = {}
for t, pairs in rows:
    for p in pairs:
        key = (round(p["beat"] * 4) / 4, round(p["carrier"] / 5) * 5)
        layers.setdefault(key, []).append((t, p))
layers = {k: v for k, v in layers.items() if len(v) >= 3}

if not AS_JSON:
    print(f"{'beat':>8} {'carrier':>9} {'windows':>8} {'share':>7} {'amp':>6}   spans")
total_windows = len(rows) or 1
ordered = sorted(layers.items(), key=lambda kv: -len(kv[1]))
out_layers = []
for (beat, carrier), hits in ordered:
    times = [t for t, _ in hits]
    amps = [p["amp"] for _, p in hits]
    beats = [p["beat"] for _, p in hits]
    # contiguous spans, so a layer that comes and goes reads as such
    spans, run = [], [times[0]]
    for t in times[1:]:
        if t - run[-1] <= hop_s * 1.5:
            run.append(t)
        else:
            spans.append((run[0], run[-1] + win_s)); run = [t]
    spans.append((run[0], run[-1] + win_s))
    out_layers.append({
        "beat": round(float(np.median(beats)), 3),
        "carrier": round(float(np.median([p["carrier"] for _, p in hits])), 2),
        "windows": len(hits),
        "share": round(100 * len(hits) / total_windows, 1),
        "amp": round(float(np.median(amps)), 3),
        "spread": round(float(max(beats) - min(beats)), 3),
        "spans": [{"from": round(a, 1), "to": round(b, 1)} for a, b in spans if b - a >= win_s],
    })

if AS_JSON:
    import json
    print(json.dumps({"file": str(path), "minutes": round(len(L) / sr / 60, 1),
                      "windows": len(rows), "layers": out_layers,
                      "dominant": out_layers[0]["beat"] if out_layers else None}))
else:
    for l in out_layers[:10]:
        spans = " ".join(f"{int(s['from'])//60}:{int(s['from'])%60:02d}-"
                         f"{int(s['to'])//60}:{int(s['to'])%60:02d}" for s in l["spans"][:4])
        print(f"{l['beat']:8.2f} {l['carrier']:9.2f} {l['windows']:8d} "
              f"{l['share']:6.1f}% {l['amp']:6.2f}   {spans}")
    print(f"\n{len(out_layers)} layers over {len(rows)} windows")

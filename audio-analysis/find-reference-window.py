#!/usr/bin/env python3
"""Pick a reference excerpt that begins and ends in silence.

A reference cut mid-word teaches the clone to start mid-word. This scans for
windows of roughly the requested length whose edges both fall inside a real
pause, and ranks them by how much actual speech they contain -- enough voice to
clone from, enough silence to learn that speech pauses. Outside the project tree.
"""
import sys, wave, struct, argparse
ap = argparse.ArgumentParser()
ap.add_argument("src"); ap.add_argument("--seconds", type=float, default=50)
ap.add_argument("--tolerance", type=float, default=12)
a = ap.parse_args()

w = wave.open(a.src); n, sr, ch, sw = w.getnframes(), w.getframerate(), w.getnchannels(), w.getsampwidth()
raw = w.readframes(n)
s = struct.unpack(f"<{n*ch}h", raw)[::ch]
peak = max(abs(x) for x in s)
thr = peak * 0.03
win = int(sr * 0.05)
loud = [max(abs(x) for x in s[i:i+win]) > thr for i in range(0, len(s) - win, win)]

# silent gaps of at least 0.4s
gaps, run = [], 0
for i, l in enumerate(loud):
    if not l: run += 1
    else:
        if run * 0.05 >= 0.4: gaps.append(((i - run) * 0.05, i * 0.05))
        run = 0
print(f"{len(gaps)} pauses of 0.4s or more in {len(s)/sr:.0f}s")

best = None
for gs, ge in gaps:
    start = (gs + ge) / 2
    for gs2, ge2 in gaps:
        end = (gs2 + ge2) / 2
        if abs((end - start) - a.seconds) > a.tolerance: continue
        i0, i1 = int(start*sr/win), int(end*sr/win)
        frac = sum(loud[i0:i1]) / max(1, i1 - i0)
        # want plenty of voice but not wall-to-wall: the pauses are the point
        score = frac if 0.45 <= frac <= 0.70 else 0
        if score and (best is None or score > best[0]):
            best = (score, start, end, frac)
if best:
    _, st, en, frac = best
    print(f"best window: {st:.2f}s to {en:.2f}s  ({en-st:.1f}s, {frac*100:.0f}% speech)")
    print(f"  --start {st:.2f} --seconds {en-st:.2f}")
else:
    print("no window matched; widen --tolerance")

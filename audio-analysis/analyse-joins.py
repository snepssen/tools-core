#!/usr/bin/env python3
"""Find abrupt starts, abrupt ends and step discontinuities in rendered takes.

A part boundary that is butt-joined shows up as a large sample-to-sample jump.
A word that starts abruptly shows up as significant amplitude in the very first
milliseconds. Outside the project tree.
"""
import sys, wave, struct, glob

def read(path):
    w = wave.open(path)
    n, sr = w.getnframes(), w.getframerate()
    raw = w.readframes(n)
    return struct.unpack(f"<{n}h", raw), sr

rows = []
for path in sorted(glob.glob(sys.argv[1])):
    s, sr = read(path)
    if not s: continue
    peak = max(abs(x) for x in s) or 1
    ms = int(sr * 0.005)                       # 5 ms
    head = max(abs(x) for x in s[:ms]) / peak
    tail = max(abs(x) for x in s[-ms:]) / peak
    # biggest single-sample jump, normalised
    jump, at = 0, 0
    for i in range(1, len(s)):
        d = abs(s[i] - s[i-1])
        if d > jump: jump, at = d, i
    rows.append((path.split("/")[-1], len(s)/sr, head, tail, jump/peak, at/sr))

rows.sort(key=lambda r: -max(r[2], r[3]))
print(f"{'take':44s} {'secs':>6s} {'head':>6s} {'tail':>6s} {'jump':>6s} {'at':>7s}")
for r in rows[:14]:
    flag = "  <== ABRUPT" if max(r[2], r[3]) > 0.10 else ""
    print(f"{r[0][:44]:44s} {r[1]:6.1f} {r[2]:6.3f} {r[3]:6.3f} {r[4]:6.3f} {r[5]:7.2f}{flag}")
print(f"\n{sum(1 for r in rows if max(r[2],r[3])>0.10)} of {len(rows)} start or end abruptly (>10% of peak in first/last 5ms)")

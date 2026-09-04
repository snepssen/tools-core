#!/usr/bin/env python3
"""How abruptly does speech resume after a written silence?

The assembler lays down digital zeros for a `pause`, then appends the next
piece. If that piece begins mid-phonation, the waveform steps from exactly 0 to
full level in one sample -- a click, and a word that starts abruptly. Measures
the rise time at every silence-to-speech transition. Outside the project tree.
"""
import sys, wave, struct, glob

for path in sorted(glob.glob(sys.argv[1]))[:int(sys.argv[2]) if len(sys.argv)>2 else 6]:
    w = wave.open(path); n, sr = w.getnframes(), w.getframerate()
    s = struct.unpack(f"<{n}h", w.readframes(n))
    peak = max(abs(x) for x in s) or 1
    thr = peak * 0.02
    onsets = []
    i, silent_run = 0, 0
    while i < n:
        if abs(s[i]) < thr:
            silent_run += 1
        else:
            if silent_run > sr * 0.4:            # a real pause, not a gap in speech
                # how many samples to reach 25% of peak from here
                j = i
                while j < min(n, i + int(sr*0.05)) and abs(s[j]) < peak*0.25:
                    j += 1
                onsets.append((i/sr, (j-i)*1000.0/sr, abs(s[i])/peak))
            silent_run = 0
        i += 1
    if not onsets: continue
    instant = [o for o in onsets if o[1] < 2.0]
    print(f"{path.split('/')[-1][:40]:40s} {len(onsets):3d} resumes, "
          f"{len(instant):3d} reach 25% peak in under 2ms")
    for o in onsets[:3]:
        print(f"      at {o[0]:7.2f}s  rise {o[1]:5.1f}ms  first sample {o[2]:.3f} of peak")

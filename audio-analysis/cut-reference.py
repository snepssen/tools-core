#!/usr/bin/env python3
"""Cut a reference excerpt, keeping its natural pauses.

    cut-reference.py in.wav out.wav --start 60 --seconds 60

The existing M1 reference was *built* -- speech runs concatenated with the
silences removed -- which makes it 81% speech. This keeps the pauses, because
a model asked to clone speech that never breathes may not learn to breathe.
Outside the project tree, like every other Python tool here.
"""
import argparse, wave
ap = argparse.ArgumentParser()
ap.add_argument("src"); ap.add_argument("dst")
ap.add_argument("--start", type=float, default=0)
ap.add_argument("--seconds", type=float, default=60)
a = ap.parse_args()

w = wave.open(a.src)
sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
w.setpos(int(a.start * sr))
frames = w.readframes(int(a.seconds * sr))
o = wave.open(a.dst, "wb")
o.setnchannels(ch); o.setsampwidth(sw); o.setframerate(sr)
o.writeframes(frames); o.close()
print(f"{a.seconds:.0f}s from {a.start:.0f}s -> {a.dst}")

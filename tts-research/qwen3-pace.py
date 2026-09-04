#!/usr/bin/env python
"""Measure Qwen3's actual speaking pace against real library lines.

    python qwen3-pace.py --gateway-root PATH [--lines 12]

`RenderPlan.wordsPerSecond` drives every duration estimate and every bed cue
timing in the app. Its 2.3 was measured against chatterbox on a single audition
line. This measures the engine that will actually speak, on lines drawn from the
library itself -- a `say` step's real wording, not a benchmark sentence -- and
reports the spread as well as the mean, because one line is not a sample.
"""
import argparse, json, pathlib, random, re, sys, time
import numpy as np, mlx.core as mx

ap = argparse.ArgumentParser()
ap.add_argument("--gateway-root", required=True,
                help="Gateway Forge checkout containing voices/ and library/")
ap.add_argument("--lines", type=int, default=12)
ap.add_argument("--voice", default="M1")
ap.add_argument("--seed", type=int, default=1729)
ap.add_argument("--min-words", type=int, default=6)
args = ap.parse_args()

root = pathlib.Path(args.gateway_root).resolve()
prof = json.loads((root / "voices" / args.voice / "profile.json").read_text())
ref_text = prof["referenceText"].strip()
ref_wav = str(root / "voices" / args.voice / prof["referenceWav"])
if not ref_text:
    sys.exit("voice has no referenceText")

# Real `say` bodies, variant groups collapsed to their first take.
lines = []
for f in sorted((root / "library" / "segments").glob("*.gws")):
    for raw in f.read_text().splitlines():
        m = re.match(r"\s*say\s+(.*)", raw)
        if not m:
            continue
        t = re.sub(r"\{([^{}|]*)(\|[^{}]*)?\}", r"\1", m.group(1)).strip()
        if len(t.split()) >= args.min_words and t not in [l[1] for l in lines]:
            lines.append((f.stem, t))
random.Random(args.seed).shuffle(lines)
lines = lines[: args.lines]
print(f"{len(lines)} lines from the library\n")

from mlx_audio.tts.utils import load
model = load("mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16")

rows = []
for i, (seg, text) in enumerate(lines, 1):
    mx.random.seed(args.seed + i)
    t0 = time.time()
    chunks = [np.array(r.audio).reshape(-1) for r in model.generate(
        text=text, ref_audio=ref_wav, ref_text=ref_text,
        temperature=0.9, top_k=50, top_p=1.0, max_tokens=1200, verbose=False)]
    gen = time.time() - t0
    wave = np.concatenate(chunks) if chunks else np.zeros(0, np.float32)
    secs = len(wave) / 24000.0
    words = len(text.split())
    if secs <= 0:
        print(f"  {i:2d}. {seg}: NO AUDIO"); continue
    wps = words / secs
    rows.append({"segment": seg, "words": words, "seconds": round(secs, 2),
                 "words_per_second": round(wps, 3), "generate_seconds": round(gen, 1)})
    print(f"  {i:2d}. {seg:28s} {words:3d}w  {secs:6.2f}s  {wps:5.2f} w/s  "
          f"(gen {gen:5.1f}s)  {text[:44]}…")

if not rows:
    sys.exit("nothing rendered")
w = np.array([r["words"] for r in rows], float)
s = np.array([r["seconds"] for r in rows], float)
per = np.array([r["words_per_second"] for r in rows], float)
# Pooled, not the mean of per-line rates: a long line should carry more weight
# than a four-word one, and the estimator is applied to whole bodies.
pooled = w.sum() / s.sum()
out = {"voice": args.voice, "lines": len(rows), "total_words": int(w.sum()),
       "total_seconds": round(float(s.sum()), 2),
       "pooled_words_per_second": round(float(pooled), 3),
       "per_line_mean": round(float(per.mean()), 3),
       "per_line_min": round(float(per.min()), 3),
       "per_line_max": round(float(per.max()), 3),
       "per_line_stdev": round(float(per.std(ddof=1)), 3) if len(per) > 1 else None,
       "measurements": rows}
p = root / "library" / "reference" / "qwen3-pace.json"
p.write_text(json.dumps(out, indent=2) + "\n")
print(f"\npooled {pooled:.3f} words/s over {int(w.sum())} words / {s.sum():.1f}s")
print(f"per-line {per.min():.2f}–{per.max():.2f}, mean {per.mean():.2f}"
      + (f", sd {per.std(ddof=1):.2f}" if len(per) > 1 else ""))
print(f"old constant 2.3 => estimates run {pooled/2.3:.2f}x long")
print(f"-> {p}")

#!/usr/bin/env python3
"""Render a line the way the *app* will, not the way the piper CLI does.

    audition.py --model M.onnx --config M.onnx.json --out out.wav "text"
    audition.py ... --plain           # the CLI's rendering, for A/B

**The check-in has been auditioning something the app does not ship.**
`python3 -m piper` is stock piper. `PiperSpeechEngine` is not: it applies three
transforms that were each added because a defect was heard and then measured,
and none of them exist in the CLI path.

1. **Two trailing PAD phonemes** before EOS (`trailingPadPhonemes = 2`). This
   is the fix for the severed breath -- the model needs somewhere to put the
   decay, and stock piper gives it one PAD.
2. **The sentence-final `.` phoneme is dropped** (`dropFinalFullStop`). That
   phoneme is exactly where this voice learned "the recording stops here", so
   it reproduces whatever sat at the training cut -- a phantom `t`, `sh`, `hm`
   after the words end. Removing the trigger removes the artifact: measured
   over 12 final sentences x 8 draws, artifact rate fell from 4.2% to 1.0%.
3. **One inference call per sentence**, joined under an 80 ms edge policy,
   rather than one call for the whole line.

So the owner has been judging "should this keep training?" against audio
strictly worse than what the app produces -- which is exactly what they
noticed on the previous voice, where the shipped result surprised them after
unpromising auditions. This renders what ships.

The only app step deliberately skipped is the 22.05k -> 24k resample, which is
linear-phase and changes nothing anyone can hear.
"""
import argparse
import sys
import wave

import no_telemetry  # noqa: F401  -- ORT's uploader thread segfaults at exit

import numpy as np  # noqa: E402
from piper import PiperVoice  # noqa: E402

# Mirrors RenderPlan.speechEdgeThreshold / speechEdgeQuietSeconds.
EDGE_THRESHOLD = 0.005
EDGE_QUIET_SECONDS = 0.080
TRAILING_PAD_PHONEMES = 2


def ids_for(phonemes, id_map, extra_pad):
    """PiperSpeechEngine.phonemesToIds, in Python.

    Stock piper interleaves one PAD after every phoneme and stops. The app
    appends `extra_pad` more before EOS.
    """
    ids = list(id_map.get("^", []))
    ids += id_map.get("_", [])
    for p in phonemes:
        if p not in id_map:
            continue
        ids += id_map[p]
        ids += id_map.get("_", [])
    for _ in range(extra_pad):
        ids += id_map.get("_", [])
    ids += id_map.get("$", [])
    return ids


def prepared(part, rate):
    """RenderPlan.preparedSpeechPart: guarantee 80 ms of quiet at each edge.

    Pads out to the requirement rather than trimming to it -- a part that
    already ends in phonation is given room, never cut back into.
    """
    if len(part) == 0:
        return part
    need = int(EDGE_QUIET_SECONDS * rate)
    lead = 0
    while lead < min(len(part), need) and abs(part[lead]) < EDGE_THRESHOLD:
        lead += 1
    tail = 0
    while tail < min(len(part), need) and abs(part[len(part) - 1 - tail]) < EDGE_THRESHOLD:
        tail += 1
    out = part
    if lead < need:
        out = np.concatenate([np.zeros(need - lead, dtype=out.dtype), out])
    if tail < need:
        out = np.concatenate([out, np.zeros(need - tail, dtype=out.dtype)])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("text")
    ap.add_argument("--model", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--plain", action="store_true",
                    help="render the way the piper CLI does, for A/B")
    args = ap.parse_args()

    voice = PiperVoice.load(args.model, config_path=args.config)
    rate = voice.config.sample_rate
    id_map = voice.config.phoneme_id_map

    sentences = voice.phonemize(args.text)
    parts = []
    for phonemes in sentences:
        ph = list(phonemes)
        if not args.plain and ph and ph[-1] == ".":
            ph = ph[:-1]
        extra = 0 if args.plain else TRAILING_PAD_PHONEMES
        audio = voice.phoneme_ids_to_audio(ids_for(ph, id_map, extra))
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        if audio.size:
            parts.append(audio if args.plain else prepared(audio, rate))
    if not parts:
        sys.exit("nothing rendered")
    joined = np.concatenate(parts)

    peak = float(np.max(np.abs(joined))) or 1.0
    pcm = np.clip(joined / peak * 0.98, -1.0, 1.0)
    with wave.open(args.out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes((pcm * 32767).astype("<i2").tobytes())
    print(f"{args.out}  {len(joined)/rate:.2f}s  "
          f"{len(sentences)} sentence(s)  "
          f"{'plain (CLI)' if args.plain else 'as the app renders'}")


if __name__ == "__main__":
    main()

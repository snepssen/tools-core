#!/usr/bin/env python3
"""Synthesize straight through PyTorch, bypassing ONNX entirely.

Built to answer one question: a glitch reported present in every ONNX-exported
sample is either (a) something the trained weights actually do, or (b) an
artifact of the export -- the legacy TorchScript tracer freezes several
data-dependent branches (attentions.py's relative-position padding, the
duration-predictor's spline discriminant check) as constants captured from one
50-phoneme dummy trace, and a different real utterance running through that
frozen graph is exactly the kind of thing that could look like a glitch "in
every sample" while never having reached the trained model at all. This
mirrors piper.voice.PiperVoice's own real preprocessing (phonemize, then
phonemes_to_ids against the voice's own config) so the comparison is apples to
apples -- not the ONNX export script's random dummy tokens.

If the glitch is here too, it's the model. If it's gone, it was the export.
"""
import argparse
import json
import sys
import wave

import numpy as np
import torch

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("checkpoint")
parser.add_argument("text")
parser.add_argument("out_wav")
parser.add_argument("--config", required=True, help="Piper voice config JSON")
parser.add_argument("--piper-source", help="optional checkout containing Piper's src directory")
args = parser.parse_args()
if args.piper_source:
    sys.path.insert(0, args.piper_source)
from piper.phoneme_ids import phonemes_to_ids  # noqa: E402
from piper.phonemize_espeak import EspeakPhonemizer  # noqa: E402
from piper.train.vits.lightning import VitsModel  # noqa: E402

CHECKPOINT = args.checkpoint
TEXT = args.text
OUT_WAV = args.out_wav
CONFIG_PATH = args.config

config = json.load(open(CONFIG_PATH))
phoneme_id_map = config["phoneme_id_map"]
noise_scale = config.get("inference", {}).get("noise_scale", 0.667)
length_scale = config.get("inference", {}).get("length_scale", 1.0)
noise_w_scale = config.get("inference", {}).get("noise_w", 0.8)

phonemizer = EspeakPhonemizer()
sentences = phonemizer.phonemize(config.get("espeak", {}).get("voice", "en-us"), TEXT)
print("phonemized:", sentences)

# One utterance, sentences concatenated -- matches how the ONNX samples were
# rendered (piper.__main__ synthesizes the whole input as sentence chunks and
# concatenates; single short lines here are one sentence each in practice).
all_phonemes = [p for sent in sentences for p in sent]
ids = phonemes_to_ids(all_phonemes, phoneme_id_map)
print("phoneme id count:", len(ids))

model = VitsModel.load_from_checkpoint(CHECKPOINT, map_location="cpu")
model_g = model.model_g
model_g.eval()
with torch.no_grad():
    model_g.dec.remove_weight_norm()

sequences = torch.LongTensor(ids).unsqueeze(0)
sequence_lengths = torch.LongTensor([sequences.size(1)])

with torch.no_grad():
    audio = model_g.infer(
        sequences,
        sequence_lengths,
        noise_scale=noise_scale,
        length_scale=length_scale,
        noise_scale_w=noise_w_scale,
        sid=None,
    )[0].squeeze().numpy()

audio = np.clip(audio, -1.0, 1.0)
pcm = (audio * 32767).astype(np.int16)

with wave.open(OUT_WAV, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(22050)
    w.writeframes(pcm.tobytes())

print("wrote", OUT_WAV)

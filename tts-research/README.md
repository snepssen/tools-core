# Qwen3-TTS research tools (retired)

> **Retired.** Gateway Forge, which these were written for, has moved from
> Qwen3-TTS to Piper, and no snepssen project uses Qwen3 any more. They are kept
> as a reference for anyone porting Qwen3-TTS to another runtime: they still
> run (last checked 2026-11-22 against the pinned
> [`requirements/tts-research.txt`](../requirements/tts-research.txt)), but
> nothing here will be updated for newer mlx-audio releases.

Ground-truth generators for validating a native Qwen3-TTS implementation
against the Python MLX reference:

- `qwen3-groundtruth.py --gateway-root PATH` records intermediate tensors and
  sampled tokens for stage-by-stage numerical comparison.
- `qwen3-tokenizer-truth.py --gateway-root PATH` records tokenizer cases and
  ICL token slices.
- `qwen3-pace.py --gateway-root PATH` measures real speaking pace across
  authored `say` lines.

These tools download or load the model named in each script and write generated
reference data into the supplied Gateway Forge checkout. They require Apple
silicon macOS, MLX, mlx-audio, NumPy, and (for tokenizer truth) Transformers,
pinned in [`requirements/tts-research.txt`](../requirements/tts-research.txt);
`qwen3-groundtruth.py` reads mlx-audio's Qwen3-TTS internals, so a newer
mlx-audio may need it adjusted.

Gateway Forge itself has since moved from Qwen3-TTS to Piper, and its
checkout no longer has the `M1` voice these default to. Any folder works as
`--gateway-root` if it holds `voices/<voice>/profile.json` (with
`referenceText` and `referenceWav`, the clip beside it) and, for the tokenizer
and pace tools, `library/segments/*.gws`; pass `--voice` for another name.
Model weights and generated tensors are not part of this repository; review the
model repository's own license and terms before redistribution.

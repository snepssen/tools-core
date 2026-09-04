# Qwen3-TTS research tools

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
silicon macOS, MLX, mlx-audio, NumPy, and (for tokenizer truth) Transformers.
Model weights and generated tensors are not part of this repository; review the
model repository's own license and terms before redistribution.

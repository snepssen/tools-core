# Piper workflows

Focused wrappers and diagnostics for Piper/VITS training and ONNX export.
They preserve fixes found while investigating concrete upstream/version
interactions; read each module docstring before using it.

- `train.py` and `train_resume.py` wrap Piper training around checkpoint and
  resume fixes.
- `check-in.sh RUN_DIR CONFIG_JSON OUTPUT_DIR [VOICE_NAME]` exports the
  highest-epoch checkpoint and renders the same diagnostic lines for A/B
  listening across training runs.
- `export.py` forces the legacy exporter and replaces a traced dynamic-shape
  helper with a scripted implementation.
- `render.py` and `audition.py` disable ONNX Runtime telemetry before Piper is
  imported.
- `direct_infer.py CHECKPOINT TEXT OUT.wav --config VOICE.json
  [--piper-source PATH]` bypasses ONNX for an A/B diagnosis. `--piper-source`
  should point to a Piper `src` directory when Piper is not installed.

Use a Piper training environment compatible with the checkpoint being tested.
The `piper-tts` package alone may not expose training modules. Upstream Piper
source is not vendored here. This directory is distributed under GPL-3.0-only
because `export.py` adapts Piper's sequence-mask/path implementation; see
`COPYING` and the source attribution in that file. Only load trusted PyTorch
checkpoints.

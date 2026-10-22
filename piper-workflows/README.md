# Piper workflows

Focused wrappers and diagnostics for Piper/VITS training and ONNX export.
They preserve fixes found while investigating concrete upstream/version
interactions; read each module docstring before using it.

- `train.py` and `train_resume.py` wrap Piper training around checkpoint and
  resume fixes. The first run and the resume are written out below.
- `check-in.sh RUN_DIR CONFIG_JSON OUTPUT_DIR [VOICE_NAME]` exports the
  highest-epoch checkpoint and renders the same diagnostic lines for A/B
  listening across training runs. A crash from ONNX Runtime on the way out
  still leaves a successful check-in when the exported model loads and each
  wav has at least a second of audio.
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

## First run and resume

`train.py fit` warm-starts a new run from `en_US-lessac-medium.ckpt`.
`train_resume.py fit` continues that run. `train.py` refuses to start when
the output or run directory already holds `*.ckpt` files, because a warm
start would silently overwrite trained weights, and the message points at
`train_resume.py`. `--force` starts the warm start anyway. Keep the base
checkpoint outside `<run-dir>`.

`--data.batch_size 4` stayed in memory on a 16 GB Mac. Batch size 8 pushed
that machine into swap (0.01 vs 0.17 it/s).

```sh
python3 piper-workflows/train.py fit \
  --data.voice_name <name> \
  --data.csv_path <metadata.csv> \
  --data.audio_dir <audio-dir> \
  --data.espeak_voice en-us \
  --data.batch_size 4 \
  --data.cache_dir <cache-dir> \
  --data.config_path <voice.json> \
  --model.sample_rate 22050 \
  --model.warmstart_ckpt <path>/en_US-lessac-medium.ckpt \
  --trainer.default_root_dir <run-dir>
```

Resume with the newest `last.ckpt` from that run:

```sh
python3 piper-workflows/train_resume.py fit \
  --data.voice_name <name> \
  --data.csv_path <metadata.csv> \
  --data.audio_dir <audio-dir> \
  --data.espeak_voice en-us \
  --data.batch_size 4 \
  --data.cache_dir <cache-dir> \
  --data.config_path <voice.json> \
  --model.sample_rate 22050 \
  --trainer.default_root_dir <run-dir> \
  --ckpt_path <newest last.ckpt>
```

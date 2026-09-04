# tools-core

Small, local-first utilities for media production, audio inspection, voice
training research, and Gateway Forge authoring.

This repository contains source code only. It deliberately excludes recordings,
lyrics, transcripts, model weights, checkpoints, generated media, caches, and
third-party source trees.

## Tool index

| Area | What it does | Runtime | Platform | Writes files |
| --- | --- | --- | --- | --- |
| [`lyric-video-maker/`](lyric-video-maker/) | Turns audio, cover art, and timed lyrics into a karaoke-style MP4 | Python 3, ffmpeg with libass; MacWhisper optional | macOS UI; render pipeline is portable | Yes |
| [`audio-analysis/`](audio-analysis/) | Measures stereo beat layers, joins, onsets, pace, and prepares voice references | Python 3; NumPy/SciPy/soundfile for beat analysis; ffmpeg for corpus cutting | macOS/Linux | Some tools |
| [`gateway-authoring/`](gateway-authoring/) | Indexes measured signals, verifies a speech corpus, and seeds provisional Gateway Forge briefings | Python 3 | macOS/Linux | Yes |
| [`piper-workflows/`](piper-workflows/) | Piper training, export, render, audition, and direct-inference wrappers for known upstream failure modes | Python 3 plus a compatible Piper training environment | Primarily macOS/Linux | Yes |
| [`tts-research/`](tts-research/) | Produces Qwen3-TTS tensor, tokenizer, and speaking-pace ground truth | Python 3, MLX, mlx-audio, Transformers | Apple silicon macOS | Yes |

Each directory has its own README with commands, dependencies, inputs, outputs,
and caveats. Run commands from the repository root unless a README says
otherwise.

## Release check

```sh
python3 scripts/check_release.py
```

The check compiles every Python file, validates shell syntax, runs the standard
library tests, and rejects private absolute paths, likely secrets, generated
media, model artifacts, caches, and unexpectedly large files.

## Dependency setup

The small utilities use Python's standard library. Optional dependency groups
are documented in [`requirements/`](requirements/). Large ML stacks are not
installed automatically because compatible versions depend on the model and
hardware being investigated.

## Privacy and scope

- The lyric-video UI listens only on `127.0.0.1` and authenticates its browser
  API with a new random token each run.
- File pickers and render jobs operate on paths you explicitly select.
- No telemetry is added by these tools. The Piper wrappers explicitly disable
  ONNX Runtime telemetry before loading Piper.
- Copyrighted source audio and lyric sheets are inputs, not redistributable
  fixtures. Keep them outside this repository.

## License

The repository is MIT licensed except for `piper-workflows/`, which is
GPL-3.0-only because one export workaround adapts a small part of Piper's GPL
implementation. Its license and attribution are included in that directory.
Downloaded model repositories retain their own licenses and are not vendored
here. See [`LICENSE`](LICENSE) for the exact boundary.

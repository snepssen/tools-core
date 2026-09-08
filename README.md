# tools-core

Small, local-first utilities for media production, audio inspection, voice
training research, and Gateway Forge authoring.

**[Open the project page →](https://snepssen.github.io/tools-core/)** — project
index, usage examples, contact details, and small interactive samples.

This repository contains source code only. It deliberately excludes recordings,
lyrics, transcripts, model weights, checkpoints, generated media, caches, and
third-party source trees.

## Tool index

| Area | What it does | Runtime | Platform | Writes files |
| --- | --- | --- | --- | --- |
| [`audio-analysis/`](audio-analysis/) | Measures stereo beat layers, joins, onsets, pace, and prepares voice references | Python 3; NumPy/SciPy/soundfile for beat analysis; ffmpeg for corpus cutting | macOS/Linux | Some tools |
| [`gateway-authoring/`](gateway-authoring/) | Indexes measured signals, verifies a speech corpus, and seeds provisional Gateway Forge briefings | Python 3 | macOS/Linux | Yes |
| [`piper-workflows/`](piper-workflows/) | Piper training, export, render, audition, and direct-inference wrappers for known upstream failure modes | Python 3 plus a compatible Piper training environment | Primarily macOS/Linux | Yes |
| [`tts-research/`](tts-research/) | Produces Qwen3-TTS tensor, tokenizer, and speaking-pace ground truth | Python 3, MLX, mlx-audio, Transformers | Apple silicon macOS | Yes |

The karaoke and narration renderer that used to live here as
`lyric-video-maker/` is now [Protoke](https://github.com/snepssen/protoke), its
own cross-platform project.

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

## The wider workshop

- [Gateway Forge](https://snepssen.github.io/gateway-forge/) — guided-session
  authoring and an experience journal.
- [Voice Forge](https://snepssen.github.io/voice-forge/) — measured Piper
  speech, pronunciation, and export.
- [Protoke](https://snepssen.github.io/protoke/) — lyric and narration video
  with a word-timed vector face.
- [Media Preflight](https://snepssen.github.io/media-preflight/) — check a
  finished file against a delivery target, and correct it without touching
  the original.
- [tools-core](https://snepssen.github.io/tools-core/) — this repository.

## Privacy and scope

- These tools take explicit paths and act only on what you name.
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

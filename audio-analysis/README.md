# Audio analysis

Diagnostic utilities for stereo beat layers, rendered-speech joins and onsets,
speaking pace, and voice-reference preparation.

The scripts are independent CLIs. Use `python3 SCRIPT --help` where supported;
legacy diagnostic scripts describe their argument shape in the module docstring.
Highlights:

- `analyse-beat.py AUDIO --json` measures persistent left/right tone pairs.
- `analyse-all-beats.sh TAPE_ROOT [OUTPUT_DIR]` batches FLAC files. Set
  `PYTHON=/path/to/python` to select an environment.
- `beat-report.py GATEWAY_ROOT BEAT_ANALYSIS_DIR` relates measurements to a
  Gateway Forge library.
- `align-corpus.py AUDIO WORDS_JSON SCRIPT_MD OUT_DIR [--dry-run]` aligns a
  continuous read to authored text and cuts training clips with ffmpeg.
- `cut-reference.py` and `find-reference-window.py` prepare natural reference
  excerpts without removing pauses.
- `analyse-joins.py`, `analyse-onsets.py`, and `analyse-pace.py` inspect common
  rendering defects.

Beat analysis requires NumPy, SciPy, and soundfile. Corpus cutting requires
ffmpeg. `index-tapes.py GATEWAY_ROOT [--dry-run]` rewrites Markdown frontmatter,
so inspect its dry run first and use it only on a version-controlled checkout.

# Gateway authoring helpers

Utilities tied to Gateway Forge's editable library layout:

- `save-signals.py GATEWAY_ROOT BEAT_ANALYSIS_DIR` writes measured signal
  profiles beneath `library/signals/measured`.
- `seed-briefings.py GATEWAY_ROOT --dry-run` previews missing provisional
  briefing files; omit `--dry-run` to write them. Existing files are preserved.
- `verify-corpus.py CORPUS_DIR RETRANSCRIPT_DIR SCRIPT_MD [--drop]` compares
  speech clips with their labels. `--drop` moves suspect clips into
  `held-back/`; run without it first.

These tools intentionally take the Gateway Forge checkout as an argument. No
private library content is included in this repository.

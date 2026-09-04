# Contributing

Keep contributions small, source-only, and reproducible. Do not commit audio,
video, lyric sheets, transcripts, model weights, checkpoints, caches, generated
corpora, access tokens, or machine-specific absolute paths.

Before opening a pull request, run:

```sh
python3 scripts/check_release.py
```

Document any command that writes to its inputs. Prefer explicit path arguments
over assumptions about the checkout location. New network listeners must remain
loopback-only unless they receive a dedicated security review.

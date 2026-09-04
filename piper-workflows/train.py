#!/usr/bin/env python3
"""Launches piper.train's CLI with one fix applied first.

PyTorch 2.6 changed torch.load's default to weights_only=True, and the
rhasspy/piper-checkpoints files were pickled under an older PyTorch that
happily embedded a pathlib.PosixPath in the saved hyperparameters. Lightning's
own checkpoint loader (LightningCLI._parse_ckpt_path) calls torch.load without
allowlisting that type, so loading fails before training code is ever reached.

torch.serialization.add_safe_globals is the fix torch's own error message
names, but the plain form isn't enough on Python 3.13: passing the class alone
registers it under its *own* __module__, which 3.13's pathlib reports as the
internal "pathlib._local" rather than "pathlib" — a rename the pickled
checkpoint predates, so the string the unpickler looks up never matches.
add_safe_globals also accepts an explicit (class, "dotted.path") override for
exactly this; that form is what actually clears the check. Confirmed by
loading the checkpoint standalone before wiring this in — the plain-class form
still raised the identical error.

This has to run before Lightning's loader does, which is why it's a wrapper
rather than a CLI flag — piper.train exposes no such flag.
"""
import pathlib
import sys

import torch.serialization

torch.serialization.add_safe_globals([(pathlib.PosixPath, "pathlib.PosixPath")])

import piper.train.__main__ as piper_main  # noqa: E402

# piper.train's own comment claims a missing "val_mos" (UTMOS) metric makes
# this ModelCheckpoint "warn once and skip" when no MOS predictor is loaded.
# On lightning 2.6.5 that is not what happens: it raises MisconfigurationException
# and kills the run — confirmed here after a full first epoch completed cleanly
# and crashed only at checkpoint-saving, once real validation metrics existed
# but val_mos specifically was still absent from them. We are not passing
# --model.mos_metric (no MOS predictor available), so val_mos is never going to
# log; the val_mel callback right before it in the list already does the useful
# job (keeps the top 5 by mel L1, plus the last checkpoint), so the broken
# val_mos callback is dropped rather than worked around some other way.
piper_main._DEFAULT_CALLBACKS = [
    cb
    for cb in piper_main._DEFAULT_CALLBACKS
    if getattr(cb, "monitor", None) != "val_mos"
]

if __name__ == "__main__":
    sys.exit(piper_main.main())

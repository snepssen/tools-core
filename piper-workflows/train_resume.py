#!/usr/bin/env python3
"""Resume a run without warm-starting over the top of it.

**A resume re-applies the warm start unless something stops it.** `VitsModel`
takes `warmstart_ckpt` as an init argument and calls `save_hyperparameters()`,
so the path is written into every checkpoint the run produces. Restoring one
rebuilds the model from those hyperparameters, `_warmstart_ckpt` is set again,
and `on_fit_start` copies the base checkpoint's weights over the ones Lightning
has just restored -- while the epoch counter carries on as if nothing happened.
The `self._warmstart_ckpt = None` at the end of `on_fit_start` only guards
against re-running inside one process; it cannot survive a restart, because the
object is rebuilt from the saved hyperparameters. Passing
`--model.warmstart_ckpt null` does not help for the same reason.

On Linux the baked-in macOS path fails loudly. Here it resolves, so the failure
is silent: a run hundreds of epochs deep quietly becomes the base model again.

This is the only safe way to continue an existing run. Diagnosed on the Steam
Deck against the Suno run; the same trap applies to every run this trainer
produces, including the Rode one.
"""

import pathlib
import sys

import torch.serialization

torch.serialization.add_safe_globals([(pathlib.PosixPath, "pathlib.PosixPath")])

import piper.train.__main__ as piper_main  # noqa: E402
from piper.train.vits.lightning import VitsModel  # noqa: E402

# Neutralise the warm start for this process, whatever the checkpoint asks for.
_original_on_fit_start = VitsModel.on_fit_start


def _on_fit_start_without_warmstart(self):
    if getattr(self, "_warmstart_ckpt", None) is not None:
        print(f"[resume] ignoring warmstart_ckpt from hyperparameters: "
              f"{self._warmstart_ckpt}", flush=True)
        self._warmstart_ckpt = None
    if getattr(self, "_vocoder_warmstart_ckpt", None) is not None:
        print("[resume] ignoring vocoder_warmstart_ckpt", flush=True)
        self._vocoder_warmstart_ckpt = None
    _original_on_fit_start(self)


VitsModel.on_fit_start = _on_fit_start_without_warmstart


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

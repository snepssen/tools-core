#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# The scripted sequence-mask/path implementation below is adapted from
# OHF-voice/piper1-gpl (commit b2758261878e4d832acb208e33915df8954ae2d4).
# Copyright belongs to the Piper contributors; see COPYING in this directory.
"""Launches piper.train.export_onnx with one fix applied first.

torch 2.13 defaults torch.onnx.export to its newer "dynamo" exporter, which
traces the model through torch.export's symbolic-shape system. VITS's
stochastic duration predictor (the rational-quadratic spline transform) has
runtime data-dependent branching that this static tracer can't verify and
refuses to export ("GuardOnDataDependentSymNode"). export_onnx.py's call site
doesn't pass a dynamo flag, so this failure is not something the CLI's own
arguments can route around.

The older TorchScript-based tracer (dynamo=False) executes one concrete trace
instead of proving the shapes statically, and has no trouble with this model
-- it is what every existing Piper voice was actually exported with, since
those checkpoints predate the dynamo exporter becoming torch's default.
"""
import sys

# Before any piper import: `import piper` pulls in onnxruntime, and the switch
# has to be thrown before its uploader thread exists.
import no_telemetry  # noqa: F401

import torch.onnx

_original_export = torch.onnx.export


def _export_with_legacy_tracer(*args, **kwargs):
    kwargs.setdefault("dynamo", False)
    return _original_export(*args, **kwargs)


torch.onnx.export = _export_with_legacy_tracer

# The actual bug behind the "y-you" stutter reported after both the length-
# match and noise_w=0 tests still had it: generate_path (the code turning
# per-phoneme durations into the frame-level alignment path) reads its output
# frame count via `t_y = mask.shape[2]`, a Python int under the legacy
# tracer -- frozen to whatever the ONE dummy trace's predicted duration
# summed to, not the real utterance's. Confirmed mechanically (not by
# listening) by tracing this at one length and running it at another: the
# untouched original mismatches, the scripted replacement below does not --
# 0.0 max abs diff against a freshly-computed reference at the new length.
#
# torch.jit.script (compilation) is what fixes this, not torch.jit.trace
# (execution recording): scripting compiles `tensor.shape[i]` into a real
# "read this tensor's shape" instruction, where tracing replaces it with
# whatever concrete number it happened to be during the one recorded run.
# Training's own code is untouched -- this only patches the module attribute
# the export process reads, and only for the duration of this process.
import piper.train.vits.commons as _commons  # noqa: E402


@torch.jit.script
def _sequence_mask_scripted(length: torch.Tensor, max_length: int) -> torch.Tensor:
    x = torch.arange(max_length, dtype=length.dtype, device=length.device)
    return x.unsqueeze(0) < length.unsqueeze(1)


@torch.jit.script
def _generate_path_scripted(duration: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    b = mask.shape[0]
    t_y = mask.shape[2]
    t_x = mask.shape[3]
    cum_duration = torch.cumsum(duration, -1)
    cum_duration_flat = cum_duration.view(b * t_x)
    path = _sequence_mask_scripted(cum_duration_flat, t_y).to(mask.dtype)
    path = path.view(b, t_x, t_y)
    path = path - torch.nn.functional.pad(path, (0, 0, 1, 0, 0, 0))[:, :-1]
    path = path.unsqueeze(1).transpose(2, 3) * mask
    return path


_commons.generate_path = _generate_path_scripted

from piper.train.export_onnx import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

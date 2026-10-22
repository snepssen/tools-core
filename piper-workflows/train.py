#!/usr/bin/env python3
"""Launches piper.train's CLI with the checkpoint fixes applied first.

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

Before that loader runs, a fit is refused when the output or run directory
already holds `*.ckpt` files. This entry point warm-starts. Launching it
again in a directory that already contains checkpoints silently overwrites
trained weights with the base checkpoint. The refusal points at
`train_resume.py`. `--force` is this wrapper's own switch (piper.train has
no such flag) and is removed before LightningCLI parses the arguments.
"""
import json
import pathlib
import sys

# LightningCLI subcommands. A bare one of these is the subcommand, never the
# value of the flag before it (a run directory is not named "fit").
_SUBCOMMANDS = {"fit", "validate", "test", "predict"}

# Directories a fit writes checkpoints into. default_root_dir / logger save_dir
# are the run root (checkpoints land under lightning_logs/…/checkpoints, or
# directly under the root when there is no logger). A ModelCheckpoint dirpath
# is the output directory the *.ckpt files are written into.
_RUN_DIR_FLAGS = {
    "--trainer.default_root_dir",
    "--trainer.logger.save_dir",
    "--trainer.logger.init_args.save_dir",
}
_CONFIG_DIR_KEYS = ("default_root_dir", "save_dir", "dirpath")
_NULL_VALUES = {"", "null", "none", "~"}


def _strip_force(argv):
    """Drop our --force switch. LightningCLI would reject the unknown flag."""
    force = False
    kept = [argv[0]]
    passthrough = False
    for arg in argv[1:]:
        if arg == "--":
            passthrough = True
            kept.append(arg)
            continue
        if not passthrough and arg == "--force":
            force = True
            continue
        kept.append(arg)
    return force, kept


def _is_fit(argv):
    """True when this invocation would warm-start a fit."""
    if any(arg in {"-h", "--help"} for arg in argv[1:]):
        return False
    args = argv[1:]
    positionals = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            break
        if arg == "--force":
            index += 1
            continue
        if arg.startswith("-") and "=" not in arg:
            nxt = args[index + 1] if index + 1 < len(args) else None
            if nxt in _SUBCOMMANDS:
                index += 1
                continue
            index += 2
            continue
        if not arg.startswith("-"):
            positionals.append(arg)
        index += 1
    return "fit" in positionals


def _is_output_flag(name):
    return name in _RUN_DIR_FLAGS or name == "--dirpath" or name.endswith(".dirpath")


def _cli_directories(argv):
    values = []
    index = 1
    while index < len(argv):
        arg = argv[index]
        if arg == "--":
            break
        name, sep, inline = arg.partition("=")
        if _is_output_flag(name):
            if sep:
                values.append(inline)
                index += 1
            elif index + 1 < len(argv):
                values.append(argv[index + 1])
                index += 2
            else:
                index += 1
            continue
        index += 1
    return values


def _option_values(argv, names):
    values = []
    index = 1
    while index < len(argv):
        arg = argv[index]
        if arg == "--":
            break
        if arg in names:
            if index + 1 < len(argv):
                values.append(argv[index + 1])
            index += 2
            continue
        if "=" in arg:
            name, value = arg.split("=", 1)
            if name in names:
                values.append(value)
        index += 1
    return values


def _clean_dir(value):
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    if " #" in text:
        text = text.split(" #", 1)[0].rstrip()
    if text.lower() in _NULL_VALUES:
        return None
    return pathlib.Path(text)


def _directories_in_json(obj, found):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in _CONFIG_DIR_KEYS and isinstance(value, str):
                found.append(value)
            else:
                _directories_in_json(value, found)
    elif isinstance(obj, list):
        for item in obj:
            _directories_in_json(item, found)


def _directories_in_config(path):
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return []
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            found = []
            _directories_in_json(json.loads(text), found)
            return found
        except json.JSONDecodeError:
            pass
    found = []
    for line in text.splitlines():
        body = line.split(" #", 1)[0].strip()
        if body.startswith("- "):
            body = body[2:].strip()
        for key in _CONFIG_DIR_KEYS:
            prefix = key + ":"
            if body.startswith(prefix):
                found.append(body[len(prefix):])
                break
    return found


def _output_directories(argv):
    """Run roots and checkpoint output directories named by this fit.

    With neither set, Lightning writes the run under ./lightning_logs.
    """
    raw = list(_cli_directories(argv))
    for config in _option_values(argv, {"--config"}):
        raw.extend(_directories_in_config(pathlib.Path(config)))
    directories = []
    seen = set()
    for value in raw:
        directory = _clean_dir(value)
        if directory is None:
            continue
        key = str(directory)
        if key not in seen:
            seen.add(key)
            directories.append(directory)
    if not directories:
        directories.append(pathlib.Path("lightning_logs"))
    return directories


def _checkpoints_under(directory):
    if not directory.is_dir():
        return []
    found = [
        path
        for path in directory.rglob("*")
        if path.is_file() and path.name.endswith(".ckpt")
    ]
    return sorted(found)


def _refusal_message(hits):
    lines = ["refusing to start:"]
    for directory, checkpoints in hits:
        shown = ", ".join(str(path) for path in checkpoints[:8])
        extra = len(checkpoints) - min(len(checkpoints), 8)
        if extra:
            shown = f"{shown}, and {extra} more"
        lines.append(f"  {directory} already holds checkpoints ({shown}).")
    lines.append(
        "A warm start would silently overwrite trained weights."
    )
    lines.append(
        "Resume with train_resume.py and --ckpt_path <newest last.ckpt>, "
        "or pass --force to start this warm start anyway."
    )
    return "\n".join(lines)


def _guard_warm_start(argv):
    """Return argv for Piper, or exit when a warm start would overwrite."""
    force, argv = _strip_force(argv)
    if force or not _is_fit(argv):
        return argv
    hits = []
    for directory in _output_directories(argv):
        checkpoints = _checkpoints_under(directory)
        if checkpoints:
            hits.append((directory, checkpoints))
    if hits:
        sys.exit(_refusal_message(hits))
    return argv


def main():
    sys.argv = _guard_warm_start(sys.argv)

    import torch.serialization

    torch.serialization.add_safe_globals([(pathlib.PosixPath, "pathlib.PosixPath")])

    import piper.train.__main__ as piper_main

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

    sys.exit(piper_main.main())


if __name__ == "__main__":
    main()

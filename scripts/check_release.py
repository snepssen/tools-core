#!/usr/bin/env python3
"""Fail when the source tree contains common publication hazards."""

from __future__ import annotations

import compileall
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
EXCLUDED_DIRS = {".git", ".venv", "venv", "__pycache__"}
GENERATED_SUFFIXES = {
    ".aiff", ".ass", ".bin", ".ckpt", ".flac", ".m4a", ".mov", ".mp3",
    ".mp4", ".onnx", ".ogg", ".pt", ".pth", ".safetensors", ".srt", ".wav",
}
TEXT_SUFFIXES = {
    ".command", ".css", ".html", ".js", ".json", ".md", ".py", ".sh",
    ".toml", ".txt", ".yaml", ".yml",
}
PRIVATE_PATHS = [
    re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+/"),
    re.compile(r"/Volumes/[A-Za-z0-9._ -]+/"),
    re.compile(r"/private/(?:tmp|var)/"),
]
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bgh[opsu]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b"),
]


def files():
    for path in ROOT.rglob("*"):
        if path.is_file() and not any(part in EXCLUDED_DIRS for part in path.parts):
            yield path


def source_audit() -> list[str]:
    failures: list[str] = []
    self_path = Path(__file__).resolve()
    for path in files():
        rel = path.relative_to(ROOT)
        if path.stat().st_size > 5 * 1024 * 1024:
            failures.append(f"{rel}: file exceeds 5 MiB")
        if path.suffix.lower() in GENERATED_SUFFIXES:
            failures.append(f"{rel}: generated/media/model artifact")
        if path == self_path or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            failures.append(f"{rel}: text-like file is not UTF-8")
            continue
        for pattern in PRIVATE_PATHS:
            if pattern.search(text):
                failures.append(f"{rel}: contains a private absolute path")
                break
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                failures.append(f"{rel}: contains a likely secret")
                break
    return failures


def shell_audit() -> list[str]:
    failures = []
    for path in files():
        if path.suffix in {".sh", ".command"}:
            result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
            if result.returncode:
                failures.append(f"{path.relative_to(ROOT)}: {result.stderr.strip()}")
    return failures


def tests_pass() -> bool:
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    return unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful()


def main() -> int:
    failures = source_audit() + shell_audit()
    if not compileall.compile_dir(ROOT, quiet=1):
        failures.append("one or more Python files did not compile")
    if not tests_pass():
        failures.append("unit tests failed")
    if failures:
        print("release check failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    count = sum(1 for _ in files())
    print(f"release check passed ({count} files audited)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

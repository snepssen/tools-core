#!/usr/bin/env python3
"""Check subtitle timing and readability; print the cues that need attention."""
import argparse
import json
import math
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / "engine"))
import captions


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return number


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def inspect(path, args):
    track = captions.load(str(path))
    if not track.get("cues"):
        raise captions.CaptionError("No readable subtitle cues found in " + str(path))
    measured = captions.measure(track, duration_s=args.duration)
    rules = [
        ("caption_max_cps", {"max": args.max_cps}, "reading-speed"),
        ("caption_max_line_length", {"max": args.max_line_length}, "line-length"),
        ("caption_max_lines", {"max": args.max_lines}, "line-count"),
        ("caption_shortest_cue_s", {"min": args.min_duration}, "short-cue"),
        ("caption_longest_cue_s", {"max": args.max_duration}, "long-cue"),
        ("caption_empty_cues", {}, "empty-cue"),
        ("caption_bad_timing", {}, "invalid-timing"),
    ]
    findings = []
    # The upstream reader intentionally skips records it cannot interpret.
    # A checker must make that visible even when other cues parsed successfully.
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if track["format"] in {"ass", "ssa"}:
        candidates = sum(line.lstrip().lower().startswith("dialogue:")
                         for line in text.splitlines())
    else:
        blocks = [b for b in re.split(r"\r?\n\s*\r?\n", text.strip()) if b.strip()]
        if track["format"] == "vtt":
            blocks = [b for b in blocks if not b.lstrip().upper().startswith(
                ("WEBVTT", "NOTE", "STYLE", "REGION"))]
        candidates = len(blocks)
    if candidates > len(track["cues"]):
        findings.append({"code": "unreadable-cue", "detail":
                         "%d cue records could not be parsed" % (candidates - len(track["cues"]))})
    for metric, rule, code in rules:
        for event in captions.offending_cues(
                metric, rule, track["cues"], limit=sys.maxsize,
                shown=measured["displays"]):
            findings.append(dict(event, code=code))
    for event in measured["caption_overlap_intervals"]:
        findings.append(dict(event, code="overlap"))
    if args.duration is not None:
        for cue in track["cues"]:
            if max(cue["start"], cue["end"]) > args.duration:
                findings.append({"code": "past-end", "start": cue["start"],
                                 "end": cue["end"], "detail": "cue %s exceeds the programme duration"
                                 % cue["index"]})
    for cue in track["cues"]:
        if cue["start"] < 0 or cue["end"] < 0:
            findings.append({"code": "negative-time", "start": cue["start"],
                             "end": cue["end"], "detail": "cue %s has a negative time"
                             % cue["index"]})
    for name in measured["caption_missing_font_names"]:
        findings.append({"code": "missing-font", "detail": name})
    findings.sort(key=lambda row: (row.get("start", float("inf")), row["code"]))
    return {"path": str(path), "format": track["format"],
            "cue_count": len(track["cues"]), "findings": findings,
            "fonts_checked": measured["caption_missing_fonts"] is not None,
            "thresholds": {"max_cps": args.max_cps,
                           "max_line_length": args.max_line_length,
                           "max_lines": args.max_lines, "min_duration": args.min_duration,
                           "max_duration": args.max_duration, "duration": args.duration}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--max-cps", type=positive, default=20)
    parser.add_argument("--max-line-length", type=positive_int, default=42)
    parser.add_argument("--max-lines", type=positive_int, default=2)
    parser.add_argument("--min-duration", type=positive, default=1.0)
    parser.add_argument("--max-duration", type=positive, default=7.0)
    parser.add_argument("--duration", type=positive, help="programme length in seconds")
    args = parser.parse_args(argv)
    if args.min_duration > args.max_duration:
        parser.error("--min-duration must not exceed --max-duration")
    reports, status = [], 0
    for path in args.files:
        path = path.expanduser().absolute()
        try:
            report = inspect(path, args)
            if report["findings"]:
                status = max(status, 1)
        except (OSError, ValueError, captions.CaptionError) as error:
            report = {"path": str(path), "error": str(error)}
            status = 2
        reports.append(report)
    if args.json:
        print(json.dumps(reports, indent=2, ensure_ascii=False, allow_nan=False))
    else:
        for report in reports:
            print(report["path"])
            if "error" in report:
                print("  Cannot check: " + report["error"])
                continue
            print("  %d cues; %d findings" % (report["cue_count"], len(report["findings"])))
            for finding in report["findings"]:
                when = ("%.3fs  " % finding["start"]) if "start" in finding else ""
                print("  %s%s: %s" % (when, finding["code"], finding["detail"]))
            if not report["fonts_checked"]:
                print("  Font availability not checked (fontconfig unavailable).")
    return status


if __name__ == "__main__":
    sys.exit(main())

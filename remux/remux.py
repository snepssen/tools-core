#!/usr/bin/env python3
"""Copy every supported media stream to a new container, without re-encoding."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / "engine"))
import formats
from engines import ConversionError
from engines import ffmpeg
from platform_support import require, MissingProgram

CONTAINERS = {"mkv", "mp4", "mov", "webm", "m4a"}
SUBTITLES = {
    "mkv": {"subrip", "ass", "ssa", "webvtt", "hdmv_pgs_subtitle", "dvd_subtitle"},
    "mp4": {"mov_text"}, "mov": {"mov_text"},
    "webm": set(), "m4a": set(),
}


def plan(source, destination):
    container = destination.suffix.lower().lstrip(".")
    if container not in CONTAINERS:
        raise ConversionError("Output must end in .mkv, .mp4, .mov, .webm or .m4a.")
    info = ffmpeg.probe(source)
    streams = info.get("streams", [])
    if not streams or not any(s.get("codec_type") in {"audio", "video"} for s in streams):
        raise ConversionError("No audio or video streams to repackage.")
    refused, choices = [], []
    for stream in streams:
        kind, codec = stream.get("codec_type"), stream.get("codec_name")
        index = stream["index"]
        if stream.get("disposition", {}).get("attached_pic"):
            fits = False  # Cover images have container-specific stream semantics.
        elif kind in {"audio", "video"}:
            fits = formats.can_hold(container, codec, kind)
        elif kind == "subtitle":
            fits = codec in SUBTITLES[container]
        elif kind == "attachment":
            fits = container == "mkv"
        else:
            fits = False
        if not fits:
            refused.append("stream %s (%s/%s)" % (index, kind, codec))
        choices.append({"index": index, "kind": kind, "codec": codec, "action": "copy"})
    if refused:
        raise ConversionError(
            "%s cannot be preserved by this tool in %s. Nothing written; "
            "no stream will be dropped or re-encoded." % (", ".join(refused), container))
    return {"source": str(source), "destination": str(destination),
            "container": container, "streams": choices}


def signature(path):
    status = path.stat()
    return status.st_dev, status.st_ino, status.st_size, status.st_mtime_ns


def write_copy(proposal):
    source, destination = Path(proposal["source"]), Path(proposal["destination"])
    binary = require("ffmpeg")
    before = signature(source)
    # A private staging directory keeps partial results out of the requested name.
    # Linking into place is atomic and refuses even a destination created meanwhile.
    with tempfile.TemporaryDirectory(prefix=".remux-", dir=str(destination.parent)) as staging:
        temporary = Path(staging) / ("output." + proposal["container"])
        command = [binary, "-nostdin", "-hide_banner", "-v", "error", "-n",
                   "-i", str(source), "-map", "0", "-map_metadata", "0",
                   "-map_chapters", "0", "-c", "copy"]
        if proposal["container"] in {"mp4", "mov", "m4a"}:
            command += ["-movflags", "+faststart"]
        command.append(str(temporary))
        result = subprocess.run(command, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, text=True)
        if result.returncode:
            raise ConversionError("FFmpeg could not preserve these streams: " + result.stderr.strip())
        actual = ffmpeg.probe(temporary).get("streams", [])
        expected = [(s["kind"], s["codec"]) for s in proposal["streams"]]
        found = [(s.get("codec_type"), s.get("codec_name")) for s in actual]
        if found != expected:
            raise ConversionError("Output stream inventory changed; the result was discarded.")
        if signature(source) != before:
            raise ConversionError("Source changed while it was being read; the result was discarded.")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.link(str(temporary), str(destination))
    return destination.stat().st_size


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--plan", action="store_true", help="explain the copy without writing")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        source = args.source.expanduser().resolve(strict=True)
        destination = args.destination.expanduser().absolute()
        if not source.is_file():
            raise ConversionError("Source must be a local file.")
        if os.path.lexists(str(destination)):
            raise ConversionError("Destination already exists; choose a new filename.")
        if not destination.parent.is_dir():
            raise ConversionError("Destination directory does not exist.")
        before = signature(source)
        proposal = plan(source, destination)
        if signature(source) != before:
            raise ConversionError("Source changed during inspection; try again once it is stable.")
        proposal["written"] = not args.plan
        if not args.plan:
            proposal["bytes"] = write_copy(proposal)
        if args.json:
            print(json.dumps(proposal, indent=2, ensure_ascii=False))
        else:
            for stream in proposal["streams"]:
                print("Copy stream %(index)s: %(kind)s / %(codec)s" % stream)
            print(("Would write " if args.plan else "Wrote ") + str(destination))
            print("No audio, video or subtitle stream re-encoded.")
        return 0
    except (OSError, subprocess.SubprocessError, ConversionError, MissingProgram) as error:
        print("remux: " + str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("remux: cancelled", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())

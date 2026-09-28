#!/usr/bin/env python3
"""
wav-tag.py — tag untagged .wav files (Suno exports, DAW bounces) from the
folder layout, so they stop showing up as "Unknown artist".

Point it at a music folder. It walks the whole tree and treats every folder
that directly contains .wav files as an album:

  Music/
    Night Drive EP/         -> Album "Night Drive EP"
      Neon.wav              -> Title "Neon", track by creation date
      City Lights (1).wav   -> Title "City Lights"
    Long Player/            -> Album "Long Player"
      A/  B/  Bonus/        -> sides: merged into "Long Player", numbering continues
    Colours/A/A01 Red.wav   -> Title "Red", track order from "A01"
    Series/Part II/         -> Album "Part II"

  * Artist  — from --artist
  * Album   — the folder name (side/disc folders like A, B, Bonus use the parent's)
  * Title   — the file name (tidied: "_" -> space, "(1)", "- Copy", "A01 " removed)
  * Track # — the number in the file name if every file has one, otherwise
              creation-date order (oldest = 1)
  * Year    — the file's creation year (or --year)

Tags are written twice so every player finds them:
  * ID3v2.3 chunk ("id3 ")  -> Apple Music, VLC, SoundCloud/Bandcamp uploads
  * RIFF LIST/INFO chunk    -> Windows Explorer, DAWs, older tools

Audio data is untouched and files are rewritten in place, so creation dates
(and therefore track numbering) survive repeated runs.

Usage:
  python3 wav-tag/wav-tag.py ~/Music --artist "Name"            # preview
  python3 wav-tag/wav-tag.py ~/Music --artist "Name" --apply    # write
  python3 wav-tag/wav-tag.py ~/Music --show                     # read back
"""

import argparse
import datetime as dt
import os
import re
import struct
import sys
from pathlib import Path

META_CHUNKS = {b"id3 ", b"ID3 "}


# ---------------------------------------------------------------- discovery

def creation_time(path: Path) -> float:
    st = path.stat()
    # macOS exposes the real creation time; fall back to mtime elsewhere.
    return getattr(st, "st_birthtime", st.st_mtime)


# "A01 Song", "B12 Song", "01 - Song", "3. Song"
NUMBER_PREFIX = re.compile(r"^(?:[A-Za-z]\d{2}\s+|\d{1,3}\s*[-.]\s+)")

# Folders that are sides/discs of the parent album rather than albums themselves:
# "A", "B", "Side A", "Disc 2", "CD1", "Bonus", "Bonus Tracks"
SIDE_FOLDER = re.compile(r"^(?:[A-Za-z]|(?:side|disc|disk|cd)\s*\w{1,2}|bonus(?:\s+tracks?)?)$", re.I)


def title_from_filename(path: Path) -> str:
    name = path.stem.replace("_", " ")
    name = re.sub(r"\s*-\s*Copy$", "", name, flags=re.I)   # "Song - Copy"
    name = re.sub(r"\s*\(\d+\)$", "", name)                 # "Song (1)"
    name = NUMBER_PREFIX.sub("", name)                      # "A01 Song", "01 - Song"
    name = re.sub(r"\s+", " ", name).strip()
    return name or path.stem


def order_tracks(wavs: list) -> list:
    """Numbered file names win (A01, A02 …); otherwise oldest file first."""
    if all(NUMBER_PREFIX.match(p.stem) for p in wavs):
        return sorted(wavs, key=lambda p: p.name.lower())
    return sorted(wavs, key=lambda p: (creation_time(p), p.name.lower()))


def side_order(folder: Path):
    # Bonus sides go last; everything else alphabetically (A, B, Disc 1, Disc 2 …).
    return (folder.name.lower().startswith("bonus"), folder.name.lower())


def find_albums(root: Path) -> dict:
    """Map album folder -> tracks in album order.

    Every folder that directly holds .wav files is an album, except side/disc
    folders (A, B, Bonus …), which are merged into their parent album with
    track numbers continuing across sides.
    """
    groups = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        wavs = [Path(dirpath, f) for f in filenames
                if f.lower().endswith(".wav") and not f.startswith(".")]
        if wavs:
            groups[Path(dirpath)] = order_tracks(wavs)

    albums = {}
    for folder in sorted(groups, key=lambda f: (f.parent, side_order(f))):
        is_side = SIDE_FOLDER.match(folder.name) and folder != root
        album_dir = folder.parent if is_side else folder
        albums.setdefault(album_dir, []).extend(groups[folder])
    return dict(sorted(albums.items()))


# ---------------------------------------------------------------- RIFF

def read_chunks(data: bytes):
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE file")
    chunks, pos = [], 12
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        chunks.append((cid, data[pos + 8:pos + 8 + size]))
        pos += 8 + size + (size & 1)
    return chunks


def is_info_list(cid: bytes, body: bytes) -> bool:
    return cid == b"LIST" and body[:4] == b"INFO"


def pack_chunk(cid: bytes, body: bytes) -> bytes:
    return cid + struct.pack("<I", len(body)) + body + (b"\x00" if len(body) & 1 else b"")


# ---------------------------------------------------------------- tag builders

def build_info(tags: dict) -> bytes:
    fields = [
        (b"INAM", tags["title"]),
        (b"IART", tags["artist"]),
        (b"IPRD", tags["album"]),
        (b"ICRD", tags["year"]),
        (b"ITRK", tags["track"]),
        (b"IGNR", tags.get("genre")),
        (b"ISFT", "wav-tag.py"),
    ]
    body = b"INFO"
    for fid, val in fields:
        if val:
            body += pack_chunk(fid, str(val).encode("utf-8") + b"\x00")
    return pack_chunk(b"LIST", body)


def id3_text_frame(fid: str, text: str) -> bytes:
    # encoding 1 = UTF-16 with BOM, double-null terminated
    payload = b"\x01" + text.encode("utf-16") + b"\x00\x00"
    return fid.encode("ascii") + struct.pack(">I", len(payload)) + b"\x00\x00" + payload


def synchsafe(n: int) -> bytes:
    return bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])


def build_id3(tags: dict) -> bytes:
    frames = [
        ("TIT2", tags["title"]),
        ("TPE1", tags["artist"]),
        ("TPE2", tags["artist"]),          # album artist keeps albums grouped
        ("TALB", tags["album"]),
        ("TYER", tags["year"]),
        ("TRCK", tags["track"]),
        ("TCON", tags.get("genre")),
    ]
    body = b"".join(id3_text_frame(f, str(v)) for f, v in frames if v)
    return pack_chunk(b"id3 ", b"ID3\x03\x00\x00" + synchsafe(len(body)) + body)


# ---------------------------------------------------------------- tag readers (--show)

def parse_info(body: bytes) -> dict:
    out, pos = {}, 4
    while pos + 8 <= len(body):
        fid = body[pos:pos + 4].decode("ascii", "replace")
        size = struct.unpack("<I", body[pos + 4:pos + 8])[0]
        out[fid] = body[pos + 8:pos + 8 + size].rstrip(b"\x00").decode("utf-8", "replace")
        pos += 8 + size + (size & 1)
    return out


def parse_id3(body: bytes) -> dict:
    if body[:3] != b"ID3":
        return {}
    s = body[6:10]
    end = 10 + ((s[0] << 21) | (s[1] << 14) | (s[2] << 7) | s[3])
    out, pos = {}, 10
    while pos + 10 <= end and body[pos:pos + 4].strip(b"\x00"):
        fid = body[pos:pos + 4].decode("ascii", "replace")
        fsize = struct.unpack(">I", body[pos + 4:pos + 8])[0]
        raw = body[pos + 10:pos + 10 + fsize]
        if fid.startswith("T") and raw:
            codec = {0: "latin-1", 1: "utf-16", 2: "utf-16-be", 3: "utf-8"}.get(raw[0], "latin-1")
            out[fid] = raw[1:].decode(codec, "replace").rstrip("\x00")
        pos += 10 + fsize
    return out


# ---------------------------------------------------------------- write

def write_tags(path: Path, tags: dict) -> None:
    chunks = read_chunks(path.read_bytes())
    kept = [(c, b) for c, b in chunks if c not in META_CHUNKS and not is_info_list(c, b)]
    body = b"WAVE" + b"".join(pack_chunk(c, b) for c, b in kept)
    body += build_info(tags) + build_id3(tags)

    st = path.stat()
    # Rewrite the same file (same inode) so the creation date is preserved.
    with open(path, "r+b") as f:
        f.write(b"RIFF" + struct.pack("<I", len(body)) + body)
        f.truncate()
        f.flush()
        os.fsync(f.fileno())
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))


# ---------------------------------------------------------------- commands

def show(root: Path, albums: dict) -> None:
    for folder, files in albums.items():
        print(f"\n{folder.relative_to(root.parent)}")
        for p in files:
            try:
                chunks = read_chunks(p.read_bytes())
            except ValueError as e:
                print(f"  {p.name}: {e}")
                continue
            id3 = next((parse_id3(b) for c, b in chunks if c in META_CHUNKS), {})
            info = next((parse_info(b) for c, b in chunks if is_info_list(c, b)), {})
            if not id3 and not info:
                print(f"  {p.name}: (no tags)")
                continue
            print(f"  {p.name}")
            print(f"     ID3 : {id3.get('TRCK','-')} | {id3.get('TIT2','-')} | "
                  f"{id3.get('TPE1','-')} | {id3.get('TALB','-')} | {id3.get('TYER','-')}")
            print(f"     INFO: {info.get('ITRK','-')} | {info.get('INAM','-')} | "
                  f"{info.get('IART','-')} | {info.get('IPRD','-')} | {info.get('ICRD','-')}")


def tag(root: Path, albums: dict, args) -> int:
    errors = done = 0
    for folder, files in albums.items():
        album = folder.name
        total = len(files)
        width = max(2, len(str(total)))
        print(f"\n[{album}]  {args.artist}  —  {total} track{'s' if total != 1 else ''}")
        for n, p in enumerate(files, 1):
            created = dt.datetime.fromtimestamp(creation_time(p))
            tags = {
                "title": title_from_filename(p),
                "artist": args.artist,
                "album": album,
                "year": args.year or str(created.year),
                "track": f"{n}/{total}",
                "genre": args.genre,
            }
            side = f"[{p.parent.name}] " if p.parent != folder else ""
            print(f"  {n:>{width}}. {side}{tags['title']:<40} {tags['year']}  "
                  f"(created {created:%Y-%m-%d %H:%M})")
            if args.apply:
                try:
                    write_tags(p, tags)
                    done += 1
                except Exception as e:  # keep going with the rest
                    errors += 1
                    print(f"      !! {p.name}: {e}")

    n_tracks = sum(len(f) for f in albums.values())
    print(f"\n{len(albums)} album(s), {n_tracks} track(s) found under {root}")
    if not args.apply:
        print("Preview only — nothing changed. Add --apply to write the tags.")
    else:
        print(f"Tagged {done} file(s)" + (f", {errors} error(s)." if errors else "."))
    return 1 if errors else 0


def main():
    ap = argparse.ArgumentParser(
        description="Tag WAVs: album = folder name, title = file name, track # = creation order.")
    ap.add_argument("folder", type=Path, help="root music folder")
    ap.add_argument("--artist", help="artist name to write on every track")
    ap.add_argument("--year", help="force one year (default: each file's creation year)")
    ap.add_argument("--genre", help="optional genre for every track")
    ap.add_argument("--apply", action="store_true", help="write tags (default is a preview)")
    ap.add_argument("--show", action="store_true", help="print the tags currently in the files")
    args = ap.parse_args()

    root = args.folder.expanduser().resolve()
    if not root.is_dir():
        sys.exit(f"Not a folder: {root}")
    albums = find_albums(root)
    if not albums:
        sys.exit(f"No .wav files found under {root}")

    if args.show:
        show(root, albums)
    elif not args.artist:
        sys.exit('Please pass --artist "Your Name" (or --show to just read tags)')
    else:
        sys.exit(tag(root, albums, args))


if __name__ == "__main__":
    main()

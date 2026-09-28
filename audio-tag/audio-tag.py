#!/usr/bin/env python3
"""
audio-tag.py — tag untagged audio (Suno exports, DAW bounces) from the folder
layout, so it stops showing up as "Unknown artist". WAV, MP3 and FLAC.

Point it at a music folder. It walks the whole tree and treats every folder
that directly contains audio files as an album:

  Music/
    Night Drive EP/         -> Album "Night Drive EP"
      Neon.wav              -> Title "Neon", track by creation date
      Neon.mp3              -> same track as Neon.wav (same name)
      City Lights (1).flac  -> Title "City Lights"
    Long Player/            -> Album "Long Player"
      A/  B/  Bonus/        -> sides: merged into "Long Player", numbering continues
    Colours/A/A01 Red.wav   -> Title "Red", track order from "A01"
    Series/Part II/         -> Album "Part II"

  * Artist  — from --artist
  * Album   — the folder name (side/disc folders like A, B, Bonus use the parent's)
  * Title   — the file name (tidied: "_" -> space, "(1)", "- Copy", "A01 " removed)
  * Track # — the number in the file name if every file has one, otherwise
              creation-date order (oldest = 1). Files that share a name
              (Song.wav, Song.mp3) are one track in two formats.
  * Year    — the track's creation year (or --year)

What is written:
  * WAV   an ID3v2.3 "id3 " chunk (Apple Music, VLC, upload pages) and a
          RIFF LIST/INFO chunk (Windows Explorer, DAWs)
  * MP3   the ID3v2 tag at the start of the file, keeping its version (2.3 or
          2.4); an existing ID3v1 tag at the end is updated to match
  * FLAC  the Vorbis comment block

Only the fields above are replaced. Everything else already in a tag — lyrics,
comments, pictures — is kept, and no pictures are added. Audio is untouched.
Files are rewritten in place, so creation dates (and therefore track
numbering) survive repeated runs.

Usage:
  python3 audio-tag/audio-tag.py ~/Music --artist "Name"            # preview
  python3 audio-tag/audio-tag.py ~/Music --artist "Name" --apply    # write
  python3 audio-tag/audio-tag.py ~/Music --show                     # read back
"""

import argparse
import datetime as dt
import os
import re
import struct
import sys
from pathlib import Path

AUDIO_SUFFIXES = {".wav", ".mp3", ".flac"}
ID3_CHUNKS = {b"id3 ", b"ID3 "}

# "A01 Song", "B12 Song", "01 - Song", "3. Song"
NUMBER_PREFIX = re.compile(r"^(?:[A-Za-z]\d{2}\s+|\d{1,3}\s*[-.]\s+)")

# Folders that are sides/discs of the parent album rather than albums themselves:
# "A", "B", "Side A", "Disc 2", "CD1", "Bonus", "Bonus Tracks"
SIDE_FOLDER = re.compile(r"^(?:[A-Za-z]|(?:side|disc|disk|cd)\s*\w{1,2}|bonus(?:\s+tracks?)?)$", re.I)


# ---------------------------------------------------------------- discovery

def creation_time(path: Path) -> float:
    st = path.stat()
    # macOS exposes the real creation time; fall back to mtime elsewhere.
    return getattr(st, "st_birthtime", st.st_mtime)


def title_from_filename(path: Path) -> str:
    name = path.stem.replace("_", " ")
    name = re.sub(r"\s*-\s*Copy$", "", name, flags=re.I)   # "Song - Copy"
    name = re.sub(r"\s*\(\d+\)$", "", name)                 # "Song (1)"
    name = NUMBER_PREFIX.sub("", name)                      # "A01 Song", "01 - Song"
    name = re.sub(r"\s+", " ", name).strip()
    return name or path.stem


def order_tracks(files: list) -> list:
    """Group files by name (one track, several formats) and put the tracks in order.

    Numbered file names win (A01, A02 …); otherwise oldest track first.
    """
    by_name = {}
    for p in files:
        by_name.setdefault(p.stem.lower(), []).append(p)
    tracks = [sorted(g, key=lambda p: p.suffix.lower()) for g in by_name.values()]
    if all(NUMBER_PREFIX.match(t[0].stem) for t in tracks):
        return sorted(tracks, key=lambda t: t[0].stem.lower())
    return sorted(tracks, key=lambda t: (min(map(creation_time, t)), t[0].stem.lower()))


def side_order(folder: Path):
    # Bonus sides go last; everything else alphabetically (A, B, Disc 1, Disc 2 …).
    return (folder.name.lower().startswith("bonus"), folder.name.lower())


def find_albums(root: Path) -> dict:
    """Map album folder -> tracks in album order; each track is a list of files.

    Every folder that directly holds audio files is an album, except side/disc
    folders (A, B, Bonus …), which are merged into their parent album with
    track numbers continuing across sides.
    """
    groups = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        audio = [Path(dirpath, f) for f in filenames
                 if Path(f).suffix.lower() in AUDIO_SUFFIXES and not f.startswith(".")]
        if audio:
            groups[Path(dirpath)] = order_tracks(audio)

    albums = {}
    for folder in sorted(groups, key=lambda f: (f.parent, side_order(f))):
        is_side = SIDE_FOLDER.match(folder.name) and folder != root
        album_dir = folder.parent if is_side else folder
        albums.setdefault(album_dir, []).extend(groups[folder])
    return dict(sorted(albums.items()))


# ---------------------------------------------------------------- ID3v2 (WAV + MP3)

def synchsafe(n: int) -> bytes:
    return bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])


def unsynchsafe(b: bytes) -> int:
    return (b[0] << 21) | (b[1] << 14) | (b[2] << 7) | b[3]


def id3_size(data: bytes) -> int:
    """Length of the ID3v2 tag at the start of data, or 0 if there is none."""
    if len(data) < 10 or data[:3] != b"ID3":
        return 0
    size = 10 + unsynchsafe(data[6:10])
    if data[3] == 4 and data[5] & 0x10:   # v2.4 footer
        size += 10
    return size


def parse_id3_frames(tag: bytes):
    """-> (major version, [(frame id, flags, body), …])."""
    major, flags = tag[3], tag[5]
    if major not in (3, 4):
        raise ValueError(f"ID3v2.{major} tag can't be rewritten safely (only 2.3 and 2.4)")
    if flags & 0x80:
        raise ValueError("unsynchronised ID3 tag can't be rewritten safely")
    end = 10 + unsynchsafe(tag[6:10])
    pos = 10
    if flags & 0x40:  # extended header: skipped, and not written back
        pos += (4 + struct.unpack(">I", tag[10:14])[0]) if major == 3 else unsynchsafe(tag[10:14])
    frames = []
    while pos + 10 <= end and tag[pos:pos + 4].strip(b"\x00"):
        fid = tag[pos:pos + 4].decode("latin-1")
        raw = tag[pos + 4:pos + 8]
        size = unsynchsafe(raw) if major == 4 else struct.unpack(">I", raw)[0]
        frames.append((fid, tag[pos + 8:pos + 10], tag[pos + 10:pos + 10 + size]))
        pos += 10 + size
    return major, frames


def id3_text(body: bytes) -> str:
    if not body:
        return ""
    codec = {0: "latin-1", 1: "utf-16", 2: "utf-16-be", 3: "utf-8"}.get(body[0], "latin-1")
    return body[1:].decode(codec, "replace").split("\x00")[0]


def build_id3(tags: dict, old_tag: bytes = b"") -> bytes:
    """An ID3v2 tag holding our fields plus every other frame of old_tag."""
    major, old_frames = parse_id3_frames(old_tag) if old_tag else (3, [])
    ours = {
        "TIT2": tags["title"],
        "TPE1": tags["artist"],
        "TPE2": tags["artist"],          # album artist keeps albums grouped
        "TALB": tags["album"],
        "TYER" if major == 3 else "TDRC": tags["year"],
        "TRCK": tags["track"],
        "TCON": tags.get("genre"),
    }
    ours = {fid: str(v) for fid, v in ours.items() if v}

    def frame(fid, flags, body):
        size = synchsafe(len(body)) if major == 4 else struct.pack(">I", len(body))
        return fid.encode("latin-1") + size + flags + body

    body = b"".join(frame(fid, fl, b) for fid, fl, b in old_frames if fid not in ours)
    for fid, text in ours.items():
        # encoding 1 = UTF-16 with BOM, valid in both 2.3 and 2.4
        body += frame(fid, b"\x00\x00", b"\x01" + text.encode("utf-16") + b"\x00\x00")
    return b"ID3" + bytes([major, 0, 0]) + synchsafe(len(body)) + body


def read_id3(tag: bytes) -> dict:
    _, frames = parse_id3_frames(tag)
    t = {fid: id3_text(b) for fid, _, b in frames if fid.startswith("T")}
    return {"track": t.get("TRCK"), "title": t.get("TIT2"), "artist": t.get("TPE1"),
            "album": t.get("TALB"), "year": t.get("TYER") or t.get("TDRC")}


# ---------------------------------------------------------------- WAV

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


def build_info(tags: dict, old_body: bytes = b"INFO") -> bytes:
    """A LIST/INFO chunk with our fields plus every other field of old_body."""
    fields = [
        (b"INAM", tags["title"]),
        (b"IART", tags["artist"]),
        (b"IPRD", tags["album"]),
        (b"ICRD", tags["year"]),
        (b"ITRK", tags["track"]),
        (b"IGNR", tags.get("genre")),
        (b"ISFT", "audio-tag.py"),
    ]
    ours = {fid for fid, val in fields if val}
    body, pos = b"INFO", 4
    while pos + 8 <= len(old_body):
        fid = old_body[pos:pos + 4]
        size = struct.unpack("<I", old_body[pos + 4:pos + 8])[0]
        if fid not in ours:
            body += pack_chunk(fid, old_body[pos + 8:pos + 8 + size])
        pos += 8 + size + (size & 1)
    for fid, val in fields:
        if val:
            body += pack_chunk(fid, str(val).encode("utf-8") + b"\x00")
    return pack_chunk(b"LIST", body)


def parse_info(body: bytes) -> dict:
    out, pos = {}, 4
    while pos + 8 <= len(body):
        fid = body[pos:pos + 4].decode("ascii", "replace")
        size = struct.unpack("<I", body[pos + 4:pos + 8])[0]
        out[fid] = body[pos + 8:pos + 8 + size].rstrip(b"\x00").decode("utf-8", "replace")
        pos += 8 + size + (size & 1)
    return out


def retag_wav(data: bytes, tags: dict) -> bytes:
    chunks = read_chunks(data)
    old_id3 = next((b for c, b in chunks if c in ID3_CHUNKS and b[:3] == b"ID3"), b"")
    old_info = next((b for c, b in chunks if is_info_list(c, b)), b"INFO")
    kept = [(c, b) for c, b in chunks if c not in ID3_CHUNKS and not is_info_list(c, b)]
    body = b"WAVE" + b"".join(pack_chunk(c, b) for c, b in kept)
    body += build_info(tags, old_info) + pack_chunk(b"id3 ", build_id3(tags, old_id3))
    return b"RIFF" + struct.pack("<I", len(body)) + body


def read_wav(data: bytes) -> list:
    chunks = read_chunks(data)
    out = []
    id3 = next((b for c, b in chunks if c in ID3_CHUNKS and b[:3] == b"ID3"), None)
    if id3:
        out.append(("ID3", read_id3(id3)))
    info = next((parse_info(b) for c, b in chunks if is_info_list(c, b)), None)
    if info:
        out.append(("INFO", {"track": info.get("ITRK"), "title": info.get("INAM"),
                             "artist": info.get("IART"), "album": info.get("IPRD"),
                             "year": info.get("ICRD")}))
    return out


# ---------------------------------------------------------------- MP3

def split_mp3(data: bytes):
    n = id3_size(data)
    tag, audio = data[:n], data[n:]
    head = audio[:4096]
    start = len(head) - len(head.lstrip(b"\x00"))   # tolerate padding left after a tag
    if not (len(audio) > start + 1 and audio[start] == 0xFF and audio[start + 1] & 0xE0 == 0xE0):
        raise ValueError("not an MP3 file (no MPEG frame after the tag)")
    return tag, audio


def update_id3v1(old: bytes, tags: dict) -> bytes:
    """Rewrite an existing ID3v1.1 tag's fields; comment and genre are kept."""
    def field(value, width):
        return str(value or "").encode("latin-1", "replace")[:width].ljust(width, b"\x00")
    track = int(tags["track"].split("/")[0])
    return (b"TAG" + field(tags["title"], 30) + field(tags["artist"], 30)
            + field(tags["album"], 30) + field(tags["year"], 4)
            + old[97:125] + b"\x00" + bytes([min(track, 255)]) + old[127:128])


def retag_mp3(data: bytes, tags: dict) -> bytes:
    tag, audio = split_mp3(data)
    if len(audio) >= 128 and audio[-128:-125] == b"TAG":
        audio = audio[:-128] + update_id3v1(audio[-128:], tags)
    return build_id3(tags, tag) + audio


def read_mp3(data: bytes) -> list:
    tag, _ = split_mp3(data)
    return [("ID3", read_id3(tag))] if tag else []


# ---------------------------------------------------------------- FLAC

VORBIS_COMMENT = 4
FLAC_FIELDS = {"TITLE": "title", "ARTIST": "artist", "ALBUMARTIST": "artist",
               "ALBUM": "album", "DATE": "year", "GENRE": "genre"}


def flac_blocks(data: bytes):
    """-> ([(block type, body), …], audio frames)."""
    if data[:4] != b"fLaC":
        raise ValueError("not a FLAC file")
    blocks, pos = [], 4
    while True:
        if pos + 4 > len(data):
            raise ValueError("FLAC metadata is truncated")
        head, size = data[pos], int.from_bytes(data[pos + 1:pos + 4], "big")
        blocks.append((head & 0x7F, data[pos + 4:pos + 4 + size]))
        pos += 4 + size
        if head & 0x80:
            return blocks, data[pos:]


def parse_vorbis(body: bytes):
    """-> (vendor, [b"KEY=value", …]) — comments kept as raw bytes."""
    n = struct.unpack("<I", body[:4])[0]
    vendor, pos = body[4:4 + n], 4 + n
    count, pos = struct.unpack("<I", body[pos:pos + 4])[0], pos + 4
    comments = []
    for _ in range(count):
        n = struct.unpack("<I", body[pos:pos + 4])[0]
        comments.append(body[pos + 4:pos + 4 + n])
        pos += 4 + n
    return vendor, comments


def comment_key(comment: bytes) -> str:
    return comment.split(b"=", 1)[0].decode("ascii", "replace").upper()


def retag_flac(data: bytes, tags: dict) -> bytes:
    blocks, audio = flac_blocks(data)
    vendor, comments = b"audio-tag.py", []
    for kind, body in blocks:
        if kind == VORBIS_COMMENT:
            vendor, comments = parse_vorbis(body)

    number, total = tags["track"].split("/")
    ours = {key: tags[field] for key, field in FLAC_FIELDS.items() if tags.get(field)}
    ours.update(TRACKNUMBER=number, TRACKTOTAL=total)
    comments = [c for c in comments if comment_key(c) not in ours]
    comments += [f"{k}={v}".encode("utf-8") for k, v in ours.items()]
    vc = struct.pack("<I", len(vendor)) + vendor + struct.pack("<I", len(comments))
    vc += b"".join(struct.pack("<I", len(c)) + c for c in comments)

    out = [(k, b) for k, b in blocks if k != VORBIS_COMMENT]
    out.insert(1, (VORBIS_COMMENT, vc))   # right after STREAMINFO
    meta = b"".join(bytes([k | (0x80 if i == len(out) - 1 else 0)]) + len(b).to_bytes(3, "big") + b
                    for i, (k, b) in enumerate(out))
    return b"fLaC" + meta + audio


def read_flac(data: bytes) -> list:
    blocks, _ = flac_blocks(data)
    body = next((b for k, b in blocks if k == VORBIS_COMMENT), None)
    if body is None:
        return []
    c = {}
    for comment in parse_vorbis(body)[1]:
        c.setdefault(comment_key(comment), comment.split(b"=", 1)[-1].decode("utf-8", "replace"))
    track = c.get("TRACKNUMBER")
    if track and c.get("TRACKTOTAL"):
        track += "/" + c["TRACKTOTAL"]
    return [("VORBIS", {"track": track, "title": c.get("TITLE"), "artist": c.get("ARTIST"),
                        "album": c.get("ALBUM"), "year": c.get("DATE")})]


# ---------------------------------------------------------------- read / write

RETAG = {".wav": retag_wav, ".mp3": retag_mp3, ".flac": retag_flac}
READ = {".wav": read_wav, ".mp3": read_mp3, ".flac": read_flac}


def write_tags(path: Path, tags: dict) -> None:
    new = RETAG[path.suffix.lower()](path.read_bytes(), tags)
    st = path.stat()
    # Rewrite the same file (same inode) so the creation date is preserved.
    with open(path, "r+b") as f:
        f.write(new)
        f.truncate()
        f.flush()
        os.fsync(f.fileno())
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))


def read_tags(path: Path) -> list:
    return READ[path.suffix.lower()](path.read_bytes())


# ---------------------------------------------------------------- commands

def show(root: Path, albums: dict) -> None:
    for folder, tracks in albums.items():
        print(f"\n{folder.relative_to(root.parent)}")
        for p in (p for track in tracks for p in track):
            try:
                blocks = read_tags(p)
            except (ValueError, struct.error) as e:
                print(f"  {p.name}: {e}")
                continue
            if not blocks:
                print(f"  {p.name}: (no tags)")
                continue
            print(f"  {p.name}")
            for label, t in blocks:
                print(f"     {label:<6}: " + " | ".join(t.get(k) or "-" for k in
                                                     ("track", "title", "artist", "album", "year")))


def tag(root: Path, albums: dict, args) -> int:
    errors = done = files = 0
    for folder, tracks in albums.items():
        album = folder.name
        total = len(tracks)
        width = max(2, len(str(total)))
        print(f"\n[{album}]  {args.artist}  —  {total} track{'s' if total != 1 else ''}")
        for n, track in enumerate(tracks, 1):
            first = track[0]
            created = dt.datetime.fromtimestamp(min(map(creation_time, track)))
            tags = {
                "title": title_from_filename(first),
                "artist": args.artist,
                "album": album,
                "year": args.year or str(created.year),
                "track": f"{n}/{total}",
                "genre": args.genre,
            }
            side = f"[{first.parent.name}] " if first.parent != folder else ""
            formats = "+".join(p.suffix.lower().lstrip(".") for p in track)
            print(f"  {n:>{width}}. {side}{tags['title']:<40} {tags['year']}  {formats:<9}"
                  f"(created {created:%Y-%m-%d %H:%M})")
            files += len(track)
            if args.apply:
                for p in track:
                    try:
                        write_tags(p, tags)
                        done += 1
                    except (OSError, ValueError, struct.error) as e:  # keep going
                        errors += 1
                        print(f"      !! {p.name}: {e}")

    n_tracks = sum(len(t) for t in albums.values())
    print(f"\n{len(albums)} album(s), {n_tracks} track(s) in {files} file(s) found under {root}")
    if not args.apply:
        print("Preview only — nothing changed. Add --apply to write the tags.")
    else:
        print(f"Tagged {done} file(s)" + (f", {errors} error(s)." if errors else "."))
    return 1 if errors else 0


def main():
    ap = argparse.ArgumentParser(
        description="Tag WAV/MP3/FLAC: album = folder name, title = file name, "
                    "track # = creation order.")
    ap.add_argument("folder", type=Path, help="root music folder")
    ap.add_argument("--artist", help="artist name to write on every track")
    ap.add_argument("--year", help="force one year (default: each track's creation year)")
    ap.add_argument("--genre", help="optional genre for every track")
    ap.add_argument("--apply", action="store_true", help="write tags (default is a preview)")
    ap.add_argument("--show", action="store_true", help="print the tags currently in the files")
    args = ap.parse_args()

    root = args.folder.expanduser().resolve()
    if not root.is_dir():
        sys.exit(f"Not a folder: {root}")
    albums = find_albums(root)
    if not albums:
        sys.exit(f"No .wav, .mp3 or .flac files found under {root}")

    if args.show:
        show(root, albums)
    elif not args.artist:
        sys.exit('Please pass --artist "Your Name" (or --show to just read tags)')
    else:
        sys.exit(tag(root, albums, args))


if __name__ == "__main__":
    main()

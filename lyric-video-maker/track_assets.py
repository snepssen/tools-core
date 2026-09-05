"""Discover a track's companion artwork and clean its Markdown lyrics."""

import os
import re
import unicodedata


AUDIO_EXTS = (".wav", ".mp3", ".m4a", ".flac", ".aiff", ".aif", ".ogg")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff")
LYRIC_EXTS = (".md", ".txt", ".rtf")

_STOP_HEADING = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:suno\s+style(?:\s+tags?)?|negative\s+tags?)\s*:?\s*$",
    re.IGNORECASE,
)
_DIRECTIVE_LINE = re.compile(r"^\s*\[[^]]+\]\s*$")
_REMOVE_PUNCTUATION = str.maketrans("", "", ".,!?;:\"“”*()[]{}#_~`")


def canonical_stem(path):
    """Return a punctuation/case-insensitive filename stem."""
    stem = os.path.splitext(os.path.basename(path))[0]
    stem = unicodedata.normalize("NFKC", stem).casefold()
    return re.sub(r"[^\w]+", "", stem)


def find_companion(audio_path, extensions):
    """Find a sibling file whose logical stem matches the audio track."""
    wanted = canonical_stem(audio_path)
    folder = os.path.dirname(audio_path)
    try:
        names = sorted(os.listdir(folder), key=str.casefold)
    except OSError:
        return None
    for name in names:
        path = os.path.join(folder, name)
        if (os.path.isfile(path) and name.lower().endswith(extensions)
                and canonical_stem(path) == wanted):
            return path
    return None


def resolve_track_assets(audio_path):
    """Return auto-matched companion paths for one audio track."""
    return {
        "audio": audio_path,
        "cover": find_companion(audio_path, IMAGE_EXTS),
        "lyrics": find_companion(audio_path, LYRIC_EXTS),
    }


def clean_lyric_line(line):
    """Remove display-hostile punctuation without flattening contractions."""
    line = unicodedata.normalize("NFKC", line).strip()
    line = line.replace("’", "'").replace("‘", "'")
    line = re.sub(r"\[[^]]*\]", " ", line)
    line = line.replace("&", " and ").replace("/", " ")
    line = re.sub(r"[—–-]+", " ", line)
    line = line.translate(_REMOVE_PUNCTUATION)
    return " ".join(line.split())


def clean_reference_lines(lines):
    """Clean lyric lines and stop before prompt/style metadata."""
    cleaned = []
    for line in lines:
        if _STOP_HEADING.match(line):
            break
        if _DIRECTIVE_LINE.match(line):
            continue
        lyric = clean_lyric_line(line)
        if lyric:
            cleaned.append(lyric)
    return cleaned


def parse_track_lyrics(path):
    """Return one cleaned lyric track from a Suno-style Markdown file.

    The first non-empty line is treated as the title. Bracket-only generation
    directions are discarded, and parsing stops before Suno/negative tags.
    Source files are never modified.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        raw_lines = handle.read().splitlines()

    significant = [line.strip() for line in raw_lines if line.strip()]
    if not significant:
        raise ValueError(f"No lyrics found in {os.path.basename(path)}")
    title = clean_lyric_line(significant[0])
    lines = clean_reference_lines(significant[1:])
    if not lines:
        raise ValueError(f"No sung lyric lines found in {os.path.basename(path)}")
    return {"title": title, "lines": lines}


def scan_audio_tree(folder):
    """Find supported audio below a chosen folder, including subfolders."""
    found = []
    for current, directories, names in os.walk(folder):
        directories[:] = sorted(
            (name for name in directories if not name.startswith(".")),
            key=str.casefold,
        )
        for name in sorted(names, key=str.casefold):
            if not name.startswith(".") and name.lower().endswith(AUDIO_EXTS):
                found.append(os.path.join(current, name))
    return found

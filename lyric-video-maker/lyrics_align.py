"""
lyrics_align.py — correct transcribed word timings with reference lyrics.

Takes MacWhisper's timed (but sometimes misrecognised) words and the true
lyrics, aligns them word-by-word, and returns the TRUE words carrying the
TRANSCRIBED timings. Reference line breaks become the lyric lines.

Also parses simple RTF (TextEdit/Things export) and plain-text lyric
sheets where tracks are separated by a line of 3+ underscores and each
track's first line is its title.
"""

import json
import os
import re
import unicodedata
from difflib import SequenceMatcher

# ------------------------------------------------------------------ RTF → text

_RTF_DESTINATIONS = (
    "fonttbl", "colortbl", "stylesheet", "expandedcolortbl", "info",
    "themedata", "listtable", "listoverridetable", "pict", "header",
    "footer", "generator", "*",
)


def rtf_to_text(data):
    """Minimal RTF to plain text. Handles Cocoa/TextEdit RTF: groups,
    \\'xx cp1252 escapes, \\uN unicode, \\par / trailing-backslash newlines."""
    if isinstance(data, bytes):
        data = data.decode("latin-1", errors="replace")
    out = []
    i, n = 0, len(data)
    skip_depth = 0
    depth = 0
    while i < n:
        c = data[i]
        if c == "{":
            depth += 1
            # destination group we should skip entirely?
            m = re.match(r"\{\\\*?\\?([a-z]+)", data[i:i + 24])
            if skip_depth == 0 and m and m.group(1) in _RTF_DESTINATIONS:
                skip_depth = depth
            i += 1
        elif c == "}":
            if skip_depth and depth == skip_depth:
                skip_depth = 0
            depth -= 1
            i += 1
        elif c == "\\":
            nxt = data[i + 1] if i + 1 < n else ""
            if nxt == "'":
                if not skip_depth:
                    try:
                        out.append(bytes([int(data[i + 2:i + 4], 16)])
                                   .decode("cp1252", errors="replace"))
                    except ValueError:
                        pass
                i += 4
            elif nxt in ("\\", "{", "}"):
                if not skip_depth:
                    out.append(nxt)
                i += 2
            elif nxt == "\n" or nxt == "\r":
                if not skip_depth:
                    out.append("\n")
                i += 2
            elif nxt == "u":
                m = re.match(r"\\u(-?\d+)\s?", data[i:])
                if m:
                    if not skip_depth:
                        cp = int(m.group(1))
                        out.append(chr(cp + 65536 if cp < 0 else cp))
                    i += m.end()
                else:
                    i += 2
            else:
                m = re.match(r"\\([a-z]+)(-?\d+)?[ ]?", data[i:])
                if m:
                    word = m.group(1)
                    if word in ("par", "line") and not skip_depth:
                        out.append("\n")
                    elif word == "tab" and not skip_depth:
                        out.append("\t")
                    i += m.end()
                else:
                    i += 2
        elif c in "\r\n":
            i += 1
        else:
            if not skip_depth:
                out.append(c)
            i += 1
    return "".join(out)


# ------------------------------------------------------------------ lyric sheet

def _norm_title(t):
    """Normalise a track title / filename stem for matching."""
    t = unicodedata.normalize("NFKC", t).casefold()
    t = re.sub(r"^\s*\d+\s*[-._)\s]\s*", "", t)     # leading track number
    t = re.sub(r"[^\w\s]", "", t)
    return " ".join(t.split())


def parse_lyric_sheet(path):
    """Parse a lyric sheet (.rtf or plain text) into {title: [lines]}.

    Tracks are separated by a line consisting of 3+ underscores (or dashes).
    The first non-empty line of each block is the track title.
    """
    with open(path, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8", errors="replace")
    if text.lstrip().startswith("{\\rtf"):
        text = rtf_to_text(raw)

    tracks = {}
    for block in re.split(r"^\s*[_\-]{3,}\s*$", text, flags=re.M):
        lines = [ln.strip() for ln in block.splitlines()]
        lines = [ln for ln in lines if ln]
        if len(lines) < 2:
            continue
        title, body = lines[0], lines[1:]
        tracks[_norm_title(title)] = {"title": title, "lines": body}
    return tracks


def match_track(tracks, audio_path):
    """Find the lyric block for an audio file by (fuzzy) title match."""
    stem = os.path.splitext(os.path.basename(audio_path))[0]
    key = _norm_title(stem)
    if key in tracks:
        return tracks[key]
    best, best_r = None, 0.0
    for k, v in tracks.items():
        r = SequenceMatcher(None, key, k).ratio()
        if r > best_r:
            best, best_r = v, r
    return best if best_r >= 0.75 else None


# ------------------------------------------------------------------ alignment

def _norm_word(w):
    w = unicodedata.normalize("NFKC", w).casefold()
    return re.sub(r"[^\w']", "", w)


def _sim(a, b):
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def align_words(trans, ref_lines):
    """Align transcribed timed words to reference lyrics.

    trans:     [{'text','start','end'}] from the transcription
    ref_lines: list of correct lyric lines (strings)

    Returns (lines, stats) where lines = [[{'text','start','end'}, ...], ...]
    following the reference's line structure, and every word carries a
    timing derived from the transcription.
    """
    ref = []          # (word, line_index)
    for li, line in enumerate(ref_lines):
        for w in line.split():
            ref.append((w, li))

    T = [_norm_word(w["text"]) for w in trans]
    R = [_norm_word(w) for w, _ in ref]
    m, n = len(T), len(R)

    GAP = -0.45
    NEG = float("-inf")
    # DP: score[i][j] = best score aligning T[:i] with R[:j]
    score = [[NEG] * (n + 1) for _ in range(m + 1)]
    back = [[0] * (n + 1) for _ in range(m + 1)]     # 1=diag 2=up(T gap) 3=left(R gap)
    score[0][0] = 0.0
    for i in range(1, m + 1):
        score[i][0] = i * GAP
        back[i][0] = 2
    for j in range(1, n + 1):
        score[0][j] = j * GAP
        back[0][j] = 3
    for i in range(1, m + 1):
        ti = T[i - 1]
        row, prow = score[i], score[i - 1]
        brow = back[i]
        for j in range(1, n + 1):
            s = _sim(ti, R[j - 1])
            diag = prow[j - 1] + (s * 2 - 1)         # -1..+1
            up = prow[j] + GAP
            left = row[j - 1] + GAP
            if diag >= up and diag >= left:
                row[j], brow[j] = diag, 1
            elif up >= left:
                row[j], brow[j] = up, 2
            else:
                row[j], brow[j] = left, 3

    # traceback → for each ref word: matched transcription index or None
    ref_map = [None] * n
    trans_used = [False] * m
    i, j = m, n
    while i > 0 or j > 0:
        b = back[i][j]
        if b == 1:
            if _sim(T[i - 1], R[j - 1]) >= 0.5:
                ref_map[j - 1] = i - 1
                trans_used[i - 1] = True
            i, j = i - 1, j - 1
        elif b == 2:
            i -= 1
        else:
            j -= 1

    # build timed reference words; synthesize timings for unmatched runs
    words = [None] * n
    matched = sum(1 for x in ref_map if x is not None)
    for j, ti in enumerate(ref_map):
        if ti is not None:
            words[j] = {"text": ref[j][0],
                        "start": trans[ti]["start"], "end": trans[ti]["end"]}

    j = 0
    while j < n:
        if words[j] is not None:
            j += 1
            continue
        k = j
        while k < n and words[k] is None:
            k += 1
        P = k - j
        prev_end = words[j - 1]["end"] if j > 0 else None
        next_start = words[k]["start"] if k < n else None
        lo = prev_end if prev_end is not None else 0.0
        hi = next_start if next_start is not None else float("inf")

        # Misrecognised transcription words inside this window mark where the
        # vocals actually are — map the correct words onto their timings.
        cands = [trans[x] for x in range(m)
                 if not trans_used[x]
                 and trans[x]["start"] >= lo - 0.05
                 and trans[x]["end"] <= hi + 0.05]
        if cands:
            C = len(cands)
            for p, x in enumerate(range(j, k)):
                ci = round(p * (C - 1) / (P - 1)) if P > 1 else 0
                words[x] = {"text": ref[x][0],
                            "start": cands[ci]["start"],
                            "end": cands[ci]["end"]}
        else:
            # nothing detected here at all — keep words compact (0.45s each)
            # against the nearest anchor instead of smearing across the gap
            need = 0.45 * P
            if next_start is not None:
                start = max(lo, next_start - need)
            elif prev_end is not None:
                start = prev_end
            else:
                start = 0.0
            t = start
            for x in range(j, k):
                words[x] = {"text": ref[x][0], "start": round(t, 3),
                            "end": round(t + 0.45, 3)}
                t += 0.45
        j = k

    # enforce monotonic order
    for j in range(1, n):
        if words[j]["start"] < words[j - 1]["end"]:
            words[j]["start"] = words[j - 1]["end"]
            words[j]["end"] = max(words[j]["end"], words[j]["start"] + 0.05)

    # group by reference line
    lines = []
    cur_li, cur = None, []
    for j, w in enumerate(words):
        li = ref[j][1]
        if li != cur_li and cur:
            lines.append(cur)
            cur = []
        cur_li = li
        cur.append(w)
    if cur:
        lines.append(cur)

    stats = {"ref_words": n, "trans_words": m, "matched": matched,
             "synthesized": n - matched}
    return lines, stats


def corrected_json(trans_words, ref_lines):
    """Return the dict to save as <song>.corrected.json."""
    lines, stats = align_words(trans_words, ref_lines)
    return {"lines": [{"words": ln} for ln in lines]}, stats

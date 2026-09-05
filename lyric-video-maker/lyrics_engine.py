"""
lyrics_engine.py — word-timed transcript JSON -> karaoke ASS subtitles.

Display model (two line slots, lower third):
  * Active line: white text, black outline; the word currently being voiced
    is rendered in the accent colour.
  * Inactive line (the line following the active one): steel grey, shown below.
  * When a line finishes, the inactive line becomes active and the next line
    appears below it.

Accepted JSON shapes:
  1. [{"timestamp": "MM:SS.mmm-MM:SS.mmm", "text": "word"}, ...]   (MacWhisper)
     (hours variant "HH:MM:SS.mmm" also accepted)
  2. {"segments": [{"words": [{"word": w, "start": s, "end": e}]}]} (Whisper)
  3. [{"start": s, "end": e, "text": w}, ...]
"""

import json
import re

import video_formats

# ---------------------------------------------------------------- parsing

def _parse_clock(t):
    """'MM:SS.mmm' or 'HH:MM:SS.mmm' -> seconds (float)."""
    parts = t.strip().split(":")
    parts = [p.replace(",", ".") for p in parts]
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    if len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    return float(parts[0])


def load_words(json_path):
    """Return list of {'text': str, 'start': float, 'end': float}."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    words = []

    def add(text, start, end):
        text = str(text).strip()
        if not text:
            return
        start, end = float(start), float(end)
        if end < start:
            start, end = end, start
        words.append({"text": text, "start": start, "end": end})

    if isinstance(data, dict) and "segments" in data:
        for seg in data["segments"]:
            wlist = seg.get("words") or []
            if wlist:
                for w in wlist:
                    add(w.get("word", w.get("text", "")),
                        w.get("start", 0), w.get("end", 0))
            else:
                add(seg.get("text", ""), seg.get("start", 0), seg.get("end", 0))
    elif isinstance(data, list):
        for entry in data:
            if "timestamp" in entry:
                ts = str(entry["timestamp"])
                sep = "-->" if "-->" in ts else "-"
                a, b = ts.split(sep, 1)
                add(entry.get("text", entry.get("word", "")),
                    _parse_clock(a), _parse_clock(b))
            else:
                add(entry.get("text", entry.get("word", "")),
                    entry.get("start", 0), entry.get("end", 0))
    else:
        raise ValueError("Unrecognised transcript JSON structure")

    words.sort(key=lambda w: w["start"])
    return words


# ---------------------------------------------------------------- line grouping

def group_lines(words, max_chars=34, max_words=8, gap_break=1.2):
    """Group words into display lines.

    A new line starts when: the pause before a word exceeds gap_break,
    the line would exceed max_chars, or it already has max_words words.
    """
    lines, cur = [], []
    for w in words:
        if cur:
            gap = w["start"] - cur[-1]["end"]
            length = len(" ".join(x["text"] for x in cur)) + 1 + len(w["text"])
            if gap > gap_break or length > max_chars or len(cur) >= max_words:
                lines.append(cur)
                cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    return [{
        "words": ln,
        "start": ln[0]["start"],
        "end": ln[-1]["end"],
        "text": " ".join(w["text"] for w in ln),
    } for ln in lines]


def wrap_line(words, max_chars, max_words):
    """Split one lyric line into balanced display chunks that fit."""
    chunks, cur = [], []
    for w in words:
        if cur:
            length = len(" ".join(x["text"] for x in cur)) + 1 + len(w["text"])
            if length > max_chars or len(cur) >= max_words:
                chunks.append(cur)
                cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)

    # Avoid a one- or two-word orphan flashing on its own when a preceding
    # chunk has room to share.
    if len(chunks) > 1:
        tail = chunks[-1]
        previous = chunks[-2]
        while len(tail) < 3 and len(previous) > 3:
            candidate = previous[-1:] + tail
            if (len(candidate) > max_words
                    or len(" ".join(w["text"] for w in candidate)) > max_chars):
                break
            tail.insert(0, previous.pop())
    return chunks


# ---------------------------------------------------------------- ASS output

def _ass_time(s):
    s = max(0.0, s)
    cs = int(round(s * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    sec, cs = divmod(rem, 100)
    return f"{h}:{m:02}:{sec:02}.{cs:02}"


def hex_to_ass(hex_color):
    """'#RRGGBB' -> ASS '&HBBGGRR&' (no alpha)."""
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{b.upper()}{g.upper()}{r.upper()}&"


def _esc(text):
    return text.replace("{", "(").replace("}", ")").replace("\\", "/")


ASS_HEADER = """[Script Info]
Title: Lyric video subtitles
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Active,{font},{active_size},{active},{active},&H000000&,&H80000000,-1,0,0,0,100,100,0,0,1,{outline_w},2,5,60,60,0,1
Style: Inactive,{font},{inactive_size},{inactive},{inactive},&H000000&,&H80000000,-1,0,0,0,100,100,0,0,1,{outline_w_inactive},2,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Text
"""

# line-spacing modes: gap between line centres as a multiple of active size
SPACING_MODES = {"tight": 0.95, "normal": 1.25, "wide": 1.6}


def smart_size_mode(words, gap_break=1.2):
    """Pick a size mode from the track's natural phrasing: group words by
    pauses only, then look at the median phrase length in characters."""
    phrases = group_lines(words, max_chars=9999, max_words=999,
                          gap_break=gap_break)
    lens = sorted(len(p["text"]) for p in phrases)
    if not lens:
        return "default"
    median = lens[len(lens) // 2]
    if median <= 14:
        return "big"
    if median >= 30:
        return "dense"
    return "default"


def build_ass(lines, colors, font="Arial Black",
              active_size=72, inactive_size=54, gap=90, hold=0.35,
              video_width=1920, video_height=1080, inactive_y=None,
              lines_per_page=5, page_lead=0.65):
    """Build the ASS document string.

    colors: {'accent': '#RRGGBB', 'active': '#RRGGBB', 'inactive': '#RRGGBB'}
    gap: distance in px between the active and inactive line centres
    """
    if inactive_y is None:
        inactive_y = video_height - 130
    accent = hex_to_ass(colors.get("accent", "#FFD400"))
    active = hex_to_ass(colors.get("active", "#FFFFFF"))
    inactive = hex_to_ass(colors.get("inactive", "#8A99A8"))

    out = [ASS_HEADER.format(
        play_res_x=video_width, play_res_y=video_height,
        font=font, active_size=active_size, inactive_size=inactive_size,
        active=active, inactive=inactive,
        outline_w=max(3, round(active_size / 17)),
        outline_w_inactive=max(2, round(inactive_size / 17)))]

    def ev(style, start, end, y, text):
        if end - start < 0.01:
            return
        out.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},{style},,0,0,0,"
            f"{{\\an5\\pos({video_width // 2},{y})}}{text}\n")

    # Keep several lines on screen as a stable reading page. Only the colour
    # emphasis moves as the song advances; text no longer jumps after every
    # very short phrase.
    pages = [lines[i:i + lines_per_page]
             for i in range(0, len(lines), lines_per_page)]
    for page_index, page in enumerate(pages):
        previous_end = (pages[page_index - 1][-1]["end"]
                        if page_index else 0.0)
        show_from = max(previous_end, page[0]["start"] - page_lead)
        if page_index + 1 < len(pages):
            next_page = pages[page_index + 1]
            show_until = max(page[-1]["end"],
                             next_page[0]["start"] - page_lead)
        else:
            show_until = page[-1]["end"] + hold

        page_words = []
        for line_index, line in enumerate(page):
            page_words.extend((word, line_index, word_index)
                              for word_index, word in enumerate(line["words"]))

        def draw_page(start, end, active_line, highlight=None):
            first_y = inactive_y - gap * (len(page) - 1)
            for line_index, line in enumerate(page):
                is_current = line_index == active_line
                base_color = active if is_current else inactive
                parts = []
                for word_index, word in enumerate(line["words"]):
                    text = _esc(word["text"])
                    if highlight == (line_index, word_index):
                        parts.append(
                            f"{{\\c{accent}}}{text}{{\\c{base_color}}}")
                    else:
                        parts.append(text)
                ev("Active" if is_current else "Inactive", start, end,
                   first_y + line_index * gap, " ".join(parts))

        cursor = show_from
        current_line = 0
        for word, line_index, word_index in page_words:
            if word["start"] > cursor:
                draw_page(cursor, word["start"], current_line)
            word_end = max(word["end"], word["start"] + 0.05)
            draw_page(max(word["start"], cursor), word_end, line_index,
                      (line_index, word_index))
            current_line = line_index
            cursor = word_end
        if show_until > cursor:
            draw_page(cursor, show_until, current_line)

    return "".join(out)


def transcript_to_ass(json_path, ass_path, colors, font="Arial Black",
                      size_mode="default", spacing="tight", smart=False,
                      gap_break=1.2, video_format="landscape"):
    # corrected/aligned transcripts carry their own line structure
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    preset_lines = None
    if isinstance(data, dict) and "lines" in data:
        preset_lines = [ln["words"] for ln in data["lines"] if ln.get("words")]
        words = [w for ln in preset_lines for w in ln]
    else:
        words = load_words(json_path)
    if not words:
        raise ValueError("No words found in transcript JSON")

    if smart:
        if preset_lines:
            lens = sorted(len(" ".join(w["text"] for w in ln))
                          for ln in preset_lines)
            median = lens[len(lens) // 2] if lens else 24
            size_mode = ("big" if median <= 14 else
                         "dense" if median >= 30 else "default")
        else:
            size_mode = smart_size_mode(words, gap_break=gap_break)
    profile = video_formats.get_video_format(video_format)
    sizes = profile["sizes"]
    max_chars, active_size, inactive_size = sizes.get(
        size_mode, sizes["default"])
    gap = round(active_size * SPACING_MODES.get(spacing,
                                                SPACING_MODES["tight"]))

    max_words = 3 if size_mode == "big" else 8
    if preset_lines:
        lines = []
        for ln in preset_lines:
            for chunk in wrap_line(ln, max_chars, max_words):
                lines.append({"words": chunk,
                              "start": chunk[0]["start"],
                              "end": chunk[-1]["end"],
                              "text": " ".join(w["text"] for w in chunk)})
    else:
        lines = group_lines(words, max_chars=max_chars, max_words=max_words,
                            gap_break=gap_break)
    doc = build_ass(lines, colors, font=font, active_size=active_size,
                    inactive_size=inactive_size, gap=gap,
                    video_width=profile["width"],
                    video_height=profile["height"],
                    inactive_y=profile["inactive_y"])
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(doc)
    return len(words), len(lines), size_mode

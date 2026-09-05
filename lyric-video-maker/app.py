#!/usr/bin/env python3
"""
Lyric Video Maker — browser GUI + processing backend.

Pipeline per song:
  1. MacWhisper CLI (mw) -> word-timed transcript JSON  (or reuse existing .json)
  2. lyrics_engine       -> karaoke .ass subtitles (3 colours + black outline)
  3. ffmpeg              -> centre-cropped cover + audio + burned-in subtitles
                            at 1920x1080 or 1080x1920, 60fps .mp4

Run:  python3 app.py          (opens http://127.0.0.1:8765 in your browser)
Test: python3 app.py --render --audio a.wav --json t.json --cover c.jpg --out o.mp4
"""

import argparse
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lyrics_engine
import lyrics_align
import track_assets
import video_effects
import video_formats

PORT = 8765
HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULTS = {
    "accent": "#FFD400",    # word being voiced
    "active": "#FFFFFF",    # active line
    "inactive": "#8A99A8",  # next (inactive) line — steel grey
    "font": "SF Pro Display",
    "sizeMode": "default",   # big | default | dense
    "smartSize": False,      # pick size mode per track automatically
    "spacing": "tight",      # tight | normal | wide
    "lineCount": 5,          # stable lyric lines visible together
    "lyricPosition": "lower",  # lower | center
    "lineGap": 1.2,
    "visualMode": "ambient",  # still | ambient | party
    "extremeMode": False,      # explicit photosensitive/strobe opt-in
    "waveform": "bottom",     # off | bottom | side
    "bpm": 0,                 # 0 estimates tempo for Party Hard
    "mwCmd": 'mw transcribe --persist "{input}"',
    "preset": "medium",
    "format": "landscape",
}

JOBS = {}        # job_id -> state dict
JOBS_LOCK = threading.Lock()
SERVER_TOKEN = secrets.token_urlsafe(32)
MAX_REQUEST_BYTES = 1_000_000


# ---------------------------------------------------------------- ffmpeg pick
# Prefer a build that actually has the subtitles (libass) filter — slim
# Homebrew ffmpeg builds don't.

def _find_ffmpeg():
    candidates = [
        "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
        "/usr/local/opt/ffmpeg-full/bin/ffmpeg",
        "ffmpeg",
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
    ]
    for c in candidates:
        try:
            r = subprocess.run([c, "-hide_banner", "-h", "filter=subtitles"],
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and "Unknown filter" not in r.stdout \
                    and "Unknown filter" not in r.stderr:
                return c
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None


FFMPEG = _find_ffmpeg()
FFPROBE = (os.path.join(os.path.dirname(FFMPEG), "ffprobe")
           if FFMPEG and os.path.dirname(FFMPEG) else "ffprobe")
if FFPROBE != "ffprobe" and not os.path.isfile(FFPROBE):
    FFPROBE = "ffprobe"


# ------------------------------------------------------------------ helpers

def log(job, msg):
    with JOBS_LOCK:
        job["log"].append(f"[{time.strftime('%H:%M:%S')}] {msg}")


def set_state(job, **kw):
    with JOBS_LOCK:
        job.update(kw)


def audio_duration(path):
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30)
        return float(r.stdout.strip())
    except Exception:
        return None


def escape_for_subtitles_filter(path):
    """Escape a path for ffmpeg's subtitles= filter option value."""
    p = path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    return p.replace("[", "\\[").replace("]", "\\]").replace(",", "\\,")


# ------------------------------------------------------------------ pipeline

def run_mw(job, item, mw_cmd_template):
    """Run MacWhisper CLI, capture stdout to <audio>.words.json."""
    audio = item["audio"]
    out_json = os.path.splitext(audio)[0] + ".words.json"
    cmd_str = mw_cmd_template.replace("{input}", audio)
    cmd = shlex.split(cmd_str)
    log(job, f"Transcribing with MacWhisper: {cmd_str}")
    set_state(job, stage="transcribing")

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
    except FileNotFoundError:
        raise RuntimeError(
            f"'{cmd[0]}' not found. Install the CLI from MacWhisper → "
            "Settings → Advanced → Command-Line Tool, or fix the command "
            "template in Settings.")

    # mw prints "Transcribing: NN%" on stderr
    def watch_stderr():
        for line in proc.stderr:
            m = re.search(r"(\d{1,3})\s*%", line)
            if m:
                set_state(job, progress=int(m.group(1)) * 0.35 / 100)
    t = threading.Thread(target=watch_stderr, daemon=True)
    t.start()

    stdout, stderr = proc.communicate()
    t.join(timeout=2)
    if proc.returncode != 0:
        tail = (stderr or "").strip().splitlines()
        tail = " / ".join(tail[-3:]) if tail else ""
        raise RuntimeError(f"mw exited with code {proc.returncode}"
                           + (f" — {tail}" if tail else ""))

    stdout = stdout.strip()
    # If the command was customised to emit JSON directly, accept it.
    try:
        json.loads(stdout)
        with open(out_json, "w", encoding="utf-8") as f:
            f.write(stdout)
        log(job, f"Transcript saved: {os.path.basename(out_json)}")
        return out_json
    except (json.JSONDecodeError, ValueError):
        pass

    # Standard path: mw printed plain text; --persist stored the session in
    # MacWhisper's database, which holds per-word timings. Read them there.
    log(job, "Reading word timings from MacWhisper's database…")
    words = words_from_macwhisper_db(audio)
    if not words:
        raise RuntimeError(
            "Transcription finished but no word timings were found in "
            "MacWhisper's database. Make sure the command template includes "
            "--persist, and that your selected model supports word "
            "timestamps (Whisper models do).")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(words, f, ensure_ascii=False)
    log(job, f"Transcript saved: {os.path.basename(out_json)} "
             f"({len(words)} words)")
    return out_json


MW_DB = os.path.expanduser(
    "~/Library/Application Support/MacWhisper/Database/main.sqlite")


def words_from_macwhisper_db(audio, db_path=MW_DB):
    """Fetch per-word timings for the newest MacWhisper session matching
    this audio file. Returns [{'text', 'start', 'end'}] in seconds."""
    import sqlite3
    base = os.path.basename(audio)
    stem, ext = os.path.splitext(base)
    ext = ext.lstrip(".")

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    try:
        row = con.execute(
            "SELECT id FROM session WHERE originalFilename = ? "
            "AND (originalExtension = ? OR originalExtension IS NULL) "
            "AND dateDeleted IS NULL "
            "ORDER BY dateCreated DESC LIMIT 1", (stem, ext)).fetchone()
        if not row:  # fall back: match on filename only
            row = con.execute(
                "SELECT id FROM session WHERE originalFilename = ? "
                "AND dateDeleted IS NULL "
                "ORDER BY dateCreated DESC LIMIT 1", (stem,)).fetchone()
        if not row:
            return []
        lines = con.execute(
            'SELECT start, "end", text, wordsJson FROM transcriptline '
            "WHERE sessionId = ? "
            "ORDER BY COALESCE(orderIndex, start), start", (row[0],)).fetchall()
    finally:
        con.close()

    words = []
    for start_ms, end_ms, text, words_json in lines:
        parsed = None
        if words_json:
            try:
                parsed = json.loads(words_json)
            except (json.JSONDecodeError, ValueError):
                parsed = None
        if parsed:
            for w in parsed:
                t = str(w.get("text", "")).strip()
                if t:
                    words.append({"text": t,
                                  "start": w["startTime"] / 1000.0,
                                  "end": w["endTime"] / 1000.0})
        elif text and text.strip():
            # no word timings for this line — keep it as one block
            words.append({"text": text.strip(),
                          "start": (start_ms or 0) / 1000.0,
                          "end": (end_ms or 0) / 1000.0})
    return words


def find_existing_json(audio):
    base = os.path.splitext(audio)[0]
    for cand in (base + ".words.json", base + ".json"):
        if os.path.isfile(cand):
            return cand
    return None


def prepare_cover(cover, out_dir, format_name):
    """Centre-crop cover art once, at the selected output dimensions."""
    profile = video_formats.get_video_format(format_name)
    width, height = profile["width"], profile["height"]
    scaled = os.path.join(
        out_dir, f"._cover_{width}x{height}_{uuid.uuid4().hex[:8]}.png")
    r = subprocess.run(
        [FFMPEG, "-y", "-i", cover,
         "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},setsar=1",
         "-frames:v", "1", scaled],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("Cover art preparation failed: " + r.stderr[-400:])
    return scaled


def render_video(job, audio, cover, ass_path, out_path, preset="medium",
                 format_name="landscape", settings=None):
    if not FFMPEG:
        raise RuntimeError(
            "No ffmpeg with subtitle support found. Run: "
            "brew install ffmpeg-full")
    dur = audio_duration(audio)
    prepared_cover = prepare_cover(cover, os.path.dirname(out_path), format_name)
    sub = escape_for_subtitles_filter(ass_path)
    settings = settings or DEFAULTS
    bpm = None
    if settings.get("visualMode") == "party":
        if settings.get("extremeMode"):
            log(job, "WARNING: Extreme strobe enabled — output requires a "
                     "photosensitivity warning")
        try:
            manual_bpm = float(settings.get("bpm") or 0)
        except (TypeError, ValueError):
            manual_bpm = 0
        if manual_bpm > 0:
            bpm = max(40.0, min(manual_bpm, 240.0))
            log(job, f"Party Hard tempo: {bpm:g} BPM (manual)")
        else:
            estimated = video_effects.estimate_bpm(audio, FFMPEG)
            bpm = estimated or 120.0
            log(job, f"Party Hard tempo: {bpm:g} BPM "
                     f"({'estimated' if estimated else 'fallback'})")
    profile = video_formats.get_video_format(format_name)
    filters, audio_map = video_effects.build_filter_graph(
        profile, sub, settings, bpm=bpm)
    cmd = [FFMPEG, "-y", "-loop", "1", "-framerate", "60", "-i", prepared_cover,
           "-i", audio,
           "-filter_complex", filters,
           "-map", "[video]", "-map", audio_map,
           "-c:v", "libx264", "-preset", preset, "-crf", "18",
           "-pix_fmt", "yuv420p", "-r", "60",
           "-c:a", "aac", "-b:a", "320k",
           "-shortest", "-movflags", "+faststart",
           "-progress", "pipe:1", "-nostats", "-loglevel", "error",
           out_path]
    log(job, "Rendering video with ffmpeg…")
    set_state(job, stage="rendering")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    err_lines = []

    def watch_err():
        for line in proc.stderr:
            err_lines.append(line)
    threading.Thread(target=watch_err, daemon=True).start()

    for line in proc.stdout:
        if line.startswith("out_time_ms=") and dur:
            try:
                done = int(line.split("=")[1]) / 1_000_000 / dur
                set_state(job, progress=0.40 + min(done, 1.0) * 0.60)
            except ValueError:
                pass
    proc.wait()
    try:
        os.remove(prepared_cover)
    except OSError:
        pass
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + "".join(err_lines)[-800:])


def process_item(job, item, settings):
    audio = item["audio"]
    companions = track_assets.resolve_track_assets(audio)
    cover = settings.get("cover") or companions["cover"]
    if not cover:
        raise RuntimeError(
            "No companion artwork found. Add a PNG/JPG with the same track "
            "name or choose fallback cover art.")
    name = os.path.splitext(os.path.basename(audio))[0]
    out_dir = settings.get("outputDir") or os.path.dirname(audio)
    format_name = settings.get("format", DEFAULTS["format"])
    profile = video_formats.get_video_format(format_name)
    out_path = os.path.join(out_dir, video_formats.output_name(audio, format_name))

    set_state(job, current=os.path.basename(audio), progress=0.0)

    # 1. transcript — reuse a .json next to the audio, then a previous
    # MacWhisper session from the database, then transcribe fresh
    tjson = None
    if settings.get("reuseJson", True):
        existing = find_existing_json(audio)
        if existing:
            log(job, f"Using existing transcript: {os.path.basename(existing)}")
            tjson = existing
        else:
            try:
                words = words_from_macwhisper_db(audio)
            except Exception:
                words = []
            if words:
                tjson = os.path.splitext(audio)[0] + ".words.json"
                with open(tjson, "w", encoding="utf-8") as f:
                    json.dump(words, f, ensure_ascii=False)
                log(job, f"Reusing earlier MacWhisper transcription "
                         f"({len(words)} words from history)")
    if not tjson:
        tjson = run_mw(job, item, settings.get("mwCmd", DEFAULTS["mwCmd"]))
    set_state(job, progress=0.35)

    # 1b. correct the words against the reference lyric sheet, if provided
    track = None
    auto_lyrics = False
    tracks = settings.get("_lyricTracks")
    if tracks:
        track = lyrics_align.match_track(tracks, audio)
    if not track and companions["lyrics"]:
        track = track_assets.parse_track_lyrics(companions["lyrics"])
        auto_lyrics = True

    if track:
        clean_lines = track_assets.clean_reference_lines(track["lines"])
        trans_words = lyrics_engine.load_words(tjson)
        data, st = lyrics_align.corrected_json(trans_words, clean_lines)
        tjson = os.path.splitext(audio)[0] + ".corrected.json"
        with open(tjson, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        source = (os.path.basename(companions["lyrics"])
                  if auto_lyrics else track["title"])
        log(job, f"Cleaned and aligned lyrics from '{source}': "
                 f"{st['matched']}/{st['ref_words']} words matched, "
                 f"{st['synthesized']} re-timed")
    elif tracks:
        log(job, "WARNING: no matching track title in the lyric sheet — "
                 "using raw transcription")
    else:
        log(job, "WARNING: no companion lyric file found — using raw "
                 "transcription")

    if not settings.get("cover"):
        log(job, f"Using companion artwork: {os.path.basename(cover)}")

    # 2. subtitles
    set_state(job, stage="styling")
    ass_path = os.path.join(out_dir, name + profile["suffix"] + ".ass")
    nwords, nlines, used_mode = lyrics_engine.transcript_to_ass(
        tjson, ass_path,
        colors={"accent": settings["accent"], "active": settings["active"],
                "inactive": settings["inactive"]},
        font=settings.get("font", DEFAULTS["font"]),
        size_mode=settings.get("sizeMode", DEFAULTS["sizeMode"]),
        spacing=settings.get("spacing", DEFAULTS["spacing"]),
        smart=bool(settings.get("smartSize", False)),
        gap_break=float(settings.get("lineGap", DEFAULTS["lineGap"])),
        line_count=int(settings.get("lineCount", DEFAULTS["lineCount"])),
        lyric_position=settings.get("lyricPosition", DEFAULTS["lyricPosition"]),
        video_format=format_name)
    smart_note = " (Smart)" if settings.get("smartSize") else ""
    log(job, f"Styled {nwords} words into {nlines} lyric lines "
             f"— {used_mode} size{smart_note} · "
             f"{settings.get('lineCount', DEFAULTS['lineCount'])} lines · "
             f"{settings.get('lyricPosition', DEFAULTS['lyricPosition'])} · "
             f"{profile['width']}x{profile['height']}")
    set_state(job, progress=0.40)

    # 3. video
    render_video(job, audio, cover, ass_path, out_path,
                 preset=settings.get("preset", "medium"),
                 format_name=format_name, settings=settings)
    log(job, f"Done: {out_path}")
    return out_path


def worker(job, settings):
    results, errors = [], []
    lyr = settings.get("lyricsFile")
    if lyr:
        try:
            settings["_lyricTracks"] = lyrics_align.parse_lyric_sheet(lyr)
            log(job, f"Lyric sheet loaded: "
                     f"{len(settings['_lyricTracks'])} tracks")
        except Exception as e:
            log(job, f"WARNING: could not read lyric sheet: {e}")
    items = job["items"]
    for i, item in enumerate(items):
        set_state(job, itemIndex=i)
        try:
            results.append(process_item(job, item, settings))
        except Exception as e:
            log(job, f"ERROR ({os.path.basename(item['audio'])}): {e}")
            errors.append(str(e))
    set_state(job, stage="finished", progress=1.0,
              results=results, errors=errors,
              status="done" if not errors else
                     ("failed" if not results else "partial"))


# ------------------------------------------------------------------ mac file pickers

def osascript(script):
    r = subprocess.run(["osascript", "-e", script],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        return None
    return r.stdout.strip()


def scan_audio_folder(folder):
    """All supported audio files below a chosen folder."""
    return track_assets.scan_audio_tree(folder)


def pick(kind):
    if kind == "audio":
        s = 'POSIX path of (choose file with prompt "Choose audio file" of type {"wav","mp3","m4a","flac","aiff","public.audio"})'
        out = osascript(s)
        return [out] if out else []
    if kind == "audioFolder":
        s = 'POSIX path of (choose folder with prompt "Choose a folder of audio files")'
        out = osascript(s)
        return scan_audio_folder(out) if out else []
    if kind == "image":
        s = 'POSIX path of (choose file with prompt "Choose cover art" of type {"public.image"})'
        out = osascript(s)
        return [out] if out else []
    if kind == "lyrics":
        s = 'POSIX path of (choose file with prompt "Choose lyric sheet (.rtf or .txt)" of type {"rtf","txt","md","public.text"})'
        out = osascript(s)
        return [out] if out else []
    if kind == "folder":
        s = 'POSIX path of (choose folder with prompt "Choose output folder")'
        out = osascript(s)
        return [out] if out else []
    return []


# ------------------------------------------------------------------ HTTP server

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):  # silence request logging
        pass

    def _authorised(self):
        supplied = self.headers.get("X-Tools-Core-Token", "")
        if not supplied:
            supplied = parse_qs(urlparse(self.path).query).get("token", [""])[0]
        return secrets.compare_digest(supplied, SERVER_TOKEN)

    def _require_auth(self):
        if self._authorised():
            return True
        self._send(403, {"error": "This request did not come from the active local app."})
        return False

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            if not self._require_auth():
                return
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        elif parsed.path.startswith("/api/"):
            if not self._require_auth():
                return
            if parsed.path.startswith("/api/status/"):
                jid = parsed.path.rsplit("/", 1)[1]
                with JOBS_LOCK:
                    job = JOBS.get(jid)
                    self._send(200, dict(job) if job else {"error": "unknown job"})
            elif parsed.path == "/api/defaults":
                self._send(200, {**DEFAULTS,
                                 "formats": video_formats.VIDEO_FORMATS})
            else:
                self._send(404, {"error": "not found"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._require_auth():
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._send(400, {"error": "invalid Content-Length"})
            return
        if n < 0 or n > MAX_REQUEST_BYTES:
            self._send(413, {"error": "request body is too large"})
            return
        try:
            payload = json.loads(self.rfile.read(n) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send(400, {"error": "request body must be valid JSON"})
            return

        if self.path == "/api/pick":
            try:
                self._send(200, {"paths": pick(payload.get("kind", "audio"))})
            except Exception as e:
                self._send(200, {"paths": [], "error": str(e)})

        elif self.path == "/api/assets":
            files = payload.get("files") or []
            self._send(200, {
                "items": [track_assets.resolve_track_assets(path)
                          for path in files]
            })

        elif self.path == "/api/start":
            files = payload.get("files") or []
            cover = payload.get("cover")
            if not files:
                self._send(400, {"error": "at least one audio file is required"})
                return
            format_name = payload.get("format", DEFAULTS["format"])
            try:
                video_formats.get_video_format(format_name)
            except ValueError as exc:
                self._send(400, {"error": str(exc)})
                return
            jid = uuid.uuid4().hex[:8]
            job = {"id": jid, "status": "running", "stage": "queued",
                   "progress": 0.0, "current": "", "itemIndex": 0,
                   "items": [{"audio": f} for f in files],
                   "log": [], "results": [], "errors": []}
            with JOBS_LOCK:
                JOBS[jid] = job
            settings = {k: payload.get(k, DEFAULTS.get(k)) for k in
                        ("accent", "active", "inactive", "font", "sizeMode",
                         "smartSize", "spacing", "lineCount", "lyricPosition",
                         "lineGap", "visualMode", "extremeMode", "waveform",
                         "bpm", "mwCmd",
                         "reuseJson", "outputDir", "lyricsFile", "format")}
            settings["cover"] = cover
            threading.Thread(target=worker, args=(job, settings),
                             daemon=True).start()
            self._send(200, {"jobId": jid})

        elif self.path == "/api/reveal":
            p = payload.get("path", "")
            if os.path.exists(p):
                subprocess.run(["open", "-R", p])
            self._send(200, {"ok": True})
        else:
            self._send(404, {"error": "not found"})


def serve():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/?token={SERVER_TOKEN}"
    print(f"Lyric Video Maker running on http://127.0.0.1:{PORT}  (Ctrl+C to quit)")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nBye")


# ------------------------------------------------------------------ CLI render (testing / headless)

def cli_render(args):
    job = {"id": "cli", "status": "running", "stage": "queued",
           "progress": 0.0, "current": "", "itemIndex": 0,
           "items": [{"audio": args.audio}], "log": [],
           "results": [], "errors": []}
    settings = dict(DEFAULTS)
    settings.update({"cover": args.cover, "reuseJson": True,
                     "outputDir": os.path.dirname(os.path.abspath(args.out)),
                     "format": args.format, "lineCount": args.lines,
                     "lyricPosition": args.lyric_position,
                     "visualMode": args.visual, "waveform": args.waveform,
                     "extremeMode": args.extreme, "bpm": args.bpm})
    if args.accent:
        settings["accent"] = args.accent
    if args.preset:
        settings["preset"] = args.preset
    if args.json:
        base = os.path.splitext(args.audio)[0] + ".json"
        if os.path.abspath(args.json) != os.path.abspath(base):
            import shutil
            shutil.copy(args.json, base)
    out = process_item(job, job["items"][0], settings)
    src = os.path.join(os.path.dirname(os.path.abspath(args.out)),
                       video_formats.output_name(args.audio, args.format))
    if os.path.abspath(src) != os.path.abspath(args.out):
        os.replace(src, args.out)
    for l in job["log"]:
        print(l)
    print("Rendered:", args.out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--render", action="store_true", help="headless render")
    ap.add_argument("--audio")
    ap.add_argument("--json")
    ap.add_argument("--cover")
    ap.add_argument("--out")
    ap.add_argument("--accent")
    ap.add_argument("--preset")
    ap.add_argument("--format", choices=tuple(video_formats.VIDEO_FORMATS),
                    default=DEFAULTS["format"])
    ap.add_argument("--lines", type=int, choices=range(1, 6),
                    default=DEFAULTS["lineCount"])
    ap.add_argument("--lyric-position", choices=("lower", "center"),
                    default=DEFAULTS["lyricPosition"])
    ap.add_argument("--visual", choices=video_effects.VISUAL_MODES,
                    default=DEFAULTS["visualMode"])
    ap.add_argument("--waveform", choices=video_effects.WAVEFORM_MODES,
                    default=DEFAULTS["waveform"])
    ap.add_argument("--extreme", action="store_true",
                    help="enable rapid flashing and audio-reactive shaders")
    ap.add_argument("--bpm", type=float, default=DEFAULTS["bpm"],
                    help="Party Hard tempo; 0 estimates it from the audio")
    a = ap.parse_args()
    if a.render:
        missing = [name for name in ("audio", "out")
                   if not getattr(a, name)]
        if missing:
            ap.error("--render requires " + ", ".join("--" + name for name in missing))
        cli_render(a)
    else:
        serve()

"""FFmpeg visual-treatment filters and lightweight tempo estimation."""

from __future__ import annotations

import math
import struct
import subprocess


VISUAL_MODES = ("still", "ambient", "party")
WAVEFORM_MODES = ("off", "bottom", "side")


def _hex(value, fallback="FFD400"):
    text = str(value or "").strip().lstrip("#")
    if len(text) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in text):
        return text.upper()
    return fallback


def _edge_glow(accent, strength=1.0):
    """Approximate a short edge falloff with concentric translucent strokes."""
    colour = _hex(accent)
    layers = ((0, 10, .11), (10, 10, .085), (20, 10, .063),
              (30, 10, .044), (40, 10, .028), (50, 10, .014))
    return ",".join(
        "drawbox="
        f"x={inset}:y={inset}:w=iw-{inset * 2}:h=ih-{inset * 2}:"
        f"color=0x{colour}@{alpha * strength:.3f}:t={thickness}"
        for inset, thickness, alpha in layers
    )


def build_filter_graph(profile, subtitle_path, settings, bpm=None):
    """Return ``(filter_complex, audio_map)`` for one complete render.

    ``subtitle_path`` must already be escaped for FFmpeg's subtitles filter.
    ``audio_map`` is either an output label or the original input stream.
    """
    width, height = int(profile["width"]), int(profile["height"])
    mode = settings.get("visualMode", "ambient")
    waveform = settings.get("waveform", "bottom")
    if mode not in VISUAL_MODES:
        mode = "ambient"
    if waveform not in WAVEFORM_MODES:
        waveform = "bottom"

    video = ["fps=60"]
    if mode == "ambient":
        video.extend([
            "zoompan="
            "z='1.035+0.006*sin(on/55)':"
            "x='iw/2-(iw/zoom/2)+sin(on/49)*5':"
            "y='ih/2-(ih/zoom/2)+cos(on/61)*5':"
            f"d=1:s={width}x{height}:fps=60",
            "eq=brightness='0.010*sin(2*PI*t/4.2)':saturation=1.05:eval=frame",
            _edge_glow(settings.get("accent"), .68),
        ])
    elif mode == "party":
        tempo = max(40.0, min(float(bpm or 120.0), 240.0))
        video.extend([
            "zoompan="
            "z='1.055+0.018*sin(on/16)':"
            "x='iw/2-(iw/zoom/2)+sin(on/13)*10':"
            "y='ih/2-(ih/zoom/2)+cos(on/17)*10':"
            f"d=1:s={width}x{height}:fps=60",
            f"hue=h='mod(floor(t*{tempo:.3f}/60)*57,360)':s=1.34",
            _edge_glow(settings.get("accent"), 1.28),
        ])

    graph = [f"[0:v]{','.join(video)}[base]"]
    visual_input = "base"
    audio_map = "1:a:0"
    if waveform != "off":
        colour = _hex(settings.get("accent"))
        graph.append("[1:a]asplit=2[audioout][wavesource]")
        audio_map = "[audioout]"
        if waveform == "bottom":
            wave_height = max(72, round(height * .085))
            margin = max(28, round(height * .035))
            graph.append(
                f"[wavesource]showfreqs=s={width}x{wave_height}:mode=bar:"
                f"r=30:colors=0x{colour}@0.62:ascale=sqrt:fscale=log:"
                "averaging=4,format=rgba,"
                "colorkey=0x000000:0.12:0.08[wave]")
            graph.append(
                f"[base][wave]overlay=0:H-h-{margin}:format=auto[decorated]")
        else:
            wave_width = max(78, round(width * .07))
            margin = max(24, round(width * .025))
            graph.append(
                f"[wavesource]showfreqs=s={height}x{wave_width}:mode=bar:"
                f"r=30:colors=0x{colour}@0.60:ascale=sqrt:fscale=log:"
                "averaging=4,format=rgba,"
                "colorkey=0x000000:0.12:0.08,transpose=1[wave]")
            graph.append(
                f"[base][wave]overlay=W-w-{margin}:0:format=auto[decorated]")
        visual_input = "decorated"

    graph.append(f"[{visual_input}]subtitles='{subtitle_path}'[video]")
    return ";".join(graph), audio_map


def estimate_bpm_from_samples(samples, sample_rate=400.0, minimum=60, maximum=180):
    """Estimate tempo from mono PCM samples using energy-onset autocorrelation."""
    if not samples or sample_rate <= 0:
        return None
    hop = max(1, round(sample_rate / 40.0))
    envelope = []
    for start in range(0, len(samples) - hop + 1, hop):
        frame = samples[start:start + hop]
        envelope.append(math.sqrt(sum(value * value for value in frame) / hop))
    if len(envelope) < 80:
        return None

    novelty = []
    for index, value in enumerate(envelope):
        history = envelope[max(0, index - 8):index]
        baseline = sum(history) / len(history) if history else value
        novelty.append(max(0.0, value - baseline))
    peak = max(novelty, default=0.0)
    if peak <= 1e-8:
        return None
    novelty = [value / peak for value in novelty]
    frame_rate = sample_rate / hop

    candidates = []
    seen_lags = set()
    for bpm in range(int(minimum), int(maximum) + 1):
        lag = max(1, round(frame_rate * 60.0 / bpm))
        if lag in seen_lags:
            continue
        seen_lags.add(lag)
        score = sum(novelty[i] * novelty[i - lag]
                    for i in range(lag, len(novelty)))
        score /= max(1, len(novelty) - lag)
        candidates.append((score, lag))
    score, lag = max(candidates)
    return round(frame_rate * 60.0 / lag, 1) if score > 1e-5 else None


def estimate_bpm(audio_path, ffmpeg, seconds=90):
    """Decode a small mono stream with FFmpeg and return an approximate BPM."""
    cmd = [ffmpeg, "-v", "error", "-t", str(seconds), "-i", audio_path,
           "-ac", "1", "-ar", "400", "-f", "f32le", "pipe:1"]
    result = subprocess.run(cmd, capture_output=True, timeout=seconds + 30)
    if result.returncode or len(result.stdout) < 4:
        return None
    count = len(result.stdout) // 4
    samples = [value[0] for value in struct.iter_unpack(
        "<f", result.stdout[:count * 4])]
    return estimate_bpm_from_samples(samples, 400.0)

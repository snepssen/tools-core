# Lyric Video Maker

Turn an audio track, cover image, and word timings into a karaoke video with
burned-in lyrics. Choose landscape (1920x1080) for desktop/YouTube or portrait
(1080x1920) for Shorts and Reels.

## Requirements

- macOS and Python 3 for the browser UI and native file pickers
- ffmpeg built with the `subtitles`/libass filter (`brew install ffmpeg-full`)
- MacWhisper Pro's `mw` CLI for automatic transcription, or an existing timed
  JSON file beside each audio track

The alignment and ASS-generation modules themselves use only Python's standard
library.

## Start

Double-click `Start Lyric Video Maker.command`, or run:

```sh
python3 lyric-video-maker/app.py
```

The app opens a token-protected page on `127.0.0.1`. The token changes every
run; use the page opened by the app rather than typing the bare address.

Select a single file or a folder. Matching artwork and lyrics are selected
automatically, so their rows turn green when the track is ready; those controls
remain available only when you want an override. Choose an output folder if
needed, set the format and lyric treatment, then create the video. A batch
searches the chosen folder recursively and processes supported audio files
sequentially.

For each audio track, the app automatically finds sibling artwork and lyrics
with the same logical filename. Punctuation and case do not need to match, so
`A04 Red Aura.wav` pairs with `A04 - Red Aura.png` and
`A04 - Red Aura.md`. A manually selected cover or lyric sheet is used as a
fallback/override.

Suno-style Markdown is cleaned for display without modifying the source file:
the title, bracketed arrangement directions, Suno style tags, negative tags,
Markdown decoration, and display-hostile punctuation are omitted. MacWhisper
still supplies the word timing. Lyrics render in stable reading pages so fast
phrases remain visible while the current word is highlighted. The UI controls
whether each page contains one to five lines, places it in the lower third or
centre, and previews the selected font, character capacity, spacing, and
colours. The character-capacity slider shows the actual wrapping limit for the
selected landscape or portrait format rather than an abstract size name.
Portrait renders use a conservative mobile-safe lyric position and add
`-short` to the filename so they can sit beside the landscape render.

## Motion and light

- **Still** leaves the artwork clean and motionless.
- **Ambient** adds slow cover drift and a shallow, fully fading edge glow.
- **Party Hard** adds stronger movement and jumps the colour treatment once per
  beat. Leave BPM empty to estimate it from the audio, or enter 40–240 BPM for
  deterministic timing.

Party Hard also exposes an **Extreme strobe** switch. This deliberately adds
rapid full-frame flashes, RGB channel separation, spectrum trails, faster
colour jumps, and a scrolling audio-reactive wash across the artwork. It is
off by default and carries an in-app photosensitivity warning because the
result can trigger seizures. Any published output using it should include a
prominent photosensitivity warning.

The audio equaliser can be disabled or placed along the bottom or right edge.
Its frequency bars are drawn from the real audio stream and remain behind the
burned-in lyrics.

## Correct lyrics

An optional `.rtf`, `.txt`, or `.md` sheet can replace transcription mistakes
while retaining word timing. Separate tracks with a line of three or more
underscores or hyphens; put the track title first and its lyrics below it.
Titles are matched to filenames after normalizing punctuation, case, and a
leading track number.

Timed JSON is searched beside the audio as `<song>.words.json` and then
`<song>.json`. Accepted formats are documented in `lyrics_engine.py`.

## Headless render

```sh
python3 lyric-video-maker/app.py --render \
  --audio song.wav --json song.words.json \
  --format portrait --lines 3 --lyric-position center \
  --visual ambient --waveform bottom --out song-short.mp4
```

Omit `--format portrait` (or pass `--format landscape`) for a 1920x1080 video.
If no matching image sits beside the audio, pass `--cover cover.jpg`.
For Party Hard, pass `--visual party`; optionally add `--bpm 128`. Add
`--extreme` only for the explicitly warned high-intensity treatment.

Convert the simple MacWhisper word-list form to SRT with:

```sh
python3 lyric-video-maker/json_to_srt.py transcript.json output.srt
```

Generated corrected JSON, ASS subtitles, and video files are intentionally
ignored by Git.

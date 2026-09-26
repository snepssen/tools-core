# Caption Check

Find subtitle cues that need attention, with the times and reasons.

```sh
python3 caption-check/caption-check.py subtitles.srt
python3 caption-check/caption-check.py subtitles.vtt --duration 120
python3 caption-check/caption-check.py subtitles.ass --json
python3 caption-check/caption-check.py subtitles.srt --max-cps 17 --max-line-length 38
```

Reads SRT, WebVTT and ASS/SSA. Reports reading speed, long lines, too many
lines, short or long displays, conflicting overlaps, empty cues, backwards
timings, unparsed cue records and missing fonts. With `--duration SECONDS`,
also reports cues beyond the programme's end. ASS cues in different rendering
positions are treated separately; successive karaoke cues showing the same
text in the same place are measured as a single reading.

The defaults are **20 characters/second, 42 characters/line, 2 lines, and
1–7 seconds per display**. These are configurable starting points, not a
delivery standard. `--max-cps`, `--max-line-length`, `--max-lines`,
`--min-duration` and `--max-duration` set them explicitly. JSON includes the
thresholds used and is always a list, even for one file.

Exit status: **0** means no findings under the selected thresholds; **1**
means findings; **2** means an input or option could not be checked. Other
files are still checked when one input fails.

Python 3.8+, standard library. No FFmpeg needed for these file checks.
Font availability uses `fc-list` when installed and otherwise says it was
not checked. Files are only read; no rewriting, uploading or caching.
This does not check wording, translation, actual audio alignment or rendered
layout. It is not a complete subtitle grammar validator.

## Source and maintenance

The reader and measurements are copied unchanged from
[Media Preflight](https://snepssen.github.io/media-preflight/).
`engine/MANIFEST.json` records the upstream version, commit and file hashes.
The standalone command supplies thresholds and reporting. Fix engine code
in Media Preflight, then copy it across:

```sh
python3 scripts/from-projects.py --project media-preflight --from ../media-preflight
python3 scripts/from-projects.py --check --only caption-check
```

Verified with generated SRT, VTT and ASS fixtures on macOS. Windows and Linux
have not been exercised for this standalone command.

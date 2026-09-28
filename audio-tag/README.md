# Audio Tag

Give untagged WAV, MP3 and FLAC files — Suno exports, DAW bounces — a title,
artist, album, year and track number, worked out from how the folder is
organised. Without tags, most players and upload pages show them as
"Unknown track – Unknown artist".

```sh
python3 audio-tag/audio-tag.py ~/Music --artist "Your Name"           # preview
python3 audio-tag/audio-tag.py ~/Music --artist "Your Name" --apply   # write
python3 audio-tag/audio-tag.py ~/Music --show                         # read back
```

Without `--apply` nothing is written: the preview lists every album and
track exactly as it would be tagged.

## How the folder becomes tags

Every folder that directly contains `.wav`, `.mp3` or `.flac` files is an
album, named after the folder. Folders called `A`, `B`, `Side A`, `Disc 2`,
`CD1` or `Bonus` are treated as sides of the album above them: their tracks
are merged into it and numbering continues across sides, with Bonus last.

```
Music/
  Night Drive EP/           album "Night Drive EP"
    Neon.wav                "Neon", track 1
    Neon.mp3                the same track in another format: also track 1
    City Lights (1).flac    "City Lights", track 2
  Long Player/              album "Long Player", tracks 1…n across A, B, Bonus
    A/  B/  Bonus/
  Colours/A/A01 Red.wav     album "Colours", "Red", ordered by A01
  Series/Part II/           album "Part II"
```

| Tag | Comes from |
| --- | --- |
| Artist, Album artist | `--artist` |
| Album | The folder name (the parent's, for side folders) |
| Title | The file name, with `_` turned into spaces and `(1)`, `- Copy` and leading `A01 ` / `01 - ` numbers removed |
| Track | `n/total`. If every file in a folder starts with a number (`A01 `, `01 - `), that order is used; otherwise creation date, oldest first. Files with the same name in different formats share one number |
| Year | The track's creation year, or `--year 2026` for all |
| Genre | `--genre`, optional |

Creation date is the file's birth time on macOS. Other systems don't record
it reliably, so there the modification time is used instead. A file
downloaded later than it was made will sort by its download time: check the
preview.

## What is written

| Format | Tags |
| --- | --- |
| WAV | An ID3v2.3 `id3 ` chunk (Apple Music, VLC, ffprobe, most upload pages) and a RIFF `LIST/INFO` chunk (Windows Explorer, DAWs), because players disagree about which to read |
| MP3 | The ID3v2 tag at the start of the file, keeping its version (2.3 or 2.4). An ID3v1 tag at the end, if present, is updated to match |
| FLAC | The Vorbis comment block (`TITLE`, `ARTIST`, `ALBUMARTIST`, `ALBUM`, `DATE`, `TRACKNUMBER`, `TRACKTOTAL`, `GENRE`) |

Only those fields are replaced. Anything else already in a tag — lyrics,
comments, composer, embedded pictures — is kept as it was, and no pictures
are added. The audio is kept byte for byte.

**Files are rewritten in place** — the same file, not a copy — so the
creation date is kept and a later run numbers tracks the same way. The
modification time is restored as well. Running it again after adding tracks
simply rewrites every tag; nothing accumulates.

Finder's Get Info and Spotlight do not read WAV tags; check the result with
`--show`, Apple Music, VLC or `ffprobe`. Distribution services such as
DistroKid take their metadata from their upload form, not from the file.

## Details

Requires Python 3.8+, standard library only. Hidden files and folders are
skipped. A file that can't be read as its format — or an MP3 whose tag is
ID3v2.2 or unsynchronised, which are not rewritten — is reported and left
untouched while the rest carry on. Status 0 means success, 1 means no audio
was found or a file could not be tagged, 2 means invalid arguments.

Since it writes to its inputs, keep a backup of masters you cannot
regenerate, and run the preview first.

Verified on macOS with real Suno WAV exports and with MP3 (ID3v2.3, v2.4,
ID3v1, lyrics and artwork) and FLAC files made by FFmpeg: tags read back
with ffprobe, decoded audio unchanged. Not yet exercised on Windows or Linux.

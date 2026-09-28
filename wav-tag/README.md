# WAV Tag

Give untagged `.wav` files — Suno exports, DAW bounces — a title, artist,
album, year and track number, worked out from how the folder is organised.
Without tags, most players and upload pages show them as
"Unknown track – Unknown artist".

```sh
python3 wav-tag/wav-tag.py ~/Music --artist "Your Name"           # preview
python3 wav-tag/wav-tag.py ~/Music --artist "Your Name" --apply   # write
python3 wav-tag/wav-tag.py ~/Music --show                         # read back
```

Without `--apply` nothing is written: the preview lists every album and
track exactly as it would be tagged.

## How the folder becomes tags

Every folder that directly contains `.wav` files is an album, named after
the folder. Folders called `A`, `B`, `Side A`, `Disc 2`, `CD1` or `Bonus`
are treated as sides of the album above them: their tracks are merged into
it and numbering continues across sides, with Bonus last.

```
Music/
  Night Drive EP/           album "Night Drive EP"
    Neon.wav                "Neon"
    City Lights (1).wav     "City Lights"
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
| Track | `n/total`. If every file in a folder starts with a number (`A01 `, `01 - `), that order is used; otherwise creation date, oldest first |
| Year | Each file's creation year, or `--year 2026` for all |
| Genre | `--genre`, optional |

Creation date is the file's birth time on macOS. Other systems don't record
it reliably, so there the modification time is used instead. A file
downloaded later than it was made will sort by its download time: check the
preview.

## What is written

Two tag blocks, because players disagree about which one to read:

- an ID3v2.3 `id3 ` chunk — Apple Music, VLC, ffprobe, most upload pages;
- a RIFF `LIST/INFO` chunk — Windows Explorer, DAWs, older tools.

Any existing ID3 and INFO chunks are replaced; every other chunk, including
the audio, is kept byte for byte. **The file is rewritten in place** — the
same file, not a copy — so its creation date is kept and a later run
numbers tracks the same way. The modification time is restored as well.
Running it again after adding tracks simply rewrites every tag.

Finder's Get Info and Spotlight do not read WAV tags; check the result with
`--show`, Apple Music, VLC or `ffprobe`. Distribution services such as
DistroKid take their metadata from their upload form, not from the file.

## Details

Requires Python 3.8+, standard library only. Hidden files and folders are
skipped. A file that is not a RIFF/WAVE file is reported and the rest carry
on. Status 0 means success, 1 means a folder had no WAV files or a file
could not be tagged, 2 means invalid arguments.

Since it writes to its inputs, keep a backup of masters you cannot
regenerate, and run the preview first.

Verified on macOS with real Suno exports; tags read back with ffprobe.
Not yet exercised on Windows or Linux.

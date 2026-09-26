# file-identify

Says what a file is from its bytes rather than its name.

```sh
python3 file-identify/identify-file.py invoice.pdf
python3 file-identify/identify-file.py --facts photo.jpg
python3 file-identify/identify-file.py --json ~/Downloads/*
python3 file-identify/identify-file.py --no-programs scan.tiff
```

```
  contract.docx
  image/png  ·  86 B  ·  1920 x 1080

  Happened  2026-09-25 23:55:39  (when it arrived on this disk)
  Made as   screenshot
  Note      named .docx, which would be document/word

  READ ME FIRST.pdf
  document/pdf  ·  774.1 KB

  Happened  2025-02-15 10:30:06  (when the file says it was made)
  Heading   Read Me First February · Contents · and
  Title     Read Me First
  Made as   authored
```

For each path it prints:

- **the real format**, and the extension's claim when that is wrong;
- **the heading** a document gives itself, read from its text: PDFs
  (including encrypted ones that open without a password), Word old and
  new, OpenDocument, RTF, Pages, Markdown, email, calendar invites, web
  pages, and spreadsheets old and new;
- **when it happened**, and from what: a photo's own clock, the date a
  document says it was made, a date in the name, or only the day it arrived
  on the disk. Those are different kinds of evidence and it says which one
  it used;
- **what made it**: camera, scanner, screenshot, printed web page, or a
  document written on a computer;
- **where it came from**, when the system kept a note of the download (the
  macOS download record, the Windows zone mark).

`--facts` prints everything that was found, each with the reader that found
it, how sure that reader is, and where two readers disagreed. `--json` is the
same for a program: one object for one path, a list for several.

`--tier` decides how far to read: `stat` looks at the name and the disk only,
`signature` also reads the first bytes, `header` parses the format, `all`
(the default) also asks ffprobe, exiftool and text recognition to fill the
gaps that remain. `--no-programs` is `header`: Python alone, no other process
started.

## It reads and never writes

Nothing is moved, renamed, cached, or sent anywhere. The files it looks at
keep their modification times, and it writes no bytecode beside itself. A
file on a cloud drive that is not downloaded is described as such, not
fetched.

It does print what it finds, and what it finds can be personal: a
payslip's heading, a photo's camera serial and location in `--facts`, the
address a file was downloaded from. That goes to your terminal and nowhere
else, but think before pasting it into a bug report.

## Requirements

Python 3.8 or newer, standard library only. Optional, used when installed:

| Program | For |
| --- | --- |
| ffprobe | video and audio the Python readers leave gaps in |
| exiftool | camera and scanner details beyond EXIF |
| tesseract, or the Mac's own text recognition | scans with no text layer |

## Where it comes from

This is [auto-sort](https://github.com/snepssen/auto-sort)'s identifier,
the part that decides what each file in a Downloads folder is before it is
filed. The code in `engine/` is a copy of auto-sort's modules, not a
rewrite: `engine/MANIFEST.json` names the auto-sort version and commit they
came from and the hash of every file.

It is never edited here. A fix goes into auto-sort, and is copied across
with the script that keeps every tool taken from auto-sort in step:

```sh
python3 scripts/from-auto-sort.py --from ~/code/auto-sort
python3 scripts/from-auto-sort.py --check
python3 scripts/from-auto-sort.py --check --from ~/code/auto-sort
```

`--check` fails if any engine file differs from the manifest, which the
release check runs; with `--from` it also fails when auto-sort has moved on
since the last copy.

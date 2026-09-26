# Bundle List

Show which files belong together before another tool separates them.

```sh
python3 bundle-list/bundle-list.py ~/Downloads
python3 bundle-list/bundle-list.py ~/Downloads --groups-only
python3 bundle-list/bundle-list.py ./assets --recursive --depth 4 --json
```

Recognises films and language-tagged subtitles, artwork and other sidecars,
RAW/JPEG pairs, model sidecars, multipart archives, and numbered image or
video sequences (eight or more members). Each result gives its primary file,
members and the reason for grouping. Nothing is moved or renamed.

By default it lists one directory, including opaque application/document
packages; ordinary subdirectories are not opened. `--recursive` descends up
to three levels by default. Recognised project folders and packages remain
whole, and hidden subdirectories are skipped during recursion. A recursive
depth of zero lists top-level ordinary directories as whole inbox items.
`--groups-only` omits ordinary single files and keeps whole directories.

This is filename-based grouping, not a dependency resolver. A group does not
prove every expected companion exists, and a frame sequence is not checked
for missing numbers. The upstream walker skips unreadable nested folders.
JSON is always a list; an empty list is a valid result. An invalid or
unreadable root exits with status 1; a completed listing exits with 0.

Python 3.8+, standard library only. No external programs, uploads or cache.

## Source and maintenance

Uses [Auto Sort](https://snepssen.github.io/auto-sort/)'s grouping code,
unchanged. `engine/MANIFEST.json` records the source commit and hashes.
Fix the engine in Auto Sort and copy it across:

```sh
python3 scripts/from-auto-sort.py --from ../auto-sort --only bundle-list
python3 scripts/from-auto-sort.py --check --only bundle-list
```

Verified on macOS with generated sidecars, image sequences, packages and
project folders. This standalone command has not been exercised on Windows
or Linux.

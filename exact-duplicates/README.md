# Exact Duplicates

Find byte-identical copies across folders. Read-only: no deletion or keeper
selection.

```sh
python3 exact-duplicates/exact-duplicates.py ~/Downloads ~/Documents
python3 exact-duplicates/exact-duplicates.py ./archive --min-size 1048576
python3 exact-duplicates/exact-duplicates.py ./archive --json
```

Compares sizes first and computes SHA-256 only for files that share a size.
Reports matching paths, file size, hash, and the logical size of the extra
copies. It does not look for similar pictures, different encodings of the
same recording, or revisions of a document.

Overlapping folder arguments are scanned once. Hard links to the same inode
are listed as aliases and do not inflate the duplicate byte count. Empty
files, symlinks, hidden entries and recognised application/document packages
are skipped. The minimum file size defaults to one byte.

The count is **logical duplicate bytes**, not a promise of disk space that
could be recovered: filesystem clones, compression and hard links outside
the selected folders affect actual storage. No copy is recommended for
deletion. Work on stable folders: this is a best-effort scan, not a filesystem
snapshot; the upstream scanner skips files and nested directories it cannot
read. A file changed during scanning may need a fresh scan.

JSON is an object with `roots`, `groups` and `duplicate_bytes`. Each group
has `paths`, `hardlink_aliases`, `size`, `sha256` and `duplicate_bytes`.
Status 0 means the scan completed, including when duplicates were found;
status 1 means a root or operation failed. No ledger or rules file is needed.

Python 3.8+, standard library only. No external programs, uploads or cache.

## Source and maintenance

Uses [Auto Sort](https://snepssen.github.io/auto-sort/)'s scanner and hash
implementation unchanged. The command normalises roots and accounts for hard
links, without using Auto Sort's keeper recommendations. Supporting mover
code is present for its hash function; this command never invokes a move.
`engine/MANIFEST.json` records the upstream version, commit and hashes.

```sh
python3 scripts/from-auto-sort.py --from ../auto-sort --only exact-duplicates
python3 scripts/from-auto-sort.py --check --only exact-duplicates
```

Verified on macOS with generated duplicates, overlapping roots, links and
packages. This standalone command has not been exercised on Windows or Linux.

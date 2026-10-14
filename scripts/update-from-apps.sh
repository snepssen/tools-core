#!/usr/bin/env bash
# Bring every extracted engine up to date with the app it comes from.
#
#   scripts/update-from-apps.sh
#
# The apps are the source: auto-sort for bundle-list, exact-duplicates,
# file-identify and tray-icon; Media Preflight for caption-check; siphon for
# remux. from-auto-sort.py and from-projects.py copy an engine and record the
# app's commit and each file's hash in its MANIFEST.json. This runs both for
# every app checked out beside tools-core, then this repository's tests and
# release check, and commits and pushes only if something changed and they
# pass. An app with uncommitted changes in an engine file is refused by the
# copy scripts themselves, so work in progress never reaches the tools.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(dirname "$(pwd)")"
[ -z "$(git status --porcelain)" ] || { echo "error: tools-core has uncommitted changes" >&2; exit 1; }

pulled=()
if [ -d "$ROOT/auto-sort" ]; then
  python3 scripts/from-auto-sort.py --from "$ROOT/auto-sort" >/dev/null && pulled+=("auto-sort")
fi
for project in media-preflight siphon; do
  [ -d "$ROOT/$project" ] || continue
  python3 scripts/from-projects.py --project "$project" --from "$ROOT/$project" >/dev/null && pulled+=("$project")
done
if [ -z "$(git status --porcelain)" ]; then
  echo "every engine already matches its app (${pulled[*]})"; exit 0
fi
git status --short
if python3 -m unittest discover -s tests -q && python3 scripts/check_release.py >/dev/null; then
  git add -A && git commit -q -m "Engines updated from ${pulled[*]}" && git push -q origin HEAD
  echo "updated from ${pulled[*]}; tests and release check passed; pushed"
else
  git checkout -q -- . && git clean -qfd
  echo "error: tools-core's checks failed on the new engines; left as it was" >&2; exit 1
fi

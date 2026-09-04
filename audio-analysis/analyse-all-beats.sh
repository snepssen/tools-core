#!/usr/bin/env bash
# Measure the binaural beat in every tape. ~30 s each, so the set is ~25 min.
# Idempotent: a tape already analysed is skipped.
set -uo pipefail
if [[ $# -lt 1 ]]; then
  echo "usage: $0 TAPE_ROOT [OUTPUT_DIR]" >&2
  exit 2
fi
ROOT="$1"
OUT="${2:-./beat-analysis}"
PY="${PYTHON:-python3}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$OUT"
i=0
while IFS= read -r flac; do
  i=$((i+1))
  name="$(basename "$flac" .flac)"
  wave="$(basename "$(dirname "$flac")")"
  key="$(echo "$wave/$name" | tr '/ ' '__' | tr -cd '[:alnum:]_-')"
  [ -s "$OUT/$key.json" ] && { echo "[$i] skip $name"; continue; }
  if "$PY" "$SCRIPT_DIR/analyse-beat.py" "$flac" --json > "$OUT/$key.json" 2>/dev/null; then
    summary="$($PY -c 'import json,sys; d=json.load(open(sys.argv[1])); print(f"{d['"'"'dominant'"'"']} Hz dominant, {len(d['"'"'runs'"'"'])} runs")' "$OUT/$key.json" 2>/dev/null)"
    echo "[$i] $wave / $name -> $summary"
  else
    echo "[$i] FAILED $name"; rm -f "$OUT/$key.json"
  fi
done < <(find "$ROOT" -type f -iname "*.flac" | sort)
echo "done: $(ls "$OUT"/*.json 2>/dev/null | wc -l | tr -d ' ') analysed"

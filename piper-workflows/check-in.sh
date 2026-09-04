#!/usr/bin/env bash
# Export the highest-epoch Piper checkpoint and render fixed diagnostic lines.
# Activate the intended Piper training environment before running this script.
set -euo pipefail

if [[ $# -lt 3 || $# -gt 4 ]]; then
  echo "usage: $0 RUN_DIR CONFIG_JSON OUTPUT_DIR [VOICE_NAME]" >&2
  exit 2
fi

RUN_DIR="$1"
CONFIG_SOURCE="$2"
OUT_DIR="$3"
VOICE_NAME="${4:-voice-check-in}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

LATEST="$({ find "$RUN_DIR" -type f -name 'epoch=*-val_mel=*.ckpt' -print 2>/dev/null || true; } | \
  sed -E 's/.*epoch=([0-9]+)-val_mel=([0-9.]+)\.ckpt/\1 \2 &/' | \
  sort -n -k1,1 | tail -1)"
CKPT="$(printf '%s\n' "$LATEST" | cut -d' ' -f3-)"
if [[ -z "$CKPT" || ! -f "$CKPT" ]]; then
  echo "no epoch checkpoint found under $RUN_DIR" >&2
  exit 1
fi

EPOCH="$(printf '%s\n' "$LATEST" | awk '{print $1}')"
VAL_MEL="$(printf '%s\n' "$LATEST" | awk '{print $2}')"
mkdir -p "$OUT_DIR"
MODEL="$OUT_DIR/$VOICE_NAME.onnx"
CONFIG="$MODEL.json"

echo "using epoch $EPOCH (val_mel=$VAL_MEL): $CKPT"
python3 "$SCRIPT_DIR/export.py" --checkpoint "$CKPT" --output-file "$MODEL"
cp "$CONFIG_SOURCE" "$CONFIG"

render() {
  local filename="$1"
  local text="$2"
  python3 "$SCRIPT_DIR/audition.py" \
    --model "$MODEL" --config "$CONFIG" --out "$OUT_DIR/$filename" "$text"
}

render "sample1-settling.wav" \
  "Let the weight of your body arrive where it rests. There is nothing to reach for now, and nothing that needs deciding."
render "sample2-breath.wav" \
  "You are not managing it. You are only noticing that it continues as it has continued through every hour."
render "sample3-counting.wav" \
  "One. Feeling relaxed and comfortable. Two. Moving further from the physical, further from concern. Three."
render "sample4-breath-tail.wav" \
  "It will still be there, and you will meet it rested."

echo "wrote $OUT_DIR"

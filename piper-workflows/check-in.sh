#!/usr/bin/env bash
# Export the highest-epoch Piper checkpoint and render fixed diagnostic lines.
# Activate the intended Piper training environment before running this script.
#
# ONNX Runtime can crash on the way out, after the export or a render has
# already succeeded. no_telemetry.py (line 9) is why: the telemetry uploader
# segfaults on a worker thread during shutdown, the process exits non-zero,
# and `set -e` cannot tell that crash from a failure that mattered. Importing
# no_telemetry disables the uploader and still does not catch every shutdown
# crash. The export below runs under `set +e` and is kept when the model still
# loads. Each render is kept when its wav exists and ffprobe reports at least
# one second. Any other non-zero exit still fails the check-in.
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

# MODEL is the exported path. no_telemetry has to be imported from this
# directory before onnxruntime opens a session, same as export.py.
model_still_loads() {
  PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}" \
    MODEL="$MODEL" \
    python3 -c 'import no_telemetry, onnxruntime, os; MODEL = os.environ["MODEL"]; onnxruntime.InferenceSession(MODEL, providers=["CPUExecutionProvider"])'
}

# A non-zero render is a crash on the way out only when the wav is real audio.
wav_long_enough() {
  local wav="$1"
  local seconds
  [[ -f "$wav" ]] || return 1
  seconds="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$wav")" || return 1
  seconds="${seconds%%$'\n'*}"
  [[ -n "$seconds" ]] || return 1
  LC_ALL=C awk -v d="$seconds" 'BEGIN { exit ((d + 0) >= 1) ? 0 : 1 }'
}

echo "using epoch $EPOCH (val_mel=$VAL_MEL): $CKPT"
export_status=0
# set +e: a shutdown crash after a good export must not abort the check-in.
set +e
python3 "$SCRIPT_DIR/export.py" --checkpoint "$CKPT" --output-file "$MODEL"
export_status=$?
set -e
if [[ "$export_status" -ne 0 ]]; then
  echo "export exited ${export_status}; checking that ${MODEL} still loads" >&2
  load_status=0
  # set +e so a failed load returns here and fails the check-in with a message.
  set +e
  model_still_loads
  load_status=$?
  set -e
  if [[ "$load_status" -ne 0 ]]; then
    echo "exported model does not load: ${MODEL}" >&2
    exit "$export_status"
  fi
fi
cp "$CONFIG_SOURCE" "$CONFIG"

render() {
  local filename="$1"
  local text="$2"
  local wav="$OUT_DIR/$filename"
  local status
  local long_enough
  # set +e: same shutdown crash, per render. Keep the wav only when ffprobe
  # reports a duration of at least 1s; otherwise this exit still fails.
  set +e
  python3 "$SCRIPT_DIR/audition.py" \
    --model "$MODEL" --config "$CONFIG" --out "$wav" "$text"
  status=$?
  set -e
  if [[ "$status" -eq 0 ]]; then
    return 0
  fi
  long_enough=1
  set +e
  wav_long_enough "$wav"
  long_enough=$?
  set -e
  if [[ "$long_enough" -eq 0 ]]; then
    echo "render exited ${status}; keeping ${wav} (ffprobe duration >= 1s)" >&2
    return 0
  fi
  echo "render failed (${status}): ${wav}" >&2
  exit "$status"
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

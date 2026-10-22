"""Piper workflow guards: warm-start overwrite refusal, and check-in crash tolerance."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / "piper-workflows" / "train.py"
CHECK_IN = ROOT / "piper-workflows" / "check-in.sh"


def load_train():
    spec = importlib.util.spec_from_file_location("piper_workflows_train", TRAIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TRAIN_MOD = load_train()


class TrainGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.previous = os.getcwd()
        os.chdir(self.folder)
        self.addCleanup(os.chdir, self.previous)

    def write_ckpt(self, relative):
        path = self.folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"ckpt")
        return path

    def guard(self, argv):
        return TRAIN_MOD._guard_warm_start(["train.py", *argv])

    def test_refuses_when_run_directory_holds_checkpoints(self):
        run = self.folder / "run"
        ckpt = self.write_ckpt("run/lightning_logs/version_0/checkpoints/last.ckpt")
        self.write_ckpt("run/epoch=4-val_mel=0.2500.ckpt")
        with self.assertRaises(SystemExit) as caught:
            self.guard(["fit", "--trainer.default_root_dir", str(run)])
        message = str(caught.exception)
        self.assertIn("train_resume.py", message)
        self.assertIn("--ckpt_path", message)
        self.assertIn("--force", message)
        self.assertIn("overwrite trained weights", message)
        self.assertIn(str(ckpt), message)

    def test_refuses_for_equals_form_and_checkpoint_dirpath(self):
        self.write_ckpt("out/last.ckpt")
        with self.assertRaises(SystemExit):
            self.guard(["fit", "--trainer.callbacks.init_args.dirpath=" + str(self.folder / "out")])

    def test_refuses_when_config_names_the_run_directory(self):
        run = self.folder / "from-config"
        self.write_ckpt("from-config/checkpoints/last.ckpt")
        config = self.folder / "fit.yaml"
        config.write_text(
            "trainer:\n  default_root_dir: " + str(run) + "\n"
            "data:\n  audio_dir: " + str(self.folder / "audio") + "\n",
            encoding="utf-8",
        )
        self.write_ckpt("audio/en_US-lessac-medium.ckpt")
        with self.assertRaises(SystemExit) as caught:
            self.guard(["fit", "--config", str(config), "--data.audio_dir", str(self.folder / "audio")])
        self.assertIn(str(run), str(caught.exception))

    def test_config_json_dirpath_is_the_output_directory(self):
        out = self.folder / "json-out"
        self.write_ckpt("json-out/epoch=1-val_mel=0.1000.ckpt")
        config = self.folder / "fit.json"
        config.write_text(
            '{"trainer": {"callbacks": [{"init_args": {"dirpath": "' + str(out) + '"}}]}}',
            encoding="utf-8",
        )
        with self.assertRaises(SystemExit):
            self.guard(["fit", "--config=" + str(config)])

    def test_empty_run_directory_is_a_first_run(self):
        run = self.folder / "fresh"
        run.mkdir()
        self.write_ckpt("elsewhere/last.ckpt")
        argv = self.guard([
            "fit",
            "--data.voice_name", "name",
            "--trainer.default_root_dir", str(run),
            "--model.warmstart_ckpt", str(self.folder / "elsewhere" / "last.ckpt"),
        ])
        self.assertIn("fit", argv)
        self.assertIn(str(run), argv)

    def test_force_strips_the_flag_and_starts_anyway(self):
        run = self.folder / "run"
        self.write_ckpt("run/last.ckpt")
        argv = self.guard(["fit", "--force", "--trainer.default_root_dir", str(run)])
        self.assertNotIn("--force", argv)
        self.assertEqual(argv[1], "fit")

    def test_default_lightning_logs_and_other_subcommands(self):
        self.write_ckpt("lightning_logs/version_1/checkpoints/last.ckpt")
        with self.assertRaises(SystemExit):
            self.guard(["fit", "--data.batch_size", "4"])
        argv = self.guard(["predict", "--trainer.default_root_dir", str(self.folder)])
        self.assertEqual(argv[1], "predict")
        argv = self.guard(["fit", "--help", "--trainer.default_root_dir", str(self.folder)])
        self.assertIn("--help", argv)

    def test_refusal_stops_before_piper_is_imported(self):
        self.write_ckpt("lightning_logs/last.ckpt")
        original = sys.argv
        sys.argv = ["train.py", "fit"]
        try:
            with self.assertRaises(SystemExit) as caught:
                TRAIN_MOD.main()
        finally:
            sys.argv = original
        self.assertIn("train_resume.py", str(caught.exception))


class CheckInCrashTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.stub = self.folder / "bin"
        self.stub.mkdir()
        self.log = self.folder / "stub.log"
        self.run = self.folder / "run"
        self.out = self.folder / "out"
        self.run.mkdir()
        (self.run / "epoch=2-val_mel=0.4000.ckpt").write_bytes(b"early")
        (self.run / "epoch=10-val_mel=0.2000.ckpt").write_bytes(b"later")
        self.config = self.folder / "voice.json"
        self.config.write_text("{}\n", encoding="utf-8")
        self._write_stub("python3", PYTHON_STUB)
        self._write_stub("ffprobe", FFPROBE_STUB)

    def _write_stub(self, name, body):
        path = self.stub / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)

    def check_in(self, **env):
        full = os.environ.copy()
        full["PATH"] = str(self.stub) + os.pathsep + full.get("PATH", "")
        full["STUB_LOG"] = str(self.log)
        full.update(env)
        done = subprocess.run(
            ["bash", str(CHECK_IN), str(self.run), str(self.config), str(self.out)],
            capture_output=True, text=True, env=full,
        )
        log = self.log.read_text(encoding="utf-8") if self.log.exists() else ""
        return done, log

    def test_shutdown_crash_keeps_a_loadable_model_and_long_wavs(self):
        done, log = self.check_in(EXPORT_STATUS="139", RENDER_STATUS="139", FFPROBE_DURATION="2.5")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("using epoch 10 (val_mel=0.2000)", done.stdout)
        self.assertIn("wrote ", done.stdout)
        self.assertIn("no_telemetry", log)
        self.assertIn("InferenceSession", log)
        self.assertIn("CPUExecutionProvider", log)
        self.assertEqual(log.count("ffprobe "), 4)
        for name in (
            "sample1-settling.wav",
            "sample2-breath.wav",
            "sample3-counting.wav",
            "sample4-breath-tail.wav",
        ):
            self.assertTrue((self.out / name).is_file(), name)
        self.assertEqual((self.out / "voice-check-in.onnx.json").read_text(encoding="utf-8"), "{}\n")

    def test_export_that_does_not_load_still_fails(self):
        done, log = self.check_in(EXPORT_STATUS="1", WRITE_MODEL="0")
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("does not load", done.stderr)
        self.assertNotIn("audition.py", log)
        self.assertFalse((self.out / "voice-check-in.onnx.json").exists())

    def test_zero_export_does_not_need_the_load_check(self):
        done, log = self.check_in(EXPORT_STATUS="0", LOAD_STATUS="1", RENDER_STATUS="0", FFPROBE_STATUS="1")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("-c ", log)
        self.assertNotIn("ffprobe ", log)

    def test_short_or_missing_wav_still_fails_the_render(self):
        short, log = self.check_in(RENDER_STATUS="7", FFPROBE_DURATION="0.25")
        self.assertEqual(short.returncode, 7, short.stderr)
        self.assertEqual(log.count("audition.py"), 1)
        self.log.unlink()
        shutil.rmtree(self.out)
        missing, log = self.check_in(RENDER_STATUS="5", WRITE_WAV="0")
        self.assertEqual(missing.returncode, 5, missing.stderr)
        self.assertNotIn("ffprobe ", log)

    def test_duration_of_one_second_is_enough(self):
        done, _log = self.check_in(RENDER_STATUS="139", FFPROBE_DURATION="1")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_usage_and_missing_checkpoint(self):
        usage = subprocess.run(["bash", str(CHECK_IN)], capture_output=True, text=True)
        self.assertEqual(usage.returncode, 2)
        empty = self.folder / "empty"
        empty.mkdir()
        missing = subprocess.run(
            ["bash", str(CHECK_IN), str(empty), str(self.config), str(self.out)],
            capture_output=True, text=True,
        )
        self.assertEqual(missing.returncode, 1)
        self.assertIn("no epoch checkpoint", missing.stderr)


PYTHON_STUB = """#!/usr/bin/env bash
set -u
printf '%s\\n' "$0 $*" >> "${STUB_LOG:?}"
if [[ "${1:-}" == "-c" ]]; then
  code="${2:-}"
  if [[ "$code" != *no_telemetry* || "$code" != *InferenceSession* || "$code" != *CPUExecutionProvider* ]]; then
    echo "load check missing pieces: $code" >&2
    exit 97
  fi
  if [[ "${LOAD_STATUS:-0}" != "0" ]]; then
    exit "$LOAD_STATUS"
  fi
  if [[ -z "${MODEL:-}" || ! -f "$MODEL" ]]; then
    echo "model missing: ${MODEL:-}" >&2
    exit 1
  fi
  exit 0
fi
out=""
prev=""
for arg in "$@"; do
  if [[ "$prev" == "--output-file" || "$prev" == "--out" ]]; then
    out="$arg"
  fi
  prev="$arg"
done
case "$(basename "$1")" in
  export.py)
    status="${EXPORT_STATUS:-0}"
    if [[ -n "$out" && "${WRITE_MODEL:-1}" == "1" ]]; then
      mkdir -p "$(dirname "$out")"
      printf 'model' > "$out"
    fi
    exit "$status"
    ;;
  audition.py)
    status="${RENDER_STATUS:-0}"
    if [[ -n "$out" && "${WRITE_WAV:-1}" == "1" ]]; then
      mkdir -p "$(dirname "$out")"
      printf 'wav' > "$out"
    fi
    exit "$status"
    ;;
esac
echo "unexpected python: $*" >&2
exit 99
"""

FFPROBE_STUB = """#!/usr/bin/env bash
printf 'ffprobe %s\\n' "$*" >> "${STUB_LOG:?}"
if [[ "${FFPROBE_STATUS:-0}" != "0" ]]; then
  exit "$FFPROBE_STATUS"
fi
printf '%s\\n' "${FFPROBE_DURATION:-1.5}"
"""


if __name__ == "__main__":
    unittest.main()

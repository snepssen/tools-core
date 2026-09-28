"""Exercise the standalone commands using temporary, generated fixtures."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


class Fixtures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def run_tool(self, name, *args):
        return subprocess.run([sys.executable, str(ROOT / name / (name + ".py")),
                               *map(str, args)], capture_output=True, text=True, timeout=60)

    def write(self, name, content):
        path = self.folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path


class CommandTests(Fixtures):
    def test_caption_clean_srt_and_vtt(self):
        srt = self.write("words.srt", "1\n00:00:01,000 --> 00:00:03,000\nHello there.\n")
        vtt = self.write("words.vtt", "WEBVTT\n\n00:01.000 --> 00:03.000\nHello there.\n")
        before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in (srt, vtt)]
        done = self.run_tool("caption-check", srt, vtt, "--json")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual([r["cue_count"] for r in json.loads(done.stdout)], [1, 1])
        self.assertEqual(before, [(p.read_bytes(), p.stat().st_mtime_ns) for p in (srt, vtt)])

    def test_caption_findings_and_thresholds(self):
        path = self.write("words.srt", "1\n00:00:01,000 --> 00:00:01,500\nToo many words to read in half a second.\n\n"
                          "2\n00:00:01,400 --> 00:00:04,000\nNext line\n\n"
                          "3\n00:00:06,000 --> 00:00:05,000\nBackwards\n")
        done = self.run_tool("caption-check", path, "--json", "--duration", "3")
        self.assertEqual(done.returncode, 1, done.stderr)
        codes = {f["code"] for f in json.loads(done.stdout)[0]["findings"]}
        self.assertTrue({"overlap", "reading-speed", "short-cue", "invalid-timing", "past-end"} <= codes)
        clean = self.write("short.srt", "1\n00:00:01,000 --> 00:00:01,500\nHello\n")
        self.assertEqual(self.run_tool("caption-check", clean, "--min-duration", ".4").returncode, 0)

    def test_caption_unreadable_record_is_not_silently_passed(self):
        path = self.write("broken.srt", "1\n00:00:01,000 --> 00:00:03,000\nHello\n\n"
                          "2\nbad --> bad\nLost words\n")
        done = self.run_tool("caption-check", path, "--json")
        self.assertEqual(done.returncode, 1)
        self.assertIn("unreadable-cue", done.stdout)
        path.write_text("not subtitles")
        self.assertEqual(self.run_tool("caption-check", path).returncode, 2)

    def test_caption_ass_separate_positions_do_not_overlap(self):
        path = self.write("words.ass", "[Script Info]\nScriptType: v4.00+\n[Events]\n"
                          "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                          "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\an8}Top\n"
                          "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\an2}Bottom\n")
        done = self.run_tool("caption-check", path, "--json")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(json.loads(done.stdout)[0]["findings"], [])

    def test_caption_invalid_options(self):
        for option in ("nan", "inf", "0", "-1"):
            self.assertEqual(self.run_tool("caption-check", "x.srt", "--max-cps", option).returncode, 2)

    def test_duplicate_content_and_overlapping_roots(self):
        a = self.write("a.txt", "same bytes")
        b = self.write("nested/b.txt", "same bytes")
        self.write("different.txt", "other data")
        self.write("empty1.txt", "")
        self.write("empty2.txt", "")
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.folder.rglob("*") if p.is_file()}
        done = self.run_tool("exact-duplicates", self.folder, b.parent, self.folder, "--json")
        self.assertEqual(done.returncode, 0, done.stderr)
        report = json.loads(done.stdout)
        self.assertEqual(report["duplicate_bytes"], len("same bytes"))
        self.assertEqual(len(report["groups"]), 1)
        self.assertEqual(set(report["groups"][0]["paths"]), {str(a.resolve()), str(b.resolve())})
        self.assertEqual(report["groups"][0]["sha256"], hashlib.sha256(b"same bytes").hexdigest())
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before})

    def test_duplicate_links_and_packages(self):
        a = self.write("a.txt", "same bytes")
        os.link(a, self.folder / "hard.txt")
        try:
            os.symlink(a, self.folder / "soft.txt")
        except OSError:
            pass
        self.write("Private.app/inside.txt", "same bytes")
        done = self.run_tool("exact-duplicates", self.folder, "--json")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["groups"], [])
        b = self.write("b.txt", "same bytes")
        done = self.run_tool("exact-duplicates", self.folder, "--json")
        group = json.loads(done.stdout)["groups"][0]
        self.assertEqual(len(group["paths"]), 2)
        self.assertEqual(group["duplicate_bytes"], a.stat().st_size)
        self.assertTrue(group["hardlink_aliases"])

    def test_missing_roots_fail(self):
        for tool in ("exact-duplicates", "bundle-list"):
            done = self.run_tool(tool, self.folder / "missing")
            self.assertEqual(done.returncode, 1, done.stdout)

    def test_bundle_sidecars_sequences_and_packages(self):
        for name in ("Film.mkv", "Film.en.srt", "Film-poster.jpg", "model.obj", "model.mtl",
                     "photo.cr2", "photo.jpg", "Lone.txt", "App.app/contents"):
            self.write(name, "fixture")
        for n in range(1, 9):
            self.write("frame%04d.png" % n, "fixture")
        done = self.run_tool("bundle-list", self.folder, "--json")
        self.assertEqual(done.returncode, 0, done.stderr)
        rows = json.loads(done.stdout)
        groups = [{Path(p).name for p in row["members"]} for row in rows]
        self.assertIn({"Film.mkv", "Film.en.srt", "Film-poster.jpg"}, groups)
        self.assertIn({"model.obj", "model.mtl"}, groups)
        self.assertIn({"photo.cr2", "photo.jpg"}, groups)
        self.assertTrue(any(row["sequence"] == 8 for row in rows))
        app = next(row for row in rows if Path(row["primary"]).name == "App.app")
        self.assertTrue(app["directory"])
        filtered = json.loads(self.run_tool("bundle-list", self.folder, "--groups-only", "--json").stdout)
        self.assertFalse(any(Path(row["primary"]).name == "Lone.txt" for row in filtered))

    def test_bundle_recursion_keeps_projects_whole(self):
        self.write("ordinary/pair.obj", "fixture")
        self.write("ordinary/pair.mtl", "fixture")
        self.write("project/package.json", "{}")
        self.write("project/index.js", "")
        rows = json.loads(self.run_tool("bundle-list", self.folder, "--recursive", "--json").stdout)
        self.assertTrue(any(len(r["members"]) == 2 for r in rows))
        self.assertTrue(any(r["reason"] == "project folder" for r in rows))
        self.assertFalse(any(Path(r["primary"]).name == "package.json" for r in rows))

    def test_grouping_ignores_listing_order_in_every_extracted_engine(self):
        # Exercise both orders explicitly: macOS and Linux need not enumerate
        # equal-sized files alike. Import each copy in its own process.
        script = '''
import itertools, json, sys
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import bundles
folder = Path(sys.argv[2])
results = []
for primary, companion in (("model.obj", "model.mtl"), ("photo.cr2", "photo.jpg")):
    for sizes in ((7, 7), (1, 100), (100, 1)):
        for name, size in zip((primary, companion), sizes):
            (folder / name).write_bytes(b"x" * size)
        for names in itertools.permutations((primary, companion)):
            items = bundles.group(str(folder), names)
            results.append(len(items) == 1 and Path(items[0].primary).name == primary
                           and {Path(p).name for p in items[0].members} == set(names))
print(json.dumps(results))
'''
        for tool in ("bundle-list", "exact-duplicates", "file-identify"):
            with self.subTest(engine=tool):
                done = subprocess.run([sys.executable, "-c", script,
                                       str(ROOT / tool / "engine"), str(self.folder)],
                                      capture_output=True, text=True, timeout=30)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(json.loads(done.stdout), [True] * 12)

    def test_upstream_manifests(self):
        for script in ("from-auto-sort.py", "from-projects.py"):
            done = subprocess.run([sys.executable, str(ROOT / "scripts" / script), "--check"],
                                  capture_output=True, text=True, timeout=30)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and ffprobe required for real remux checks")
class RemuxTests(Fixtures):
    def media(self):
        source = self.folder / "source.mp4"
        result = subprocess.run([
            FFMPEG, "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=10:d=1",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-f", "lavfi", "-i", "sine=frequency=880:duration=1",
            "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "libx264",
            "-c:a", "aac", "-metadata:s:a:0", "language=eng",
            "-metadata:s:a:1", "language=fra", str(source)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return source

    def packets(self, path):
        result = subprocess.run([FFPROBE, "-v", "error", "-show_packets", "-show_data_hash", "sha256",
                                 "-show_entries", "packet=stream_index,data_hash", "-of", "json", str(path)],
                                capture_output=True, text=True, check=True)
        streams = {}
        for packet in json.loads(result.stdout)["packets"]:
            streams.setdefault(packet["stream_index"], []).append(packet["data_hash"])
        return streams

    def test_remux_preserves_every_packet_in_multiple_tracks(self):
        source = self.media()
        before = source.read_bytes()
        output = self.folder / "out.mkv"
        done = self.run_tool("remux", source, output, "--json")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(json.loads(done.stdout)["streams"]), 3)
        self.assertEqual(self.packets(source), self.packets(output))
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(list(self.folder.glob(".remux-*")), [])

    def test_remux_plan_refusal_and_no_overwrite(self):
        source = self.media()
        output = self.folder / "out.mkv"
        done = self.run_tool("remux", source, output, "--plan", "--json")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse(json.loads(done.stdout)["written"])
        self.assertFalse(output.exists())
        incompatible = self.folder / "out.webm"
        done = self.run_tool("remux", source, incompatible)
        self.assertEqual(done.returncode, 1)
        self.assertIn("cannot be preserved", done.stderr)
        self.assertFalse(incompatible.exists())
        output.write_bytes(b"keep me")
        done = self.run_tool("remux", source, output)
        self.assertEqual(done.returncode, 1)
        self.assertEqual(output.read_bytes(), b"keep me")
        self.assertEqual(self.run_tool("remux", source, source).returncode, 1)

    def test_remux_refuses_subtitle_conversion(self):
        source = self.media()
        subtitles = self.write("words.srt", "1\n00:00:00,000 --> 00:00:00,900\nHello\n")
        with_subs = self.folder / "subtitles.mkv"
        subprocess.run([FFMPEG, "-v", "error", "-i", str(source), "-i", str(subtitles),
                        "-map", "0", "-map", "1", "-c", "copy", str(with_subs)], check=True)
        out = self.folder / "subtitle-copy.mkv"
        done = self.run_tool("remux", with_subs, out)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.packets(with_subs), self.packets(out))
        refused = self.folder / "subtitle-conversion.mp4"
        done = self.run_tool("remux", with_subs, refused)
        self.assertEqual(done.returncode, 1)
        self.assertIn("subtitle/subrip", done.stderr)
        self.assertFalse(refused.exists())


class WavTagTests(Fixtures):
    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location("wav_tag", ROOT / "wav-tag" / "wav-tag.py")
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def wav(self, name, age_hours):
        import wave
        path = self.folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(bytes(range(256)) * 16)
        # Setting an older mtime also moves macOS birth time back, so this
        # controls creation order on every platform.
        stamp = 1_700_000_000 - age_hours * 3600
        os.utime(path, (stamp, stamp))
        return path

    def tags(self, path):
        chunks = self.mod.read_chunks(path.read_bytes())
        id3 = next(self.mod.parse_id3(b) for c, b in chunks if c in self.mod.META_CHUNKS)
        info = next(self.mod.parse_info(b) for c, b in chunks if self.mod.is_info_list(c, b))
        return id3, info

    def frames(self, path):
        import wave
        with wave.open(str(path)) as w:
            return w.getparams()[:4], w.readframes(w.getnframes())

    def test_preview_writes_nothing(self):
        path = self.wav("EP/Song.wav", 1)
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        done = self.run_tool("wav-tag", self.folder, "--artist", "Someone")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Preview only", done.stdout)
        self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))

    def test_folders_sides_titles_and_order(self):
        # Created out of name order: creation date must decide.
        late = self.wav("Night EP/Aa_Song (1).wav", 1)
        early = self.wav("Night EP/Zed Song - Copy.wav", 5)
        # Numbered names win over creation date; sides merge, Bonus last.
        b1 = self.wav("LP/B/B01 Third.wav", 9)
        a2 = self.wav("LP/A/A02 Second.wav", 8)
        a1 = self.wav("LP/A/A01 First.wav", 1)
        bonus = self.wav("LP/Bonus/Extra.wav", 20)
        audio = {p: self.frames(p) for p in (late, early, a1, a2, b1, bonus)}
        times = {p: p.stat().st_mtime_ns for p in audio}

        done = self.run_tool("wav-tag", self.folder, "--artist", "Someone", "--apply")
        self.assertEqual(done.returncode, 0, done.stderr)

        expected = {
            early: ("Zed Song", "Night EP", "1/2"),
            late: ("Aa Song", "Night EP", "2/2"),
            a1: ("First", "LP", "1/4"),
            a2: ("Second", "LP", "2/4"),
            b1: ("Third", "LP", "3/4"),
            bonus: ("Extra", "LP", "4/4"),
        }
        for path, (title, album, track) in expected.items():
            id3, info = self.tags(path)
            self.assertEqual((id3["TIT2"], id3["TALB"], id3["TRCK"], id3["TPE1"]),
                             (title, album, track, "Someone"), path.name)
            self.assertEqual((info["INAM"], info["IPRD"], info["ITRK"], info["IART"]),
                             (title, album, track, "Someone"), path.name)
            self.assertEqual(self.frames(path), audio[path])
            self.assertEqual(path.stat().st_mtime_ns, times[path])

        # Re-running replaces the tags rather than stacking another copy.
        size = a1.stat().st_size
        self.assertEqual(self.run_tool("wav-tag", self.folder, "--artist", "Someone",
                                       "--apply").returncode, 0)
        self.assertEqual(a1.stat().st_size, size)
        shown = self.run_tool("wav-tag", self.folder, "--show")
        self.assertIn("1/4 | First | Someone | LP", shown.stdout)

    def test_unreadable_file_fails_without_stopping_the_rest(self):
        good = self.wav("EP/Good.wav", 2)
        bad = self.write("EP/Bad.wav", "not audio")
        done = self.run_tool("wav-tag", self.folder, "--artist", "Someone", "--apply")
        self.assertEqual(done.returncode, 1)
        self.assertIn("Bad.wav", done.stdout)
        self.assertEqual(bad.read_text(), "not audio")
        self.assertEqual(self.tags(good)[0]["TIT2"], "Good")


if __name__ == "__main__":
    unittest.main()

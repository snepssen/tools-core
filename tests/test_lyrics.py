import json
from pathlib import Path
import sys
import tempfile
import unittest


TOOL = Path(__file__).resolve().parents[1] / "lyric-video-maker"
sys.path.insert(0, str(TOOL))

import lyrics_align  # noqa: E402
import lyrics_engine  # noqa: E402
import video_effects  # noqa: E402
import video_formats  # noqa: E402


class LyricsEngineTests(unittest.TestCase):
    def test_loads_and_sorts_supported_word_list(self):
        data = [
            {"timestamp": "00:02.000-00:03.000", "text": "second"},
            {"timestamp": "00:00.500-00:01.000", "text": "first"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "words.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            words = lyrics_engine.load_words(path)
        self.assertEqual([word["text"] for word in words], ["first", "second"])
        self.assertEqual(words[0]["start"], 0.5)

    def test_ass_escapes_control_characters(self):
        lines = [{
            "start": 0.0,
            "end": 1.0,
            "text": r"a{b}\\c",
            "words": [{"text": r"a{b}\\c", "start": 0.0, "end": 1.0}],
        }]
        ass = lyrics_engine.build_ass(
            lines,
            {"accent": "#FFD400", "active": "#FFFFFF", "inactive": "#8A99A8"},
        )
        self.assertIn("a(b)//c", ass)
        self.assertNotIn(r"a{b}", ass)

    def test_portrait_ass_uses_portrait_canvas_and_centres_lyrics(self):
        data = [
            {"start": 0.0, "end": 0.4, "text": "hello"},
            {"start": 0.4, "end": 0.9, "text": "portrait"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "words.json"
            target = Path(directory) / "words.ass"
            source.write_text(json.dumps(data), encoding="utf-8")
            lyrics_engine.transcript_to_ass(
                source, target,
                {"accent": "#FFD400", "active": "#FFFFFF",
                 "inactive": "#8A99A8"},
                video_format="portrait",
            )
            ass = target.read_text(encoding="utf-8")
        self.assertIn("PlayResX: 1080", ass)
        self.assertIn("PlayResY: 1920", ass)
        self.assertIn(r"\pos(540,", ass)

    def test_reading_page_keeps_up_to_five_lines_visible(self):
        lines = []
        for index, word in enumerate(("one", "two", "three", "four")):
            start = index * 0.25
            lines.append({
                "start": start, "end": start + 0.25, "text": word,
                "words": [{"text": word, "start": start,
                           "end": start + 0.25}],
            })
        ass = lyrics_engine.build_ass(
            lines,
            {"accent": "#FFD400", "active": "#FFFFFF",
             "inactive": "#8A99A8"},
        )
        first_window = [line for line in ass.splitlines()
                        if ",0:00:00.00,0:00:00.25," in line]
        self.assertEqual(len(first_window), 4)
        self.assertTrue(any("one" in line for line in first_window))
        self.assertTrue(any("two" in line for line in first_window))
        self.assertTrue(any("three" in line for line in first_window))
        self.assertTrue(any("four" in line for line in first_window))

    def test_line_count_limits_each_reading_page(self):
        lines = [{
            "start": index, "end": index + 1, "text": word,
            "words": [{"text": word, "start": index, "end": index + 1}],
        } for index, word in enumerate(("one", "two", "three", "four"))]
        ass = lyrics_engine.build_ass(
            lines,
            {"accent": "#FFD400", "active": "#FFFFFF",
             "inactive": "#8A99A8"},
            lines_per_page=2,
        )
        first_window = [line for line in ass.splitlines()
                        if ",0:00:00.00,0:00:01.00," in line]
        self.assertEqual(len(first_window), 2)
        self.assertFalse(any("three" in line for line in first_window))

    def test_centre_position_straddles_canvas_midpoint(self):
        lines = [{
            "start": index, "end": index + 1, "text": word,
            "words": [{"text": word, "start": index, "end": index + 1}],
        } for index, word in enumerate(("one", "two", "three"))]
        ass = lyrics_engine.build_ass(
            lines,
            {"accent": "#FFD400", "active": "#FFFFFF",
             "inactive": "#8A99A8"},
            gap=100, lyric_position="center",
        )
        self.assertIn(r"\pos(960,440)", ass)
        self.assertIn(r"\pos(960,540)", ass)
        self.assertIn(r"\pos(960,640)", ass)

    def test_wrap_line_rebalances_a_short_orphan(self):
        words = [{"text": word, "start": index, "end": index + 0.5}
                 for index, word in enumerate(
                     ("one", "two", "three", "four", "five", "six"))]
        chunks = lyrics_engine.wrap_line(words, max_chars=100, max_words=5)
        self.assertEqual([len(chunk) for chunk in chunks], [3, 3])


class VideoFormatTests(unittest.TestCase):
    def test_portrait_output_does_not_overwrite_landscape(self):
        self.assertEqual(video_formats.output_name("song.wav", "landscape"),
                         "song.mp4")
        self.assertEqual(video_formats.output_name("song.wav", "portrait"),
                         "song-short.mp4")

    def test_unknown_format_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown video format"):
            video_formats.get_video_format("square")


class VideoEffectsTests(unittest.TestCase):
    def test_ambient_bottom_waveform_builds_mapped_filter_graph(self):
        graph, audio_map = video_effects.build_filter_graph(
            video_formats.VIDEO_FORMATS["landscape"], "words.ass",
            {"visualMode": "ambient", "waveform": "bottom",
             "accent": "#FFD400"},
        )
        self.assertIn("zoompan=", graph)
        self.assertIn("showfreqs=s=1920x", graph)
        self.assertIn("subtitles='words.ass'[video]", graph)
        self.assertEqual(audio_map, "[audioout]")

    def test_party_mode_uses_manual_tempo_and_side_waveform(self):
        graph, _ = video_effects.build_filter_graph(
            video_formats.VIDEO_FORMATS["portrait"], "words.ass",
            {"visualMode": "party", "waveform": "side",
             "accent": "#12ABEF"}, bpm=128,
        )
        self.assertIn("t*128.000/60", graph)
        self.assertIn("showfreqs=s=1920x", graph)
        self.assertIn("transpose=1", graph)

    def test_estimates_synthetic_120_bpm_pulse(self):
        sample_rate = 400
        samples = [0.0] * (sample_rate * 12)
        for index in range(0, len(samples), sample_rate // 2):
            for offset in range(8):
                samples[index + offset] = 1.0
        bpm = video_effects.estimate_bpm_from_samples(samples, sample_rate)
        self.assertIsNotNone(bpm)
        self.assertLessEqual(abs(bpm - 120), 2)


class LyricsAlignmentTests(unittest.TestCase):
    def test_rtf_conversion_discards_font_table(self):
        rtf = r"{\rtf1{\fonttbl{\f0 Helvetica;}}Hello\par world}"
        self.assertEqual(lyrics_align.rtf_to_text(rtf).strip(), "Hello\nworld")

    def test_title_match_ignores_track_number_and_punctuation(self):
        tracks = {"shadow at the gates": {"title": "Shadow At The Gates", "lines": ["x"]}}
        match = lyrics_align.match_track(tracks, "/music/04 - Shadow at the Gates.wav")
        self.assertEqual(match["title"], "Shadow At The Gates")


if __name__ == "__main__":
    unittest.main()

import json
from pathlib import Path
import sys
import tempfile
import unittest


TOOL = Path(__file__).resolve().parents[1] / "lyric-video-maker"
sys.path.insert(0, str(TOOL))

import lyrics_align  # noqa: E402
import lyrics_engine  # noqa: E402
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


class VideoFormatTests(unittest.TestCase):
    def test_portrait_output_does_not_overwrite_landscape(self):
        self.assertEqual(video_formats.output_name("song.wav", "landscape"),
                         "song.mp4")
        self.assertEqual(video_formats.output_name("song.wav", "portrait"),
                         "song-short.mp4")

    def test_unknown_format_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown video format"):
            video_formats.get_video_format("square")


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

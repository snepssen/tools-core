from pathlib import Path
import sys
import tempfile
import unittest


TOOL = Path(__file__).resolve().parents[1] / "lyric-video-maker"
sys.path.insert(0, str(TOOL))

import track_assets  # noqa: E402


class TrackAssetTests(unittest.TestCase):
    def test_matches_companions_despite_separator_and_case_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            audio = folder / "B06 VoidKitty.wav"
            cover = folder / "B06 - Voidkitty.png"
            lyrics = folder / "B06 - Voidkitty.md"
            for path in (audio, cover, lyrics):
                path.write_text("", encoding="utf-8")
            matched = track_assets.resolve_track_assets(str(audio))
        self.assertEqual(matched["cover"], str(cover))
        self.assertEqual(matched["lyrics"], str(lyrics))

    def test_suno_markdown_becomes_clean_sung_lines(self):
        source = """Red Aura

[Intro — spoken low]
Hello... (there)! *Wake* up?
[Verse 1]
Don't look — just listen.

Suno style tags
This prompt must not appear

Negative tags
Nor this
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Red Aura.md"
            path.write_text(source, encoding="utf-8")
            track = track_assets.parse_track_lyrics(path)
        self.assertEqual(track["title"], "Red Aura")
        self.assertEqual(track["lines"],
                         ["Hello there Wake up", "Don't look just listen"])

    def test_folder_scan_is_recursive_and_sorted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "A").mkdir()
            (root / "B").mkdir()
            (root / "B" / "B01.wav").write_text("", encoding="utf-8")
            (root / "A" / "A01.wav").write_text("", encoding="utf-8")
            found = track_assets.scan_audio_tree(str(root))
        self.assertEqual([Path(path).name for path in found],
                         ["A01.wav", "B01.wav"])


if __name__ == "__main__":
    unittest.main()

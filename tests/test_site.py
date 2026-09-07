from html.parser import HTMLParser
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "docs" / "index.html"


class SiteParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.fragments = []
        self.images_without_alt = []
        self.buttons_without_type = []
        self.inline_handlers = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            self.ids.append(values["id"])
        if tag == "a" and values.get("href", "").startswith("#"):
            self.fragments.append(values["href"][1:])
        if tag == "img" and not values.get("alt"):
            self.images_without_alt.append(values.get("src", "unknown"))
        if tag == "button" and values.get("type") != "button":
            self.buttons_without_type.append(values.get("id", "unnamed"))
        self.inline_handlers.extend(name for name, _ in attrs if name.startswith("on"))


class SiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = SITE.read_text(encoding="utf-8")
        cls.parser = SiteParser()
        cls.parser.feed(cls.html)

    def test_ids_are_unique_and_fragments_resolve(self):
        self.assertEqual(len(self.parser.ids), len(set(self.parser.ids)))
        self.assertEqual(set(self.parser.fragments) - set(self.parser.ids), set())

    def test_images_and_buttons_are_labelled(self):
        self.assertEqual(self.parser.images_without_alt, [])
        self.assertEqual(self.parser.buttons_without_type, [])

    def test_no_inline_event_handlers(self):
        self.assertEqual(self.parser.inline_handlers, [])

    def test_public_contact_and_projects_are_present(self):
        for text in ("Gateway Forge", "Voice Forge", "tools-core", "snepssen@proton.me"):
            self.assertIn(text, self.html)


class FaceDemoTests(unittest.TestCase):
    """The face demo plays the renderer's own frames, not a copy of them."""

    @classmethod
    def setUpClass(cls):
        cls.loop = (ROOT / "docs" / "face-loop.js").read_text(encoding="utf-8")
        cls.html = SITE.read_text(encoding="utf-8")
        cls.script = (ROOT / "docs" / "site.js").read_text(encoding="utf-8")

    def test_the_frames_ship_as_a_script_not_a_fetch(self):
        # The page declares connect-src 'none'. Keeping it that way is worth
        # more than the convenience of fetching a JSON file.
        self.assertIn("connect-src 'none'", self.html)
        self.assertNotIn("fetch(", self.script)
        self.assertIn("face-loop.js", self.html)
        self.assertIn("window.FACE_LOOP", self.loop)

    def test_the_frames_load_before_the_script_that_uses_them(self):
        self.assertLess(self.html.index("face-loop.js"),
                        self.html.index("site.js"))

    def test_the_loop_holds_real_geometry(self):
        import json

        data = json.loads(self.loop[self.loop.index("=") + 1:]
                          .rstrip().rstrip(";"))
        self.assertGreater(len(data["frames"]), 30)
        self.assertGreater(data["fps"], 0)
        for frame in data["frames"]:
            self.assertEqual(len(frame), 3)          # two eyes and a mouth
            for shape in frame:
                self.assertGreaterEqual(len(shape), 6)
                self.assertEqual(len(shape) % 2, 0)

    def test_the_mouth_actually_moves_across_the_loop(self):
        import json

        data = json.loads(self.loop[self.loop.index("=") + 1:]
                          .rstrip().rstrip(";"))
        heights = []
        for frame in data["frames"]:
            ys = frame[2][1::2]
            heights.append(max(ys) - min(ys))
        self.assertGreater(max(heights) - min(heights), 20)

    def test_the_face_canvas_scales_instead_of_overflowing(self):
        # Its drawing buffer is a fixed 520x230. Left at that size the element
        # is wider than the stage that centres it, so it hangs off the right
        # — the face looks off centre even though it is centred in the canvas.
        rule = [line for line in self.html.splitlines()
                if "#faceCanvas {" in line]
        self.assertTrue(rule, "#faceCanvas needs a sizing rule")
        style = rule[0]
        self.assertIn("width: 100%", style)
        self.assertIn("height: auto", style)
        self.assertIn("max-width", style)

    def test_the_demo_stops_when_the_tab_is_hidden(self):
        self.assertIn("visibilitychange", self.script)


if __name__ == "__main__":
    unittest.main()

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


if __name__ == "__main__":
    unittest.main()

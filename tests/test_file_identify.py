"""file-identify: auto-sort's identifier, run on its own.

The engine is a copy and must stay one; the command must say what a file is
from its bytes, and must leave everything it looks at exactly as it was.
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "file-identify"


def png(path, width=640, height=480):
    def chunk(name, payload):
        return (struct.pack(">I", len(payload)) + name + payload
                + struct.pack(">I", zlib.crc32(name + payload) & 0xffffffff))
    body = (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2,
                                         0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\0" * 16))
            + chunk(b"IEND", b""))
    Path(path).write_bytes(body)


def docx(path, title):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>%s</w:t>'
            "</w:r></w:p></w:body></w:document>" % title)
        archive.writestr(
            "docProps/core.xml",
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/'
            'package/2006/metadata/core-properties" xmlns:dc="http://purl.org'
            '/dc/elements/1.1/"><dc:title>%s</dc:title></cp:coreProperties>'
            % title)


class FileIdentify(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="file-identify-")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_tool(self, *arguments):
        return subprocess.run(
            [sys.executable, str(TOOL / "identify-file.py"), *arguments],
            capture_output=True, text=True, timeout=120)

    def facts(self, path):
        done = self.run_tool("--json", "--no-programs", path)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)["facts"]

    def test_the_bytes_decide_not_the_name(self):
        path = os.path.join(self.dir, "contract.docx")
        png(path)
        facts = self.facts(path)
        self.assertEqual(facts["kind"]["value"], "image")
        self.assertEqual(facts["format"]["value"], "png")
        self.assertTrue(facts["extension_lies"]["value"])
        self.assertEqual(facts["width"]["value"], 640)
        done = self.run_tool("--no-programs", path)
        self.assertIn("image/png", done.stdout)
        self.assertIn("named .docx", done.stdout)

    def test_a_document_is_read_for_what_it_calls_itself(self):
        path = os.path.join(self.dir, "download (3).docx")
        docx(path, "Tenancy Agreement")
        facts = self.facts(path)
        self.assertEqual(facts["kind"]["value"], "document")
        self.assertIn("Tenancy Agreement",
                      " ".join(str(facts[name]["value"]) for name in facts
                               if name in ("title", "heading", "doc_title")))

    def test_it_reads_and_changes_nothing(self):
        path = os.path.join(self.dir, "photo.png")
        png(path)
        before = os.stat(path)
        listing = sorted(os.listdir(self.dir))
        engine = sorted(p.name for p in (TOOL / "engine").iterdir())
        self.run_tool("--facts", path)
        after = os.stat(path)
        self.assertEqual((before.st_size, before.st_mtime_ns),
                         (after.st_size, after.st_mtime_ns))
        self.assertEqual(sorted(os.listdir(self.dir)), listing)
        self.assertEqual(sorted(p.name for p in (TOOL / "engine").iterdir()),
                         engine)

    def test_several_files_and_a_missing_one(self):
        first = os.path.join(self.dir, "a.png")
        png(first)
        done = self.run_tool("--json", "--no-programs", first,
                             os.path.join(self.dir, "not-there.pdf"))
        self.assertEqual(done.returncode, 1)
        self.assertIn("No such file", done.stderr)
        found = json.loads(done.stdout)
        self.assertEqual([entry["path"] for entry in found],
                         [os.path.abspath(first)])

    def test_the_engine_is_still_auto_sorts(self):
        done = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "from-auto-sort.py"),
             "--check", "--only", "file-identify"],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)


if __name__ == "__main__":
    unittest.main()

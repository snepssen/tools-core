"""tray-icon: auto-sort's tray, holding a menu of shell commands.

The engine is auto-sort's and tested there on every platform's terms; here
it must still be auto-sort's, and the command line must turn into the menu
it describes.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tray-icon"


def load():
    spec = importlib.util.spec_from_file_location("tray_icon",
                                                  TOOL / "tray-icon.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TheMenu(unittest.TestCase):

    def setUp(self):
        self.tool = load()
        self.parser_args = ["Backups", "--item", "Open", "true",
                            "--separator", "--item", "Back up now", "true"]

    def look(self, *extra):
        return self.tool.look_for(self.tool.build_parser().parse_args(
            self.parser_args + list(extra)))

    def labels(self, look):
        return [entry.label if entry else "-" for entry in look.entries]

    def test_entries_in_order_then_quit(self):
        look = self.look()
        self.assertEqual(self.labels(look),
                         ["Open", "-", "Back up now", "-", "Quit"])
        self.assertEqual(look.click, "run-0")
        self.assertEqual(look.title, "Backups")

    def test_the_click_can_be_chosen_or_left_to_the_menu(self):
        self.assertEqual(self.look("--click", "Back up now").click, "run-1")
        self.assertIsNone(self.look("--no-click").click)
        with self.assertRaises(SystemExit):
            self.look("--click", "Nothing like this")


class TheCommands(unittest.TestCase):

    def setUp(self):
        self.tool = load()
        self.dir = tempfile.mkdtemp(prefix="tray-icon-")
        self.said = []

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def wait(self, commands):
        for _ in range(100):
            commands.reap()
            if not commands.running:
                return
            time.sleep(0.05)
        self.fail("the commands never finished")

    def test_an_entry_runs_its_command_and_a_failure_is_said(self):
        marker = os.path.join(self.dir, "ran")
        commands = self.tool.Commands(
            [("Touch", "%s -c \"open(%r, 'w').close()\""
              % (sys.executable, marker)),
             ("Fail", "%s -c \"raise SystemExit(3)\"" % sys.executable)],
            output=self.said.append)
        actions = commands.actions()
        actions["run-0"]()
        actions["run-1"]()
        self.wait(commands)
        self.assertTrue(os.path.exists(marker))
        self.assertIn("  Fail exited with 3", self.said)
        self.assertFalse(commands.quit)
        actions["quit"]()
        self.assertTrue(commands.quit)


class TheWholeThing(unittest.TestCase):

    def test_it_puts_an_icon_up_and_takes_it_down(self):
        if sys.platform != "darwin":
            self.skipTest("an icon can be put up here only on macOS; Linux "
                          "and Windows are tested in auto-sort")
        process = subprocess.Popen(
            [sys.executable, str(TOOL / "tray-icon.py"), "tools-core test",
             "--item", "Nothing", "true"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            line = process.stdout.readline()
            self.assertIn("is in the menu bar", line)
            process.send_signal(signal.SIGTERM)
            self.assertEqual(process.wait(timeout=10), 0)
        finally:
            if process.poll() is None:
                process.kill()
            process.stdout.close()
            process.stderr.close()

    def test_the_engine_is_still_auto_sorts(self):
        done = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "from-auto-sort.py"),
             "--check", "--only", "tray-icon"],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)


if __name__ == "__main__":
    unittest.main()

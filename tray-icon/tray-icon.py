#!/usr/bin/env python3
"""Put an icon with a menu in the menu bar, notification area or panel.

    python3 tray-icon/tray-icon.py "Backups" \
        --item "Open the folder" "open ~/Backups" \
        --item "Back up now" "~/bin/backup.sh" \
        --separator \
        --item "Show the log" "open ~/Backups/backup.log"

Each `--item LABEL COMMAND` is a menu entry that runs COMMAND in the shell
when it is chosen; `--separator` draws a line. A left click runs the first
entry, or the one named by `--click`; `--no-click` makes a left click show
the menu instead. A Quit entry is always added at the end, and Ctrl-C in
the terminal does the same.

Commands run in the background, so a slow one does not freeze the menu, and
their output comes out in this terminal. Nothing is installed: on macOS the
icon is made through the Objective-C runtime, on Windows through the Win32
shell, and on Linux it is a StatusNotifierItem spoken over D-Bus -- all with
the standard library. The code in `engine/` is auto-sort's own tray, copied
unchanged (see scripts/from-auto-sort.py).
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "engine"))
sys.dont_write_bytecode = True

import tray                                              # noqa: E402

QUIT = "quit"


class Commands(object):
    """The menu's actions: each entry's command, run without waiting."""

    def __init__(self, entries, output=print):
        self.entries = entries
        self.output = output
        self.running = []
        self.quit = False

    def actions(self):
        found = {QUIT: self._quit}
        for number, (label, command) in enumerate(self.entries):
            found["run-%d" % number] = (
                lambda label=label, command=command: self.run(label, command))
        return found

    def run(self, label, command):
        self.output("> %s: %s" % (label, command))
        try:
            process = subprocess.Popen(command, shell=True)
        except OSError as error:
            self.output("  could not start it: %s" % error)
            return
        self.running.append((label, process))

    def reap(self):
        """Say which commands have finished badly, and forget them all."""
        still = []
        for label, process in self.running:
            code = process.poll()
            if code is None:
                still.append((label, process))
            elif code != 0:
                self.output("  %s exited with %d" % (label, code))
        self.running = still

    def _quit(self):
        self.quit = True


def look_for(options):
    """The Look the engine draws, from the command line's entries."""
    drawn, number, click = [], 0, None
    for entry in options.entries or []:
        if entry is None:
            drawn.append(None)
            continue
        label, _command = entry
        action = "run-%d" % number
        drawn.append(tray.Entry(action, label))
        if options.click is None and click is None:
            click = action
        if options.click == label:
            click = action
        number += 1
    if options.click is not None and not any(
            item and item.label == options.click for item in drawn):
        raise SystemExit("--click %r is not one of the entries"
                         % options.click)
    if drawn and drawn[-1] is not None:
        drawn.append(None)
    drawn.append(tray.Entry(QUIT, "Quit"))
    return tray.Look(options.title, drawn,
                     click=None if options.no_click else click,
                     status=options.status or "", status_paused="",
                     symbol=options.symbol, icon=options.icon)


def build_parser():
    parser = argparse.ArgumentParser(
        description="An icon with a menu, whose entries run commands.")
    parser.add_argument("title", help="the icon's name, shown as its tooltip")
    parser.add_argument("--item", dest="entries", action="append", nargs=2,
                        metavar=("LABEL", "COMMAND"),
                        help="a menu entry that runs COMMAND in the shell")
    parser.add_argument("--separator", dest="entries", action="append_const",
                        const=None, help="a line between entries")
    click = parser.add_mutually_exclusive_group()
    click.add_argument("--click", metavar="LABEL",
                       help="the entry a left click runs (default: the "
                            "first)")
    click.add_argument("--no-click", action="store_true",
                       help="a left click shows the menu")
    parser.add_argument("--status", help="a second tooltip line, on Linux")
    parser.add_argument("--symbol", default="terminal",
                        help="macOS: an SF Symbol name (default: terminal)")
    parser.add_argument("--icon", default="utilities-terminal",
                        help="Linux: a freedesktop icon name (default: "
                             "utilities-terminal)")
    return parser


def main(argv=None):
    parser = build_parser()
    options = parser.parse_args(argv)
    # A log of what was chosen is only useful as it happens, and a pipe or
    # a file would otherwise hold it back until the icon quits.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    entries = [entry for entry in options.entries or [] if entry is not None]
    if len(entries) > tray.Look.MAX_ENTRIES - 2:
        parser.error("at most %d entries" % (tray.Look.MAX_ENTRIES - 2))

    commands = Commands(entries)
    look = look_for(options)
    icon = tray.create(commands.actions(), look)
    if isinstance(icon, tray.UnavailableTray):
        print("No tray icon: %s" % icon.reason, file=sys.stderr)
        return 1
    if not icon.available:
        # Linux, with no panel hosting icons yet: it waits for one.
        print(icon.reason)
    print("%s is in the %s. Quit from its menu, or press Ctrl-C here."
          % (options.title, "menu bar" if sys.platform == "darwin"
             else "notification area" if sys.platform.startswith("win")
             else "panel"))

    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: commands._quit())
    try:
        while not commands.quit:
            started = time.monotonic()
            icon.pump(0.25)
            commands.reap()
            # Windows answers what is queued and returns at once; the other
            # two wait for the next click. Either way, never spin.
            if time.monotonic() - started < 0.02:
                time.sleep(0.05)
    except KeyboardInterrupt:
        print()
    finally:
        icon.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

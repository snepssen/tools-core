# tray-icon

An icon with a menu in the macOS menu bar, the Windows notification area or
a Linux panel, whose entries run shell commands. Nothing to install.

```sh
python3 tray-icon/tray-icon.py "Backups" \
    --item "Open the folder" "open ~/Backups" \
    --item "Back up now" "~/bin/backup.sh" \
    --separator \
    --item "Show the log" "open ~/Backups/backup.log"
```

- `--item LABEL COMMAND` adds a menu entry that runs COMMAND in the shell.
  Commands run in the background, so a slow one does not freeze the menu,
  and their output appears in the terminal the icon was started from. One
  that fails says so there.
- `--separator` draws a line between entries.
- A left click runs the first entry, or the one `--click LABEL` names.
  `--no-click` makes a left click open the menu instead.
- A Quit entry is always added at the end. Ctrl-C in the terminal, or a
  `kill`, does the same.
- `--symbol` picks the macOS icon from the SF Symbols set (default
  `terminal`); `--icon` a freedesktop icon name on Linux (default
  `utilities-terminal`). Windows shows the shell's icon for a plain file.
- `--status` is a second tooltip line, where Linux panels show one.

It runs for as long as the terminal command does. To keep it after logging
out and in again, start it from whatever starts things at login: a
LaunchAgent on macOS, the Startup folder on Windows, an autostart `.desktop`
file on Linux.

## Where it has been seen

| | |
| --- | --- |
| macOS | Seen in the menu bar, daily, as auto-sort's icon. |
| Linux, KDE Plasma | Seen on a Steam Deck: icon, menu, and every entry. |
| Linux, other panels | Built to the StatusNotifierItem specification; not seen. GNOME shows these icons only with the AppIndicator extension, which Ubuntu ships and enables. |
| Windows | Built to the Win32 documentation and its structures checked against it, but not yet seen on a Windows desktop. |

If it does not appear, the message it prints says why: no session bus, no
panel hosting icons yet (it waits, and appears when one starts), or the
system refusing the icon.

## As a library

`engine/tray.py` is the whole thing, and it can be imported:

```python
import sys
sys.path.insert(0, "tray-icon/engine")
import tray

look = tray.Look("Backups", [
    tray.Entry("open", "Open the folder"),
    tray.Entry("pause", "Pause", paused_label="Resume"),
    None,                                     # a separator
    tray.Entry("quit", "Quit"),
], click="open")
icon = tray.create({"open": open_folder, "pause": toggle, "quit": stop}, look)
while running:
    icon.pump(0.25)       # answers clicks, runs callbacks, then returns
    icon.set_paused(paused)
icon.close()
```

No threads: the program calls `pump` from its own loop, and a click runs
its callback from inside that call. `set_paused(True)` shows each entry's
`paused_label` and badges the icon where the platform can. `create` never
raises; where there is no tray to be had it returns an object with the
same methods that does nothing, and says why in `reason`.

On Windows `pump` returns as soon as the queue is empty, so a loop that has
nothing else to wait on should sleep between calls, as `tray-icon.py` does.

## Where it comes from

This is [auto-sort](https://github.com/snepssen/auto-sort)'s tray icon.
`engine/` holds its `tray.py`, `dbuswire.py` (the D-Bus wire protocol,
spoken with sockets and `struct`) and `winapi.py` (the Win32 functions it
calls, with their signatures declared), copied unchanged;
`engine/MANIFEST.json` names the auto-sort commit and the hash of each.
It is never edited here: a fix goes into auto-sort and is copied across.

```sh
python3 scripts/from-auto-sort.py --from ~/code/auto-sort
python3 scripts/from-auto-sort.py --check
```

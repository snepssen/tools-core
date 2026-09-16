#!/usr/bin/env python3
"""Photograph the workshop's project pages, whole, in both themes.

    python3 site-capture/shoot-pages.py --root ~/code
    python3 site-capture/shoot-pages.py --root ~/code --only siphon
    python3 site-capture/shoot-pages.py --root ~/code --measure

`--root` is the directory holding the project repositories; each page is read
from `<root>/<slug>/docs`. The pages themselves are listed in pages.json, so
adding a project is one entry there.

Nothing is written into a repository: each `docs` directory is copied to a
staging area, and it is the copy that gets modified. It needs modifying
because a browser taking one photograph is not a visitor reading a page, and
almost everything below is a version of that.

**Two runs produce the same pictures.** That is the property worth having,
because the failures here are not crashes — they are a page that looks nearly
right. A screenshot in fallback type, or a figure that is an empty box, is
wrong in a way nobody notices until it is published. Each fix below was a
difference between two runs first.

  * **The theme is stamped, not hoped for.** Headless Chrome reports
    `prefers-color-scheme: light` whatever the machine is set to, so a dark
    page would never be photographed dark. Every stylesheet here defines
    `:root[data-theme="dark"]` and `:root[data-theme="light"]`, so stamping
    `<html>` gives both pictures from one page. siphon's figures are
    `<picture>` keyed on `prefers-color-scheme`, which the stamp does not
    reach, so the matching `<source>` is resolved by hand too — otherwise its
    light page is photographed carrying its dark screenshots.

  * **The fonts are fetched first.** They arrive from fonts.gstatic.com while
    the shutter is already open, and when they lose that race the page is
    photographed in fallback type: Gateway Forge came out 174px shorter that
    way, on one run in two.

  * **The pictures travel inside the page.** Declaring each image's intrinsic
    size stops the layout shifting, but a reserved box can still be empty when
    the shutter goes, and no amount of waiting fixes it — Chrome shoots when
    virtual time runs out, and virtual time does not wait for real reads. A
    `data:` URI is not fetched at all.

  * **The page is asked to hold still.** These pages fade their cards in on
    scroll and tools-core's hero pulses without stopping. Each stylesheet
    already describes the still version of itself under
    `prefers-reduced-motion`; this asks for it directly.

**The one thing left is the height.** The whole page is photographed by
opening a window as tall as the page, which changes what a viewport unit
means: tools-core's hero is `min-height: 77vh`, so in a 9192px window the hero
becomes 9192px tall and the page is one empty screen. Viewport units are
pinned to what they resolve to at the viewport in pages.json — but pinning the
CSS is not the whole story, because tools-core also sizes two canvases from
`window.innerHeight` in its own JavaScript, which no rewriting of CSS reaches.
Asking the page for `scrollHeight` gives an answer a few pixels either side of
the browser's, and sometimes no answer at all.

So the height is a number somebody measured and checked (`--measure` helps),
not one this script guesses. What the script does instead is **check its own
work**: after every capture it reads the foot of the image and says whether
the page ended where it was supposed to. An overshoot is trimmed; a page that
ran off the bottom is reported and the run exits non-zero. A wrong height is a
message rather than a quietly wrong picture.

What is left is a 163x4px strip of protoke's video controls, which is a moving
picture and will not hold still.

Pillow is needed for the check, the trim and the contact sheet. It is
optional: without it the captures are still taken, unverified, and the script
says so.
"""

import argparse
import base64
import http.server
import json
import mimetypes
import re
import shutil
import socketserver
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CATALOGUE = HERE / "pages.json"
PORT = 9412
SCALE = 1

CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
)

# How much background at the foot of a capture counts as overshooting the page.
SLACK = 24

try:
    from PIL import Image, ImageDraw
except ImportError:                                   # optional, see the docstring
    Image = ImageDraw = None


def chrome():
    for path in CHROME_CANDIDATES:
        if Path(path).is_file():
            return path
    raise SystemExit("No Chrome or Chromium to take screenshots with.")


# ---------------------------------------------------------------------------
# Staging: the copy that gets modified, so the repositories do not
# ---------------------------------------------------------------------------

def stage(root, pages, stage_dir, viewport):
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    width, height = viewport
    for page in pages:
        source = root / page["slug"] / "docs"
        if not (source / "index.html").is_file():
            raise SystemExit(f"No page at {source / 'index.html'}")
        target = stage_dir / page["slug"]
        shutil.copytree(source, target, ignore=shutil.ignore_patterns(
            "__pycache__", "*.py", "sections", ".git"))
        html = size_images(
            (target / "index.html").read_text(encoding="utf-8"), target)
        html = localise_fonts(html, target, stage_dir / ".fonts")
        html = inline_images(html, target)
        for theme in ("dark", "light"):
            (target / f"_{theme}.html").write_text(
                prepare(html, theme, height), encoding="utf-8")


# A current desktop Chrome, because Google Fonts serves a different stylesheet
# to browsers it does not recognise — woff2 to this one, truetype otherwise.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")


def fetch(url, cache):
    """Download once, and keep it, so a run of six pages is one set of fetches."""
    name = re.sub(r"[^A-Za-z0-9._-]", "_", url.split("/", 3)[-1])[-120:]
    path = cache / name
    if not path.is_file():
        cache.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(request, timeout=60) as response:
            path.write_bytes(response.read())
    return path


def localise_fonts(html, target, cache):
    """Serve the webfonts from beside the page instead of over the network.

    The fonts are half the reason these pages look the way they do, and they
    arrive from fonts.gstatic.com while the shutter is already open. When they
    lose that race the page is photographed in fallback type — Gateway Forge
    came out 174px shorter, which is a wrong picture rather than a different
    one. Fetched once, written next to the staged page, and linked locally,
    they are simply there before the first paint.

    Needs the network once per font file. Without it the remote link is left
    alone and the capture takes its chances, which is said out loud.
    """
    links = re.findall(r'<link rel="stylesheet" href="(https://fonts\.googleapis\.com/[^"]+)">',
                       html)
    if not links:
        return html
    fonts = target / "_fonts"
    fonts.mkdir(exist_ok=True)
    for index, link in enumerate(links):
        try:
            css = fetch(link.replace("&amp;", "&"), cache).read_text(encoding="utf-8")
            for remote in sorted(set(re.findall(r"url\((https://fonts\.gstatic\.com/[^)]+)\)",
                                                css))):
                local = fetch(remote, cache)
                shutil.copy(local, fonts / local.name)
                css = css.replace(remote, f"_fonts/{local.name}")
        except (urllib.error.URLError, OSError) as problem:
            print(f"  fonts: {target.name} keeps its remote stylesheet ({problem})",
                  file=sys.stderr)
            continue
        sheet = fonts / f"sheet{index}.css"
        sheet.write_text(css, encoding="utf-8")
        html = html.replace(f'<link rel="stylesheet" href="{link}">',
                            f'<link rel="stylesheet" href="_fonts/{sheet.name}">')
    return html


def png_size(path):
    """Width and height from a PNG's header, without needing Pillow."""
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        return None
    return (int.from_bytes(header[16:20], "big"),
            int.from_bytes(header[20:24], "big"))


def size_images(html, docs):
    """Give every local <img> its intrinsic size, so the layout cannot shift.

    An <img> with no width or height contributes no height until it has
    loaded, which makes the page's height depend on when each file happens to
    arrive — voice-forge's light capture came out 837px short exactly once
    because one of its four screenshots was still in flight. With the size
    declared the browser reserves the space immediately and the height is the
    same every run.
    """
    def add(match):
        tag = match.group(0)
        if " width=" in tag or " height=" in tag:
            return tag
        source = re.search(r'src="([^"]+)"', tag)
        if not source or source.group(1).startswith(("http:", "https:", "data:")):
            return tag
        size = png_size(docs / source.group(1))
        if not size:
            return tag
        return f'{tag[:-1].rstrip()} width="{size[0]}" height="{size[1]}">'

    return re.sub(r"<img\b[^>]*>", add, html)


def inline_images(html, docs):
    """Carry the screenshots in the page instead of fetching them.

    Declaring a size stops the layout moving, but it does not make the picture
    arrive: Chrome takes the shot when virtual time runs out, and virtual time
    does not wait for real reads, so a screenshot inside the page could still
    be an empty reserved box. Raising the budget cannot fix that — the budget
    is spent in milliseconds of real time. A data: URI is not fetched at all,
    so there is nothing left to lose the race.
    """
    def encode(match):
        attribute, path = match.group(1), match.group(2)
        if path.startswith(("http:", "https:", "data:")):
            return match.group(0)
        source = docs / path
        if not source.is_file():
            return match.group(0)
        kind = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        if not kind.startswith("image/"):
            return match.group(0)
        data = base64.b64encode(source.read_bytes()).decode("ascii")
        return f'{attribute}="data:{kind};base64,{data}"'

    # poster= as well as src=: protoke's demo video shows a poster frame, and
    # left to a fetch it sometimes had not arrived when the shutter went.
    return re.sub(r'\b(src|srcset|poster)="([^"]+)"', encode, html)


def prepare(html, theme, viewport_height):
    """One page, told what a browser would otherwise have decided for itself."""
    stamped, count = re.subn(r'<html lang="en">',
                             f'<html lang="en" data-theme="{theme}">', html, count=1)
    if not count:
        raise SystemExit('Could not stamp the theme: no <html lang="en"> to stamp.')

    # The <picture> sources the stamp cannot reach.
    if theme == "dark":
        stamped = stamped.replace('media="(prefers-color-scheme: dark)"', 'media="all"')
    else:
        stamped = re.sub(
            r'\s*<source srcset="[^"]*" media="\(prefers-color-scheme: dark\)">',
            "", stamped)

    # Viewport units, pinned to the viewport the page is being read at.
    def pin(match):
        return f"{round(float(match.group(1)) / 100 * viewport_height)}px"

    stamped = re.sub(r"([0-9.]+)(?:vh|svh|dvh|lvh)\b", pin, stamped)

    # Every page here fades its ecosystem cards in as they are scrolled to, and
    # tools-core's hero has a pulse that never stops. A photograph taken while
    # any of that is in flight is a photograph of a moment, not of the page, and
    # two runs then differ. Each stylesheet already describes the still version
    # of itself under prefers-reduced-motion; this asks for it directly, so the
    # capture is of the settled page and is the same every time.
    still = ("<style>*,*::before,*::after{animation:none !important;"
             "transition:none !important}"
             "[data-eco-reveal],[data-eco-reveal] *{opacity:1 !important;"
             "transform:none !important}</style>")
    return stamped.replace("</head>", f"{still}</head>", 1)


def serve(directory):
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(
        *a, directory=str(directory), **k)
    socketserver.TCPServer.allow_reuse_address = True
    server = socketserver.TCPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# ---------------------------------------------------------------------------
# Capture, and checking the capture
# ---------------------------------------------------------------------------

def shoot(url, out, width, height):
    subprocess.run(
        [chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars",
         f"--window-size={width},{height}",
         f"--force-device-scale-factor={SCALE}",
         # Wait for rendering to settle rather than photographing whenever
         # Chrome first calls the page ready. Without this the webfonts
         # sometimes arrive after the shutter and the page is captured in
         # fallback type — which is not just a different picture but a wrong
         # one: Gateway Forge came out 174px shorter that way.
         "--run-all-compositor-stages-before-draw",
         "--virtual-time-budget=15000",
         f"--screenshot={out}", url],
        capture_output=True, timeout=300)
    return out.is_file() and out.stat().st_size > 0


def background_tail(image):
    """How many rows at the foot of the image are nothing but page background."""
    ground = image.getpixel((image.width - 2, image.height - 2))
    for y in range(image.height - 1, -1, -1):
        row = image.crop((0, y, image.width, y + 1))
        if row.getcolors(maxcolors=4) != [(image.width, ground)]:
            return image.height - (y + 1)
    return image.height


def verify(path, trim=True):
    """Say whether the page ended where the catalogue said it would."""
    if Image is None:
        return "not checked (no Pillow)"
    with Image.open(path) as opened:
        image = opened.convert("RGB")
        tail = background_tail(image)
        if tail == 0:
            return "CUT OFF — the page runs past the recorded height"
        if tail <= SLACK:
            return "ends cleanly"
        if not trim:
            return f"{tail}px of blank below the page"
        image.crop((0, 0, image.width, image.height - tail + SLACK)).save(path)
        return f"trimmed {tail - SLACK}px of blank"


def measure(stage_dir, pages, viewport):
    """Report each page's height, for checking by eye before it is recorded.

    Deliberately not wired into the capture: read what it prints, look at the
    page, and paste the number into pages.json yourself. See the docstring for
    why a discovered height is not to be trusted.
    """
    width, height = viewport
    probe = ('<script>(function(){function m(){document.documentElement'
             '.setAttribute("data-page-height",document.documentElement.scrollHeight);}'
             'm();addEventListener("load",m);'
             'if(document.fonts&&document.fonts.ready)document.fonts.ready.then(m);'
             'setTimeout(m,2000);})();</script>')
    for page in pages:
        source = stage_dir / page["slug"] / "_dark.html"
        target = stage_dir / page["slug"] / "_measure.html"
        target.write_text(source.read_text(encoding="utf-8")
                          .replace("</body>", probe + "</body>"), encoding="utf-8")
        dom = subprocess.run(
            [chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars",
             f"--window-size={width},{height}", "--virtual-time-budget=8000",
             "--dump-dom", f"http://127.0.0.1:{PORT}/{page['slug']}/_measure.html"],
            capture_output=True, text=True, timeout=180).stdout
        found = re.search(r'data-page-height="(\d+)"', dom)
        reading = int(found.group(1)) if found else None
        recorded = page["height"]
        if reading is None:
            note = "no reading — measure this one in a real browser"
        elif abs(reading - recorded) <= 4:
            note = "agrees with pages.json"
        else:
            note = f"pages.json says {recorded} ({reading - recorded:+d})"
        print(f"  {page['slug']:18} {str(reading):>7}  {note}")


# ---------------------------------------------------------------------------
# Contact sheet
# ---------------------------------------------------------------------------

def contact_sheet(out_dir, pages, theme, width, fold=1180, cols=3, tile=470):
    if Image is None:
        return None
    pad, label = 18, 26
    tiles = []
    for page in pages:
        path = out_dir / f"{page['slug']}-page-{theme}.png"
        if not path.is_file():
            continue
        with Image.open(path) as opened:
            image = opened.convert("RGB")
            top = image.crop((0, 0, image.width, min(fold, image.height)))
            tiles.append((page["slug"],
                          top.resize((tile, round(top.height * tile / top.width)),
                                     Image.LANCZOS)))
    if not tiles:
        return None
    rows = [tiles[i:i + cols] for i in range(0, len(tiles), cols)]
    row_heights = [max(t.height for _, t in row) + label for row in rows]
    sheet = Image.new(
        "RGB",
        (cols * tile + (cols + 1) * pad, sum(row_heights) + (len(rows) + 1) * pad),
        (14, 14, 14) if theme == "dark" else (238, 236, 228))
    ink = (235, 235, 235) if theme == "dark" else (30, 30, 30)
    draw = ImageDraw.Draw(sheet)
    y = pad
    for row, row_height in zip(rows, row_heights):
        x = pad
        for slug, image in row:
            draw.text((x + 1, y), slug, fill=ink)
            sheet.paste(image, (x, y + label))
            x += tile + pad
        y += row_height + pad
    path = out_dir / f"_contact-sheet-{theme}.png"
    sheet.save(path)
    return path


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", required=True, type=Path,
                        help="directory holding the project repositories")
    parser.add_argument("--out", type=Path, default=Path("page-shots"),
                        help="where to write the images (default: ./page-shots)")
    parser.add_argument("--only", action="append", metavar="SLUG",
                        help="capture just this page; repeatable")
    parser.add_argument("--measure", action="store_true",
                        help="report page heights instead of capturing")
    parser.add_argument("--no-trim", action="store_true",
                        help="report an overshoot without correcting it")
    args = parser.parse_args()

    catalogue = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    viewport = catalogue["viewport"]
    pages = catalogue["pages"]
    if args.only:
        wanted = set(args.only)
        pages = [p for p in pages if p["slug"] in wanted]
        missing = wanted - {p["slug"] for p in pages}
        if missing:
            raise SystemExit(f"Not in pages.json: {', '.join(sorted(missing))}")
    if not pages:
        raise SystemExit("No pages to capture.")

    root = args.root.expanduser().resolve()
    out_dir = args.out.expanduser().resolve()
    stage_dir = out_dir / ".staging"
    out_dir.mkdir(parents=True, exist_ok=True)

    stage(root, pages, stage_dir, viewport)
    server = serve(stage_dir)
    width = viewport[0]
    try:
        if args.measure:
            print(f"Heights at {width}px wide:")
            measure(stage_dir, pages, viewport)
            return 0

        if Image is None:
            print("Pillow is not installed: captures will not be checked or"
                  " trimmed, and no contact sheet will be made.\n",
                  file=sys.stderr)

        failed = False
        for page in pages:
            for theme in ("dark", "light"):
                out = out_dir / f"{page['slug']}-page-{theme}.png"
                url = f"http://127.0.0.1:{PORT}/{page['slug']}/_{theme}.html"
                if not shoot(url, out, width, page["height"]):
                    print(f"  {out.name:34} FAILED", file=sys.stderr)
                    failed = True
                    continue
                note = verify(out, trim=not args.no_trim)
                if "CUT OFF" in note:
                    failed = True
                size = out.stat().st_size // 1024
                print(f"  {out.name:34} {size:>5} KB   {note}")

        for theme in ("dark", "light"):
            sheet = contact_sheet(out_dir, pages, theme, width)
            if sheet:
                print(f"  {sheet.name:34} {sheet.stat().st_size // 1024:>5} KB")
        return 1 if failed else 0
    finally:
        server.shutdown()
        shutil.rmtree(stage_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Move a project page's webfonts out of Google and into its own repository.

    python3 site-fonts/self-host.py --root ~/code --dry-run
    python3 site-fonts/self-host.py --root ~/code
    python3 site-fonts/self-host.py --root ~/code --only voice-forge

Finds every page under `--root` that fetches its type from fonts.googleapis.com,
downloads what that page actually uses into `docs/fonts/`, writes a
`docs/fonts.css` beside it, and points the page at that instead.

Why bother: a page that loads its fonts from Google tells Google who is reading
it, on every visit, including the reader's address and the page they are on.
These pages are otherwise local-first to the point of having no analytics at
all, so the type was the only thing reporting back.

**Google's own stylesheet is kept, not rewritten.** Each `@font-face` block is
copied across exactly as served — `font-weight` ranges, `font-stretch`,
`font-variation-settings` for the optical-size axes that Fraunces, Newsreader
and Bricolage Grotesque are requested with — and only the `url()` is changed.
Reproducing those by hand is how a self-hosting job quietly loses an italic or
flattens a variable axis.

**Only the cuts the page can use are kept.** Google serves a family divided
into latin, latin-ext, cyrillic, greek and vietnamese, each guarded by a
`unicode-range`, and a browser downloads only the ones its text needs. Copied
wholesale, that is most of a megabyte of Cyrillic per repository that no
reader will ever ask for, so each block is tested and dropped if it has
nothing to set. The `unicode-range` is copied across with the block, so a
character that turns up later and falls outside what was kept falls back down
the stack rather than rendering wrongly.

**The test asks the page, not its source.** Which is the whole reason this is
a program rather than a judgement call. Read statically, every page here looks
like it needs latin-ext: they all carry Voice Forge's card in the ecosystem
grid, and that card's glyph is the IPA for "hello" — həˈləʊ — whose
characters are latin-ext, not latin. Keeping it on those grounds adds about
1.8 MB across the five repositories for three characters that never touch a
webfont: the glyph is set in `ui-monospace`, and Voice Forge's own masthead
IPA is set in Doulos SIL. So the page is loaded in a browser and asked which
family it sets each character in, and the answer is believed over the markup.
"""

import argparse
import re
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Google serves a different stylesheet to browsers it does not recognise:
# woff2 and variable axes to this one, truetype to anything older.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

GOOGLE_CSS = re.compile(r"https://fonts\.googleapis\.com/css2\?[^\"')]+")
FACE = re.compile(r"(?:/\*\s*([a-z0-9-]+)\s*\*/\s*)?(@font-face\s*\{.*?\})", re.S)
URL_IN_FACE = re.compile(r"url\((https://fonts\.gstatic\.com/[^)]+)\)")
RANGE_IN_FACE = re.compile(r"unicode-range:\s*([^;}]+)")


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def parse_ranges(text):
    """`U+0000-00FF, U+0131` into a list of (first, last) codepoints."""
    spans = []
    for piece in text.split(","):
        piece = piece.strip().removeprefix("U+").removeprefix("u+")
        if not piece:
            continue
        if "-" in piece:
            low, high = piece.split("-", 1)
            spans.append((int(low, 16), int(high, 16)))
        elif "?" in piece:                       # U+00?? style wildcard
            spans.append((int(piece.replace("?", "0"), 16),
                          int(piece.replace("?", "F"), 16)))
        else:
            spans.append((int(piece, 16), int(piece, 16)))
    return spans


PROBE = r"""
(function () {
  // Which characters are set in which family, asked of the page rather than
  // guessed from its source. Only the first name in each stack counts: that is
  // the family the author asked for, and the one a subset would be kept for.
  var perFamily = {};
  var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  var node;
  while ((node = walker.nextNode())) {
    var text = node.nodeValue;
    if (!text || !text.trim()) continue;
    var family = getComputedStyle(node.parentElement).fontFamily
                   .split(",")[0].replace(/['"]/g, "").trim();
    perFamily[family] = (perFamily[family] || "") + text;
  }
  // Pseudo-element content too: these pages draw arrows and rules with it.
  document.querySelectorAll("*").forEach(function (el) {
    ["::before", "::after"].forEach(function (part) {
      var cs = getComputedStyle(el, part);
      var content = cs.content;
      if (!content || content === "none" || content === "normal") return;
      var family = cs.fontFamily.split(",")[0].replace(/['"]/g, "").trim();
      perFamily[family] = (perFamily[family] || "") + content.replace(/^"|"$/g, "");
    });
  });
  var out = {};
  Object.keys(perFamily).forEach(function (f) {
    out[f] = Array.from(new Set(perFamily[f].split(""))).join("");
  });
  document.documentElement.setAttribute("data-font-use", JSON.stringify(out));
})();
"""


def characters_by_family(docs):
    """Ask a browser which characters each font family is actually asked to set.

    Scanning the source instead gets this badly wrong, and expensively: every
    page in this family carries Voice Forge's card in its ecosystem grid, and
    that card's glyph is the IPA for "hello". Read statically, those three
    characters pull the latin-ext cut of all three webfonts into every
    repository — about two megabytes across the set — when the glyph is set in
    ui-monospace and never touches a webfont at all.
    """
    import http.server, json, socketserver, subprocess, tempfile, threading
    chrome = next((p for p in (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/usr/bin/google-chrome", "/usr/bin/chromium",
        "/usr/bin/chromium-browser") if Path(p).is_file()), None)
    if not chrome:
        raise SystemExit("This needs Chrome or Chromium to ask the page what it sets.")

    with tempfile.TemporaryDirectory() as temporary:
        staged = Path(temporary) / "docs"
        shutil.copytree(docs, staged, ignore=shutil.ignore_patterns("__pycache__"))
        (staged / "_probe.js").write_text(PROBE, encoding="utf-8")
        page = (staged / "index.html").read_text(encoding="utf-8")
        (staged / "_probe.html").write_text(
            page.replace("</body>", '<script src="_probe.js"></script></body>'),
            encoding="utf-8")
        handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(
            *a, directory=str(staged), **k)
        # Port 0: the OS picks a free one. A fixed port meant the second
        # repository in a run could collide with the first one's socket before
        # it had let go, and the run died three pages in.
        socketserver.TCPServer.allow_reuse_address = True
        with socketserver.TCPServer(("127.0.0.1", 0), handler) as server:
            port = server.server_address[1]
            threading.Thread(target=server.serve_forever, daemon=True).start()
            dom = subprocess.run(
                [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                 "--window-size=1440,900", "--virtual-time-budget=8000", "--dump-dom",
                 f"http://127.0.0.1:{port}/_probe.html"],
                capture_output=True, text=True, timeout=180).stdout
            server.shutdown()
    found = re.search(r'data-font-use="([^"]*)"', dom)
    if not found:
        raise SystemExit(f"{docs}: the page did not report what it sets.")
    import html as html_module
    return json.loads(html_module.unescape(found.group(1)))


FAMILY_IN_FACE = re.compile(r"font-family:\s*['\"]?([^;'\"]+)")


def wanted(block, usage):
    """Whether this cut of this family has anything on the page to set."""
    family = FAMILY_IN_FACE.search(block)
    characters = usage.get(family.group(1).strip(), "") if family else ""
    if not characters:
        return False
    found = RANGE_IN_FACE.search(block)
    if not found:
        return True                    # no range given: it covers everything
    spans = parse_ranges(found.group(1))
    return any(low <= ord(c) <= high for c in characters for low, high in spans)


STRING = re.compile(r'"(?:[^"\\]|\\.)*"')


def catalogue_fonts(page_py):
    """What the catalogue really says, by importing it rather than reading it.

    siphon writes the URL as three adjacent string literals inside a constant,
    which Python joins and a regex does not: scraped, it came back as Space
    Grotesk alone, and this tool cheerfully offered to self-host a third of
    that page's type. The catalogue is a module; ask the module.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("page", page_py)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PAGE["meta"].get("fonts", "")


def replace_url(text, url, replacement='"fonts.css"'):
    """Swap the URL for a literal, however many pieces it was written in."""
    start = text.find('"' + url[:40])
    if start < 0:
        return None
    joined, position = "", start
    while position < len(text):
        match = STRING.match(text, position)
        if not match:
            break
        joined += match.group(0)[1:-1]
        position = match.end()
        if joined == url:
            return text[:start] + replacement + text[position:]
        gap = re.match(r"[\s]*", text[position:])          # only whitespace may
        position += gap.end()                               # separate the pieces
    return None


def source_url(docs):
    """The Google stylesheet this page's type came from, for a re-run."""
    local = docs / "fonts.css"
    if local.is_file():
        found = GOOGLE_CSS.search(local.read_text(encoding="utf-8"))
        if found:
            return found.group(0)
    return None


def find_link(docs):
    """The Google stylesheet, and the file that names it."""
    page_py = docs / "page.py"
    if page_py.is_file():
        url = catalogue_fonts(page_py)
        if url.startswith("https://fonts.googleapis.com"):
            return page_py, url
        return None, None
    index = docs / "index.html"
    if index.is_file():
        found = GOOGLE_CSS.search(index.read_text(encoding="utf-8"))
        if found:
            return index, found.group(0)
    return None, None


def self_host(docs, dry_run):
    source, url = find_link(docs)
    if not url:
        return f"already self-hosted" if (docs / "fonts.css").is_file() else "no webfonts"

    css = fetch(url.replace("&amp;", "&")).decode("utf-8")
    usage = characters_by_family(docs)
    blocks, kept, dropped, total = [], 0, [], 0

    for subset, block in FACE.findall(css):
        if not wanted(block, usage):
            dropped.append(subset or "?")
            continue
        remote = URL_IN_FACE.search(block)
        if not remote:
            continue
        data = fetch(remote.group(1))
        name = f"{remote.group(1).rsplit('/', 1)[-1].split('?')[0]}"
        if not dry_run:
            (docs / "fonts").mkdir(exist_ok=True)
            (docs / "fonts" / name).write_bytes(data)
        blocks.append(block.replace(remote.group(1), f"fonts/{name}"))
        kept += 1
        total += len(data)

    if dry_run:
        return (f"{kept} faces, {total / 1024:.0f} KB"
                + (f"; would drop {', '.join(sorted(set(dropped)))}" if dropped else ""))

    header = (
        "/* The type this page uses, served from this repository.\n"
        " *\n"
        " * Written by tools-core/site-fonts/self-host.py, which copies each\n"
        " * @font-face across from Google's own stylesheet exactly as served and\n"
        " * changes only the url(). Do not hand-edit: re-run the tool.\n"
        " *\n"
        " * Loading these from fonts.googleapis.com told Google the address of\n"
        " * everyone who read the page. These pages have no analytics of any\n"
        " * kind, so the type was the last thing reporting back.\n"
        " *\n"
        f" * From: {url}\n"
        " */\n\n")
    (docs / "fonts.css").write_text(header + "\n\n".join(blocks) + "\n", encoding="utf-8")

    text = source.read_text(encoding="utf-8")
    if source.name == "page.py":
        replaced = replace_url(text, url)
        if replaced is None:
            raise SystemExit(
                f"{source}: found the URL by importing the catalogue but could not "
                f"locate the literal to replace. Set its 'fonts' to \"fonts.css\" by hand.")
        text = replaced
    else:
        text = re.sub(r'\s*<link rel="preconnect" href="https://fonts\.[^"]*"[^>]*>', "", text)
        text = text.replace(url, "fonts.css")
    source.write_text(text, encoding="utf-8")

    note = f"{kept} faces, {total / 1024:.0f} KB"
    if dropped:
        note += f"; dropped {', '.join(sorted(set(dropped)))}"
    return note


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", required=True, type=Path,
                        help="directory holding the project repositories")
    parser.add_argument("--only", action="append", metavar="SLUG",
                        help="just this repository; repeatable")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be downloaded and dropped")
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    repos = sorted(p for p in root.iterdir() if (p / "docs" / "index.html").is_file())
    if args.only:
        repos = [p for p in repos if p.name in set(args.only)]
    if not repos:
        raise SystemExit("Nothing with a docs/index.html under that root.")

    failed = False
    for repo in repos:
        try:
            print(f"  {repo.name:18} {self_host(repo / 'docs', args.dry_run)}")
        except (urllib.error.URLError, OSError) as problem:
            print(f"  {repo.name:18} FAILED: {problem}", file=sys.stderr)
            failed = True
    if not args.dry_run:
        print("\nRebuild the generated pages, then check them:"
              "\n  python3 docs/build.py   (or docs/sync.py for the hub)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

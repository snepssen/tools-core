# site-fonts

Moves a project page's webfonts out of Google and into its own repository.

```sh
python3 site-fonts/self-host.py --root ~/code --dry-run
python3 site-fonts/self-host.py --root ~/code
python3 site-fonts/self-host.py --root ~/code --only voice-forge
```

`--root` is the directory holding the project repositories. Every page under it
that fetches type from fonts.googleapis.com gets the faces it actually uses
downloaded into `docs/fonts/`, a `docs/fonts.css` written beside them, and its
own reference pointed at that instead — the catalogue entry for a generated
page, the `<link>` for a hand-written one. Rebuild afterwards.

## Why

A page that loads its type from Google tells Google who is reading it: the
reader's address, and which page, on every visit. These pages have no
analytics, no trackers and no cookies, so the fonts were the only thing
reporting back. tools-core said so in its own footer while doing it.

## What it will not get wrong

**Google's stylesheet is copied, not reconstructed.** Each `@font-face` block
is taken across exactly as served — weight ranges, `font-stretch`, the
`font-variation-settings` that carry the optical-size axes Fraunces, Newsreader
and Bricolage Grotesque are requested with — and only the `url()` changes.
Retyping those by hand is how a self-hosting job quietly loses an italic.

**Only the cuts the page can use are kept**, and the test asks the page rather
than reading it. Statically, all five pages look like they need latin-ext:
each carries Voice Forge's card in the shared ecosystem grid and that card's
glyph is həˈləʊ, whose characters are latin-ext. Keeping it on that evidence
adds about 1.8 MB across the set for three characters that never touch a
webfont — the glyph is set in `ui-monospace`, and Voice Forge's own masthead
IPA is set in Doulos SIL. So the page is loaded in a browser and asked which
family it sets each character in. That took the five repositories from 3.9 MB
of fonts to 904 KB.

The `unicode-range` travels with each block it keeps, so a character that
appears later and falls outside the kept cuts falls back down the stack rather
than rendering wrongly.

## Checking it worked

The failure mode is silent — a page in fallback type looks fine until you know
the shapes. Worth doing after a run:

```sh
python3 ../site-capture/shoot-pages.py --root ~/code
```

and comparing against the previous captures. When these five were converted,
eleven of twelve were pixel-identical; the twelfth differed only in protoke's
video controls, which never hold still.

## Requirements

Python 3, and Chrome or Chromium for the which-family-sets-what question. The
network, once, to fetch the fonts.

# site-capture

Photographs the workshop's project pages — whole, top to bottom, in both
themes — so they can be reviewed side by side without opening six tabs.

```sh
python3 site-capture/shoot-pages.py --root ~/code
python3 site-capture/shoot-pages.py --root ~/code --only siphon --only protoke
python3 site-capture/shoot-pages.py --root ~/code --measure
```

`--root` is the directory holding the project repositories; each page is read
from `<root>/<slug>/docs`. Images land in `./page-shots` unless `--out` says
otherwise: one PNG per page per theme, 1440px wide, plus a contact sheet of
every page above the fold.

Nothing is written into any repository. Each `docs` directory is copied to a
staging area and the copy is what gets modified; the staging area is removed
afterwards.

## Adding a page

One entry in [`pages.json`](pages.json):

```json
{ "slug": "new-project", "height": 12345 }
```

`height` is the page's full height in CSS pixels at the viewport named at the
top of that file. Get it with `--measure`, **look at what it prints**, and
paste it in. It is recorded rather than discovered because a page does not
have one height — see below.

## Why a screenshot needs this much help

A browser taking one photograph is not a visitor reading a page. Left alone,
headless Chrome will photograph a page in fallback type, with empty boxes
where the figures go, mid-fade, and in the wrong theme — each of which looks
close enough to right to be published by mistake.

So the staged copy is told what a real visit would have worked out: the theme
is stamped on `<html>` (Chrome always reports `prefers-color-scheme: light`),
the webfonts are downloaded and served locally, the images are carried in the
page as `data:` URIs, and animations are stopped the way each stylesheet
already defines under `prefers-reduced-motion`.

tools-core sets a Content-Security-Policy, so anything staged in is written
beside the page where `'self'` covers it, and the one clause widened is
`data:` for `img-src`. Nothing is removed from the policy: a resource the real
page would refuse is still refused here.

Two runs produce the same bytes, for every page but protoke, where a
four-pixel strip of video controls will not hold still. That comparison is
what catches races — but not everything. The webfonts spent a while being
fetched to a path one directory too deep, 404ing every one of them and
putting every page back in fallback type, and two runs agreed about it
perfectly. Look at a heading occasionally.

## The height, and why it is written down

The whole page is captured by opening a window as tall as the page, which
changes what a viewport unit means. tools-core's hero is `min-height: 77vh`:
in a 9192px window it becomes 9192px tall and the page is one empty screen.
Viewport units are pinned before capture to fix that — but tools-core also
sizes two canvases from `window.innerHeight` in its own JavaScript, and no
rewriting of CSS reaches that. Asking the page for `scrollHeight` lands a few
pixels either side of the browser's answer, and sometimes returns nothing.

Rather than guess, the script checks its work. After each capture it reads the
foot of the image: an overshoot is trimmed, and a page that ran off the bottom
is reported and the run exits non-zero. A stale height in `pages.json` shows
up as a message instead of a silently cropped page.

## Requirements

Python 3 and Google Chrome or Chromium. Pillow is optional and listed in
[`requirements/site-capture.txt`](../requirements/site-capture.txt); it is
what performs the check, the trim and the contact sheet. Without it the
captures are still taken, unverified, and the script says so.

Downloading the fonts needs the network once per font file. Without it each
page keeps its remote stylesheet, the capture takes its chances, and that is
printed too.

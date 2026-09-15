#!/usr/bin/env python3
"""Keep the shared regions of the hub page in step with the catalogue.

    python3 docs/sync.py            rewrites the rail and the grid in place
    python3 docs/sync.py --check    fails if either is out of date

The five project pages are generated whole from build.py, because they share a
masthead, a jump navigation and a section rhythm. This page does not: it is the
hub, with a hero, a site navigation, sections that each carry their own .wrap,
and no jump bar at all. Running it through the project-page generator would
mean teaching that generator five special cases that only this page ever uses,
which is the coupling the generator exists to avoid.

What this page does share is the project rail and the ecosystem grid — and
those are exactly the parts that go stale when a project is added or renamed.
So those two regions are rewritten from the same ecosystem.json and the same
build.py functions the other pages use, and everything else here stays hand-
written, which is what it wants to be.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build

HERE = Path(__file__).resolve().parent
PAGE = HERE / "index.html"
SLUG = "tools-core"


def replace(html, start, end, new):
    """Swap one region, matched by its opening and closing lines."""
    first = html.index(start)
    last = html.index(end, first) + len(end)
    return html[:first] + new + html[last:], html[first:last]


def sync(html, ecosystem):
    rail = build.reindent(build.rail(ecosystem, SLUG).strip("\n"), 2)
    html, _ = replace(html, '  <div class="ecosystem-progress"', "  </nav>\n", rail + "\n")

    inner = build.reindent(build.grid_inner(ecosystem, SLUG), 6)
    section = ('    <section class="ecosystem-more" aria-labelledby="ecosystem-heading"'
               ' data-eco-reveal>\n      <div class="wrap">\n'
               f"{inner}\n      </div>\n    </section>\n")
    html, _ = replace(html, '    <section class="ecosystem-more"',
                      "      </div>\n    </section>\n", section)
    return html


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="report drift instead of correcting it")
    args = parser.parse_args()

    current = PAGE.read_text(encoding="utf-8")
    wanted = sync(current, build.load_ecosystem())
    if current == wanted:
        print("docs/index.html matches the catalogue.")
        return 0
    if args.check:
        print("docs/index.html is out of date. Run: python3 docs/sync.py",
              file=sys.stderr)
        return 1
    PAGE.write_text(wanted, encoding="utf-8")
    print("docs/index.html — rail and ecosystem grid rewritten from the catalogue")
    return 0


if __name__ == "__main__":
    sys.exit(main())

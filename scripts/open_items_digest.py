#!/usr/bin/env python3
"""Turn OPEN_ITEMS.md into a one-page-first PDF digest of what needs the owner.

OPEN_ITEMS.md is the working list and it is long: 300 lines, eight sections,
closed items kept in place so an ID means the same thing next week. That is the
right shape for working from and the wrong shape for reading over coffee, which
is what this produces -- the items still open, the ones needing the owner first,
and what moved since the last run.

Nothing here decides what is open. The file's own conventions do:

  * A row whose Item cell opens with ~~struck text~~ is answered or closed --
    that is how the file records a close without renumbering. Everything else
    is open. A row that closed only PART of itself (B6, closed for Trade-out %
    and still open for two other KPIs) does not strike its cell, so it stays.
  * The "Live and uncertain" column is the file's own flag for an item the
    dashboard is publishing something against today. `yes` is the top block.
  * Section headings say who is blocked. OWNER_SECTIONS is that reading, with
    OWNER_ITEMS for the individual rows in a mixed section that are a click or
    an answer rather than pipeline work.

Usage:
    python scripts/open_items_digest.py                  # write the PDF
    python scripts/open_items_digest.py --html /tmp/d.html   # and the web copy
    python scripts/open_items_digest.py --print          # to stdout, no PDF
    python scripts/open_items_digest.py --no-state       # don't record the run

The state file is what lets tomorrow's digest say what changed. It is committed
for that reason: a scheduled run gets a fresh checkout, so an uncommitted state
file would make every morning look like the first one.

A 6am routine runs this daily, sends the PDF and republishes the web copy to
one fixed URL -- https://claude.ai/artifact/DMKnbsK1C4uPGijQaZV1VK -- so the
link keeps working while the contents move. That republish must always pass
that url; publishing without it makes a second artifact and the constant link
is the whole point of it.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "OPEN_ITEMS.md")
# Neither lands in docs/. That directory is what GitHub Pages serves, and the
# digest is a working note rather than part of the dashboard. The state file is
# committed (see the module docstring); the PDF is gitignored -- it is rebuilt
# from the markdown every run, so a binary in history would be 200KB a morning
# of something already fully described by the file beside it.
STATE = os.path.join(ROOT, "open_items_state.json")
OUT = os.path.join(ROOT, "open_items_digest.pdf")

# Sections whose every open row is the owner's: a file, an answer, or a click.
# B is EliseAI's answer, but chasing EliseAI is the owner's to do, so it reads
# as theirs on the digest and says who it is actually waiting on.
OWNER_SECTIONS = {"A", "B", "E", "F"}

# Rows in a mixed section that are the owner's anyway. C is mostly Drive
# housekeeping the pipeline can do; C5 is two IDs only the owner can set. G is
# work found while building, except G6, which is a question about the building.
OWNER_ITEMS = {"C5", "G6"}

# What each section is, in the digest's own words.
SECTION_BLURB = {
    "A": "a file, an answer, or a click only you can give",
    "B": "waiting on EliseAI — yours to chase",
    "C": "Drive housekeeping, surfaced by the pipeline logs",
    "D": "parsers not built; each needs one sample file",
    "E": "keeping data out of git history — built, not activated, strictly ordered",
    "F": "cosmetic, awaiting a yes/no",
    "G": "found while building the Drive-only Landing tab",
    "H": "how the scorecard actually refreshes",
}

# Chromium ships with the browsers Playwright manages here; there is no
# reportlab or wkhtmltopdf in this image. Print-to-PDF is what is actually
# installed, and it renders the stylesheet below rather than approximating it.
CHROME_CANDIDATES = [
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell",
    shutil.which("chromium") or "",
    shutil.which("chromium-browser") or "",
    shutil.which("google-chrome") or "",
]


# --------------------------------------------------------------------------
# reading the file


def find_chrome():
    for p in CHROME_CANDIDATES:
        if p and os.path.exists(p):
            return p
    return None


def split_cells(line):
    """A markdown table row into its cells, without the leading/trailing pipes.

    Item text carries `|` nowhere today, but it carries plenty of `**bold**`
    and inline code, so this stays a simple split rather than a parser.
    """
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse(path=SOURCE):
    """[{section, letter, id, item, blocks, live, closed}], in file order."""
    items, letter, title, header = [], None, None, None
    for raw in open(path, encoding="utf-8"):
        line = raw.rstrip("\n")
        m = re.match(r"^## ([A-Z]) · (.+)$", line)
        if m:
            letter, title, header = m.group(1), m.group(2).strip(), None
            continue
        if line.startswith("## "):
            # "Closed" and anything else that is not a lettered section: stop
            # collecting. Rows below here are prose, not table rows.
            letter, title, header = None, None, None
            continue
        if letter is None or not line.startswith("|"):
            continue
        cells = split_cells(line)
        if header is None:
            header = cells
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue  # the |---|---| separator
        col = {h.lower(): c for h, c in zip(header, cells)}
        ident = col.get("#", "").strip()
        if not re.match(r"^[A-Z]\d+", ident):
            continue
        # The item text is whatever column follows "#", by position rather
        # than by name: the sections head it "Item", "Step" and "Drive folder",
        # and matching on the name rendered section E as three blank rows.
        item = (cells[1] if len(cells) > 1 else "").strip()
        items.append({
            "section": title,
            "letter": letter,
            "id": ident,
            "item": item,
            "blocks": col.get("what it blocks", "").strip(),
            "detail": col.get("detail", "").strip(),
            "live": col.get("live and uncertain", "").strip(),
            # The file's own close convention: the Item cell opens struck
            # through, with what the answer turned out to be after it.
            "closed": item.startswith("~~"),
        })
    return items


def is_live(it):
    """The file's flag for an item the dashboard publishes against today."""
    return re.match(r"^\*{0,2}yes", it["live"], re.I) is not None


def is_owner(it):
    return it["letter"] in OWNER_SECTIONS or it["id"] in OWNER_ITEMS


def as_of(path=SOURCE):
    """The file's own 'State as of' line, so the digest cannot claim newer."""
    head = open(path, encoding="utf-8").read(600)
    m = re.search(r"State as of (\d{4}-\d{2}-\d{2})", head)
    return m.group(1) if m else None


# --------------------------------------------------------------------------
# what moved since last time


def load_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except (OSError, ValueError):
        return None


def changes(items, prev):
    """(newly_open, newly_closed, first_run)."""
    if not prev or "open" not in prev:
        return [], [], True
    was_open = set(prev["open"])
    now_open = {it["id"] for it in items if not it["closed"]}
    new = sorted(now_open - was_open - set(prev.get("closed") or []))
    # Both ways an item can close land here: struck through in place, which is
    # the file's own convention, and moved down to ## Closed, where it stops
    # parsing as a row at all. Neither is in now_open, so one subtraction
    # covers both.
    gone = sorted(was_open - now_open)
    return new, gone, False


def write_state(items, path=STATE):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_as_of": as_of(),
        "open": sorted(it["id"] for it in items if not it["closed"]),
        "closed": sorted(it["id"] for it in items if it["closed"]),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, sort_keys=True)
    return payload


# --------------------------------------------------------------------------
# rendering


def md_to_html(s):
    """The little markdown the item cells actually use, escaped first.

    Escaping first is the point: these strings are read out of a file and
    dropped into a document, so nothing in them may become markup on its own.
    """
    s = (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    s = re.sub(r"~~(.+?)~~", r"<del>\1</del>", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s


# One stylesheet serves the PDF and the web page. The tokens below are the
# light palette, which is what Chromium prints; the dark blocks only matter on
# screen. Amber is the dashboard's own signal colour, kept here so a reader
# moving between the two pages does not have to relearn what it means -- and
# spent on one thing, the live-and-uncertain block.
FONTS = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
         "family=Archivo:wght@500;600;700&family=Source+Sans+3:wght@400;600&"
         'family=JetBrains+Mono:wght@500;700&display=swap">')

CSS = """
:root {
  --ground: #fbfbfc;      /* a neutral pulled a touch warm, toward the amber */
  --panel:  #ffffff;
  --ink:    #16181d;
  --muted:  #62656f;
  --rule:   #dcdde3;
  --accent: #8a5d00;      /* amber, darkened until it reads on white */
  --soft:   #fff7e8;      /* the live block's ground */
  --softrule: #d9a72e;
  --chip:   #f1f1f4;      /* inline code */
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --ground: #15171b; --panel: #1c1f25; --ink: #e9eaee; --muted: #979ba6;
    --rule: #2c3038; --accent: #e3a933; --soft: #241d10; --softrule: #8a6412;
    --chip: #262a31;
  }
}
:root[data-theme="dark"] {
  --ground: #15171b; --panel: #1c1f25; --ink: #e9eaee; --muted: #979ba6;
  --rule: #2c3038; --accent: #e3a933; --soft: #241d10; --softrule: #8a6412;
  --chip: #262a31;
}

* { box-sizing: border-box; }
body {
  margin: 0; padding-block: 28px; padding-left: 16px; padding-right: 16px;
  background: var(--ground); color: var(--ink);
  font: 400 15px/1.5 "Source Sans 3", ui-sans-serif, system-ui, -apple-system,
        "Segoe UI", Helvetica, Arial, sans-serif;
  font-variant-numeric: tabular-nums;
}
.wrap { max-width: 760px; margin: 0 auto; }

h1 {
  font: 700 26px/1.15 Archivo, ui-sans-serif, system-ui, Helvetica, Arial,
        sans-serif;
  margin: 0 0 6px; letter-spacing: -.4px; text-wrap: balance;
}
.sub { color: var(--muted); font-size: 13px; margin: 0 0 22px; }
.sub b { color: var(--ink); font-weight: 600; }

h2 {
  font: 600 15px/1.2 Archivo, ui-sans-serif, system-ui, Helvetica, Arial,
        sans-serif;
  margin: 28px 0 4px; padding-bottom: 5px;
  border-bottom: 1.5px solid var(--ink);
  display: flex; justify-content: space-between; align-items: baseline; gap: 12px;
}
h2 .n { color: var(--muted); font-weight: 500; font-size: 12px;
        white-space: nowrap; }

/* An eyebrow, not a heading: it names which section of OPEN_ITEMS.md the rows
   under it came from, which is the file's own answer to who is blocked. */
.blurb {
  color: var(--muted); font-size: 11px; letter-spacing: .06em;
  text-transform: uppercase; margin: 14px 0 7px;
  font-family: Archivo, ui-sans-serif, system-ui, sans-serif; font-weight: 600;
}

/* The ID is an identifier, so it is set as one, in its own column. */
.it { display: grid; grid-template-columns: 44px 1fr; gap: 0 12px;
      margin: 0 0 11px; break-inside: avoid; }
.id { font: 700 12px/1.7 "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo,
      Consolas, monospace; color: var(--accent); letter-spacing: .02em; }
.it p { margin: 0 0 4px; }
.meta { color: var(--muted); font-size: 12.5px; line-height: 1.45; }
.meta b { color: var(--ink); font-weight: 600; }

code { font: 500 12.5px/1 "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo,
       Consolas, monospace; background: var(--chip); color: var(--ink);
       padding: 1px 4px; border-radius: 3px; }
del { color: var(--muted); }

/* The one place colour is spent: the file's own flag for an item the page is
   publishing against today. */
.live { background: var(--soft); border-left: 3px solid var(--softrule);
        padding: 14px 16px 6px; margin: 0 0 18px; }
.live .hd {
  font: 700 11px/1.3 Archivo, ui-sans-serif, system-ui, sans-serif;
  text-transform: uppercase; letter-spacing: .08em; color: var(--accent);
  margin: 0 0 12px;
}

.moved { border: 1px solid var(--rule); background: var(--panel);
         border-radius: 4px; padding: 12px 14px; margin: 0 0 18px;
         font-size: 13.5px; }
.moved .hd { font: 600 11px/1.3 Archivo, ui-sans-serif, system-ui, sans-serif;
             text-transform: uppercase; letter-spacing: .08em;
             color: var(--muted); margin: 0 0 6px; }
.moved .row { margin: 3px 0; }
.moved .row b { font-weight: 600; }

.none { color: var(--muted); font-style: italic; }
.foot { margin-top: 30px; padding-top: 10px; border-top: 1px solid var(--rule);
        color: var(--muted); font-size: 11.5px; line-height: 1.5; }

@media print {
  /* Chromium prints the light tokens above; this block is only page setup. */
  @page { size: Letter; margin: 15mm 14mm 16mm; }
  body { padding: 0; background: #fff; font-size: 10.5pt; }
  .wrap { max-width: none; }
  h1 { font-size: 19pt; }
  h2 { margin-top: 20px; }
  .live, .moved { break-inside: avoid; }
}
"""


def render_item(it, show_meta=True):
    # Two cells exactly: the id, then everything else. The meta line is a
    # sibling of the item text inside the body cell -- as a direct child of
    # the grid it lands in the 44px id column and wraps a word per line.
    out = [f'<div class="it"><span class="id">{it["id"]}</span><div>',
           f'<p>{md_to_html(it["item"])}</p>']
    if show_meta:
        bits = []
        if it["blocks"]:
            bits.append("<b>Blocks:</b> " + md_to_html(it["blocks"]))
        if it["detail"]:
            bits.append(md_to_html(it["detail"]))
        if bits:
            out.append('<p class="meta">' + " &nbsp;·&nbsp; ".join(bits) + "</p>")
    out.append("</div></div>")
    return "".join(out)


def build_html(items, prev, standalone=True):
    """The digest as one HTML document.

    `standalone` wraps it as a whole file, which is what Chromium prints. The
    Artifact tool supplies its own doctype and head, so the web copy passes
    False and the two stay one document rather than two that must agree.
    """
    now = datetime.now().astimezone()
    open_items = [it for it in items if not it["closed"]]
    live = [it for it in open_items if is_live(it)]
    owner = [it for it in open_items if is_owner(it) and not is_live(it)]
    rest = [it for it in open_items if not is_owner(it) and not is_live(it)]
    new, gone, first = changes(items, prev)

    h = (['<!doctype html><meta charset="utf-8">'] if standalone else [])
    h += ["<title>Align Open Items</title>", FONTS,
         f"<style>{CSS}</style>", '<div class="wrap">',
         "<h1>Align Resi Dashboard — open items</h1>",
         # The two counts are not nested: an item can be live and still be
         # ours to fix (G3 is), so adding them would claim work is waiting on
         # the owner that is not.
         f'<div class="sub">{now:%A %-d %B %Y, %-I:%M %p %Z} &nbsp;·&nbsp; '
         f"<b>{len(open_items)}</b> open &nbsp;·&nbsp; "
         f"<b>{sum(1 for it in open_items if is_owner(it))}</b> waiting on you "
         f"&nbsp;·&nbsp; <b>{len(live)}</b> live and uncertain "
         f"&nbsp;·&nbsp; OPEN_ITEMS.md as of {as_of() or 'unknown'}</div>"]

    # What moved. First on the page after the header, because on a digest read
    # every morning the delta is the part that is not yesterday's.
    if first:
        h.append('<div class="moved"><div class="hd">First digest</div>'
                 '<div class="row">No previous run to compare against — '
                 "tomorrow's will list what moved.</div></div>")
    elif new or gone:
        h.append('<div class="moved"><div class="hd">Since the last digest</div>')
        if gone:
            h.append('<div class="row"><b>Closed:</b> ' + ", ".join(gone) + "</div>")
        if new:
            h.append('<div class="row"><b>New:</b> ' + ", ".join(new) + "</div>")
        h.append("</div>")
    else:
        h.append('<div class="moved"><div class="hd">Since the last digest</div>'
                 '<div class="row">Nothing opened or closed.</div></div>')

    if live:
        h.append('<div class="live"><div class="hd">Live and uncertain — '
                 "the page is publishing against these today</div>")
        h += [render_item(it) for it in live]
        h.append("</div>")

    owner_live = [it for it in live if is_owner(it)]
    h.append('<h2>Waiting on you <span class="n">'
             + (f"{len(owner)} more" if owner_live else str(len(owner)))
             + "</span></h2>")
    if owner_live:
        h.append('<p class="blurb">Besides '
                 + ", ".join(it["id"] for it in owner_live)
                 + " above.</p>")
    if owner:
        by_letter = {}
        for it in owner:
            by_letter.setdefault(it["letter"], []).append(it)
        for letter in sorted(by_letter):
            h.append(f'<p class="blurb">{letter} · '
                     f'{SECTION_BLURB.get(letter, "")}</p>')
            h += [render_item(it) for it in by_letter[letter]]
    else:
        h.append('<p class="none">Nothing is waiting on you.</p>')

    h.append(f'<h2>Open, not blocked on you <span class="n">{len(rest)}</span>'
             "</h2>")
    if rest:
        by_letter = {}
        for it in rest:
            by_letter.setdefault(it["letter"], []).append(it)
        for letter in sorted(by_letter):
            h.append(f'<p class="blurb">{letter} · '
                     f'{SECTION_BLURB.get(letter, "")}</p>')
            # These are the pipeline's own work, so the item line alone: the
            # "what it blocks" prose is for the rows someone is waiting on.
            h += [render_item(it, show_meta=False) for it in by_letter[letter]]
    else:
        h.append('<p class="none">Nothing open.</p>')

    closed = [it for it in items if it["closed"]]
    h.append('<div class="foot">Generated from OPEN_ITEMS.md by '
             "<code>scripts/open_items_digest.py</code>. Open means the row's "
             "Item cell is not struck through — the file's own way of recording "
             f"a close without renumbering. {len(closed)} row(s) in the tables "
             "are answered or closed and are left out. &quot;Waiting on you&quot; "
             "is sections " + ", ".join(sorted(OWNER_SECTIONS)) +
             " plus " + ", ".join(sorted(OWNER_ITEMS)) + ".</div>")
    h.append("</div>")
    return "".join(h)


def to_pdf(html, out=OUT):
    chrome = find_chrome()
    if not chrome:
        raise SystemExit("no chromium to print with — looked in "
                         + ", ".join(p for p in CHROME_CANDIDATES if p))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "digest.html")
        with open(src, "w", encoding="utf-8") as f:
            f.write(html)
        cmd = [chrome, "--headless", "--disable-gpu", "--no-sandbox",
               "--no-pdf-header-footer", f"--user-data-dir={tmp}/profile",
               f"--print-to-pdf={out}", f"file://{src}"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if not os.path.exists(out) or os.path.getsize(out) < 1000:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit(f"chromium wrote no usable PDF to {out}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--print", dest="stdout", action="store_true",
                    help="summarise to stdout and write no PDF")
    ap.add_argument("--html", metavar="PATH",
                    help="also write the page as HTML (the web copy; same "
                         "document, minus the file wrapper)")
    ap.add_argument("--no-state", action="store_true",
                    help="do not record this run (so the next digest still "
                         "compares against the previous real one)")
    a = ap.parse_args()

    items = parse()
    if not items:
        raise SystemExit(f"parsed no item rows out of {SOURCE} — has the table "
                         f"shape changed?")
    prev = load_state()
    open_items = [it for it in items if not it["closed"]]
    live = [it for it in open_items if is_live(it)]
    owner = [it for it in open_items if is_owner(it)]
    new, gone, first = changes(items, prev)

    print(f"{len(items)} row(s): {len(open_items)} open, "
          f"{len(items) - len(open_items)} answered or closed")
    print(f"  waiting on you: {len(owner)}  ({', '.join(it['id'] for it in owner)})")
    print(f"  live and uncertain: {len(live)}  "
          f"({', '.join(it['id'] for it in live) or 'none'})")
    if first:
        print("  since last digest: first run, nothing to compare")
    else:
        print(f"  since last digest: closed {', '.join(gone) or 'none'}; "
              f"new {', '.join(new) or 'none'}")

    if a.stdout:
        return
    path = to_pdf(build_html(items, prev), a.out)
    print(f"\nwrote {path} ({os.path.getsize(path):,} bytes)")
    if a.html:
        with open(a.html, "w", encoding="utf-8") as f:
            f.write(build_html(items, prev, standalone=False))
        print(f"wrote {a.html}")
    if not a.no_state:
        st = write_state(items)
        print(f"wrote {STATE}: {len(st['open'])} open, {len(st['closed'])} closed")


if __name__ == "__main__":
    main()

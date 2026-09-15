#!/usr/bin/env python3
"""Render LANDING_DRIVE_PACKET.md to PDF, for the copy kept in Drive.

The packet is a markdown file in the repo so it can be diffed and reviewed; the
PDF exists because the people who pull the Yardi exports do not read the repo.
Both come from the same source, so they cannot disagree -- regenerating is the
only supported way to change the PDF.

Refresh the status section first, so the PDF reports what is true today:

    python scripts/landing_drive_status.py --write
    python scripts/publish_packet_pdf.py

Rendering is headless Chromium's own print-to-PDF (the browser is already on
this image for Playwright), so the PDF matches what the HTML says rather than
going through a second layout engine with its own table rules.
"""
import argparse
import datetime
import os
import shutil
import subprocess
import sys
import tempfile

import markdown

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "LANDING_DRIVE_PACKET.md")

# Playwright's browsers live here on this image; a plain `chromium` on PATH is
# the fallback for a machine that has one installed normally.
CANDIDATES = [
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    "/opt/pw-browsers/chromium/chrome-linux/chrome",
]

ap = argparse.ArgumentParser()
ap.add_argument("--out", default=os.path.join(ROOT, "build", "Landing-Drive-Packet.pdf"))
ap.add_argument("--html-only", action="store_true", help="write the HTML and stop")
args = ap.parse_args()


def chromium():
    for c in CANDIDATES:
        if os.path.exists(c):
            return c
    found = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    if found:
        return found
    sys.exit("FATAL: no Chromium found; looked in " + ", ".join(CANDIDATES))


with open(SOURCE) as fh:
    md = fh.read()

# The committed markdown names Drive folders by path only. This repo is public
# and the project keeps folder ids in secrets, so the ids live in a gitignored
# file and are merged in here -- the PDF goes to Drive, where a working link is
# the point, and never to GitHub. Without the file the PDF simply keeps the
# "(link in the PDF)" placeholders rather than failing.
LINKS = os.path.join(ROOT, "config", "drive_folders.local.json")
if os.path.exists(LINKS):
    import json as _json
    import re as _re
    folders = _json.load(open(LINKS)).get("folders", {})
    unknown = set()

    # Every packet row names its destination as a path -- "Report Lander -> Rent
    # Roll". The last segment is the folder, so that is what gets looked up; the
    # whole path becomes the link text, because the path is what someone reads.
    def link(m):
        parent, child = m.group(1), m.group(2).rstrip()
        fid = folders.get(child)
        if not fid:
            unknown.add(child)
            return m.group(0)
        return f"[{parent} \u2192 {child}](https://drive.google.com/drive/folders/{fid})"

    md = _re.sub(r"(Report Lander|Resi Dashboard) \u2192 (_?[A-Za-z0-9][A-Za-z0-9 &_-]*?)(?=\s*[|*\n.]|$)",
                 link, md)
    if unknown:
        # A destination the map cannot name is a packet/Drive mismatch worth
        # seeing, not something to quietly leave unlinked.
        print("  [warn] no Drive id for: " + ", ".join(sorted(unknown)), file=sys.stderr)
else:
    print(f"  [note] {os.path.basename(LINKS)} absent - PDF will carry no Drive links")

# `tables` for the packet's tables, `fenced_code` for the command blocks,
# `attr_list` so nothing in the source needs raw HTML to lay out.
body = markdown.markdown(md, extensions=["tables", "fenced_code", "attr_list", "sane_lists"])

generated = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

# Print CSS, not screen CSS: a serif body at 10.5pt, tables that do not split a
# row across a page, and a repeating header row so a table running over a page
# break still says what its columns are.
STYLE = """
@page { size: Letter; margin: 16mm 14mm 18mm 14mm; }
* { box-sizing: border-box; }
body { font: 10.5pt/1.5 "DejaVu Serif", Georgia, serif; color: #1a1a1a; margin: 0; }
h1 { font-size: 20pt; margin: 0 0 2pt; letter-spacing: -0.2pt; }
h2 { font-size: 13pt; margin: 18pt 0 6pt; padding-top: 8pt;
     border-top: 1.5pt solid #1a1a1a; page-break-after: avoid; }
h3 { font-size: 11pt; margin: 14pt 0 4pt; page-break-after: avoid; }
p, li { orphans: 3; widows: 3; }
/* Normal weight and upright only: a bold or italic run inside a code span
   makes Chromium embed a whole extra font subset, and it re-embeds each one
   per page -- six subsets was most of a 212KB file for four pages of text. */
code, pre, th code { font-weight: normal !important; font-style: normal !important; }
code { font-family: "DejaVu Sans Mono", Consolas, monospace; font-size: 8.8pt;
       background: #f2f2f0; padding: 0.5pt 2.5pt; border-radius: 2pt; }
pre { background: #f2f2f0; padding: 7pt 9pt; border-radius: 3pt; font-size: 8.5pt;
      overflow-wrap: break-word; white-space: pre-wrap; }
pre code { background: none; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0 10pt;
        font-size: 8.6pt; page-break-inside: auto; }
thead { display: table-header-group; }
tr { page-break-inside: avoid; page-break-after: auto; }
th { background: #1a1a1a; color: #fff; text-align: left; padding: 4.5pt 5pt;
     font-weight: 600; font-size: 8.4pt; }
td { border-bottom: 0.5pt solid #d8d8d4; padding: 4pt 5pt; vertical-align: top; }
tbody tr:nth-child(even) td { background: #faf9f7; }
a { color: #1a1a1a; text-decoration: underline; }
blockquote { margin: 8pt 0; padding: 6pt 10pt; border-left: 2.5pt solid #1a1a1a;
             background: #faf9f7; }
hr { border: none; border-top: 0.5pt solid #d8d8d4; margin: 14pt 0; }
em { color: #555; }
.stamp { font-size: 8pt; color: #666; margin: 0 0 14pt;
         padding-bottom: 8pt; border-bottom: 0.5pt solid #d8d8d4; }
"""

html = f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>The Landing (Drive) — report packet</title>
<style>{STYLE}</style></head>
<body>
<div class="stamp">Generated {generated} from LANDING_DRIVE_PACKET.md ·
regenerate with <code>scripts/publish_packet_pdf.py</code> · do not edit this PDF
by hand, edit the markdown</div>
{body}
</body></html>
"""

os.makedirs(os.path.dirname(args.out), exist_ok=True)

if args.html_only:
    out = os.path.splitext(args.out)[0] + ".html"
    with open(out, "w") as fh:
        fh.write(html)
    print(f"wrote {out}")
    sys.exit(0)

with tempfile.TemporaryDirectory() as tmp:
    src = os.path.join(tmp, "packet.html")
    with open(src, "w") as fh:
        fh.write(html)
    cmd = [
        chromium(), "--headless", "--disable-gpu", "--no-sandbox",
        # Chromium refuses to write a PDF for a file:// URL without this.
        "--no-pdf-header-footer",
        f"--print-to-pdf={args.out}", "file://" + src,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if r.returncode != 0 or not os.path.exists(args.out):
        sys.exit("FATAL: chromium failed to render\n" + (r.stderr or "")[-1500:])

size = os.path.getsize(args.out)
if size < 5000:
    # A near-empty PDF renders as a blank page and looks like a successful run.
    sys.exit(f"FATAL: {args.out} is only {size} bytes — the render is empty")
print(f"wrote {args.out} ({size:,} bytes)")

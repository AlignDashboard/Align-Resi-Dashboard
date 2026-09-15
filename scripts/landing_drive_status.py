#!/usr/bin/env python3
"""Report the freshness of every feed behind the `Landing (Drive)` tab.

LANDING_DRIVE_PACKET.md carries the standing pull list — which export, which
Drive folder, what the filer matches on. This script answers the other half:
what has actually arrived, and how old it is today. It reads only published
JSON (`docs/metrics.json`, `docs/scorecard.json`, `data/the-landing/*.json`),
so it runs anywhere the repo is checked out, with no Drive access and no
network.

It exists because a hand-written freshness table is stale the day after it is
written, and a stale table is read as a map. Refresh the packet's second
section with:

    python scripts/landing_drive_status.py --write

Exit status is 0 always: this reports, it does not gate.
"""
import argparse
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLUG = "the-landing"

ap = argparse.ArgumentParser()
ap.add_argument("--markdown", action="store_true", help="emit the packet's table")
ap.add_argument("--write", action="store_true",
                help="replace section 2 of LANDING_DRIVE_PACKET.md in place")
ap.add_argument("--slug", default=SLUG)
ap.add_argument("--today", help="override today's date (YYYY-MM-DD), for testing")
args = ap.parse_args()

today = (datetime.date.fromisoformat(args.today) if args.today
         else datetime.datetime.now(datetime.timezone.utc).date())


def load(path):
    p = os.path.join(ROOT, path)
    if not os.path.exists(p):
        return None
    with open(p) as fh:
        return json.load(fh)


def deep(obj, key):
    """First value for `key` anywhere in obj, preferring the last list entry.

    The per-feed JSON nests its arrival differently per parser — a point in a
    `points` list, a week in `weeks`, a scalar at the top — so the packet would
    need a rule per feed to find one. The newest entry is the last one in every
    accumulating store, hence the reversed walk.
    """
    if isinstance(obj, dict):
        if key in obj and not isinstance(obj[key], (dict, list)):
            return obj[key]
        for v in obj.values():
            got = deep(v, key)
            if got is not None:
                return got
    elif isinstance(obj, list):
        for v in reversed(obj):
            got = deep(v, key)
            if got is not None:
                return got
    return None


def age(stamp):
    """Whole days between an ISO-8601 stamp (date or datetime) and today."""
    if not stamp:
        return None
    s = str(stamp).replace("Z", "+00:00")
    try:
        d = datetime.datetime.fromisoformat(s).date()
    except ValueError:
        try:
            d = datetime.date.fromisoformat(s[:10])
        except ValueError:
            return None
    return (today - d).days


metrics = load("docs/metrics.json") or {}
scorecard = load("docs/scorecard.json") or {}
measured = (scorecard.get("measured") or {}).get(args.slug, {})


def from_block(block, slug):
    """A per-property entry out of a metrics.json block, by slug.

    Exact match only. `leasing` carries Chorus and Madelon beside The Landing,
    so falling back to the first entry would report another building's week
    under this one's name.
    """
    props = (metrics.get(block) or {}).get("properties") or []
    for p in props:
        if p.get("slug") == slug:
            return p
    return None


def data_file(name):
    return load(f"data/{args.slug}/{name}.json")


def feed_data(name, cover_key):
    d = data_file(name)
    if not d:
        return None, None, None
    return deep(d, cover_key), deep(d, "landed_at"), (
        deep(d, "source_file") or deep(d, "source_files"))


def feed_metrics(block, cover_key):
    p = from_block(block, args.slug)
    if not p:
        return None, None, None
    return deep(p, cover_key), deep(p, "landed_at"), deep(p, "source_file")


def feed_scorecard(prefix, cover_key="as_of"):
    pre = prefix + "_" if prefix else ""
    return (measured.get(pre + cover_key),
            measured.get(pre + "received_at"),
            measured.get(pre + "source"))


# Each row: label, cadence in days (None = event-driven), and how to find it.
# Cadence is what makes an age actionable — 15 days is current for a monthly
# export and two weeks late for a weekly one.
FEEDS = [
    ("T12 statement",       30,   lambda: feed_data("monthly_pl", "period_end")),
    ("Budget",              365,  lambda: feed_data("budget", "as_of")),
    ("Rent roll",           7,    lambda: feed_metrics("rent_roll", "as_of")),
    ("Delinquency",         30,   lambda: feed_scorecard("")),  # see owner note
    ("Weekly leasing",      7,    lambda: feed_data("leasing_detail", "week_ending")),
    ("Renewal tracker",     7,    lambda: feed_data("renewal_tracker", "as_of")),
    ("Unit directory",      None, lambda: feed_data("unit_directory", "as_of")),
    ("EliseAI bldg metrics", 30,  lambda: feed_scorecard("bldg")),
    ("EliseAI funnel",      7,    lambda: feed_data("leasing_funnel", "as_of")),
]


def verdict(days, cadence):
    if days is None:
        return "never arrived"
    if cadence is None:
        return f"{days}d — refresh on change only"
    if days <= cadence:
        return f"{days}d — current"
    return f"{days}d — DUE (every {cadence}d)"


rows = []
for label, cadence, get in FEEDS:
    cover, landed, source = get()
    days = age(landed)
    v = verdict(days, cadence)
    # The delinquency cells are shared between the Drive AR report and the
    # workbook, last run wins (open item G3). A fresh-looking arrival here can
    # be the workbook's, so say whose it is rather than letting the date imply.
    if label == "Delinquency":
        what = str(measured.get("received_what") or "")
        if what and "Drive" not in what:
            v += " — but the WORKBOOK wrote last"
    rows.append((label, cover, landed, days, cadence, source, v))

def table():
    out = [f"_Feed state as of {today.isoformat()} — regenerate with "
           "`python scripts/landing_drive_status.py --write`._", "",
           "| Feed | Covers | Landed | Status |", "| --- | --- | --- |"
           " --- |"]
    for label, cover, landed, days, cadence, source, v in rows:
        due = v.startswith("never") or "DUE" in v
        out.append("| %s | %s | %s | %s |" % (
            ("**%s**" % label) if due else label,
            cover or "—",
            (str(landed)[:10] if landed else "—"),
            ("**%s**" % v) if due else v))
    return "\n".join(out)


PACKET = os.path.join(ROOT, "LANDING_DRIVE_PACKET.md")
BEGIN, END = "<!-- BEGIN STATUS -->", "<!-- END STATUS -->"

if args.write:
    with open(PACKET) as fh:
        doc = fh.read()
    i, j = doc.find(BEGIN), doc.find(END)
    if i < 0 or j < 0 or j < i:
        # Refusing beats writing the table somewhere it will not be read, or
        # eating the section the markers were meant to bound.
        sys.exit(f"FATAL: {os.path.basename(PACKET)} has no "
                 f"{BEGIN} / {END} pair to replace")
    new_doc = doc[:i] + BEGIN + "\n" + table() + "\n" + doc[j:]
    if new_doc == doc:
        print("section 2 already current — nothing written")
    else:
        with open(PACKET, "w") as fh:
            fh.write(new_doc)
        print(f"section 2 rewritten in {os.path.basename(PACKET)}")
elif args.markdown:
    print(table())
else:
    where = "Landing (Drive)" if args.slug == SLUG else args.slug
    print(f"{where} feed state — {today.isoformat()}\n")
    w = max(len(r[0]) for r in rows)
    for label, cover, landed, days, cadence, source, v in rows:
        print("  %-*s  %-16s  %-12s  %s" % (
            w, label, str(cover or "-")[:16], str(landed or "-")[:10], v))
    due = [r[0] for r in rows if r[6].startswith("never") or "DUE" in r[6]]
    print("\n%d of %d feeds want a fresh export: %s"
          % (len(due), len(rows), ", ".join(due) if due else "none"))

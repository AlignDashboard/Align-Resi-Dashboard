#!/usr/bin/env python3
"""Checks for open_items_digest.py — fixture-free, no network, no PDF.

The digest is read as a status report, so the failure that matters is a silent
one: a row that stops parsing, a closed item counted as open, an item credited
to the owner that is ours. Each check below fails when its guard is removed.

Run: python scripts/test_open_items_digest.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import open_items_digest as D  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def write(text):
    fd, path = tempfile.mkstemp(suffix=".md")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    return path


SYNTHETIC = """# Open Items

State as of 2026-09-16. IDs are stable.

## A · Blocked on the owner (a file, an answer, or a click)

| # | Item | What it blocks | Live and uncertain |
| --- | --- | --- | --- |
| A1 | ~~Old question~~ **Answered: yes.** Settled last week | nothing | no |
| A2 | A live question with a `code` cell and **bold** | The KPI | **yes** — it is on the page |
| A3 | A quiet question | Nothing yet | no |

## D · Parsers not built

| # | Drive folder |
| --- | --- |
| D1 | Some Folder |

## E · Keeping data out of git history

| # | Step |
| --- | --- |
| E1 | Flip the Pages source |

## G · Found while building

| # | Item | What it blocks | Live and uncertain |
| --- | --- | --- | --- |
| G1 | Ours to fix | Provenance | contained — narrowed by hand |
| G6 | A question about the building | Nothing | no |

## Closed

2026-09-17 — **A4 removed.** | X1 | this line is prose, not a row | none | no |
"""


def main():
    path = write(SYNTHETIC)
    items = D.parse(path)
    by = {it["id"]: it for it in items}

    print("parsing")
    check("every lettered section's rows are read", len(items) == 7,
          f"got {len(items)}: {[i['id'] for i in items]}")
    check("prose under ## Closed is not read as a row", "X1" not in by)
    check("a two-column section is read (D)", "D1" in by)
    # Positional, not by column name: the sections head this column "Item",
    # "Drive folder" and "Step". Matching on "item" rendered E as blank rows.
    check("a section heading its column 'Step' still carries text (E)",
          by.get("E1", {}).get("item") == "Flip the Pages source")
    check("a section heading it 'Drive folder' carries text (D)",
          by.get("D1", {}).get("item") == "Some Folder")
    check("the separator row is skipped", all(set(i["id"]) - set("-: ") for i in items))

    print("\nopen vs closed")
    # The file's own convention: a close strikes the Item cell rather than
    # deleting the row, so the ID keeps meaning the same thing next week.
    check("a struck-through item is closed", by["A1"]["closed"] is True)
    check("a plain item is open", by["A2"]["closed"] is False)
    check("closed items are excluded from the open count",
          len([i for i in items if not i["closed"]]) == 6)

    print("\nthe live flag")
    check("**yes** is live", D.is_live(by["A2"]) is True)
    check("plain no is not live", D.is_live(by["A3"]) is False)
    check("'contained — …' is not live", D.is_live(by["G1"]) is False)

    print("\nwho it is waiting on")
    check("a section-A row is the owner's", D.is_owner(by["A3"]) is True)
    check("a section-G row is not, by default", D.is_owner(by["G1"]) is False)
    check("OWNER_ITEMS overrides the section", D.is_owner(by["G6"]) is True)
    check("section D is not the owner's", D.is_owner(by["D1"]) is False)

    print("\nwhat moved since last time")
    check("no previous state reads as a first run",
          D.changes(items, None)[2] is True)
    prev = {"open": ["A2", "A3", "D1", "E1", "G1", "G6"], "closed": ["A1"]}
    new, gone, first = D.changes(items, prev)
    check("an unchanged file moves nothing", (new, gone, first) == ([], [], False),
          f"{new} {gone} {first}")
    # A row that closes is struck in place; a row moved down to ## Closed stops
    # parsing as a row. Both have to read as closed, or the digest would go on
    # listing an item that is done.
    was = dict(prev, open=prev["open"] + ["A9"])
    check("an item that left the tables reads as closed",
          D.changes(items, was)[1] == ["A9"])
    struck = D.parse(write(SYNTHETIC.replace(
        "| A3 | A quiet question", "| A3 | ~~A quiet question~~ **Done.**")))
    check("an item struck in place reads as closed",
          D.changes(struck, prev)[1] == ["A3"])
    check("a row added since reads as new",
          D.changes(items, {"open": ["A2"], "closed": ["A1"]})[0]
          == ["A3", "D1", "E1", "G1", "G6"])

    print("\nrendering")
    # These strings are read out of a file and dropped into a document, so
    # nothing in them may become markup on its own.
    check("markup in an item is escaped before any formatting is applied",
          D.md_to_html("a <script>x</script> & b")
          == "a &lt;script&gt;x&lt;/script&gt; &amp; b")
    check("bold, code and strike still render",
          D.md_to_html("**b** `c` ~~d~~")
          == "<strong>b</strong> <code>c</code> <del>d</del>")
    html = D.build_html(items, prev, source_as_of=D.as_of(path))
    check("a live item is rendered", "A2" in html)
    check("a closed item is not rendered", "Old question" not in html)
    check("the live block leads the page",
          html.find("LIVE AND UNCERTAIN") < html.find("Waiting on you"))
    check("the two counts are not added together",
          "5</b> waiting on you" not in html and "4</b> waiting on you" in html,
          "owner=4 (A2,A3,E1,G6) and live=1 (A2) overlap")
    # The date must come from the file that was PARSED, not from whichever
    # file as_of() would find. These two differ now -- the real OPEN_ITEMS.md
    # has moved past the fixture's 2026-09-16 -- which is what caught the
    # header dating a page from a file it had not rendered.
    check("the as-of date is the parsed file's, not the real file's",
          "2026-09-16" in D.build_html(D.parse(path), prev,
                                       source_as_of=D.as_of(path))
          and D.as_of() != "2026-09-16")

    print("\nthe real file")
    real = D.parse()
    check("OPEN_ITEMS.md still parses", len(real) > 20, f"got {len(real)}")
    check("every row has an item text", all(i["item"] for i in real))
    check("the real file's as-of date is found", D.as_of() is not None)

    print()
    if FAILED:
        print(f"{len(FAILED)} check(s) failed: " + ", ".join(FAILED))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

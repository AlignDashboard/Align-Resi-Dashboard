#!/usr/bin/env python3
"""Guard tests: an older snapshot report never overwrites a newer one.

The rent roll, the delinquency summary, the unit directory, the funnel, the
concession burn-off and the renewal tracker are each stored as ONE file per
property, replaced by the next parse. process_manifest walks files in filename
order, and that order is not date order: the Gmail filer prefixes the arrival
date ("2026-10-05 RentRoll10_05_2026.xlsx") while a hand-dropped export has no
prefix ("RentRoll09_28_2026.xlsx"), and "2" sorts before "R". So the newer roll
was processed first and the older one overwrote it -- every step green, the
page a week stale, nothing in the log.

store_report now keeps the newest as_of -- or, for the renewal tracker, whose
as_of is how far forward the copy reaches rather than when it was made, the
latest Drive arrival. Checked here:

  * the comparison itself -- older, newer, equal, missing and mismatched dates;
  * store_report directly -- an older parse is refused, an equal one replaces;
  * process_manifest end to end, through BOTH of its store call sites (the
    single-property shape the rent roll uses and the sectioned shape the
    delinquency summary uses), with the newer file sorting first by name;
  * the log -- a refused file says "[keep]" and is not reported as stored;
  * the renewal tracker -- a later copy reading a month shorter still wins.

Fixture-free and offline: the parsers are stubbed, so no workbook (and no
resident name) is involved.

Run: python scripts/test_snapshot_order.py
"""
import contextlib
import io
import json
import os
import pathlib
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import build_metrics as bm        # noqa: E402

PASS = FAIL = 0
LANDING = {"name": "The Landing", "slug": "the-landing"}


def ok(name, cond, detail=None):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"\n        {detail}" if detail is not None else ""))


# A parser stub. process_manifest imports item["parser"] by name and calls
# parse(path); this one reads the parse it should return from the "report"
# file itself, so each manifest item carries its own as_of.
STUB = '''
import json
def parse(path):
    return json.load(open(path))
'''


def roll(as_of, src):
    return {"report_type": "rent_roll", "property": "The Landing",
            "property_code": "p0005611", "as_of": as_of, "source_file": src,
            "totals": {"units": 263}, "units": [], "checks": []}


def delq(as_of, src):
    # The sectioned shape parse_delinquency returns, which process_manifest
    # stores through its second call site (grouped by property).
    return {"report_type": "ar_analytics", "as_of": as_of, "source_file": src,
            "summary": {}, "sections": [{"property_code": "p0005611",
                                          "summary": {}, "residents": []}]}


def tracker(as_of, src, landed=None):
    # A renewal tracker's as_of is its furthest-forward month SHEET, not the
    # date of the copy -- which is why its store compares arrivals instead.
    t = {"report_type": "renewal_tracker", "property": "The Landing",
         "property_code": "The Landing", "as_of": as_of, "source_file": src,
         "covers": {"from": "2024-01", "to": as_of}, "months": [], "mtm": None,
         "unread_sheets": [], "problems": [], "checks": []}
    if landed:
        t["landed_at"] = landed
    return t


def run_manifest(tmp, items):
    """Write the reports and a manifest into tmp, run process_manifest there.

    Returns (stdout, data dir). The repo's config/ is linked in, because
    process_manifest resolves properties and the report map relative to cwd.
    """
    work = pathlib.Path(tmp) / f"run{len(os.listdir(tmp))}"
    (work / "_downloads").mkdir(parents=True)
    os.symlink(os.path.join(REPO, "config"), work / "config")
    manifest = []
    for name, rtype, parsed, *landed in items:
        p = work / "_downloads" / name
        p.write_text(json.dumps(parsed))
        manifest.append({"report_type": rtype, "parser": "stub_snapshot_parser",
                         "path": str(p), "name": name,
                         "landed_at": landed[0] if landed else "2026-10-05T12:00:00Z"})
    (work / "_downloads" / "manifest.json").write_text(json.dumps(manifest))

    prev_cwd, prev_data = os.getcwd(), bm.DATA
    bm.DATA = work / "data"
    out = io.StringIO()
    try:
        os.chdir(work)
        with contextlib.redirect_stdout(out):
            bm.process_manifest()
    finally:
        os.chdir(prev_cwd)
        bm.DATA = prev_data
    return out.getvalue(), work / "data" / "the-landing"


def main():
    tmp = tempfile.mkdtemp(prefix="snapshot_order_")
    stubdir = pathlib.Path(tmp) / "stubs"
    stubdir.mkdir()
    (stubdir / "stub_snapshot_parser.py").write_text(STUB)
    sys.path.insert(0, str(stubdir))
    try:
        print("1. the comparison")
        o = bm.older_as_of
        ok("an older day is older", o("2026-09-21", "2026-10-05"))
        ok("a newer day is not", not o("2026-10-05", "2026-09-21"))
        ok("the same day is not -- a re-export replaces", not o("2026-09-21", "2026-09-21"))
        ok("month precision compares too (renewal tracker)", o("2026-11", "2026-12"))
        ok("no new date: never refuse", not o(None, "2026-09-21"))
        ok("no stored date: never refuse", not o("2026-09-21", None))
        ok("mixed precision: no claim either way", not o("2026-09", "2026-09-21"))
        ok("not a date at all: no claim", not o("Sep 21 2026", "2026-10-05"))

        print("\n2. store_report directly")
        prev = bm.DATA
        bm.DATA = pathlib.Path(tmp) / "direct"
        try:
            fp = bm.DATA / "the-landing" / "rent_roll.json"
            with contextlib.redirect_stdout(io.StringIO()):
                bm.store_rent_roll(LANDING, roll("2026-10-05", "new.xlsx"))
                r = bm.store_rent_roll(LANDING, roll("2026-09-21", "old.xlsx"))
            held = json.load(open(fp))
            ok("an older parse is refused", r is bm.KEPT_NEWER, r)
            ok("...and the newer file is untouched",
               (held["as_of"], held["source_file"]) == ("2026-10-05", "new.xlsx"), held)
            with contextlib.redirect_stdout(io.StringIO()):
                r = bm.store_rent_roll(LANDING, roll("2026-10-05", "reexport.xlsx"))
            held = json.load(open(fp))
            ok("an equal as_of replaces (a corrected re-export wins)",
               r is not bm.KEPT_NEWER and held["source_file"] == "reexport.xlsx", held)
            with contextlib.redirect_stdout(io.StringIO()):
                bm.store_rent_roll(LANDING, roll(None, "undated.xlsx"))
            held = json.load(open(fp))
            ok("an undated parse still stores, as before the guard",
               held["source_file"] == "undated.xlsx", held)
            fp.write_text("{not json")
            with contextlib.redirect_stdout(io.StringIO()):
                bm.store_rent_roll(LANDING, roll("2026-09-01", "after-corrupt.xlsx"))
            ok("an unreadable stored file is replaced, not fatal",
               json.load(open(fp))["source_file"] == "after-corrupt.xlsx")
        finally:
            bm.DATA = prev

        print("\n3. process_manifest: rent roll, newer file sorting FIRST by name")
        newer = "2026-10-05 RentRoll10_05_2026.xlsx"
        older = "RentRoll09_28_2026.xlsx"
        ok("the premise: the filer's prefixed name sorts ahead", sorted([older, newer])[0] == newer)
        log, d = run_manifest(tmp, [
            (older, "rent_roll", roll("2026-09-21", older)),
            (newer, "rent_roll", roll("2026-10-05", newer)),
        ])
        held = json.load(open(d / "rent_roll.json"))
        ok("the newer roll is what is stored",
           (held["as_of"], held["source_file"]) == ("2026-10-05", newer), held)
        ok("the refusal is in the log", "[keep]" in log and older in log, log)
        ok("the older roll is not reported as stored",
           "as of 2026-09-21)" not in log, log)

        print("\n4. process_manifest: delinquency, through the sectioned call site")
        log, d = run_manifest(tmp, [
            ("Delinquency_9_1_2026.xlsx", "ar_analytics",
             delq("2026-09-01", "Delinquency_9_1_2026.xlsx")),
            ("2026-10-02 Delinquency_10_1_2026.xlsx", "ar_analytics",
             delq("2026-10-01", "2026-10-02 Delinquency_10_1_2026.xlsx")),
        ])
        held = json.load(open(d / "delinquency.json"))
        ok("the newer summary is what is stored", held["as_of"] == "2026-10-01", held)
        ok("the older one is kept out of the '[ok] stored' lines",
           "as of 2026-09-01)" not in log and "[keep]" in log, log)

        print("\n5. process_manifest: in date order, nothing changes")
        log, d = run_manifest(tmp, [
            ("RentRoll09_11_2026.xlsx", "rent_roll", roll("2026-09-11", "RentRoll09_11_2026.xlsx")),
            ("RentRoll09_28_2026.xlsx", "rent_roll", roll("2026-09-21", "RentRoll09_28_2026.xlsx")),
        ])
        held = json.load(open(d / "rent_roll.json"))
        ok("the later file still wins", held["as_of"] == "2026-09-21", held)
        ok("and nothing is refused", "[keep]" not in log, log)

        print("\n6. the renewal tracker: the later ARRIVAL wins, not the later as_of")
        L = bm.older_landed
        ok("an earlier arrival is older", L("2026-09-08T23:28:49.326Z", "2026-09-21T23:28:34.027Z"))
        ok("a later one is not", L("2026-09-21T23:28:34.027Z", "2026-09-08T23:28:49.326Z") is False)
        ok("a missing arrival makes no claim", L(None, "2026-09-21T23:28:34.027Z") is None)
        ok("an unreadable one makes no claim", L("last Tuesday", "2026-09-21T23:28:34Z") is None)
        prev = bm.DATA
        bm.DATA = pathlib.Path(tmp) / "tracker"
        try:
            fp = bm.DATA / "the-landing" / "renewal_tracker.json"
            with contextlib.redirect_stdout(io.StringIO()):
                bm.store_renewal_tracker(LANDING, tracker("2026-12", "(42).xlsx",
                                                          "2026-09-08T23:28:49.326Z"))
                r = bm.store_renewal_tracker(LANDING, tracker("2026-11", "(47).xlsx",
                                                              "2026-09-21T23:28:34.027Z"))
            held = json.load(open(fp))
            ok("a later copy reading a month SHORTER still replaces (the 2026-10-05 bug)",
               r is not bm.KEPT_NEWER and held["source_file"] == "(47).xlsx", held)
            with contextlib.redirect_stdout(io.StringIO()):
                r = bm.store_renewal_tracker(LANDING, tracker("2027-06", "(40).xlsx",
                                                              "2026-09-02T23:28:00Z"))
            held = json.load(open(fp))
            ok("an earlier copy reaching FURTHER forward is refused",
               r is bm.KEPT_NEWER and held["source_file"] == "(47).xlsx", held)
            with contextlib.redirect_stdout(io.StringIO()):
                r = bm.store_renewal_tracker(LANDING, tracker("2026-10", "local.xlsx"))
            ok("with no arrival time, as_of decides as before",
               r is bm.KEPT_NEWER and json.load(open(fp))["source_file"] == "(47).xlsx")
        finally:
            bm.DATA = prev

        print("\n7. process_manifest: the Landing trackers of 2026-10-05")
        old = "2026-09-08 Landing 2025 Renewal Tracker - Full (42).xlsx"
        new = "2026-09-21 Landing 2025 Renewal Tracker - Full (47).xlsx"
        # an older copy dropped by hand: no arrival prefix, so it sorts LAST
        hand = "Landing 2025 Renewal Tracker - Full (40).xlsx"
        log, d = run_manifest(tmp, [
            (new, "renewal_tracker", tracker("2026-11", new), "2026-09-21T23:28:34.027Z"),
            (old, "renewal_tracker", tracker("2026-12", old), "2026-09-08T23:28:49.326Z"),
            (hand, "renewal_tracker", tracker("2026-12", hand), "2026-09-02T18:00:00Z"),
        ])
        held = json.load(open(d / "renewal_tracker.json"))
        ok("the copy that arrived last is what is stored, a month short or not",
           held["source_file"] == new, held)
        ok("the hand-dropped earlier copy, processed last, is refused by its arrival",
           "[keep]" in log and hand in log and "keeping the later arrival" in log, log)
    finally:
        sys.path.remove(str(stubdir))
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()

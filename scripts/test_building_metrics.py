#!/usr/bin/env python3
"""Guard tests for the building-metrics history: every EliseAI export kept.

The export carries leads, tours, applications and occupancy for every building
EliseAI covers, and until 2026-10-08 only the newest one was ever read -- by the
scorecard fill -- so none of it was a series. parse_building_metrics reads
every export and store_building_metrics keeps one point per export date. What
has to hold:

  - the parse: one section per building row, the filename's LAST date as the
    export date, First Tours Attended as tours whatever else the file carries,
    and a building whose counts do not reproduce the export's own rates refused
    rather than read. A missing column refuses the file -- the export has
    already dropped columns once without notice (B9).
  - the store: points accumulate by export date and are never superseded by a
    later export; one date re-filed is one point, and the later arrival wins.
  - the block: active buildings only, points in date order, and only the keys
    the card reads.
  - the router: the export's own headings reach their buildings through the
    property master, end to end through process_manifest.

Fixture-free: every export is built in a temp dir, and every figure is invented.
Run: python scripts/test_building_metrics.py
"""
import csv
import json
import os
import pathlib
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import build_metrics as bm  # noqa: E402
import parse_building_metrics as pbm  # noqa: E402

PASS = FAIL = 0


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"   PASS {name}")
    else:
        FAIL += 1
        print(f"   FAIL {name}\n        got  {got!r}\n        want {want!r}")


NEW_COLS = ["Property", "Organization", "Occupancy Rate (Period End)",
            "Exposure Rate (Period End)", "Vacant Units (Period End)",
            "New Prospects", "First Tours Booked", "First Tours Attended",
            "Applications Completed", "Leases Signed",
            "Prospect to Tour Attended Rate", "Prospect to App Completed Rate"]
# The 75/79-column layout also published Total Tours Attended.
OLD_COLS = NEW_COLS[:7] + ["Total Tours Attended"] + NEW_COLS[7:]


def row(prop, occ, leads, tours, apps, *, total_tours=None, tour_rate=None,
        app_rate=None):
    """One building, with the export's own rates computed from its counts
    unless a test plants a different one."""
    r = {"Property": prop, "Organization": "Unknown",
         "Occupancy Rate (Period End)": occ, "Exposure Rate (Period End)": 4.5,
         "Vacant Units (Period End)": 6, "New Prospects": leads,
         "First Tours Booked": tours + 3, "First Tours Attended": tours,
         "Applications Completed": apps, "Leases Signed": 2,
         "Prospect to Tour Attended Rate":
             round(tours / leads * 100, 2) if tour_rate is None else tour_rate,
         "Prospect to App Completed Rate":
             round(apps / leads * 100, 2) if app_rate is None else app_rate}
    if total_tours is not None:
        r["Total Tours Attended"] = total_tours
    return r


def write(dirpath, name, rows, cols=NEW_COLS):
    p = os.path.join(dirpath, name)
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: ("" if r.get(c) is None else r.get(c)) for c in cols})
    return p


tmp = tempfile.mkdtemp()
try:
    print("the export's date is the filename's last date")
    check("dashed name", pbm.as_of_from_name("metrics-building-2026-09-28.csv"), "2026-09-28")
    check("undashed name", pbm.as_of_from_name("metricsbuilding20260819.csv"), "2026-08-19")
    check("the filer's arrival prefix does not date the export",
          pbm.as_of_from_name("2026-10-06 metrics-building-2026-10-05.csv"), "2026-10-05")

    print("one section per building, read to the column")
    p = write(tmp, "metrics-building-2026-09-28.csv",
              [row("The Landing", 98.86, 101, 12, 3),
               row("335 3rd Street", 10.53, 81, 19, 5, app_rate="")])
    parsed = pbm.parse(p)
    secs = {s["property_code"]: s for s in parsed["sections"]}
    check("dated from the name", parsed["as_of"], "2026-09-28")
    check("both buildings read", sorted(secs), ["335 3rd Street", "The Landing"])
    land = secs["The Landing"]
    check("leads, tours, applications and occupancy",
          (land["new_prospects"], land["first_tours_attended"],
           land["applications_completed"], land["occupancy"]), (101.0, 12.0, 3.0, 98.86))
    check("a count that reproduces its rate passes both checks",
          [c["ok"] for c in land["checks"]], [True, True])
    third = secs["335 3rd Street"]
    check("a rate the row does not print is unchecked, not passed",
          [c["ok"] for c in third["checks"]], [True, None])
    check("and an unchecked rate refuses nothing", third.get("refused"), None)

    print("tours are FIRST tours attended, whatever else the file carries")
    p = write(tmp, "metricsbuilding20260826.csv",
              [row("Chorus", 97.12, 352, 70, 14, total_tours=71)], cols=OLD_COLS)
    sec = pbm.parse(p)["sections"][0]
    check("the old layout reads First Tours Attended, not Total",
          sec["first_tours_attended"], 70.0)

    print("a building that cannot reproduce its own rates is refused")
    p = write(tmp, "metrics-building-2026-10-05.csv",
              [row("The Landing", 98.86, 101, 12, 3, tour_rate=15.79),
               row("Chorus", 95.43, 295, 88, 20)])
    secs = {s["property_code"]: s for s in pbm.parse(p)["sections"]}
    check("the failing building is marked refused",
          "Prospect to Tour Attended Rate" in (secs["The Landing"].get("refused") or ""), True)
    check("its neighbour in the same file is not", secs["Chorus"].get("refused"), None)

    print("a column the card needs, gone from the header, refuses the file")
    p = write(tmp, "metrics-building-2026-10-12.csv",
              [row("The Landing", 98.86, 101, 12, 3)],
              cols=[c for c in NEW_COLS if c != "New Prospects"])
    try:
        pbm.parse(p)
        check("missing New Prospects raises", "no error", "ValueError")
    except ValueError as e:
        check("missing New Prospects raises, naming it", "New Prospects" in str(e), True)

    print("the store keeps one point per export date")
    bm.DATA = pathlib.Path(tmp) / "data"
    prop = {"slug": "the-landing", "name": "The Landing"}

    def store(as_of, leads, landed, refused=None):
        sec = {"property_code": "The Landing", "as_of": as_of, "occupancy": 98.0,
               "exposure": 4.0, "vacant_units": 5, "new_prospects": leads,
               "first_tours_booked": 20, "first_tours_attended": 15,
               "applications_completed": 4, "leases_signed": 3}
        if refused:
            sec["refused"] = refused
        return bm.store_building_metrics(prop, {
            "report_type": "bldg_metrics_csv", "as_of": as_of, "landed_at": landed,
            "source_file": f"metrics-building-{as_of}.csv", "sections": [sec]})

    fp = bm.DATA / "the-landing" / "building_metrics.json"
    pts = lambda: json.load(open(fp))["points"]  # noqa: E731
    store("2026-09-28", 101, "2026-09-28T17:12:11Z")
    store("2026-08-31", 107, "2026-08-31T17:55:34Z")
    check("a later export does not supersede an earlier one",
          [p["as_of"] for p in pts()], ["2026-08-31", "2026-09-28"])
    store("2026-09-28", 99, "2026-09-29T09:00:00Z")
    check("one date re-filed is still one point", len(pts()), 2)
    check("and the later arrival's figures win",
          next(p for p in pts() if p["as_of"] == "2026-09-28")["new_prospects"], 99)
    got = store("2026-09-28", 50, "2026-09-28T08:00:00Z")
    check("an earlier arrival of a held date is turned away", got is bm.KEPT_NEWER, True)
    check("and leaves the held point alone",
          next(p for p in pts() if p["as_of"] == "2026-09-28")["new_prospects"], 99)
    got = store("2026-10-05", 80, "2026-10-05T17:24:01Z", refused="rates do not reproduce")
    check("a refused building is not stored", (got is bm.KEPT_NEWER, len(pts())), (True, 2))

    print("the published block")
    os.makedirs(bm.DATA / "chorus", exist_ok=True)
    json.dump({"points": [{"as_of": "2026-09-28", "new_prospects": 285, "occupancy": 96.4,
                           "first_tours_attended": 79, "applications_completed": 15,
                           "heading": "Chorus", "extra": "not published"},
                          {"as_of": "2026-08-19", "new_prospects": 313}]},
              open(bm.DATA / "chorus" / "building_metrics.json", "w"))
    os.makedirs(bm.DATA / "madelon", exist_ok=True)
    json.dump({"points": [{"as_of": "2026-09-28", "new_prospects": 220}]},
              open(bm.DATA / "madelon" / "building_metrics.json", "w"))
    block = bm.building_metrics_block([
        {"slug": "the-landing", "name": "The Landing", "active": True},
        {"slug": "chorus", "name": "Chorus", "active": True},
        {"slug": "madelon", "name": "Madelon", "active": False},
        {"slug": "palma", "name": "Palma", "active": True}])
    by = {p["slug"]: p for p in block["properties"]}
    check("active buildings with a store, and nothing else", sorted(by), ["chorus", "the-landing"])
    check("points in date order", [p["as_of"] for p in by["chorus"]["points"]],
          ["2026-08-19", "2026-09-28"])
    check("only the keys the card reads", sorted(by["chorus"]["points"][1]),
          sorted(("as_of", "landed_at", "source_file") + bm.BLDG_FIELDS))
    check("available", block["available"], True)

    print("the router: the export's own headings reach their buildings")
    run = pathlib.Path(tmp) / "run"
    (run / "config").mkdir(parents=True)
    for f in ("properties.json", "report_map.json", "coa_map.json"):
        shutil.copy(os.path.join(REPO, "config", f), run / "config" / f)
    (run / "_downloads").mkdir()
    csv1 = write(str(run / "_downloads"), "metrics-building-2026-09-22.csv",
                 [row("Chorus", 96.15, 302, 67, 15), row("The Landing", 99.24, 84, 18, 6),
                  row("The Madelon", 96.53, 244, 32, 2), row("335 3rd Street", 10.53, 82, 18, 6),
                  row("Nowhere Towers", 50.0, 10, 1, 0)])
    csv2 = write(str(run / "_downloads"), "metrics-building-2026-09-28.csv",
                 [row("The Landing", 99.24, 101, 14, 4)])
    json.dump([{"name": os.path.basename(c), "path": c, "report_type": "bldg_metrics_csv",
                "parser": "parse_building_metrics", "landed_at": landed}
               for c, landed in ((csv1, "2026-09-22T22:27:05Z"), (csv2, "2026-09-28T17:12:11Z"))],
              open(run / "_downloads" / "manifest.json", "w"))
    cwd, data = os.getcwd(), bm.DATA
    os.environ["PARSE_CACHE"] = "off"
    try:
        os.chdir(run)
        bm.DATA = pathlib.Path("data")
        bm.process_manifest()
        held = {s: json.load(open(run / "data" / s / "building_metrics.json"))["points"]
                for s in ("the-landing", "chorus", "madelon", "335-third-street")
                if (run / "data" / s / "building_metrics.json").exists()}
    finally:
        os.chdir(cwd)
        bm.DATA = data
    check("all four EliseAI buildings are stored, by their own headings",
          sorted(held), ["335-third-street", "chorus", "madelon", "the-landing"])
    check("The Landing has both exports, in date order",
          [p["as_of"] for p in held.get("the-landing", [])], ["2026-09-22", "2026-09-28"])
    check("each point records the file Drive filed it under",
          held["the-landing"][1]["source_file"], "metrics-building-2026-09-28.csv")
    check("and when it landed", held["the-landing"][1]["landed_at"], "2026-09-28T17:12:11Z")
    check("a heading the master does not know is stored nowhere",
          sorted(p.name for p in (run / "data").iterdir()),
          ["335-third-street", "chorus", "madelon", "the-landing"])
finally:
    shutil.rmtree(tmp)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)

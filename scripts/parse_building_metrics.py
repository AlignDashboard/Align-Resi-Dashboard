#!/usr/bin/env python3
"""Read the EliseAI building-metrics export as one section per building.

`metrics-building-<YYYY-MM-DD>.csv` (`metricsbuilding<YYYYMMDD>.csv` before
2026-08) is one row per community. populate_building_metrics.py fills the
scorecard from the NEWEST export and keeps nothing else, so the leasing counts
and the occupancy in it never became a series. This reads every export, so the
store can keep one point per export date -- the Portfolio tab's Leasing &
Occupancy card draws them.

What it reads, per building:

  occupancy               Occupancy Rate (Period End), percent
  exposure                Exposure Rate (Period End), percent -- leased is 100
                          less this, the scorecard's own reading of Leased %
  vacant_units            Vacant Units (Period End)
  new_prospects           New Prospects                 -> leads
  first_tours_booked      First Tours Booked
  first_tours_attended    First Tours Attended          -> tours
  applications_completed  Applications Completed        -> applications
  leases_signed           Leases Signed

FIRST tours, because it is the count in every export. Total Tours Attended went
with the 75 -> 40 column change on 2026-09-22 (open item B9); First Tours
Attended is in the 79- and 75-column exports before it and the 40- and
41-column ones since. Where both were published they agree within a tour or two
(The Landing 22/22, Chorus 70/71 on 08-31), and the export's own Prospect to
Tour Attended Rate is computed from the FIRST count -- so it is the one the file
itself treats as its tours.

Checked against the export's own arithmetic, because a file that cannot
reproduce its own rates is not saying what its column names say:

  First Tours Attended   / New Prospects  ==  Prospect to Tour Attended Rate
  Applications Completed / New Prospects  ==  Prospect to App Completed Rate

to the hundredth the export prints. A building whose counts fail is marked
`refused` and the store reports it rather than keeping it. A rate the row does
not print (335 Third's blanks) cannot be checked and is said to be unchecked,
not passed.

A column the card needs that is missing from the header refuses the whole
file: B9 is the evidence that the export's columns move without notice, and a
dropped column read as blank would draw as a building with no leads.

No person-level data: one row per building, counts and rates only. The export
states its period nowhere inside the file, so the filename date is the snapshot
date, and the counts trail one month from it (owner, 2026-08-20).
"""
import csv
import os
import re
import sys

# store key -> the export's column
FIELDS = {
    "occupancy": "Occupancy Rate (Period End)",
    "exposure": "Exposure Rate (Period End)",
    "vacant_units": "Vacant Units (Period End)",
    "new_prospects": "New Prospects",
    "first_tours_booked": "First Tours Booked",
    "first_tours_attended": "First Tours Attended",
    "applications_completed": "Applications Completed",
    "leases_signed": "Leases Signed",
}
# The columns the card draws. Without one of these the file is refused; the
# others are kept where present and published as null where not.
REQUIRED = ("occupancy", "new_prospects", "first_tours_attended",
            "applications_completed")
# (count, over, the export's own rate for count / over, in percent)
RATE_CHECKS = (
    ("first_tours_attended", "new_prospects", "Prospect to Tour Attended Rate"),
    ("applications_completed", "new_prospects", "Prospect to App Completed Rate"),
)
# The export prints rates to the hundredth of a percentage point, so a count
# that reproduces its rate lands within half a hundredth of it.
RATE_TOLERANCE = 0.006


def as_of_from_name(path):
    """metricsbuilding20260819.csv or metrics-building-2026-08-19.csv ->
    2026-08-19 (EliseAI changed the naming between exports). The export states
    its period nowhere inside the file, so the filename is the only date.
    populate_building_metrics reads it from here, so the two cannot date one
    export differently.

    The LAST date in the name, not the first: the Gmail filer prefixes the
    arrival date to what it files, and "2026-10-06 metrics-building-2026-10-05"
    is the export of the 5th that arrived on the 6th -- the daily leasing
    parser's rule. A name whose only date is that prefix falls back to it."""
    found = re.findall(r"(20\d{2})-?(\d{2})-?(\d{2})", os.path.basename(path))
    return "-".join(found[-1]) if found else None


def num(v):
    v = (v or "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def parse(path):
    as_of = as_of_from_name(path)
    if not as_of:
        raise ValueError(f"no date in the filename {os.path.basename(path)!r}; "
                         f"the export carries its date nowhere else")
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        header = list(reader.fieldnames or [])
        rows = list(reader)
    if "Property" not in header:
        raise ValueError("no Property column -- not a building-metrics export")
    missing = [FIELDS[k] for k in REQUIRED if FIELDS[k] not in header]
    if missing:
        raise ValueError("the export no longer carries " + ", ".join(missing)
                         + " -- refused rather than read as blank")

    sections = []
    for r in rows:
        heading = (r.get("Property") or "").strip()
        if not heading:
            continue
        vals = {k: num(r.get(col)) for k, col in FIELDS.items()}
        checks, failed = [], []
        for count, over, col in RATE_CHECKS:
            rate = num(r.get(col)) if col in header else None
            a, b = vals[count], vals[over]
            label = f"{FIELDS[count]} / {FIELDS[over]} reproduces {col}"
            if rate is None or a is None or not b:
                checks.append({"check": label, "ok": None,
                               "note": "not checkable: the row prints no rate"
                                       if rate is None else "not checkable: no prospects"})
                continue
            got = a / b * 100
            ok = abs(got - rate) <= RATE_TOLERANCE
            checks.append({"check": label, "ok": ok, "export": rate,
                           "computed": round(got, 4)})
            if not ok:
                failed.append(f"{FIELDS[count]} {a:g} / {FIELDS[over]} {b:g} = "
                              f"{got:.2f}%, but its {col} is {rate:.2f}%")
        sec = {"property_code": heading, "as_of": as_of, **vals, "checks": checks}
        if failed:
            sec["refused"] = "; ".join(failed)
        sections.append(sec)

    if not sections:
        raise ValueError("no building rows")
    # No source_file: process_manifest records the name Drive filed it under,
    # which is the name a reader would search the folder for.
    return {"report_type": "bldg_metrics_csv", "as_of": as_of,
            "columns": len(header), "sections": sections}


if __name__ == "__main__":
    import json
    for p in sys.argv[1:]:
        print(json.dumps(parse(p), indent=2))

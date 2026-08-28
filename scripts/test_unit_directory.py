#!/usr/bin/env python3
"""Guard tests for the Unit Directory parser.

Fixture-free: builds synthetic exports shaped like the real Yardi one — a title
row, a header row, a bare property-code row opening each section, unit rows, a
"Total <code>" row closing it, and a "Grand Total" row at the end — then checks
the section split, the floorplan table, the placeholder count, and that every
tie-out the parser claims to make actually refuses a broken file.

Run: python scripts/test_unit_directory.py
"""
import os
import sys
import tempfile

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse_unit_directory as ud  # noqa: E402

PASS = FAIL = 0


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


HEADER = ["Unit", "Address", "Unit Type", "Rent", "Deposit", "Sqft", "Room", "Baths", "Notes"]

# (unit, plan, rent, sqft, beds, baths)
LANDING = [
    ("101", "laa1", 5595, 560, 1, 1),
    ("102", "laa1", 5640, 536, 1, 1),
    ("209", "lac1", 7924, 1096, 3, 2),
    ("355", "lab19", 8241, 1095, 2, 2),
    ("WAITLIST", "laa1", 5565, 821, 1, 1),
]
CHORUS = [
    ("0201", "cha1V", 5005, 684, 1, 1),
    ("0312", "chs1F", 3897, 505, 0, 1),      # a studio: Room = 0
]


def build(path, rows_by_code, break_section=None, break_grand=False,
          extra_col=False, mixed_beds=False):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Report1"
    ws.append(["Unit Directory"])
    ws.append(["For Selected Properties"])
    # extra_col shifts every data column right by one, which is what an added
    # export column does -- the parser anchors on the header, so it must cope.
    pad = [None] if extra_col else []
    ws.append(pad + HEADER)
    g_units = g_rent = g_sqft = 0
    for code, rows in rows_by_code.items():
        ws.append(pad + [code])
        rent = sqft = 0
        for i, (unit, plan, r, sf, bed, bath) in enumerate(rows):
            if mixed_beds and code == "p0005611" and plan == "laa1" and i == 1:
                bed = 2                      # same plan, a different bedroom count
            ws.append(pad + [unit, "somewhere", plan, float(r), 0.0, float(sf),
                             float(bed), float(bath), None])
            rent += r
            sqft += sf
        n = len(rows)
        if break_section == code:
            n += 1                           # the report claims one unit more
        ws.append(pad + [f"Total {code}", None, f"Units: {n}", float(rent), 0.0, float(sqft)])
        g_units += len(rows)
        g_rent += rent
        g_sqft += sqft
    ws.append(pad + ["Grand Total", None, f"Units: {g_units + (7 if break_grand else 0)}",
                     float(g_rent), 0.0, float(g_sqft)])
    wb.save(path)


def main():
    tmp = tempfile.mkdtemp()
    both = {"p0005611": LANDING, "p0003872": CHORUS}

    good = os.path.join(tmp, "UnitDirectory08_25_2026.xlsx")
    build(good, both)
    p = ud.parse(good)

    print("sections and tie-outs")
    ok("no problems on a clean export", not p["problems"], p["problems"])
    ok("as-of read from the filename", p["as_of"] == "2026-08-25", p["as_of"])
    codes = [s["property_code"] for s in p["sections"]]
    ok("one section per property code", codes == ["p0005611", "p0003872"], codes)
    land = p["sections"][0]
    ok("unit count is the section's own rows", land["units"] == 5, land["units"])
    ok("placeholders counted apart from apartments",
       land["residential_units"] == 4 and land["placeholder_units"] == 1
       and land["placeholders"] == ["WAITLIST"], land)
    ok("rent and sqft totals tie out",
       all(c["gap"] < 0.01 for c in land["checks"]) and len(land["checks"]) == 3,
       land["checks"])
    ok("grand total checked across sections",
       p["checks"] and p["checks"][0]["gap"] == 0, p["checks"])

    print("the floorplan table")
    pl = land["plans"]
    ok("one entry per plan", sorted(pl) == ["laa1", "lab19", "lac1"], sorted(pl))
    ok("bedrooms and baths carried", pl["lac1"]["bedrooms"] == 3 and pl["lac1"]["baths"] == 2.0, pl["lac1"])
    ok("plan unit count includes its placeholder", pl["laa1"]["units"] == 3, pl["laa1"])
    ok("sqft range and average",
       pl["laa1"]["sqft_min"] == 536 and pl["laa1"]["sqft_max"] == 821
       and pl["laa1"]["sqft_avg"] == round((560 + 536 + 821) / 3), pl["laa1"])
    ok("rent range", pl["laa1"]["rent_min"] == 5565 and pl["laa1"]["rent_max"] == 5640, pl["laa1"])
    ok("a studio keeps bedrooms 0, not null",
       p["sections"][1]["plans"]["chs1F"]["bedrooms"] == 0,
       p["sections"][1]["plans"]["chs1F"])

    print("refusals")
    bad = os.path.join(tmp, "UnitDirectory08_25_2026.xlsx".replace("08", "09"))
    build(bad, both, break_section="p0005611")
    pb = ud.parse(bad)
    ok("a unit count that disagrees with the report is reported",
       any("unit count does not tie out" in x for x in pb["problems"]), pb["problems"])
    ok("...and only for the section that broke",
       not any("p0003872" in x for x in pb["problems"]), pb["problems"])

    bg = os.path.join(tmp, "grand.xlsx")
    build(bg, both, break_grand=True)
    pg = ud.parse(bg)
    ok("a grand total that disagrees is reported",
       any("grand total" in x for x in pg["problems"]), pg["problems"])

    mb = os.path.join(tmp, "mixed.xlsx")
    build(mb, both, mixed_beds=True)
    pm = ud.parse(mb)
    ok("a plan with two bedroom counts is reported, not averaged",
       any("bedrooms" in x for x in pm["problems"])
       and pm["sections"][0]["plans"]["laa1"]["bedrooms"] == 1, pm["problems"])

    print("layout drift")
    sh = os.path.join(tmp, "shifted.xlsx")
    build(sh, both, extra_col=True)
    ps = ud.parse(sh)
    ok("a column inserted before Unit does not move the read",
       not ps["problems"] and ps["sections"][0]["plans"] == pl, ps["problems"])

    blank = os.path.join(tmp, "blank.xlsx")
    wb = openpyxl.Workbook()
    wb.active.title = "Report1"
    wb.active.append(["Some other report"])
    wb.save(blank)
    try:
        ud.parse(blank)
        ok("a file with no directory header raises", False, "no exception")
    except Exception as e:                                  # noqa: BLE001
        ok("a file with no directory header raises", "header" in str(e).lower(), str(e))

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()

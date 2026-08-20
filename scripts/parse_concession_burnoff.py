"""
parse_concession_burnoff.py
---------------------------
Parses the Yardi concession burn-off export (ConcessionBurnOffMM_DD_YYYY.xlsx).
One sheet ("Report1"), verified against the 2026-08-10 export via the inspect
workflow:

  r1  Concession Burn Off
  r2  For Selected Properties
  r3  As Of = 08/10/2026
  r4-6  a header split over three rows:
        Unit | Unit Type | Resident | Name | Move In Date | Lease Start Date |
        Total Recurring Concessions | Current Lease Concessions |
        Current Lease Concessions Remaining | Concession End Date |
        Lease Term | Market Rent | Lease Rent | Current Month
  r7+  one row per unit with an active concession, then a total row

The Resident/Name columns are read only to tell a data row from the total row
and are NEVER put in the output -- the row dicts simply do not carry them, in
addition to build_metrics.scrub() stripping PII centrally.

ATTRIBUTION: the export says only "For Selected Properties" -- no property code
or name anywhere in the file (inspector confirmed), so the parse carries
property_code None and an "unattributed" flag. build_metrics logs it and stores
nothing until the owner settles which property (or properties) the export
covers; guessing would file one building's concessions under another.

Tie-out: the unit rows must sum to the total row on every money column, else
the parse is refused.
"""

import datetime
import os
import re

import openpyxl

SHEET = "Report1"
TITLE = "Concession Burn Off"

# canonical keys, in sheet column order (C and D are the resident-name columns,
# read for row classification but never emitted)
COLS = ("unit", "unit_type", "_resident", "_name", "move_in", "lease_start",
        "recurring_concessions", "current_lease_concessions",
        "concessions_remaining", "concession_end", "lease_term",
        "market_rent", "lease_rent", "current_month")
MONEY = ("recurring_concessions", "current_lease_concessions",
         "concessions_remaining", "market_rent", "lease_rent")


def _date(v):
    if isinstance(v, (datetime.datetime, datetime.date)):
        return (v.date() if isinstance(v, datetime.datetime) else v).isoformat()
    return v


def parse(path, strict=True):
    wb = openpyxl.load_workbook(path, data_only=True)
    if SHEET not in wb.sheetnames:
        raise ValueError(f"not a concession burn-off export: no {SHEET!r} sheet")
    ws = wb[SHEET]

    if str(ws["A1"].value or "").strip() != TITLE:
        raise ValueError(f"A1 is {ws['A1'].value!r}, expected {TITLE!r} -- layout moved")
    coverage = str(ws["A2"].value or "").strip() or None
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", str(ws["A3"].value or ""))
    as_of = f"{m.group(3)}-{m.group(1)}-{m.group(2)}" if m else None
    if strict and not as_of:
        raise ValueError(f"no 'As Of = MM/DD/YYYY' in A3 ({ws['A3'].value!r})")

    # the header spans rows 4-6; row 4 must still carry the anchor labels
    if str(ws["A4"].value or "").strip() != "Unit":
        raise ValueError(f"A4 is {ws['A4'].value!r}, expected 'Unit' -- header moved")

    units, total_row = [], None
    for r in ws.iter_rows(min_row=7, values_only=True):
        vals = dict(zip(COLS, r))
        has_money = any(vals.get(k) is not None for k in MONEY)
        if not has_money and vals.get("unit") is None:
            continue
        label = str(vals.get("unit") or "").strip().lower()
        # the total row has money but no unit number (or says so outright)
        if has_money and (vals.get("unit") is None or label.startswith("total")):
            total_row = vals
            continue
        units.append({
            "unit": vals.get("unit"),
            "unit_type": vals.get("unit_type"),
            "move_in": _date(vals.get("move_in")),
            "lease_start": _date(vals.get("lease_start")),
            "concession_end": _date(vals.get("concession_end")),
            "lease_term": vals.get("lease_term"),
            "recurring_concessions": vals.get("recurring_concessions"),
            "current_lease_concessions": vals.get("current_lease_concessions"),
            "concessions_remaining": vals.get("concessions_remaining"),
            "market_rent": vals.get("market_rent"),
            "lease_rent": vals.get("lease_rent"),
        })

    totals = {k: round(sum(u[k] or 0 for u in units), 2)
              for k in MONEY}
    checks = []
    if total_row is not None:
        for k in MONEY:
            want = total_row.get(k)
            if want is None:
                continue
            ok = abs(totals[k] - want) < 0.5
            checks.append({"field": k, "units_sum": totals[k],
                           "report_total": round(want, 2), "ok": ok})
            if strict and not ok:
                raise ValueError(f"tie-out failed: units sum to {totals[k]:,.2f} "
                                 f"for {k} but the report total says {want:,.2f}")

    return {
        "report_type": "concession_burnoff",
        "as_of": as_of,
        "source_file": os.path.basename(path),
        # no property code or name anywhere in the export
        "property_code": None,
        "unattributed": True,
        "coverage": coverage,
        "unit_count": len(units),
        "totals": totals,
        "units": units,
        "checks": checks,
    }


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(parse(sys.argv[1]), indent=2, default=str))

"""
parse_daily_leasing.py
----------------------
Parses the weekly leasing workbook (`Daily Report- Week Ending <date>.xlsx`)
into the per-lease trade-out detail the dashboard's Trade-outs card needs.

This is the report behind the analyst workbook's `Lease Detail` tab, which is
hand-typed today. It is *not* a RealPage export, despite that tab's name: it is
Align's own weekly leasing workbook, filed into the Drive `Daily Leasing
Reports` folder. The NEW LEASES block on its `Weekly_Leases` sheet carries the
one field nothing else in the pipeline has -- PRIOR LEASE RATE, what the unit
rented for before. Without it no trade-out can be computed from any source.

Two traps this handles, both of which would publish a wrong building or a wrong
number:

  * The file names its property in three places and they do not always agree.
    Chorus's 2026-09-09 copy says "Chorus / 416 units" in the `Weekly_Leases`
    header block and "The Landing / 263 units" on its `Information` sheet,
    which is a template field nobody updated. Order of trust is therefore the
    FILENAME (when it names a known property), then the `Weekly_Leases` header,
    then `Information` last -- and any disagreement is reported rather than
    silently resolved. The Landing's own file needs the second source: its name,
    `Daily Report- Week Ending 9.7.26.xlsx`, carries no property at all.
  * The lease rows are followed by a CANCEL/DENIALS section whose rows sit in
    the same columns, and by a WEEKLY AVERAGE row. Reading past either inflates
    the week.

The report computes its own trade-out, so every row is checked against its own
arithmetic -- lease rent less prior rate must equal the trade-out dollars, and
the percentage must equal that over the prior rate. A file that fails its own
arithmetic is reported rather than returned.

Usage:
    from parse_daily_leasing import parse
    result = parse("path/to/Daily Report- Week Ending 9.7.26.xlsx")
"""
import json
import os
import re
import sys

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xlsx_anchors import (LayoutError, cell, header_map, norm,  # noqa: E402
                          property_from_filename, rows_until)

SHEET = "Weekly_Leases"
INFO_SHEET = "Information"

# field -> pattern matched against the joined header text. "MKT (M) / AHP (A)"
# on The Landing is "MKT (M)" on Chorus, so that one is matched loosely.
COLUMNS = {
    "unit": r"^apt ?#",
    "rent_type": r"^mkt",
    "floor_plan": r"floor plan",
    "beds_baths": r"^brxba",
    "sqft": r"size \(sqft\)|^sq ?ft",
    "lease_rent": r"^lease rent",
    "gross_psf": r"^gross \$",
    "concession": r"total rent concession",
    "net_rent": r"^net rent value",
    "net_psf": r"^net \$",
    "prior_rent": r"prior lease rate",
    "tradeout_amount": r"trade ?out \$",
    "tradeout_pct": r"trade ?out %",
    "move_in": r"scheduled mi date",
    "term": r"^lease term",
    "agent": r"leasing associate",
}

# Sections that follow the lease block in the same columns. Reading past any of
# these mixes cancellations and move-outs into the lease list.
STOP = [r"^cancel", r"^weekly average", r"^total", r"^apt ?#", r"^move ?outs?",
        r"^notices?", r"^lease breaks?"]

# Rows whose arithmetic may disagree by this much and still count as clean --
# the workbook rounds its displayed trade-out to the dollar.
TOLERANCE = 1.01


def _all_dates(text):
    """Every date-shaped token in `text`, in order, as YYYY-MM-DD.

    Two spellings: ISO, which is how the filer writes the arrival date it
    prefixes, and the M.D.YY the on-site team writes ("Week Ending 9.7.26",
    "09.07.2026- 09.13.2026-").
    """
    out = []
    for m in re.finditer(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)"
                         r"|(?<!\d)(\d{1,2})\.(\d{1,2})\.(\d{2,4})(?!\d)", str(text)):
        if m.group(1):
            out.append((m.start(), m.group(0)))
            continue
        mo, day, yr = int(m.group(4)), int(m.group(5)), int(m.group(6))
        yr += 2000 if yr < 100 else 0
        if 1 <= mo <= 12 and 1 <= day <= 31:
            out.append((m.start(), f"{yr:04d}-{mo:02d}-{day:02d}"))
    return out


def _date_like(v):
    """The first date-shaped token in `v`, or None."""
    got = _all_dates(v) if v is not None else []
    return got[0][1] if got else None


def _week_from_filename(path):
    """The week a file covers, from its NAME, or None.

    The LAST date in the name: the filer prefixes its own arrival date at the
    front, and what follows is the week -- "Week Ending 9.7.26" for The
    Landing, a "09.07.2026- 09.13.2026-" range for Chorus, whose last date is
    the week end either way.

    The one date that is never the week is that arrival prefix standing alone,
    so a single date at the very start of the name is ignored and the sheet
    decides. A single date anywhere else IS the week -- that is a file placed
    by hand rather than by the filer, which carries no prefix.
    """
    got = _all_dates(os.path.basename(path))
    if not got:
        return None
    if len(got) == 1 and got[0][0] == 0:
        return None                     # only the filer's own arrival prefix
    return got[-1][1]


def _week_ending(ws, path):
    """What the SHEET says its week ends on, as YYYY-MM-DD, or None.

    Two spellings in the wild: The Landing writes 'Week Ending' beside a real
    date cell; Chorus writes 'Week To Date' beside the text 'Ending 09.13.26'.
    So the row is found on the word "ending" anywhere in it and the first
    date-shaped value to its right wins.

    This is not the week LABEL -- see parse(). The cell drifts between
    snapshots of one week: the 2026-08-31 and 2026-09-08 copies of "Week Ending
    9.7.26" say 2026-09-07 and 2026-09-06, which keyed the store twice for one
    week and counted it twice.
    """
    for r in range(1, min(ws.max_row, 24) + 1):
        cells = [(c, ws.cell(row=r, column=c).value)
                 for c in range(1, min(ws.max_column, 14) + 1)]
        at = next((c for c, v in cells if "ending" in norm(v)), None)
        if at is None:
            continue
        for c, v in cells:
            if c < at:
                continue
            got = _date_like(cell(ws, r, c) if not isinstance(v, str) else v)
            if got:
                return got
    return None


def _sheet_property(ws):
    """Property and unit count from the Weekly_Leases header block.

    This is the reliable in-file source: Chorus's copy names Chorus and 416
    units here while its Information sheet still says The Landing and 263.
    """
    name = units = None
    for r in range(1, min(ws.max_row, 20) + 1):
        for c in range(1, min(ws.max_column, 6) + 1):
            label = norm(ws.cell(row=r, column=c).value).rstrip(":")
            if label not in ("property", "units"):
                continue
            for cc in range(c + 1, min(c + 5, ws.max_column) + 1):
                v = ws.cell(row=r, column=cc).value
                if v is None or str(v).strip() == "":
                    continue
                if label == "property" and name is None:
                    name = str(v).strip()
                elif label == "units" and units is None:
                    units = v
                break
    return name, units


def _info(wb):
    if INFO_SHEET not in wb.sheetnames:
        return None, None
    ws = wb[INFO_SHEET]
    name = units = None
    for r in range(1, min(ws.max_row, 12) + 1):
        label = norm(ws.cell(row=r, column=1).value)
        if label == "property":
            name = ws.cell(row=r, column=2).value
        elif label == "units":
            units = ws.cell(row=r, column=2).value
    return name, units


def parse(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    if SHEET not in wb.sheetnames:
        raise LayoutError(f"{os.path.basename(path)}: no {SHEET!r} sheet — "
                          f"sheets are {wb.sheetnames}")
    ws = wb[SHEET]

    info_name, info_units = _info(wb)
    sheet_name, sheet_units = _sheet_property(ws)
    file_name = property_from_filename(path)
    # Order of trust: the filename, then this sheet's own header block, then
    # the Information sheet last -- see the module docstring. Chorus's file
    # names Chorus in the first two and The Landing in the third.
    resolved = file_name or sheet_name or info_name
    problems = []
    named = [("filename", file_name), ("Weekly_Leases header", sheet_name),
             ("Information sheet", info_name)]
    disagree = [f"{src} says {v!r}" for src, v in named
                if v and norm(v) != norm(resolved)]
    if disagree:
        problems.append(
            f"the file disagrees with itself about which property it is: "
            + "; ".join(disagree) + f". {resolved!r} is used, from the "
            + next(src for src, v in named if v and norm(v) == norm(resolved))
            + ". The Information sheet is a template field and is not always updated")

    fields, header_row = header_map(ws, COLUMNS, search_rows=45, join_rows=2)
    def _numeric(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    leases, stopped = rows_until(
        ws, header_row + 1, fields, STOP, "unit",
        # A blank spacer row carries no unit and no rent; a real lease has both,
        # and the rent must be a NUMBER. The sections below the lease block
        # overlap its columns -- a cancellation row puts its scheduled move-in
        # date where a lease's rent goes -- so a truthiness test alone lets a
        # date through and the totals then fail on str + int. STOP is the
        # primary guard; this is the one that keeps a surprise from crashing a
        # whole pipeline run instead of reporting itself.
        keep=lambda rec: rec.get("unit") is not None and _numeric(rec.get("lease_rent")))

    checks, clean = [], 0
    for lease in leases:
        rent, prior = lease.get("lease_rent"), lease.get("prior_rent")
        amt, pct = lease.get("tradeout_amount"), lease.get("tradeout_pct")
        if rent is None or prior is None or not prior:
            problems.append(f"unit {lease.get('unit')}: no prior lease rate — "
                            f"its trade-out cannot be verified")
            continue
        ok_amt = amt is not None and abs((rent - prior) - amt) < TOLERANCE
        ok_pct = pct is not None and abs(((rent - prior) / prior) - pct) < 0.005
        if ok_amt and ok_pct:
            clean += 1
        else:
            problems.append(
                f"unit {lease.get('unit')}: the report's own trade-out does not "
                f"reconcile — rent {rent} less prior {prior} is {rent - prior}, "
                f"the report says {amt} ({pct})")
    checks.append({"check": "every lease reconciles to its own trade-out",
                   "ok": clean == len(leases), "clean": clean,
                   "leases": len(leases)})

    # The week LABEL comes from the filename when it carries one, because the
    # sheet's own cell drifts between snapshots of the same week -- see
    # _week_ending. The store keys on this, so a drifting cell would file one
    # week twice; the sheet's answer is kept beside it and a disagreement is
    # reported rather than silently resolved.
    sheet_week = _week_ending(ws, path)
    file_week = _week_from_filename(path)
    week_ending = file_week or sheet_week
    if file_week and sheet_week and file_week != sheet_week:
        problems.append(
            f"the filename says the week ends {file_week} and the sheet says "
            f"{sheet_week}; the filename is used, because the sheet's cell moves "
            f"between snapshots of one week and would file that week twice")
    checks.append({"check": "week-ending date found", "ok": week_ending is not None,
                   "note": (f"{week_ending} (from the "
                            f"{'filename' if file_week else 'sheet'})")
                           if week_ending else
                           "no week-ending date in the header block or the filename"})
    checks.append({"check": "stopped at a section marker", "ok": stopped is not None,
                   "note": f"stopped at row {stopped[0]} ({stopped[1]!r})" if stopped
                           else "ran to the end of the sheet without a "
                                "CANCEL/DENIALS or WEEKLY AVERAGE marker"})
    checks.append({"check": "property resolved", "ok": resolved is not None,
                   "note": f"{resolved} (from the {'filename' if file_name else 'Weekly_Leases header' if sheet_name else 'Information sheet'})"
                           if resolved else "neither the filename nor the "
                                            "Information sheet names a property"})
    if not resolved:
        problems.append("no property could be resolved from the filename or the "
                        "Information sheet")

    total = sum(l["lease_rent"] or 0 for l in leases)
    prior_total = sum(l.get("prior_rent") or 0 for l in leases)
    return {
        "report_type": "daily_leasing_report",
        "property": resolved,
        # what build_metrics routes on; the aliases in config/properties.json
        # carry the plain names, so the resolved name resolves
        "property_code": resolved,
        "property_from_filename": file_name,
        "property_from_sheet": info_name,
        "sheet_units": sheet_units if sheet_units is not None else info_units,
        "property_from_sheet_header": sheet_name,
        "as_of": week_ending,
        "week_ending_sheet": sheet_week,
        "source_file": os.path.basename(path),
        "sheet": ws.title,
        "header_row": header_row,
        "columns": {k: v for k, v in sorted(fields.items(), key=lambda kv: kv[1])},
        "leases": leases,
        "totals": {
            "leases": len(leases),
            "lease_rent": round(total, 2),
            "prior_rent": round(prior_total, 2),
            "tradeout_amount": round(total - prior_total, 2),
            # unweighted, to match how the Trade-outs card averages the
            # new-lease side; the rent-weighted figure is derivable from the
            # totals above and is not asserted here as if it were the same thing
            "tradeout_pct_mean": (round(sum(l["tradeout_pct"] for l in leases
                                            if l.get("tradeout_pct") is not None)
                                        / len(leases), 6) if leases else None),
            "sqft": round(sum(l.get("sqft") or 0 for l in leases), 2),
            "concession": round(sum(l.get("concession") or 0 for l in leases), 2),
        },
        "checks": checks,
        "problems": problems,
    }


if __name__ == "__main__":
    out = parse(sys.argv[1])
    out.pop("leases", None) if "--summary" in sys.argv else None
    print(json.dumps(out, indent=2, default=str))

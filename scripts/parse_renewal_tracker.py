"""
parse_renewal_tracker.py
------------------------
Parses the renewal tracker (`Landing 2025 Renewal Tracker - Full (N).xlsx`,
Drive `Renewal Tracker`) into monthly renewal aggregates plus the
month-to-month roster.

This is the report behind the analyst workbook's `Source Renewal Tracker` and
`MTM` tabs, refreshed by pasting today. Unlike the weekly leasing workbook, one
file carries the whole history: a sheet per month, January 2024 through
December 2026 in the 2026-09-08 copy, plus an `MTM` sheet.

What makes this file awkward, and what each guard is for:

  * **The layout changes by vintage.** The 2024 sheets are a 69-81 column
    Yardi-style table with the header on row 14; the 2025-26 sheets are a
    ~22 column hand-built table with the header on row 8, 9, 10 or 11; two
    sheets put it on row 1. Column names moved with it ("Current Rent" became
    "CURRENT GROSS RENT", "Renewal Offer" became "BEST OFFER RATE"). So the
    header is matched by label with alternates, per sheet, and a sheet whose
    header cannot be found is RECORDED AS UNREAD rather than failing the file
    or -- much worse -- being read with the wrong columns.
  * **Every sheet carries resident names.** `NAMES` on the monthly sheets,
    `Name` on MTM. They are read only to tell a data row from a spacer and are
    never emitted; `build_metrics.scrub` is the backstop.
  * **A month sheet is a snapshot of offers, not of signings.** The status
    column is what separates "offered" from "renewed", so counts are reported
    per status rather than as one "renewals" number that would silently mean
    different things on different sheets.

Usage:
    from parse_renewal_tracker import parse
    result = parse("path/to/Landing 2025 Renewal Tracker - Full (42).xlsx")
"""
import json
import os
import re
import sys

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xlsx_anchors import (LayoutError, header_map, norm,  # noqa: E402
                          property_from_filename)

MTM_SHEET = "MTM"

# Monthly sheet columns. Alternates are separated by | because the workbook
# renamed them between vintages -- see the module docstring.
MONTH_COLUMNS = {
    "status": r"^status$",
    "unit": r"^unit$|^apt",
    "unit_type": r"unit type|floor ?plan",
    "lease_end": r"current lease end date|^lease exp|lease expiration",
    "current_rent": r"^current\s*(gross|effective)?\s*rent$",
    "current_term": r"current term|curent lease length|current lease length",
    "market_rent": r"^market rate$|^market rent$",
    "offered_rent": r"best offer rate|offered gross rate|^renewal offer|new lease rent|^offer rate$",
    "offer_difference": r"best offer difference|\$ increase|^best offer \$",
    "offer_pct": r"best offer %|% increase|best offer % change",
    "ltl": r"^current ltl$|^ltl$",
}
# The minimum that makes a sheet worth reading: without a unit, a current rent
# and an offered rent there is no renewal to report.
MONTH_REQUIRED = ("unit", "current_rent")

MTM_COLUMNS = {
    "status": r"^status$",
    "unit": r"^unit$",
    "unit_type": r"unit type",
    "resident_code": r"^code$",
    "mtm_charge": r"month to month charge",
    "mtm_charge_pct": r"mtm charge as %",
    "lease_from": r"lease from",
    "lease_to": r"lease to",
    "current_rent": r"^current rent$",
    "market_rent": r"^market rent$",
    "total_while_mtm": r"total rate while on mtm",
    "proposed_rate": r"proposed new rate",
    "increase_needed": r"rate increase needed",
}
MTM_REQUIRED = ("unit", "current_rent")

# Anything that is not a resident row. The monthly sheets end with totals and
# scratch notes in the same columns.
STOP_LABELS = (r"^total", r"^grand total", r"^summary", r"^count", r"^average",
               r"^notes?$", r"^tbd$")

MONTH_RE = re.compile(
    r"^(january|february|march|april|may|june|july|august|september|october|"
    r"november|december)\s+(\d{4})", re.I)
MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"])}


def sheet_month(title):
    """'September 2026' | 'February 2025 ' | 'July 2025 (2)' -> '2026-09'."""
    m = MONTH_RE.match(title.strip())
    if not m:
        return None
    return f"{int(m.group(2)):04d}-{MONTHS[m.group(1).lower()]:02d}"


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _money(v):
    """'$4,326' | '4,326' | 4326 | ' ha' -> 4326.0 | None.

    The 2025 sheets store money as preformatted text, so a numeric-only read
    sees a month of renewals as an empty month.
    """
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if not isinstance(v, str):
        return None
    s = v.replace("$", "").replace(",", "").strip()
    if not s or s.endswith("%"):
        return None
    try:
        return float(s)
    except ValueError:
        return None          # the sheets carry stray text like " ha"


# A renewal offer lands within this band of the current rent. Wider than any
# real increase, narrow enough to tell an offered RATE from an offered
# DIFFERENCE -- which is the whole problem below.
RATE_LO, RATE_HI = 0.6, 2.0


def _offered(current, candidates):
    """(offered rent, which column it came from) -- decided by ARITHMETIC.

    The label cannot be trusted: "BEST OFFER $" is the offer DIFFERENCE on the
    May 2025 sheet (4932 x 9.9% = 488) and the offered RATE on June 2025's
    (4326 x 1.0499 = 4542). Same words, opposite meanings, one month apart.

    A rate sits near the current rent and a difference sits near zero, so the
    two are cleanly separable by size: anything inside RATE_LO..RATE_HI of the
    current rent is a rate, anything that lands in that band once ADDED to the
    current rent is a difference. Neither -> the row is not published, rather
    than publishing an increase that is off by the whole rent.
    """
    for name, v in candidates:
        if v is not None and RATE_LO * current <= v <= RATE_HI * current:
            return v, name + " (a rate)"
    for name, v in candidates:
        if v is not None and RATE_LO * current <= current + v <= RATE_HI * current:
            return current + v, name + " (a difference)"
    return None, None


def _read_rows(ws, spec, required, label_field="unit"):
    """Rows from a sheet whose header is found by label. (rows, header_row).

    Raises LayoutError when the header cannot be found or the columns that make
    the sheet meaningful are missing -- the caller records that sheet as unread
    rather than guessing at its columns.
    """
    fields, header_row = header_map(ws, spec, search_rows=20, join_rows=2,
                                    min_hits=len(required) + 1)
    missing = [f for f in required if f not in fields]
    if missing:
        raise LayoutError(f"{ws.title!r}: header found on row {header_row} but "
                          f"without {', '.join(missing)}")
    out = []
    blanks = 0
    for r in range(header_row + 1, ws.max_row + 1):
        label = norm(ws.cell(row=r, column=fields[label_field]).value)
        if any(re.search(p, label) for p in STOP_LABELS):
            break
        if not label:
            blanks += 1
            # a run of blanks is the end of the table; a single spacer is not
            if blanks >= 6:
                break
            continue
        blanks = 0
        rec = {f: ws.cell(row=r, column=c).value for f, c in fields.items()}
        # Names are read to tell a row from a spacer and dropped here. Nothing
        # downstream ever sees them; scrub() in build_metrics is the backstop.
        rec.pop("name", None)
        for k in ("current_rent", "market_rent", "offered_rent",
                  "offer_difference"):
            if k in rec:
                rec[k] = _money(rec[k])
        cur = rec.get("current_rent")
        if cur:
            rec["offered_rent"], rec["offer_basis"] = _offered(
                cur, [("offered_rent", rec.get("offered_rent")),
                      ("offer_difference", rec.get("offer_difference"))])
        else:
            rec["offered_rent"] = rec["offer_basis"] = None
        if not cur and rec.get("offered_rent") is None:
            continue
        for k in ("lease_end", "lease_from", "lease_to"):
            if k in rec and rec[k] is not None:
                rec[k] = str(rec[k])[:10]
        out.append(rec)
    return out, header_row


def _month_summary(month, rows):
    """One row per month for the Trade-outs card's renewal series."""
    cur = [_num(r.get("current_rent")) for r in rows]
    off = [_num(r.get("offered_rent")) for r in rows]
    paired = [(c, o) for c, o in zip(cur, off) if c and o]
    bases = sorted({r["offer_basis"] for r in rows if r.get("offer_basis")})
    cur_total = round(sum(c for c, _ in paired), 2)
    off_total = round(sum(o for _, o in paired), 2)
    statuses = {}
    for r in rows:
        s = str(r.get("status") or "").strip() or "(blank)"
        statuses[s] = statuses.get(s, 0) + 1
    return {
        "month": month,
        "rows": len(rows),
        # only offers with both sides can carry an increase; the count the
        # dashboard plots is this one, not len(rows)
        "leases": len(paired),
        "current_rent": cur_total,
        "offered_rent": off_total,
        # rent-weighted, which is the only form these aggregates support: the
        # card's footnote says so, and an unweighted mean over rows missing one
        # side would quietly mean something else
        "wtd_increase": (round(off_total / cur_total - 1, 6)
                         if cur_total else None),
        "statuses": dict(sorted(statuses.items())),
        # which column the offered rent was taken from, and whether it was read
        # as a rate or as a difference -- recorded because the label alone does
        # not say, and a month that resolved the other way is worth seeing
        "offer_basis": bases,
        "unresolved": sum(1 for r in rows
                          if _num(r.get("current_rent")) and not r.get("offered_rent")),
    }


def parse(path):
    # Not read_only: header_map and _read_rows both address cells directly, and
    # openpyxl's read-only worksheet re-walks the sheet on every random access,
    # which turns the 499-row x 81-column 2024 sheets into minutes of work.
    wb = openpyxl.load_workbook(path, data_only=True)
    months, unread, mtm = [], [], None
    problems, checks = [], []

    for title in wb.sheetnames:
        if norm(title) == norm(MTM_SHEET):
            try:
                rows, hdr = _read_rows(wb[title], MTM_COLUMNS, MTM_REQUIRED)
            except LayoutError as e:
                unread.append({"sheet": title, "why": str(e)})
                continue
            charges = [_money(r.get("mtm_charge")) for r in rows]
            no_rent = sum(1 for r in rows if _money(r.get("current_rent")) is None)
            mtm = {
                "sheet": title, "header_row": hdr, "units": len(rows),
                # rows on the sheet whose current rent is "-" or blank: real
                # roster entries the aggregates cannot include, counted so the
                # difference between the roster and the totals is visible
                "rows_without_rent": no_rent,
                "current_rent": round(sum(_money(r.get("current_rent")) or 0
                                          for r in rows), 2),
                "market_rent": round(sum(_money(r.get("market_rent")) or 0
                                         for r in rows), 2),
                "mtm_charge": round(sum(c for c in charges if c), 2),
                "units_with_charge": sum(1 for c in charges if c),
                "statuses": dict(sorted(
                    (lambda d: d)({s: sum(1 for r in rows
                                          if (str(r.get("status") or "").strip()
                                              or "(blank)") == s)
                                   for s in {str(r.get("status") or "").strip()
                                             or "(blank)" for r in rows}}).items())),
                "rows": rows,
            }
            continue

        month = sheet_month(title)
        if month is None:
            unread.append({"sheet": title, "why": "not a month sheet"})
            continue
        try:
            rows, hdr = _read_rows(wb[title], MONTH_COLUMNS, MONTH_REQUIRED)
        except LayoutError as e:
            unread.append({"sheet": title, "why": str(e)})
            continue
        summary = _month_summary(month, rows)
        summary.update({"sheet": title, "header_row": hdr})
        months.append(summary)

    # Two sheets can name the same month ("July 2025" and "July 2025 (2)").
    # Keep the one with more offers rather than whichever sorted last, and say
    # so -- silently dropping half a month's renewals is the failure here.
    by_month = {}
    for m in sorted(months, key=lambda x: (x["month"], x["leases"])):
        prior = by_month.get(m["month"])
        if prior:
            problems.append(
                f"{m['month']} appears on two sheets ({prior['sheet']!r} with "
                f"{prior['leases']} offers and {m['sheet']!r} with {m['leases']}); "
                f"the fuller one is used")
        by_month[m["month"]] = m
    months = [by_month[k] for k in sorted(by_month)]

    checks.append({"check": "month sheets read", "ok": len(months) >= 6,
                   "note": f"{len(months)} month sheet(s) read, "
                           f"{len(unread)} not read"})
    checks.append({"check": "MTM roster read", "ok": mtm is not None,
                   "note": (f"{mtm['units']} units on {mtm['sheet']!r}" if mtm
                            else "no MTM sheet could be read")})
    skipped = [u for u in unread if u["why"] != "not a month sheet"]
    checks.append({"check": "every month sheet had a readable header",
                   "ok": not skipped,
                   "note": (f"{len(skipped)} sheet(s) skipped: "
                            + ", ".join(u["sheet"] for u in skipped[:6]))
                           if skipped else "all month sheets read"})
    if skipped:
        problems.append(
            f"{len(skipped)} sheet(s) were skipped because their header could "
            f"not be matched — they are older layouts, and their months are "
            f"absent from the series rather than wrong: "
            + ", ".join(u["sheet"] for u in skipped[:8]))
    prop = property_from_filename(path)
    checks.append({"check": "property named in the filename", "ok": prop is not None,
                   "note": prop or "the filename names no known property — the "
                                   "tracker names it nowhere else, so this file "
                                   "cannot be routed"})
    if prop is None:
        problems.append("the filename names no known property; a renewal tracker "
                        "carries its building only in its name")

    if not months:
        raise LayoutError(f"{os.path.basename(path)}: no month sheet could be "
                          f"read — this may not be a renewal tracker")

    return {
        "report_type": "renewal_tracker",
        # The tracker names its property nowhere inside itself -- every sheet
        # is a month of one building -- so the filename is the only source
        # ("Landing 2025 Renewal Tracker", "Chorus 2026 Renewal Tracker").
        "property": prop,
        "property_code": prop,
        # The newest month SHEET, which on a tracker runs ahead of today: it
        # carries offers already made for leases that have not expired yet.
        # `covers` is the honest span; landed_at is when the file arrived.
        "as_of": months[-1]["month"] if months else None,
        "covers": {"from": months[0]["month"], "to": months[-1]["month"]} if months else None,
        "source_file": os.path.basename(path),
        "months": months,
        "mtm": mtm,
        "unread_sheets": unread,
        "checks": checks,
        "problems": problems,
    }


if __name__ == "__main__":
    out = parse(sys.argv[1])
    if out.get("mtm"):
        out["mtm"].pop("rows", None)
    print(json.dumps(out, indent=2, default=str))

"""
parse_lease_tradeout.py
-----------------------
Parses the Yardi **Lease Tradeout Report** (`LeaseTradeoutReport-<property>.XLS`,
Drive `Historical Tradeout Reports`) into the per-lease trade-out history behind
the Trade-out % tile on the `Landing (Drive)` tab.

This is the only feed that carries a trade-out with *its own* history. The
weekly leasing workbook covers a fortnight and the EliseAI export publishes a
single trailing-month rate with no rows behind it; this report is one row per
new lease with the lease it replaced beside it, over whatever window it was run
for (The Landing's first file: 2024-08-01 to 2026-09-16, 247 leases).

Five things it is careful about, each of which would publish a wrong number:

  * **The header is two rows and half its names appear twice.** `Rate Type`,
    `Lease Start`, `Term`, `Prem`, `Gross Rent`, `Conc` and `Eff Rent` all sit
    once under `Current Lease` and again under `Previous Lease`, and only the
    group row above tells them apart. So the group row is forward-filled across
    its merged span and joined to the column row; matching on the column row
    alone picks whichever came first and silently swaps the two sides of every
    trade-out, which inverts the sign of the whole report.
  * **The report's own percentage is rent-weighted, not a mean.** Its Grand
    Total reads 23.4%, which is total current effective rent over total
    previous effective rent; the mean of the per-lease percentages is 70.1%.
    The gap is concessions: a previous lease with $2,977 gross and $2,260 of
    concession has an effective rent of $717, and one such row prints 434.6%.
    Both are published, the weighted one as the figure and the mean beside it,
    because a mean of ratios over a denominator that can approach zero is not
    a rate anyone should quote.
  * **A lease is dated by its App/Signed date**, which is what the report's own
    header says it selected on (`Lease Date: App Date/Signed Date`). Using the
    lease start instead would move leases between months against the report's
    own window and let a file report months outside the range it names.
  * **Every figure is tied out against the file's own `Grand Total:` row** on
    all three money columns, and the weighted percentage recomputed from them.
    A file that does not reproduce its own total is reported, not returned:
    silently dropping a floor-plan section would understate the building.
  * **The `Total:` and `Grand Total:` rows are identical here** because the
    file covers one property, and the per-section `Subtotal:` rows repeat the
    same columns. All of them are skipped by label before any row is read as a
    lease, so a subtotal is never counted as a 1,458-month lease.

No resident, no name, no lease id — 32 columns, checked. It still goes through
`store_report`'s central scrub, like the unit directory, rather than by
remembering that this one is safe.

Usage:
    from parse_lease_tradeout import parse
    result = parse("path/to/LeaseTradeoutReport-Landing.XLS")
"""
import datetime as dt
import io
import json
import os
import re
import sys

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xlsx_anchors import LayoutError, norm, property_from_filename  # noqa: E402

REPORT_TYPE = "lease_tradeout"

# Rows whose first cell is one of these are the report's own arithmetic, never
# a lease. Matched before anything else so a subtotal cannot be read as a row.
TOTAL_LABELS = ("subtotal:", "average:", "total:", "total average:",
                "grand total:", "grand total averages:")

# (group, column) -> field. The group is the merged banner above the column and
# is what tells the two halves of a trade-out apart; "" means the column has no
# group of its own (the trailing four).
COLUMNS = {
    ("unit details", "unit type"): "unit_type",
    ("unit details", "building"): "building",
    ("unit details", "unit"): "unit",
    ("unit details", "sq ft"): "sqft",
    ("current lease", "rate type"): "rate_type",
    ("current lease", "lease type"): "lease_type",
    ("current lease", "app signed date"): "signed",
    ("current lease", "lease start"): "start",
    ("current lease", "lease end"): "end",
    ("current lease", "term"): "term",
    ("current lease", "prem"): "premium",
    ("current lease", "gross rent"): "gross_rent",
    ("current lease", "conc"): "concession",
    ("current lease", "eff rent"): "eff_rent",
    ("previous lease", "rate type"): "prev_rate_type",
    ("previous lease", "lease start"): "prev_start",
    ("previous lease", "scheduled lease end"): "prev_scheduled_end",
    ("previous lease", "actual lease end"): "prev_actual_end",
    ("previous lease", "term"): "prev_term",
    ("previous lease", "prem"): "prev_premium",
    ("previous lease", "gross rent"): "prev_gross_rent",
    ("previous lease", "conc"): "prev_concession",
    ("previous lease", "eff rent"): "prev_eff_rent",
    ("vacant days", ""): "vacant_days",
    ("term variance", ""): "term_variance",
    ("trade out %", ""): "tradeout_pct",
    ("trade out $", ""): "tradeout_amount",
}

# the money columns the file's own Grand Total row has to reproduce
TIE_OUT = ("eff_rent", "prev_eff_rent", "tradeout_amount")

# What a file actually is, whatever it is called.
ZIP_MAGIC = b"PK\x03\x04"      # xlsx (a zip)
OLE2_MAGIC = b"\xd0\xcf\x11\xe0"  # genuine legacy .xls


def _open_workbook(path):
    """Load the workbook by CONTENT, not by extension.

    Yardi names this export `.XLS` and writes an `.xlsx` — the bytes start
    `PK\x03\x04`. openpyxl refuses a path ending `.xls` before it looks at it,
    so handing it the path raises "openpyxl does not support the old .xls file
    format" on a file it can read perfectly well. Passing the bytes skips that
    check. A file that really is the old format is named as such rather than
    left to fail somewhere further in.
    """
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw.startswith(OLE2_MAGIC):
        raise LayoutError(
            f"{os.path.basename(path)} is a genuine legacy .xls (OLE2) file, "
            f"which this pipeline cannot read — re-export it as .xlsx")
    if not raw.startswith(ZIP_MAGIC):
        raise LayoutError(
            f"{os.path.basename(path)} is neither an .xlsx nor an .xls "
            f"(starts {raw[:4]!r}) — not a Lease Tradeout Report")
    # Not read_only: this export carries no worksheet dimension record, and
    # openpyxl's read-only worksheet trusts that record rather than scanning --
    # it reports a single empty row for all 279 of them, so the header is never
    # found and the file looks like it is not a tradeout report at all. The
    # files are tens of kilobytes; the full reader costs nothing here.
    return openpyxl.load_workbook(io.BytesIO(raw), data_only=True)


def _num(v):
    """A Yardi money/percent/count cell as a float, or None.

    The export writes a negative two different ways in the same row, and puts
    the symbols in an order a single regex gets wrong: the dollar column uses
    `-$78` and the percentage column uses `(2.5%)` — parenthesised with the
    sign marker OUTSIDE the percent sign. Matching a pattern like `\)?%?$`
    therefore rejects every negative percentage, which is not an error anyone
    sees: 42 of The Landing's 247 leases went to None and only the positive
    ones were left to average. So the decorations come off first and what is
    left has to be a number.
    """
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).strip()
    if not t:
        return None
    neg = t.startswith("(") and t.endswith(")")
    for ch in "()$%, ":
        t = t.replace(ch, "")
    if t.startswith("-"):
        neg, t = True, t[1:]
    if not t or not re.fullmatch(r"\d*\.?\d+", t):
        return None
    return -float(t) if neg else float(t)


def _pct(v):
    """A percentage cell as a fraction. `35.0%` -> 0.35, `(2.5%)` -> -0.025."""
    x = _num(v)
    return None if x is None else x / 100.0


def _date(v):
    """`5/8/25` or a real datetime -> date, else None."""
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    t = "" if v is None else str(v).strip()
    if not t:
        return None
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(t, fmt).date()
        except ValueError:
            pass
    return None


def _header(rows):
    """Locate the two-row header and return {field: column index}.

    The group row's banners are merged across their columns, so only the first
    cell of each span carries text; it is forward-filled before being joined to
    the column row. Without that every `Previous Lease` column reads as a
    `Current Lease` one and the trade-out comes out backwards.
    """
    for i, row in enumerate(rows[:30]):
        cells = [norm(c) for c in row]
        if "unit type" not in cells or i + 1 > len(rows):
            continue
        col_row, grp_row = cells, [norm(c) for c in rows[i - 1]]
        filled, cur = [], ""
        for g in grp_row:
            cur = g or cur
            filled.append(cur)
        # A column with no group of its own (the trailing four) carries its own
        # name in the group row and nothing in the column row.
        idx = {}
        for c, (g, name) in enumerate(zip(filled, col_row)):
            key = (g, name) if name else (grp_row[c] if c < len(grp_row) else "", "")
            if key in COLUMNS:
                idx.setdefault(COLUMNS[key], c)
        missing = [f for f in COLUMNS.values() if f not in idx]
        if missing:
            raise LayoutError(
                "lease tradeout header found but these columns did not match: "
                + ", ".join(sorted(missing)))
        return idx, i + 1
    raise LayoutError("no 'Unit Type' header row — not a Lease Tradeout Report")


def _period(rows):
    """`From: 8/1/24 To: 9/16/26` -> (date, date). Both required."""
    for row in rows[:12]:
        for c in row:
            t = "" if c is None else str(c).strip()
            m = re.search(r"From:\s*(\S+)\s*To:\s*(\S+)", t, re.I)
            if m:
                a, b = _date(m.group(1)), _date(m.group(2))
                if a and b:
                    return a, b
                raise LayoutError(f"unreadable report period: {t!r}")
    raise LayoutError("no 'From: … To: …' period row — refusing to guess the window")


def _setting(rows, label):
    """The value of a `Label: value` setting row, or None."""
    pat = re.compile(re.escape(label) + r"\s*:\s*(.+?)\s*$", re.I)
    for row in rows[:12]:
        for c in row:
            t = "" if c is None else str(c).strip()
            m = pat.search(t)
            if m:
                return re.split(r"\s{2,}|\s+\w+ Date:", m.group(1))[0].strip()
    return None


def _property(rows, path):
    """(name, source, disagreement). Filename first, then the report's own row.

    Same order of trust as the weekly leasing workbook, for the same reason:
    the filename is what the person exporting chose for this file, where an
    owner-entity row is a Yardi field that outlives a re-org. They agree on The
    Landing's first file; a disagreement is reported rather than resolved.
    """
    from_name = property_from_filename(path)
    owner = None
    for row in rows[:20]:
        t = "" if not row or row[0] is None else str(row[0]).strip()
        if re.search(r"\b(LLC|LP|L\.P\.|Inc\.?|Property Owner)\b", t, re.I):
            owner = t
            break
    from_row = None
    if owner:
        cfg = json.load(open(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..",
            "config", "properties.json")))
        props = cfg if isinstance(cfg, list) else cfg.get("properties", [])
        low = owner.lower()
        for p in props:
            names = [p.get("name")] + list(p.get("aliases") or [])
            if any(n and n.lower() in low for n in names):
                from_row = p.get("name")
                break
    name = from_name or from_row
    disagree = (from_name and from_row and from_name != from_row
                and f"filename says {from_name!r}, the report's own owner row "
                    f"says {owner!r}")
    return name, ("filename" if from_name else "owner row"), (disagree or None), owner


def parse(path):
    """Parse a Lease Tradeout Report. Raises LayoutError on a file it cannot read."""
    wb = _open_workbook(path)
    ws = wb[wb.sheetnames[0]]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()

    idx, first = _header(rows)
    start, end = _period(rows)
    name, name_from, disagree, owner = _property(rows, path)

    get = lambda row, f: row[idx[f]] if idx[f] < len(row) else None  # noqa: E731
    iso = lambda v: (lambda d: d.isoformat() if d else None)(_date(v))  # noqa: E731

    leases, totals_row, plan, problems = [], None, None, []
    if disagree:
        problems.append(disagree)
    for row in rows[first:]:
        if not row:
            continue
        head = norm(row[0])
        if head in TOTAL_LABELS:
            if head == "grand total:":
                totals_row = row
            continue
        # "Floor Plan:" names the section the rows below it belong to; the code
        # itself sits a couple of cells along rather than beside the label.
        if head.startswith("floor plan"):
            plan = next((str(c).strip() for c in row[1:] if c not in (None, "")), None)
            continue
        signed, eff, prev_eff = (_date(get(row, "signed")), _num(get(row, "eff_rent")),
                                 _num(get(row, "prev_eff_rent")))
        if signed is None or eff is None or prev_eff is None:
            continue
        leases.append({
            "floor_plan": plan,
            "unit": str(get(row, "unit") or "").strip() or None,
            "unit_type": str(get(row, "unit_type") or "").strip() or None,
            "sqft": _num(get(row, "sqft")),
            "signed": signed.isoformat(),
            "month": signed.strftime("%Y-%m"),
            "lease_start": iso(get(row, "start")),
            "term": _num(get(row, "term")),
            "gross_rent": _num(get(row, "gross_rent")),
            "concession": _num(get(row, "concession")),
            "eff_rent": eff,
            # The previous lease's start is what makes a turnover unique: a
            # unit can turn over twice inside one window (102 does), so the
            # store keys on it alongside the unit and the signed date.
            "prev_start": iso(get(row, "prev_start")),
            "prev_term": _num(get(row, "prev_term")),
            "prev_gross_rent": _num(get(row, "prev_gross_rent")),
            "prev_concession": _num(get(row, "prev_concession")),
            "prev_eff_rent": prev_eff,
            "vacant_days": _num(get(row, "vacant_days")),
            "tradeout_amount": _num(get(row, "tradeout_amount")),
            "tradeout_pct": _pct(get(row, "tradeout_pct")),
        })

    if not leases:
        raise LayoutError("no lease rows read — the report's layout has moved")

    sums = {f: round(sum(l[f] or 0 for l in leases), 2) for f in TIE_OUT}
    checks, tol = [], 1.0
    if totals_row is None:
        raise LayoutError("no 'Grand Total:' row — nothing to tie the leases out against")
    for f in TIE_OUT:
        want = _num(totals_row[idx[f]] if idx[f] < len(totals_row) else None)
        if want is None:
            raise LayoutError(f"the Grand Total row carries no {f}")
        diff = round(sums[f] - want, 2)
        checks.append({"field": f, "leases": sums[f], "report_total": want, "diff": diff})
        if abs(diff) > tol:
            raise LayoutError(
                f"leases sum to {sums[f]:,.2f} for {f} but the report's own Grand "
                f"Total says {want:,.2f} (off by {diff:,.2f}) — refusing to publish")

    return {
        "report_type": REPORT_TYPE,
        "property": name,
        "property_from": name_from,
        "owner_row": owner,
        "source_file": os.path.basename(path),
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "as_of": end.isoformat(),
        "rate_type": _setting(rows, "Desired Rate Type"),
        "lease_date_basis": _setting(rows, "Lease Date"),
        "tradeout_basis": _setting(rows, "Calculate Tradeout on"),
        "leases": leases,
        "totals": summarise(leases),
        "checks": checks,
        "problems": problems,
    }


def summarise(leases):
    """Weighted and mean trade-out over a list of leases, plus the monthly series.

    `pct` is the report's own definition — total current effective rent over
    total previous effective rent — and is what any published figure should
    use. `mean_pct` is the arithmetic mean of the per-lease percentages, kept
    beside it because it is what the Trade-outs card's other feed reports and
    the two are not interchangeable: concessions drive an effective rent toward
    zero and one such lease prints in the hundreds of percent.
    """
    if not leases:
        return None
    cur = round(sum(l["eff_rent"] or 0 for l in leases), 2)
    prev = round(sum(l["prev_eff_rent"] or 0 for l in leases), 2)
    pcts = [l["tradeout_pct"] for l in leases if l["tradeout_pct"] is not None]
    months = {}
    for l in leases:
        m = months.setdefault(l["month"], {"month": l["month"], "leases": 0,
                                           "eff_rent": 0.0, "prev_eff_rent": 0.0,
                                           "tradeout_amount": 0.0, "_pcts": []})
        m["leases"] += 1
        m["eff_rent"] += l["eff_rent"] or 0
        m["prev_eff_rent"] += l["prev_eff_rent"] or 0
        m["tradeout_amount"] += l["tradeout_amount"] or 0
        if l["tradeout_pct"] is not None:
            m["_pcts"].append(l["tradeout_pct"])
    series = []
    for m in sorted(months.values(), key=lambda x: x["month"]):
        for k in ("eff_rent", "prev_eff_rent", "tradeout_amount"):
            m[k] = round(m[k], 2)
        m["pct"] = round(m["eff_rent"] / m["prev_eff_rent"] - 1, 6) if m["prev_eff_rent"] else None
        # The month's mean beside its weighted figure, for the same reason the
        # totals carry both: the Trade-outs card draws one and names the other,
        # and a month like Nov 2024 reads 550.9% as a mean against 55.7%
        # weighted, which is the concession effect at monthly resolution.
        ps = m.pop("_pcts")
        m["mean_pct"] = round(sum(ps) / len(ps), 6) if ps else None
        series.append(m)
    return {
        "leases": len(leases),
        "eff_rent": cur,
        "prev_eff_rent": prev,
        "tradeout_amount": round(cur - prev, 2),
        "pct": round(cur / prev - 1, 6) if prev else None,
        "mean_pct": round(sum(pcts) / len(pcts), 6) if pcts else None,
        "months": series,
    }


def window(leases, months, end_month=None):
    """The trailing `months` calendar months of `leases`, summarised.

    Counted in months present in the file rather than in leases: a window is
    "the last three months", and a month in which nothing was signed is still
    one of them. Returns None when the file does not hold that many.
    """
    if not leases:
        return None
    keys = sorted({l["month"] for l in leases})
    end = end_month or keys[-1]
    y, m = int(end[:4]), int(end[5:7])
    wanted = set()
    for _ in range(months):
        wanted.add(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    span = [l for l in leases if l["month"] in wanted]
    if not span:
        return None
    out = summarise(span)
    out["window_months"] = months
    out["window_start"] = min(wanted)
    out["window_end"] = end
    out["complete"] = min(wanted) >= keys[0]
    return out


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    result = parse(argv[1])
    t = result["totals"]
    print(f"{result['property']} · {result['period_start']} to {result['period_end']}")
    print(f"  {t['leases']} leases · {t['pct'] * 100:.1f}% weighted trade-out "
          f"(${t['tradeout_amount']:,.0f}) · mean of the per-lease rates "
          f"{t['mean_pct'] * 100:.1f}%")
    for n in (3, 6, 12):
        w = window(result["leases"], n)
        if w:
            print(f"  T{n:<3} {w['window_start']}..{w['window_end']}  "
                  f"n={w['leases']:<4} {w['pct'] * 100:>6.1f}%"
                  + ("" if w["complete"] else "  (window starts before the file does)"))
    for c in result["checks"]:
        print(f"  tie-out {c['field']}: {c['leases']:,.2f} vs {c['report_total']:,.2f} "
              f"(diff {c['diff']:,.2f})")
    for p in result["problems"]:
        print(f"  [warn] {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

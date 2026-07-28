"""
parse_delinquency.py
--------------------
Parses a Yardi rs_rp_DelinquencySummaryReport export into per-resident balances
plus the aging summary the dashboard shows.

Anchors on header labels, not positions, and ties the parsed rows out against
the report's own Grand Total.

The one judgement this encodes, taken from how the workbook already treats it:
the ground-floor retail tenant (unit code NONRES*) is reported alongside the
residents but is a single commercial receivable. Mixing it into resident aging
overstates resident credit risk, so it is split out. Residential gross is the
sum of positive balances and credits are the negatives, kept separate rather
than netted, because a prepayment is not a collection.

Usage:
    from parse_delinquency import parse
    result = parse("path/to/delinquency.xlsx")
"""
import json
import os
import re
import sys

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xlsx_anchors import (LayoutError, header_map, norm,  # noqa: E402
                          rows_until)

COLUMNS = {
    "unit": r"(property\s*)?unit",
    "resident_code": r"resident code",
    "resident_name": r"resident (last )?name",
    "status": r"resident status",
    "total_charges": r"total charges",
    "future_charges": r"future charges",
    "d0_30": r"0\s*-\s*30",
    "d31_60": r"31\s*-\s*60",
    "d61_90": r"61\s*-\s*90",
    "over90": r"over\s*90",
    "prepayments": r"prepayment",
    "total_owed": r"total owed",
}

STOP = [r"^total\b", r"^grand total", r"^report total"]
NONRES = re.compile(r"^nonres", re.I)
AGING = ("d0_30", "d31_60", "d61_90", "over90")


def _num(v):
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.replace(",", "").replace("$", "").strip()
        if s.startswith("(") and s.endswith(")"):
            s = "-" + s[1:-1]
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _property(ws, unit_col):
    """'p0005611 - The Landing' appears as a group header above the rows."""
    for r in range(1, min(ws.max_row, 40) + 1):
        v = ws.cell(row=r, column=unit_col).value
        if not isinstance(v, str):
            continue
        m = re.match(r"^([A-Za-z0-9._-]{4,20})\s*[-–]\s*(.+)$", v.strip())
        if m and not m.group(2).lower().startswith("the landing unit"):
            return m.group(2).strip(), m.group(1).strip()
    return None, None


def _as_of(ws):
    months = ["january", "february", "march", "april", "may", "june", "july",
              "august", "september", "october", "november", "december"]
    for r in range(1, min(ws.max_row, 40) + 1):
        for c in range(1, ws.max_column + 1):
            v = ws.cell(row=r, column=c).value
            if not isinstance(v, str):
                continue
            m = re.search(r"as of\s*:?\s*(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})", v, re.I)
            if m:
                mon = next((i for i, n in enumerate(months, 1)
                            if n.startswith(m.group(2).lower()[:3])), None)
                if mon:
                    return f"{m.group(3)}-{mon:02d}-{int(m.group(1)):02d}"
            m = re.search(r"as of\s*:?\s*(\d{1,2})/(\d{1,2})/(\d{4})", v, re.I)
            if m:
                return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return None


def _grand_total(ws, fields):
    for r in range(ws.max_row, 1, -1):
        label = norm(ws.cell(row=r, column=fields["unit"]).value)
        if re.search(r"grand total|^total\b", label):
            owed = _num(ws.cell(row=r, column=fields["total_owed"]).value)
            if owed is not None:
                return {"row": r, "total_owed": owed,
                        **{k: _num(ws.cell(row=r, column=fields[k]).value) or 0.0
                           for k in AGING}}
    return None


def _pick_sheet(wb):
    for name in wb.sheetnames:
        if "delinq" in name.lower():
            return wb[name]
    return wb[wb.sheetnames[0]]


def parse(path, strict=True):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = _pick_sheet(wb)
    fields, header_row = header_map(ws, COLUMNS)

    rows, stopped = rows_until(
        ws, header_row + 1, fields, STOP, "unit",
        keep=lambda rec: rec["unit"] not in (None, "")
                         and (rec.get("resident_code") not in (None, "")
                              or _num(rec.get("total_owed")) is not None))

    residents = []
    for rec in rows:
        r = {"unit": str(rec["unit"]).strip(),
             "resident_code": rec.get("resident_code"),
             "resident_name": rec.get("resident_name"),
             "status": rec.get("status")}
        for k in ("total_charges", "future_charges", "prepayments", "total_owed") + AGING:
            r[k] = _num(rec.get(k)) or 0.0
        r["residential"] = not bool(NONRES.match(r["unit"]))
        residents.append(r)

    res = [r for r in residents if r["residential"]]
    ret = [r for r in residents if not r["residential"]]
    owing = [r for r in res if r["total_owed"] > 0]

    gross = round(sum(r["total_owed"] for r in owing), 2)
    credits = round(sum(r["total_owed"] for r in res if r["total_owed"] < 0), 2)
    # Aging is reported for accounts that owe; a credit balance has no bucket.
    aging = {k: round(sum(r[k] for r in owing), 2) for k in AGING}

    summary = {
        "units_with_balance": len(owing),
        "gross_owed": gross,
        "credits": credits,
        "net": round(gross + credits, 2),
        "aging": aging,
        "retail_balance": round(sum(r["total_owed"] for r in ret), 2),
        "retail_over90": round(sum(r["over90"] for r in ret), 2),
        "total_all": round(sum(r["total_owed"] for r in residents), 2),
        "resident_rows": len(res),
        "retail_rows": len(ret),
    }

    checks, problems = [], []

    ag_sum = round(sum(aging.values()), 2)
    ok = abs(ag_sum - gross) < 0.02
    checks.append({"check": "aging buckets sum to gross owed", "ok": ok,
                   "aging_sum": ag_sum, "gross": gross})
    if not ok:
        problems.append(f"aging buckets sum to {ag_sum:,.2f} but gross owed is {gross:,.2f}")

    gt = _grand_total(ws, fields)
    if gt:
        delta = abs(summary["total_all"] - gt["total_owed"])
        ok = delta < 0.02
        checks.append({"check": "total owed ties to the report Grand Total", "ok": ok,
                       "parsed": summary["total_all"], "report": gt["total_owed"],
                       "delta": round(delta, 2)})
        if not ok:
            problems.append(
                f"parsed total owed {summary['total_all']:,.2f} vs the report's Grand "
                f"Total (row {gt['row']}) {gt['total_owed']:,.2f}")
    else:
        checks.append({"check": "report Grand Total found", "ok": False,
                       "note": "no Grand Total row located — cannot tie out"})
        problems.append("no Grand Total row found in the export to tie out against")

    as_of = _as_of(ws)
    checks.append({"check": "as-of date found", "ok": as_of is not None,
                   "note": as_of or "no as-of date in the export — the caller should "
                                   "fall back to the file's date"})
    checks.append({"check": "stopped at a total row", "ok": stopped is not None,
                   "note": f"stopped at row {stopped[0]} ({stopped[1]!r})" if stopped
                           else "ran to the end of the sheet without a total row"})
    if stopped is None:
        problems.append("no total row after the resident rows — a summary row may "
                        "have been read as a resident")

    if not residents:
        problems.append("no resident rows found")

    if problems and strict:
        raise ValueError("delinquency report did not tie out:\n  - "
                         + "\n  - ".join(problems))

    name, code = _property(ws, fields["unit"])
    return {
        "report_type": "delinquency",
        "property": name,
        "property_code": code,
        "as_of": as_of,
        "source_file": os.path.basename(path),
        "sheet": ws.title,
        "header_row": header_row,
        "columns": {k: v for k, v in sorted(fields.items(), key=lambda kv: kv[1])},
        "residents": residents,
        "summary": summary,
        "checks": checks,
        "problems": problems,
    }


if __name__ == "__main__":
    out = parse(sys.argv[1])
    slim = dict(out)
    slim["residents"] = out["residents"][:3] + [f"... {len(out['residents']) - 3} more"]
    print(json.dumps(slim, indent=2, default=str))

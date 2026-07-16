"""
parse_t12_statement.py
----------------------
Parses a Yardi 12-Month (T12) Statement export and extracts the expense-ratio
inputs. Anchors on Yardi ACCOUNT CODES (column A), not row positions, so it is
robust to suppress-zero exports and minor layout shifts.

Expense ratio (per Align definition) =
    TOTAL OPERATING EXPENSE RECOVERABLE (code 5999-9998)
    -------------------------------------------------------
    TOTAL OPERATING REVENUE            (code 4999-9999)

Usage:
    from parse_t12_statement import parse_t12
    result = parse_t12("path/to/statement.xlsx")
"""

import sys
import json
import openpyxl

# Yardi rollup account codes we anchor on. If the chart definition changes,
# change these codes -- the rest of the logic is generic.
CODE_REVENUE = "4999-9999"   # TOTAL OPERATING REVENUE
CODE_OPEX    = "5999-9998"   # TOTAL OPERATING EXPENSE RECOVERABLE

MONTHS_COLS = range(2, 14)   # columns C..N hold the 12 monthly values
TOTAL_COL   = 14             # column O holds the row total


def _load_rows(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Report1"]
    return list(ws.iter_rows(values_only=True))


def _property_name(rows):
    # Row 0, col A: e.g. "Palma North (rspalman)"
    cell = rows[0][0] if rows and rows[0] else None
    return str(cell).split("(")[0].strip() if cell else "Unknown Property"


def _property_code(rows):
    # Row 0, col A: e.g. "Palma North (rspalman)" -> "rspalman"
    cell = str(rows[0][0]) if rows and rows[0] and rows[0][0] else ""
    if "(" in cell and ")" in cell:
        return cell[cell.rfind("(") + 1:cell.rfind(")")].strip()
    return None


def _book(rows):
    """Return the accounting book, e.g. 'Accrual' or 'Cash', from the header
    rows (a line like 'Book = Accrual ; Tree = align_resbv')."""
    for r in rows[:6]:
        cell = str(r[0]) if r and r[0] else ""
        if "Book" in cell and "=" in cell:
            part = cell.split("Book")[1].split("=")[1]
            return part.split(";")[0].strip()
    return None


def _month_labels(rows):
    for r in rows:
        if r[2] and "Jul" in str(r[2]) or (r[2] and any(m in str(r[2]) for m in
                ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])):
            # header row: strip the year for compact labels
            labels = []
            for c in MONTHS_COLS:
                v = str(r[c]) if r[c] else ""
                labels.append(v.split()[0] if v else "")
            if all(labels):
                return labels
    return None


def _line_by_code(rows, code):
    """Return the 12 monthly values for a given account code, or None."""
    for r in rows:
        if r[0] and str(r[0]).strip() == code:
            return [float(r[c]) if r[c] is not None else 0.0 for c in MONTHS_COLS]
    return None


def _period_end(rows):
    """Return the last month label in the header, e.g. 'Jun 2026'."""
    for r in rows:
        vals = [str(r[c]) for c in MONTHS_COLS if r[c]]
        if len(vals) == 12 and any(m in vals[0] for m in
                ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]):
            return vals[-1]
    return None


def parse_t12(path):
    rows = _load_rows(path)
    prop = _property_name(rows)
    code = _property_code(rows)
    labels = _month_labels(rows)
    rev = _line_by_code(rows, CODE_REVENUE)
    opex = _line_by_code(rows, CODE_OPEX)

    if rev is None:
        raise ValueError(f"Revenue line {CODE_REVENUE} not found in {path}")
    if opex is None:
        raise ValueError(f"Opex line {CODE_OPEX} not found in {path}")

    rev_t12 = sum(rev)
    opex_t12 = sum(opex)
    ratio_t12 = round(100 * opex_t12 / rev_t12, 1) if rev_t12 else None

    monthly = [
        round(100 * opex[k] / rev[k], 1) if rev[k] else None
        for k in range(12)
    ]

    # Statement end period = last month column; used as the rolling-T12 key.
    period_end = _period_end(rows)

    return {
        "property": prop,
        "property_code": code,
        "book": _book(rows),
        "period_end": period_end,
        "labels": labels,
        "revenue_monthly": [round(x, 2) for x in rev],
        "opex_recoverable_monthly": [round(x, 2) for x in opex],
        "revenue_t12": round(rev_t12, 2),
        "opex_recoverable_t12": round(opex_t12, 2),
        "expense_ratio_t12": ratio_t12,
        "expense_ratio_monthly": monthly,
    }


if __name__ == "__main__":
    out = parse_t12(sys.argv[1])
    print(json.dumps(out, indent=2))

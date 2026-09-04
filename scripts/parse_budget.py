#!/usr/bin/env python3
"""Parse the Yardi 12-month budget export (``12_Month_Budget_Accrual.xlsx``).

The budget arrives in exactly the T12 statement's shape — account codes in
column A, twelve month columns and a Total, on the JPM tree — so this parser
is a thin wrapper over ``parse_t12_statement``: the same code anchors, the
same COA translation, the same Align-tree grouping, and the same to-the-cent
tie-out against the file's own TOTAL EXPENSES row. What it adds is identity:

- It **refuses a file that is not a budget.** The export carries a bare
  ``Budget`` marker row in its header block where an actuals statement says
  something else; an actuals statement misfiled into the Budgets folder must
  not be published as the plan it would then be compared against.
- It reads the **budget year** from the Period row (``Jan 2026-Dec 2026``)
  and requires the budget to start in January, since the scorecard's Budget
  Variance KPI is a calendar-YTD measure and a mid-year window would make
  "January through the current month" silently mean something else.

Emits aggregates only — monthly revenue and operating-expense lines plus the
Align-grouped expense buckets. A budget carries no resident and no lease, but
it still goes through ``store_report`` downstream so the central scrub covers
it by default.

  python scripts/parse_budget.py <12_Month_Budget_Accrual.xlsx>
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse_t12_statement as t12  # noqa: E402

REPORT_TYPE = "budget"

PERIOD = re.compile(r"period\s*=\s*(\w{3})\s+(\d{4})\s*-\s*(\w{3})\s+(\d{4})", re.I)


def _is_budget(rows):
    """The header block carries a row that just says 'Budget'."""
    for r in rows[:6]:
        cell = str(r[0]).strip().lower() if r and r[0] else ""
        if cell == "budget":
            return True
    return False


def _period(rows):
    """(first month, first year, last month, last year) from the Period row."""
    for r in rows[:6]:
        cell = str(r[0]) if r and r[0] else ""
        m = PERIOD.search(cell)
        if m:
            return m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
    return None


def parse(path):
    rows = t12._load_rows(path)
    if not _is_budget(rows):
        raise ValueError(
            "not a budget: no 'Budget' marker row in the header block -- an "
            "actuals statement in the Budgets folder is refused rather than "
            "published as the plan")
    period = _period(rows)
    if not period:
        raise ValueError("no 'Period = <mon> <year>-<mon> <year>' row found")
    m0, y0, m1, y1 = period
    if m0.lower() != "jan" or y0 != y1:
        raise ValueError(
            f"budget covers {m0} {y0}-{m1} {y1}; the Budget Variance KPI is "
            f"calendar-YTD, so only a Jan-Dec single-year budget is accepted")

    base = t12.parse_t12(path)
    buckets = base.get("expense_buckets") or {}
    return {
        "report_type": REPORT_TYPE,
        "source_file": os.path.basename(path),
        "property": base.get("property"),
        "property_code": base.get("property_code"),
        "property_codes": base.get("property_codes"),
        "tree": base.get("tree"),
        "year": y0,
        # coverage, not arrival: the period the plan describes
        "as_of": f"Jan {y0}-Dec {y1}",
        "labels": base.get("labels"),
        "revenue_monthly": base.get("revenue_monthly"),
        "opex_operating_monthly": base.get("opex_recoverable_monthly"),
        # the Align-grouped buckets sum to the file's TOTAL EXPENSES (operating
        # + non-operating), the same basket the actuals' expense_buckets carry,
        # so a controllable cut computed on both sides compares like with like
        "buckets": buckets.get("buckets"),
        "buckets_unmapped": buckets.get("unmapped_accounts"),
        "buckets_tieout_gap": buckets.get("recoverable_tieout_max_gap"),
        "buckets_error": base.get("expense_buckets_error"),
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    import json
    p = parse(sys.argv[1])
    print(f"{p['property']} ({'+'.join(p['property_codes'] or [])}) "
          f"budget {p['year']}, tree {p['tree']}")
    print(f"revenue Jan-Dec: {sum(p['revenue_monthly']):,.0f}   "
          f"operating expense: {sum(p['opex_operating_monthly']):,.0f}")
    if p["buckets"]:
        for g, vs in sorted(p["buckets"].items()):
            print(f"  {g:36} {sum(vs):>12,.0f}")
        print(f"  tie-out gap vs TOTAL EXPENSES: {p['buckets_tieout_gap']}")
    if p["buckets_error"]:
        print(f"BUCKETS REFUSED: {p['buckets_error']}")
    json.dump(p, sys.stdout, indent=1, default=str) if "--json" in sys.argv else None

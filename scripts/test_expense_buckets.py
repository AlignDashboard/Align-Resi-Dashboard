#!/usr/bin/env python3
"""Guard tests for the T12 expense-bucket classification.

Fixture-free: builds synthetic statements shaped like the real Yardi exports
(section headers ending -0000, leaf accounts, TOTAL rollups ending 98/99, the
5999-9998 recoverable total, and a below-the-NOI-line 6xxx region) and checks
classification, the per-month tie-out, the refusal path, and that financing /
non-cash lines never reach a bucket.

Run: python scripts/test_expense_buckets.py
"""
import os
import sys
import tempfile

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse_t12_statement as t12  # noqa: E402

PASS = FAIL = 0


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


MONTHS = ["Jul 2025", "Aug 2025", "Sep 2025", "Oct 2025", "Nov 2025", "Dec 2025",
          "Jan 2026", "Feb 2026", "Mar 2026", "Apr 2026", "May 2026", "Jun 2026"]


def build(path, break_tieout=False):
    """A statement whose recoverable leaves are known by bucket."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Report1"
    rows = [
        ["The Landing (p0005611)"], ["Statement (12 months)"],
        ["Period = Jul 2025-Jun 2026"], ["Book = Accrual ; Tree = align_resbv"],
        ["", ""] + MONTHS + ["Total"],
        ["4000-0000", "OPERATING REVENUE"],
        ["4050-5100", "Residential Market rent potential"] + [700000] * 12,
        ["4999-9999", "TOTAL OPERATING REVENUE"] + [700000] * 12,
        ["5000-0000", "OPERATING EXPENSE RECOVERABLE"],
        ["5110-0000", "CLEANING"],
        ["5110-1000", "Cleaning-Contract Srvcs"] + [1000] * 12,
        ["5110-9999", "TOTAL CLEANING"] + [1000] * 12,
        ["5170-0000", "ADMIN"],
        ["5170-1250", "Admin-Software"] + [200] * 12,
        ["5170-3000", "ADMIN-PAYROLL"],
        ["5170-3120", "Admin Payroll- - taxes and benefits"] + [300] * 12,
        ["5170-3199", "TOTAL ADMIN - Payroll"] + [300] * 12,
        ["5170-9999", "TOTAL ADMIN"] + [500] * 12,
        ["5499-9999", "TOTAL CAM/OPERATING EXPENSES"] + [1500] * 12,
        ["5999-9998", "TOTAL OPERATING EXPENSE RECOVERABLE"]
        + [1500 + (999 if break_tieout else 0)] * 12,
        ["5999-9999", "NET OPERATING INCOME"] + [698500] * 12,
        ["6000-0000", "OTHER EXPENSES"],
        ["6110-0000", "MARKETING ADMIN"],
        ["6130-0200", "Marketing-Digital Advertising"] + [400] * 12,
        ["6139-9999", "TOTAL MARKETING ADMIN"] + [400] * 12,
        ["6200-0000", "FIXED EXPENSES"],
        ["6210-1000", "Real Estate Taxes"] + [172500] * 12,
        ["6220-1000", "Property Insurance"] + [22000] * 12,
        ["6230-1000", "Management Fees"] + [25000] * 12,
        ["6300-0000", "FINANCING"],
        ["6310-1000", "Interest Expense - Mortgage"] + [90000] * 12,
        ["6320-1000", "Depreciation Expense"] + [50000] * 12,
    ]
    for r in rows:
        ws.append(r)
    wb.save(path)


def build_jpm(path, break_tieout=False):
    """A statement shaped like The Landing's: JPM tree, four property codes in
    the title row, six-digit accounts that config/coa_map.json translates."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Report1"
    rows = [
        ["Property =  p0005611 p0005612 p0005671 p0005640"],
        ["Statement (12 months)"],
        ["Period = Aug 2025-Jul 2026"],
        ["Book = Accrual ; Tree = jpm_bf1"],
        ["", ""] + ["Aug 2025", "Sep 2025", "Oct 2025", "Nov 2025", "Dec 2025",
                    "Jan 2026", "Feb 2026", "Mar 2026", "Apr 2026", "May 2026",
                    "Jun 2026", "Jul 2026"] + ["Total"],
        ["400000-3000", "REVENUE"],
        ["410400-0001", "Market rent potential"] + [700000] * 12,
        ["499999-9999", "TOTAL REVENUE"] + [700000] * 12,
        ["500000-0000", "EXPENSES"],
        ["510200-0000", "REAL ESTATE TAX EXP."],
        ["510200-0001", "Real estate tax expense"] + [170000] * 12,
        ["510299-9999", "TOTAL REAL ESTATE TAX EXP."] + [170000] * 12,
        ["510440-0005", "Payroll - other"] + [50000] * 12,
        ["510505-0001", "Cleaning contract"] + [8000] * 12,
        ["510510-0041", "Courtesy patrol"] + [3000] * 12,   # NOT in the COA map
        ["510605-0001", "Electricity - int"] + [14000] * 12,
        ["510800-0001", "Insurance exp  - property"] + [21000] * 12,
        ["511105-0001", "Legal"] + [2000] * 12,
        ["519999-9999", "TOTAL OPERATING EXPENSES"] + [268000] * 12,
        ["520510-0001", "Franchise tax expense"] + [300] * 12,
        ["549999-9999", "TOTAL EXPENSES"]
        + [268300 + (999 if break_tieout else 0)] * 12,
        ["599999-9999", "TOTAL NET OPERATING INCOME"] + [431700] * 12,
        ["600000-0000", "FINANCING EXPENSES"],
        ["610100-0001", "Mortgage interest"] + [90000] * 12,
    ]
    for r in rows:
        ws.append(r)
    wb.save(path)


def main():
    tmp = tempfile.mkdtemp()
    good = os.path.join(tmp, "good.xlsx")
    bad = os.path.join(tmp, "bad.xlsx")
    build(good)
    build(bad, break_tieout=True)

    print("classification and tie-out")
    p = t12.parse_t12(good)
    eb = p["expense_buckets"]
    ok("buckets present, no error", eb is not None and p["expense_buckets_error"] is None,
       p["expense_buckets_error"])
    b = eb["buckets"]
    ok("contract line classified", b.get("Contract services", [0])[0] == 1000, b)
    ok("payroll taxes land in payroll, not taxes",
       b.get("Payroll & benefits", [0])[0] == 300
       and b.get("Real estate & other taxes", [0])[0] == 172500, b)
    ok("software lands in administrative", b.get("Administrative", [0])[0] == 200, b)
    ok("marketing from the 6xxx region", b.get("Marketing & advertising", [0])[0] == 400, b)
    ok("insurance and mgmt fee bucketed",
       b.get("Insurance", [0])[0] == 22000 and b.get("Management fee", [0])[0] == 25000, b)
    ok("no rollup was double counted",
       sum(v[0] for v in b.values()) == 1000 + 200 + 300 + 400 + 172500 + 22000 + 25000,
       {k: v[0] for k, v in b.items()})
    ok("recoverable tie-out gap ~0", eb["recoverable_tieout_max_gap"] < 0.01,
       eb["recoverable_tieout_max_gap"])
    ok("interest and depreciation excluded",
       "Interest Expense - Mortgage" in eb["below_line_excluded"]
       and "Depreciation Expense" in eb["below_line_excluded"],
       eb["below_line_excluded"])
    ok("nothing fell to Other on this fixture", not eb["other_labels"], eb["other_labels"])
    ok("ratio output unaffected", p["expense_ratio_t12"] is not None)
    ok("align tree publishes no total-expense anchor",
       p["expenses_total_anchor"] is None and p["expenses_total_monthly"] is None
       and p["expenses_total_t12"] is None,
       (p["expenses_total_anchor"], p["expenses_total_t12"]))

    print("refusal")
    pb = t12.parse_t12(bad)
    ok("broken tie-out refuses buckets", pb["expense_buckets"] is None)
    ok("...with the reason stated",
       "tie out" in (pb["expense_buckets_error"] or ""), pb["expense_buckets_error"])
    ok("...but the ratio still parses", pb["expense_ratio_t12"] is not None)

    print("jpm tree via the COA mapping")
    jgood = os.path.join(tmp, "jpm.xlsx")
    jbad = os.path.join(tmp, "jpm_bad.xlsx")
    build_jpm(jgood)
    build_jpm(jbad, break_tieout=True)
    jp = t12.parse_t12(jgood)
    ok("four property codes from the title row",
       jp["property_codes"] == ["p0005611", "p0005612", "p0005671", "p0005640"],
       jp["property_codes"])
    ok("tree detected", jp["tree"] == "jpm_bf1", jp["tree"])
    ok("revenue anchored on 499999-9999", jp["revenue_t12"] == 700000 * 12,
       jp["revenue_t12"])
    ok("opex anchored on 519999-9999", jp["opex_recoverable_t12"] == 268000 * 12,
       jp["opex_recoverable_t12"])
    ok("opex basis recorded", "jpm" in jp["opex_basis"], jp["opex_basis"])
    ok("total expenses anchored on 549999-9999",
       jp["expenses_total_anchor"] == "549999-9999"
       and jp["expenses_total_t12"] == 268300 * 12,
       (jp["expenses_total_anchor"], jp["expenses_total_t12"]))
    ok("total expenses basis names the row",
       "549999-9999" in (jp["expenses_total_basis"] or ""),
       jp["expenses_total_basis"])
    # The whole point of the second anchor: it is not the operating total. The
    # franchise tax line between them is what the Operating Summary card was
    # missing while it read 519999-9999.
    ok("total expenses exceeds operating expenses by the 52xxxx region",
       jp["expenses_total_t12"] - jp["opex_recoverable_t12"] == 300 * 12,
       (jp["expenses_total_t12"], jp["opex_recoverable_t12"]))
    ok("revenue less total expenses reproduces the statement's NOI line",
       all(jp["revenue_monthly"][i] - jp["expenses_total_monthly"][i] == 431700
           for i in range(12)),
       (jp["revenue_monthly"][0], jp["expenses_total_monthly"][0]))
    jb = jp["expense_buckets"]
    ok("jpm buckets present", jb is not None and jp["expense_buckets_error"] is None,
       jp["expense_buckets_error"])
    g = jb["buckets"]
    ok("RE tax + franchise tax grouped as Taxes", g.get("Taxes", [0])[0] == 170300, g)
    ok("payroll via COA (510440-0005 -> 5170-3115)",
       g.get("Payroll & benefits", [0])[0] == 50000, g)
    ok("cleaning contract -> Cleaning (5110)", g.get("Cleaning", [0])[0] == 8000, g)
    ok("utilities via COA", g.get("Utilities (net of billbacks)", [0])[0] == 14000, g)
    ok("legal -> Professional fees", g.get("Professional fees", [0])[0] == 2000, g)
    ok("unmapped account grouped by its label and reported",
       g.get("Security & fire/life safety", [0])[0] == 3000
       and any("510510-0041" in a for a in jb["unmapped_accounts"]),
       (g.get("Security & fire/life safety"), jb["unmapped_accounts"]))
    ok("financing never enters the groups",
       sum(v[0] for v in g.values()) == 268300, {k: v[0] for k, v in g.items()})
    ok("jpm tie-out against TOTAL EXPENSES", jb["recoverable_tieout_max_gap"] < 0.01,
       jb["recoverable_tieout_max_gap"])
    ok("grouping recorded as COA-mapped", jb["grouping"] == "align_tree_via_coa_map",
       jb.get("grouping"))
    jpb = t12.parse_t12(jbad)
    ok("broken jpm tie-out refuses buckets, keeps the ratio",
       jpb["expense_buckets"] is None and jpb["expense_ratio_t12"] is not None,
       jpb["expense_buckets_error"])

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()

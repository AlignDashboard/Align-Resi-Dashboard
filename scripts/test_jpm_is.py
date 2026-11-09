#!/usr/bin/env python3
"""Guard tests for the jpm_is statement layout.

The Landing's 12-month statement of 2026-11-09 arrived on the jpm_is account
tree: the same six-digit JPM accounts as jpm_bf1, with every total printed as a
labelled row and NO account code. The parser anchored only on coded totals
(499999-9999 and the rest), so the file was refused whole and a green run
published the August statement for another day.

What these hold down, fixture-free, against statements built in a temp dir:

  1. the read -- revenue, total expenses and NOI from the uncoded rows, the
     tree named in the anchor, and no operating-only figure invented;
  2. the guard -- revenue less the expense row must reproduce the statement's
     own Net Operating Income row, so a row that stopped being the whole
     expense load above NOI is refused rather than read;
  3. the labels -- only an UNCODED row is a total, and a label on two uncoded
     rows is refused rather than resolved;
  4. the buckets and the rent section -- each ties out against its labelled
     total, and a refusal there costs that block, not the statement;
  5. the stitch -- a jpm_is point is not spliced onto jpm_bf1 months, though
     both read the whole expense load, and jpm_is points do join each other.

Run: python scripts/test_jpm_is.py
"""
import os
import pathlib
import shutil
import sys
import tempfile

import openpyxl

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_metrics as bm                       # noqa: E402
import parse_t12_statement as t12                # noqa: E402
from test_expense_buckets import build_jpm       # noqa: E402

PASS = FAIL = 0


def ok(label, cond, detail=None):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}" + (f"\n        {detail}" if detail is not None else ""))


MONTHS = ["Nov 2025", "Dec 2025", "Jan 2026", "Feb 2026", "Mar 2026", "Apr 2026",
          "May 2026", "Jun 2026", "Jul 2026", "Aug 2026", "Sep 2026", "Oct 2026"]


def build_is(path, *, noi_off=0.0, operating_slice=False, dup_label=False,
             coded_decoy=False, leaf_off=0.0, rent_off=0.0, drop=None):
    """A statement shaped like the 2026-11-09 one: uncoded section headings and
    totals, the 52xxxx accounts inside 'Total Operating Expenses', the month-
    to-month premium in revenue. Every figure is invented."""
    rent = [1000000, -150000, -40000, -7000, -500]      # 410400-0001..0006
    rental_income = sum(rent)                           # 802500
    other = 7500 + 30000                                # MTM premium, garage
    revenue = rental_income + other + 5000              # + interest income
    leaves = [("510200-0001", "Real estate tax expense", 145000),
              ("510485-0001", "Payroll - resid. manager", 12000),
              ("510505-0001", "Cleaning contract", 8000),
              ("510510-0041", "Courtesy patrol", 3000),          # not in the COA map
              ("510605-0005", "Water and sewer", 22000),
              ("510800-0002", "Insurance exp - liab.", 23000),
              ("511067-0008", "Property management fee", 27000),
              ("520510-0001", "Franchise tax expense", 300),     # 52xxxx, inside the total
              ("520600-0018", "Renters Insurance Expense", 600)]
    expenses = sum(v for _, _, v in leaves)
    noi = revenue - expenses
    total_row = expenses - (900 if operating_slice else 0)   # 52xxxx left out
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Report1"
    rows = [["The Landing (p0005611)"], ["Statement (12 months)"],
            ["Period = Nov 2025-Oct 2026"], ["Book = Accrual ; Tree = jpm_is"],
            ["", ""] + MONTHS + ["Total"],
            ["", "REVENUE"]]
    if coded_decoy:
        # An account that happens to carry a total's name is not that total.
        rows.append(["442600-0099", "Total Revenue"] + [1] * 12)
    for code, label, v in zip(("410400-0001", "410400-0002", "410400-0003",
                               "410400-0004", "410400-0006"),
                              ("Market rent potential", "Loss / Gain to Lease",
                               "Vacancy loss", "Employee rent allowance",
                               "Rental concessions"), rent):
        if code != drop:
            rows.append([code, label] + [v] * 12)
    rows += [["", "Total Rental Income"] + [rental_income + rent_off] * 12,
             ["440200-0014", "Resid. - month to month"] + [7500] * 12,
             ["440200-0027", "Resid. - Garage"] + [30000 - (1 if coded_decoy else 0)] * 12,
             ["", "Total Other Income"] + [other] * 12,
             ["450000-0008", "Interest inc- oper. acct."] + [5000] * 12,
             ["", "Total Interest Income"] + [5000] * 12,
             ["", "Total Revenue"] + [revenue] * 12]
    if dup_label:
        rows.append(["", "Total Revenue"] + [revenue] * 12)
    rows += [["", "EXPENSES"], ["", "Operating Expenses"]]
    for code, label, v in leaves:
        rows.append([code, label] + [v + (leaf_off if code == "510505-0001" else 0)] * 12)
    rows += [["", "Total Operating Expenses"] + [total_row] * 12,
             ["", "Net Operating Income"] + [noi + noi_off] * 12,
             ["", "Interest Expense"],
             ["610100-0001", "Mortgage int exp - first"] + [460000] * 12,
             ["", "Total Interest Expense"] + [460000] * 12,
             ["", "Capital Additions"],
             ["110105-1533", "Res. Building Improvement"] + [5000] * 12,
             ["", "Total Capital Additions"] + [5000] * 12]
    for r in rows:
        ws.append(r)
    wb.save(path)
    return {"revenue": revenue, "expenses": expenses, "noi": noi,
            "rental_income": rental_income}


def refused(fn, *a):
    try:
        fn(*a)
        return None
    except ValueError as e:
        return str(e)


def main():
    tmp = tempfile.mkdtemp(prefix="jpm_is_")
    try:
        path = os.path.join(tmp, "is.xlsx")
        want = build_is(path)
        p = t12.parse_t12(path)

        print("1. the read")
        ok("the tree is detected", p["tree"] == "jpm_is", p["tree"])
        ok("the property code comes from the title row",
           p["property_codes"] == ["p0005611"], p["property_codes"])
        ok("revenue is the uncoded 'Total Revenue' row",
           p["revenue_monthly"] == [want["revenue"]] * 12, p["revenue_monthly"][:1])
        ok("total expenses are the uncoded 'Total Operating Expenses' row, 52xxxx included",
           p["expenses_total_monthly"] == [want["expenses"]] * 12,
           p["expenses_total_monthly"][:1])
        ok("the anchor names the tree and the row, not a code it does not have",
           p["expenses_total_anchor"] == t12.JPM_IS_ANCHOR == "jpm_is Total Operating Expenses",
           p["expenses_total_anchor"])
        ok("no operating-only figure is invented -- the tree has no such subtotal",
           p["opex_recoverable_monthly"] is None and p["opex_recoverable_t12"] is None
           and p["opex_basis"] is None)
        ok("the ratio is taken on the total",
           p["expense_ratio_t12"] == round(100 * want["expenses"] / want["revenue"], 1),
           p["expense_ratio_t12"])
        ok("the period end is the last month column", p["period_end"] == "Oct 2026",
           p["period_end"])

        print("\n2. the NOI guard")
        bad = os.path.join(tmp, "noi_off.xlsx")
        build_is(bad, noi_off=250.0)
        err = refused(t12.parse_t12, bad)
        ok("a statement whose NOI row disagrees with revenue less expenses is refused",
           err is not None and "Net Operating Income" in err, err)
        bad = os.path.join(tmp, "slice.xlsx")
        build_is(bad, operating_slice=True)
        err = refused(t12.parse_t12, bad)
        ok("an expense row that leaves the 52xxxx accounts out is refused, "
           "not read as the whole expense load", err is not None, err)

        print("\n3. the labels")
        bad = os.path.join(tmp, "dup.xlsx")
        build_is(bad, dup_label=True)
        err = refused(t12.parse_t12, bad)
        ok("a total label on two uncoded rows is refused rather than resolved",
           err is not None and "2 uncoded rows" in err, err)
        decoy = os.path.join(tmp, "decoy.xlsx")
        want_d = build_is(decoy, coded_decoy=True)
        pd = t12.parse_t12(decoy)
        ok("a coded account carrying a total's name is not read as the total",
           pd["revenue_monthly"] == [want_d["revenue"]] * 12, pd["revenue_monthly"][:1])
        bad = os.path.join(tmp, "nolabel.xlsx")
        build_is(bad)
        wb = openpyxl.load_workbook(bad)
        for r in wb["Report1"].iter_rows():
            if r[1].value == "Net Operating Income":
                r[1].value = "NOI"
        wb.save(bad)
        err = refused(t12.parse_t12, bad)
        ok("a renamed total is refused with the row it looked for",
           err is not None and "'Net Operating Income'" in err, err)

        print("\n4. the buckets and the rent section")
        eb = p["expense_buckets"]
        ok("the buckets tie out against the labelled total, to the cent",
           eb is not None and eb["recoverable_tieout_max_gap"] == 0.0,
           p["expense_buckets_error"])
        ok("every expense leaf is in a bucket -- and nothing else is",
           round(sum(sum(v) for v in eb["buckets"].values()), 2)
           == round(12 * want["expenses"], 2),
           {k: sum(v) for k, v in eb["buckets"].items()})
        ok("an account the COA map does not know goes to the lump, as on jpm_bf1",
           any(a.startswith("510510-0041") for a in eb["unmapped_accounts"]),
           eb["unmapped_accounts"])
        bad = os.path.join(tmp, "leaf.xlsx")
        build_is(bad, leaf_off=10.0)
        pb = t12.parse_t12(bad)
        ok("a leaf that no longer sums to the total refuses the buckets and only them",
           pb["expense_buckets"] is None and "Total Operating Expenses" in
           (pb["expense_buckets_error"] or "") and pb["revenue_monthly"],
           pb["expense_buckets_error"])
        rc = p["rent_capture"]
        ok("the rent section ties out against the uncoded 'Total Rental Income'",
           rc is not None and rc["basis"] == "jpm_is Total Rental Income"
           and rc["tieout_max_gap"] == 0.0 and rc["rental_income"][0] == want["rental_income"],
           (p["rent_capture_error"], rc and rc["basis"]))
        ok("its deductions are flipped to the workbook's sign, as on jpm_bf1",
           rc["loss_to_lease"][0] == 150000 and rc["vacancy_loss"][0] == 40000,
           (rc["loss_to_lease"][0], rc["vacancy_loss"][0]))
        bad = os.path.join(tmp, "rent.xlsx")
        build_is(bad, drop="410400-0004")
        pr = t12.parse_t12(bad)
        ok("a rent section missing a leaf is refused, not read short",
           pr["rent_capture"] is None and "Total Rental Income" in (pr["rent_capture_error"] or ""),
           pr["rent_capture_error"])

        print("\n5. the stitch")
        bf1 = os.path.join(tmp, "bf1.xlsx")
        build_jpm(bf1)
        pb1 = t12.parse_t12(bf1)
        ok("a jpm_bf1 statement still reads its coded anchors",
           pb1["expenses_total_anchor"] == t12.JPM_EXP_ALL
           and pb1["opex_recoverable_monthly"] is not None)
        prev = bm.DATA
        bm.DATA = pathlib.Path(tmp) / "data"
        try:
            prop = {"name": "Fixture", "slug": "fixture"}
            pb1["landed_at"] = "2026-09-14T00:00:00Z"
            p["landed_at"] = "2026-11-09T18:43:27Z"
            bm.store_monthly_pl(prop, [pb1])               # Aug 2025-Jul 2026
            hist = bm.store_monthly_pl(prop, [p])          # Nov 2025-Oct 2026
            bm.store_expense_ratio(prop, [pb1])
            ratio = bm.store_expense_ratio(prop, [p])
        finally:
            bm.DATA = prev
        new = hist["points"][-1]
        ok("the stored point is the whole expense load, on the jpm_is anchor",
           new["expense_scope"] == "total" and new["expense_anchor"] == t12.JPM_IS_ANCHOR,
           (new["expense_scope"], new["expense_anchor"]))
        run = bm.stitch_monthly_pl(hist["points"], "fixture")
        ok("the P&L run starts at the first jpm_is month, not at the jpm_bf1 ones",
           run["months"][0] == "2025-11" and run["months"][-1] == "2026-10"
           and len(run["months"]) == 12, (run["months"][0], run["months"][-1]))
        ok("...and carries the new anchor", run["expense_anchor"] == t12.JPM_IS_ANCHOR)
        trend, _ = bm.ratio_trend(ratio["points"], "fixture")
        ok("the ratio trend keeps only the jpm_is point",
           [pt["period_end"] for pt in trend] == ["Oct 2026"],
           [pt["period_end"] for pt in trend])
        later = dict(new, period_end="Dec 2026",
                     revenue=new["revenue"], opex=new["opex"], noi=new["noi"])
        run2 = bm.stitch_monthly_pl(hist["points"] + [later], "fixture")
        ok("two jpm_is statements do join into one longer run",
           run2["months"][0] == "2025-11" and run2["months"][-1] == "2026-12"
           and len(run2["months"]) == 14, (run2["months"][0], run2["months"][-1]))
        same = [dict(pt, expense_anchor=t12.JPM_EXP_ALL) for pt in hist["points"]]
        run3 = bm.stitch_monthly_pl(same, "fixture")
        ok("points that agree on scope AND anchor still stitch across statements",
           run3["months"][0] == "2025-08" and len(run3["months"]) == 15,
           (run3["months"][0], len(run3["months"])))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()

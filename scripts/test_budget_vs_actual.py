"""
Guard tests for the budget feed behind the Portfolio tab's Budget vs Actual card.

The card compares a plan against actuals month by month. Everything that can go
wrong here is invisible in the numbers -- a plan lined up against the wrong
months still draws twelve pairs of bars, and a missing month that reads as zero
still totals. So these are the checks:

  - A budget is a CALENDAR year and the window the card draws is not. The
    statement runs Sep-Aug today, so a store that held only the newest year
    would leave four months with no plan. store_budget keeps a point per year;
    re-filing a year replaces that year rather than the file.
  - The published block carries explicit YYYY-MM keys. Bare "Jan".."Dec" labels
    cannot say which year a month belongs to, and this series spans two.
  - A month in a year with NO budget publishes null, not zero. Zero would read
    as a plan of nothing and turn an unplanned month into a 100% overspend.
  - A category a PLANNED year does not name is a real zero -- that year's
    buckets tie out against its own total expenses, so nothing is missing.
  - The scorecard's Budget Variance picks the STATEMENT's year, not the newest
    plan on file. Picking the newest would measure this year's actuals against
    next year's plan and publish the difference as a variance.

Statements come from test_expense_buckets' own builder; budgets are built here
in the same shape. No network, no fixtures.

Run: python scripts/test_budget_vs_actual.py
"""

import json
import os
import pathlib
import shutil
import sys
import tempfile

import openpyxl

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

CHECKS = []

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def ok(name, cond, detail=""):
    CHECKS.append((name, bool(cond)))
    print(f"   {'PASS' if cond else 'FAIL'} {name}" + (f"  [{detail}]" if detail and not cond else ""))


def build(path, year, marker="Budget", period=None, taxes=170000,
          cleaning=8000, extra=None, labels_from=None, break_tieout=False):
    """A Yardi 12-month export on the JPM tree.

    A budget and an actuals statement are the SAME layout -- parse_budget is a
    thin wrapper over the T12 parser -- so one builder makes both and the only
    difference is the marker row and the period, which is exactly the
    difference the parser identifies a budget by.

    Carries all four families the controllable basket excludes (taxes,
    insurance, utilities, the management fee), because budget_variance_ytd
    withholds the figure unless every one of them is found by name.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Report1"
    total = taxes + cleaning + 50000 + 21000 + 14000 + 20000 + 300 + (extra or 0)
    heads = labels_from or [f"{m} {year}" for m in MONTHS]
    rows = [
        ["Report1 The Landing (p0005611)"],
        [marker],
        [period or f"Period = Jan {year}-Dec {year}"],
        ["Book = Accrual ; Tree = jpm_bf1"],
        ["", ""] + heads + ["Total"],
        ["400000-3000", "REVENUE"],
        ["410400-0001", "Market rent potential"] + [700000] * 12,
        ["499999-9999", "TOTAL REVENUE"] + [700000] * 12,
        ["500000-0000", "EXPENSES"],
        ["510200-0001", "Real estate tax expense"] + [taxes] * 12,
        ["510440-0005", "Payroll - other"] + [50000] * 12,
        ["510505-0001", "Cleaning contract"] + [cleaning] * 12,
        ["510605-0001", "Electricity - int"] + [14000] * 12,
        ["510800-0002", "Insurance exp - liab."] + [21000] * 12,
        ["511067-0008", "Property management fee"] + [20000] * 12,
    ]
    if extra:
        # a marketing line only one year plans for
        rows.append(["510905-0015", "Internet"] + [extra] * 12)
    rows += [
        ["519999-9999", "TOTAL OPERATING EXPENSES"] + [total - 300] * 12,
        ["520510-0001", "Franchise tax expense"] + [300] * 12,
        ["549999-9999", "TOTAL EXPENSES"]
        + [total + (999 if break_tieout else 0)] * 12,
        ["599999-9999", "TOTAL NET OPERATING INCOME"] + [700000 - total] * 12,
    ]
    for r in rows:
        ws.append(r)
    wb.save(path)


def main():
    import build_metrics as bm
    import parse_budget

    tmp = tempfile.mkdtemp()
    os.chdir(tmp)
    (pathlib.Path(tmp) / "config").symlink_to(ROOT / "config")
    (pathlib.Path(tmp) / "docs").mkdir()
    bm.DATA = pathlib.Path(tmp) / "data"
    prop = {"slug": "the-landing", "name": "The Landing"}

    print("1. the parser identifies a budget and refuses what is not one")
    b25 = os.path.join(tmp, "b25.xlsx")
    b26 = os.path.join(tmp, "b26.xlsx")
    build(b25, 2025, taxes=150000)
    build(b26, 2026, taxes=170000, extra=5000)
    p25, p26 = parse_budget.parse(b25), parse_budget.parse(b26)
    ok("a budget parses and reports its year", (p25["year"], p26["year"]) == (2025, 2026))
    ok("buckets tie out to the file's own TOTAL EXPENSES",
       p25["buckets_tieout_gap"] == 0 and p26["buckets_tieout_gap"] == 0)

    notbudget = os.path.join(tmp, "nb.xlsx")
    build(notbudget, 2026, marker="Statement (12 months)")
    try:
        parse_budget.parse(notbudget)
        ok("an actuals statement in the Budgets folder is refused", False)
    except ValueError:
        ok("an actuals statement in the Budgets folder is refused", True)

    midyear = os.path.join(tmp, "mid.xlsx")
    build(midyear, 2026, period="Period = Jul 2026-Jun 2027")
    try:
        parse_budget.parse(midyear)
        ok("a budget that does not start in January is refused", False)
    except ValueError:
        ok("a budget that does not start in January is refused", True)

    print("\n2. store_budget keeps a point per YEAR, not a file per property")
    p25["source_file"], p25["landed_at"] = "b25.xlsx", "2026-09-16T10:00:00Z"
    p26["source_file"], p26["landed_at"] = "b26.xlsx", "2026-09-16T11:00:00Z"
    bm.store_budget(prop, p25)
    bm.store_budget(prop, p26)
    held = json.load(open(bm.DATA / "the-landing" / "budget.json"))
    ok("both years are on file", [y["year"] for y in held["years"]] == [2025, 2026])

    # the same year again, from a re-export: replaces that year, adds nothing
    p26b = parse_budget.parse(b26)
    p26b["source_file"], p26b["landed_at"] = "b26-v2.xlsx", "2026-09-17T09:00:00Z"
    bm.store_budget(prop, p26b)
    held = json.load(open(bm.DATA / "the-landing" / "budget.json"))
    ok("re-filing a year replaces that year rather than duplicating it",
       [y["year"] for y in held["years"]] == [2025, 2026])
    ok("the re-export's own provenance is what is kept",
       held["years"][-1]["source_file"] == "b26-v2.xlsx")
    ok("the year before is untouched by a re-export",
       held["years"][0]["source_file"] == "b25.xlsx")

    # the shape that existed before budgets were kept per year
    flat = dict({k: p25.get(k) for k in bm.BUDGET_KEYS}, source_file="old.xlsx",
                landed_at="2026-09-03T19:20:47Z")
    json.dump(flat, open(bm.DATA / "the-landing" / "budget.json", "w"))
    bm.store_budget(prop, p26)
    held = json.load(open(bm.DATA / "the-landing" / "budget.json"))
    ok("a pre-per-year file is carried in as its own year, not dropped",
       [y["year"] for y in held["years"]] == [2025, 2026]
       and held["years"][0]["source_file"] == "old.xlsx")

    print("\n3. the published block is keyed by YYYY-MM and spans the years held")
    # restore the two real years, then add the statement the card measures
    shutil.rmtree(bm.DATA / "the-landing")
    bm.store_budget(prop, p25)
    bm.store_budget(prop, p26)
    stmt = os.path.join(tmp, "t12.xlsx")
    # the actuals: the same layout, over a window that straddles the year end --
    # which is the whole reason the plan has to be kept per year
    build(stmt, 2026, marker="Statement (12 months)",
          period="Period = Aug 2025-Jul 2026",
          labels_from=[f"{m} 2025" for m in MONTHS[7:]]
                      + [f"{m} 2026" for m in MONTHS[:7]],
          taxes=175000, cleaning=9000)
    import parse_t12_statement as t12
    parsed = t12.parse_t12(stmt)
    parsed["landed_at"] = "2026-08-26T23:15:02Z"
    parsed["source_file"] = "12_Month_Statement_Accrual.xlsx"
    bm.store_expense_buckets(prop, [parsed])

    props = [dict(prop, active=True)]
    bm.load_properties = lambda: (props, {})
    os.chdir(tmp)
    bm.build_metrics_json()
    m = json.load(open("docs/metrics.json"))
    bud = m["budget"]["properties"][0]
    ok("the budget block is published", m["budget"]["available"])
    ok("months are explicit YYYY-MM keys spanning both years",
       bud["months"][0] == "2025-01" and bud["months"][-1] == "2026-12"
       and len(bud["months"]) == 24, str(bud["months"][:2]))
    ok("every year on file names its own source and arrival",
       {y["year"] for y in bud["years"]} == {2025, 2026}
       and all(y["source_file"] and y["landed_at"] for y in bud["years"]))

    print("\n4. the statement's T12 window has a plan for every month of it")
    eb = m["expense_buckets"]["properties"][0]
    em, ey = eb["period_end"].split()
    end = int(ey) * 12 + MONTHS.index(em)
    window = [f"{(end - i) // 12}-{(end - i) % 12 + 1:02d}"
              for i in range(len(eb["labels"]) - 1, -1, -1)]
    ok("the window really does cross the calendar boundary",
       window[0][:4] != window[-1][:4], " ".join([window[0], window[-1]]))
    ok("every month of the window is in the published budget",
       all(k in bud["months"] for k in window))
    at = {k: i for i, k in enumerate(bud["months"])}
    ok("no month of the window is unplanned",
       all(any(bud["buckets"][n][at[k]] is not None for n in bud["buckets"])
           for k in window))

    print("\n5. a covered year's silence is zero; an uncovered year's is null")
    # 2025 plans no Internet line, 2026 does -- but 2025 still ties out, so its
    # plan for that category is nil rather than unknown.
    ok("a category a covered year does not name is zero, not null",
       bud["buckets"]["Marketing & advertising"][at["2025-06"]] == 0
       and bud["buckets"]["Marketing & advertising"][at["2026-06"]] == 5000)

    # drop the middle year and check the gap publishes as unknown
    shutil.rmtree(bm.DATA / "the-landing")
    b27 = os.path.join(tmp, "b27.xlsx")
    build(b27, 2027)
    p27 = parse_budget.parse(b27)
    p27["source_file"], p27["landed_at"] = "b27.xlsx", "2026-09-16T12:00:00Z"
    bm.store_budget(prop, p25)
    bm.store_budget(prop, p27)
    bm.store_expense_buckets(prop, [parsed])
    bm.build_metrics_json()
    gap = json.load(open("docs/metrics.json"))["budget"]["properties"][0]
    gat = {k: i for i, k in enumerate(gap["months"])}
    ok("a year with no budget on file is reported as missing",
       gap["years_missing"] == [2026])
    ok("its months publish as null, never as a plan of zero",
       all(gap["buckets"][n][gat["2026-06"]] is None for n in gap["buckets"]))
    ok("the years either side are unaffected",
       gap["buckets"]["Taxes"][gat["2025-06"]] is not None
       and gap["buckets"]["Taxes"][gat["2027-06"]] is not None)

    print("\n6. Budget Variance grades the statement's year, not the newest plan")
    shutil.rmtree(bm.DATA / "the-landing")
    bm.store_budget(prop, p25)
    bm.store_budget(prop, p26)
    bm.store_budget(prop, p27)      # a 2027 plan is on file and must be ignored
    bm.store_expense_buckets(prop, [parsed])
    import populate_scorecard as ps
    bv = ps.budget_variance_ytd("the-landing")
    ok("the variance is computed at all", bv.get("pct") is not None, bv.get("why", ""))
    ok("it names the statement's own year's budget file",
       bv.get("source") == "b26.xlsx", str(bv.get("source")))
    ok("and the window is calendar-YTD to the statement's end",
       bv.get("window") == "Jan-Jul 2026", str(bv.get("window")))

    shutil.rmtree(bm.DATA / "the-landing")
    bm.store_budget(prop, p27)
    bm.store_expense_buckets(prop, [parsed])
    miss = ps.budget_variance_ytd("the-landing")
    ok("with no plan for the statement's year it refuses and says so",
       miss.get("pct") is None and "2026" in (miss.get("why") or ""),
       str(miss.get("why")))

    os.chdir(ROOT)
    shutil.rmtree(tmp, ignore_errors=True)

    failed = [n for n, good in CHECKS if not good]
    print()
    if failed:
        print(f"FAIL: {len(failed)} of {len(CHECKS)} check(s)")
        for n in failed:
            print(f"  - {n}")
        return 1
    print(f"PASS: {len(CHECKS)} checks — budgets are kept per year, published on "
          f"explicit month keys, and an unplanned month stays unplanned.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

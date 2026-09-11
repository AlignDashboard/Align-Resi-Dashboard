#!/usr/bin/env python3
"""Guard tests for the statement's rental-income section and its stitch.

Fixture-free: builds statement rows in memory, in the shape parse_t12_statement
reads (code in column A, label in B, twelve months in C..N). Covers the three
ways this could publish a wrong number silently -- a leaf the parser does not
name being dropped, the deduction signs not being flipped to the workbook's
convention, and two statements on different bases being stitched into one
chart -- plus the refusals.

Run: python scripts/test_rent_capture.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_metrics                       # noqa: E402
import parse_t12_statement as t12          # noqa: E402

PASS = FAIL = 0


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def row(code, label, vals):
    r = [code, label] + list(vals)
    r.append(sum(vals))
    return r


def twelve(v):
    return [float(v)] * 12


def jpm_rows(extra=None, break_total=False):
    """A clean JPM section: 1000 potential, less 100/50/10/5 of deductions."""
    gross, l2l, vac, allow, conc = 1000.0, -100.0, -50.0, -10.0, -5.0
    other = extra if extra is not None else 0.0
    total = gross + l2l + vac + allow + conc + other + (7 if break_total else 0)
    rows = [
        row("410400-0000", " RESIDENTIAL RENTAL INCOME", [0] * 12),
        row("410400-0001", " Market rent potential", twelve(gross)),
        row("410400-0002", " Loss / Gain to lease", twelve(l2l)),
        row("410400-0003", " Vacancy loss", twelve(vac)),
        row("410400-0004", " Employee rent allowance", twelve(allow)),
        row("410400-0006", " Rental concessions", twelve(conc)),
    ]
    if extra is not None:
        rows.append(row("410400-0005", " Administrative units", twelve(extra)))
    rows.append(row("410499-9999", " TOTAL RESIDENTIAL RENTAL INCOME", twelve(total)))
    return rows


def point(period_end, labels, gross, income, basis="jpm 410499-9999"):
    p = {"period_end": period_end, "labels": labels, "basis": basis}
    for k in build_metrics.RENT_CAPTURE_KEYS:
        p[k] = [0.0] * len(labels)
    p["market_potential"] = list(gross)
    p["rental_income"] = list(income)
    p["loss_to_lease"] = [g - i for g, i in zip(gross, income)]
    return p


def main():
    print("the jpm section")
    rc = t12.rent_capture(jpm_rows(), "jpm_bf1")
    ok("reads the gross line", rc["market_potential"][0] == 1000, rc["market_potential"][0])
    ok("accrued income is the statement's own total row",
       rc["rental_income"][0] == 835 and rc["basis"] == "jpm 410499-9999", rc["rental_income"][0])
    ok("deductions are flipped positive, the workbook's convention",
       [rc[k][0] for k in t12.DEDUCTIONS] == [100, 50, 10, 5],
       [rc[k][0] for k in t12.DEDUCTIONS])
    ok("ties out to the cent", rc["tieout_max_gap"] == 0, rc["tieout_max_gap"])
    ok("gross less the deductions reproduces income",
       rc["market_potential"][0] - sum(rc[k][0] for k in t12.DEDUCTIONS)
       == rc["rental_income"][0])
    ok("nothing to report on a clean section", not rc["problems"], rc["problems"])

    print("\na leaf the parser does not name")
    rc2 = t12.rent_capture(jpm_rows(extra=25.0), "jpm_bf1")
    ok("lands in 'other' rather than being dropped", rc2["other"][0] == 25, rc2["other"][0])
    ok("...and the section still ties out", rc2["tieout_max_gap"] == 0, rc2["tieout_max_gap"])
    ok("...and it is named in the problems", any("410400-0005" in x for x in rc2["problems"]),
       rc2["problems"])

    print("\nrefusals")
    try:
        t12.rent_capture(jpm_rows(break_total=True), "jpm_bf1")
        ok("a section that does not reproduce its total is refused", False, "no exception")
    except ValueError as e:
        ok("a section that does not reproduce its total is refused",
           "does not tie out" in str(e), str(e))
    ok("a statement with no rental-income section returns None",
       t12.rent_capture([row("519999-9999", "TOTAL OPERATING EXPENSES", twelve(5))],
                        "jpm_bf1") is None)
    no_total = [r for r in jpm_rows() if r[0] != "410499-9999"]
    ok("a section with no total row is refused, not derived",
       t12.rent_capture(no_total, "jpm_bf1") is None)

    print("\nthe align tree")
    al = [row("4050-5100", " Residential Market rent potential", twelve(1000)),
          row("4050-5105", " Residential Loss / Gain to lease", twelve(-100)),
          row("4050-5110", " Residential Vacancy loss", twelve(-50)),
          row("4050-5120", " Residential Employee rent allowance", twelve(-10)),
          row("4050-5115", " Residential Rental concessions", twelve(-5))]
    ra = t12.rent_capture(al, "align_resbv")
    ok("reads the five named accounts", ra["market_potential"][0] == 1000
       and ra["loss_to_lease"][0] == 100, ra["market_potential"][0])
    ok("income is derived, and has no tie-out to report",
       ra["rental_income"][0] == 835 and ra["tieout_max_gap"] is None, ra["rental_income"][0])
    ok("...and says so rather than presenting it as read",
       any("derived" in x for x in ra["problems"]), ra["problems"])

    print("\nthe stitch")
    L = ["Aug","Sep","Oct","Nov","Dec","Jan","Feb","Mar","Apr","May","Jun","Jul"]
    a = point("Jul 2026", L, [100] * 12, [90] * 12)
    # the next statement moves one month on and restates Jul
    b = point("Aug 2026", ["Sep","Oct","Nov","Dec","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug"],
              [100] * 11 + [200], [90] * 11 + [180])
    st = build_metrics.stitch_rent_capture([a, b])
    ok("two statements make one run longer than either",
       len(st["months"]) == 13, len(st["months"]))
    ok("months are labelled continuously",
       st["months"][0] == "2025-08" and st["months"][-1] == "2026-08", st["months"][:1] + st["months"][-1:])
    ok("the newest statement wins a month both report",
       st["market_potential"][-1] == 200, st["market_potential"][-1])
    ok("ttm is the trailing twelve of the run, not the newest file's column",
       st["ttm"]["months"] == 12 and st["ttm"]["market_potential"] == 1300,
       st["ttm"])
    ok("capture rate is income over potential",
       abs(st["ttm"]["capture_rate"] - (st["ttm"]["rental_income"] / 1300)) < 1e-9)

    c = point("Aug 2026", b["labels"], [100] * 11 + [200], [90] * 11 + [180],
              basis="align 4050-51xx, derived (no section total row)")
    st2 = build_metrics.stitch_rent_capture([a, c])
    # c restates eleven of a's months on the other basis and adds one, so the
    # only month left on the old basis is a's first. Without the guard the run
    # would be thirteen months spanning both bases; with it, twelve.
    ok("a basis change cuts the run rather than charting across it",
       len(st2["months"]) == 12 and st2["months"][0] == "2025-09"
       and st2["basis"].startswith("align"),
       (len(st2["months"]), st2["months"][0], st2["basis"]))

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()

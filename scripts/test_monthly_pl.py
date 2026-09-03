"""
test_monthly_pl.py
------------------
Guards the Operating Summary card's expense row. That row is the statement's
TOTAL EXPENSES line (jpm 549999-9999), not TOTAL OPERATING EXPENSES
(519999-9999), and the difference between the two is real money -- so the two
things that can go wrong silently are checked here:

  * the wrong anchor being stored, or two building codes being summed across
    different anchors, which would produce a figure that is neither total nor
    operating expense;
  * a trailing window straddling the anchor change, which would read the gap
    between the anchors as a swing in spending.

No network and no fixtures on disk: the statements are built in a temp dir by
test_expense_buckets' own builders, so both test files describe one shape.

Usage: python scripts/test_monthly_pl.py
"""

import os
import sys
import json
import shutil
import pathlib
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import build_metrics as bm
import parse_t12_statement as t12
from test_expense_buckets import build, build_jpm

PASS = FAIL = 0


def ok(label, cond, detail=None):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}" + (f"\n        {detail}" if detail is not None else ""))


def store(tmp, parses, slug="fixture"):
    """Run store_monthly_pl against a throwaway data/ and return its one point."""
    prev = bm.DATA
    bm.DATA = pathlib.Path(tmp) / "data"
    try:
        hist = bm.store_monthly_pl({"name": "Fixture", "slug": slug}, parses)
    finally:
        bm.DATA = prev
    return hist["points"][-1]


def month_run(period_end, opex, scope, revenue=700000.0):
    """A stored point of arbitrary length, for exercising the stitcher."""
    n = len(opex)
    return {"period_end": period_end,
            "labels": [""] * n,
            "revenue": [revenue] * n,
            "opex": list(opex),
            "noi": [revenue - v for v in opex],
            "expense_scope": scope,
            "expense_anchor": t12.JPM_EXP_ALL if scope == "total" else None,
            "basis": scope}


def main():
    tmp = tempfile.mkdtemp()
    try:
        jpm_path = os.path.join(tmp, "jpm.xlsx")
        align_path = os.path.join(tmp, "align.xlsx")
        build_jpm(jpm_path)
        build(align_path)
        jpm = t12.parse_t12(jpm_path)
        align = t12.parse_t12(align_path)

        print("the expense row is TOTAL EXPENSES, not TOTAL OPERATING EXPENSES")
        pt = store(tmp, [jpm])
        ok("anchored on 549999-9999",
           pt["expense_anchor"] == "549999-9999" and pt["expense_scope"] == "total",
           (pt["expense_anchor"], pt["expense_scope"]))
        ok("expense row carries the total, not the operating slice",
           pt["opex"] == [268300.0] * 12, pt["opex"][:2])
        ok("...which is above the operating total it replaced",
           pt["opex"][0] > jpm["opex_recoverable_monthly"][0],
           (pt["opex"][0], jpm["opex_recoverable_monthly"][0]))
        ok("the three rows reconcile",
           all(abs(pt["revenue"][i] - pt["opex"][i] - pt["noi"][i]) < 0.01
               for i in range(12)),
           (pt["revenue"][0], pt["opex"][0], pt["noi"][0]))
        ok("NOI matches the statement's own NOI line",
           pt["noi"] == [431700.0] * 12, pt["noi"][:2])
        ok("basis names the row the card prints",
           "549999-9999" in (pt["basis"] or ""), pt["basis"])

        print("\na statement with no total-expense row says so instead of inventing one")
        apt = store(tmp, [align], slug="align")
        ok("falls back to the operating anchor",
           apt["expense_scope"] == "operating" and apt["expense_anchor"] is None,
           (apt["expense_scope"], apt["expense_anchor"]))
        ok("expense row is the align recoverable total",
           apt["opex"] == [1500.0] * 12, apt["opex"][:2])
        ok("basis names the align anchor",
           "5999-9998" in (apt["basis"] or ""), apt["basis"])

        print("\ncodes are never summed across different anchors")
        # Same period, one code with a total-expense row and one without: summing
        # them would give a figure that is neither, so the pair drops to the
        # anchor both do carry.
        other = dict(align)
        other["property_code"] = "p9999999"
        other["property_codes"] = ["p9999999"]
        other["period_end"] = jpm["period_end"]
        other["labels"] = jpm["labels"]
        mixed = store(tmp, [jpm, other], slug="mixed")
        ok("mixed anchors fall back to operating expenses",
           mixed["expense_scope"] == "operating" and mixed["expense_anchor"] is None,
           (mixed["expense_scope"], mixed["expense_anchor"]))
        ok("...summing the operating anchor both codes do carry",
           mixed["opex"] == [268000.0 + 1500.0] * 12, mixed["opex"][:2])

        print("\nthe stitched series never straddles the anchor change")
        old = month_run("Jul 2025", [100.0] * 12, "operating")
        new = month_run("Jul 2026", [200.0] * 12, "total")
        s = bm.stitch_monthly_pl([old, new])
        ok("run cut at the switch, not mixed",
           len(s["opex"]) == 12 and set(s["opex"]) == {200.0},
           (len(s["opex"]), sorted(set(s["opex"]))))
        ok("the surviving scope is the newest one",
           s["expense_scope"] == "total" and s["expense_anchor"] == "549999-9999",
           (s["expense_scope"], s["expense_anchor"]))
        ok("last month is still the newest month",
           s["months"][-1] == "2026-07", s["months"][-1])

        # A point stored before expense_scope existed is an operating-slice one,
        # so it must not be read as matching a "total" newest point.
        legacy = month_run("Jul 2025", [100.0] * 12, "operating")
        del legacy["expense_scope"]
        del legacy["expense_anchor"]
        s2 = bm.stitch_monthly_pl([legacy, new])
        ok("a point predating expense_scope counts as operating",
           len(s2["opex"]) == 12 and set(s2["opex"]) == {200.0},
           (len(s2["opex"]), sorted(set(s2["opex"]))))

        print("\nsame anchor still stitches into one long series")
        a = month_run("Jan 2026", [100.0] * 12, "total")
        b = month_run("Jul 2026", [200.0] * 12, "total")
        s3 = bm.stitch_monthly_pl([a, b])
        ok("18 months across two overlapping statements",
           len(s3["opex"]) == 18, len(s3["opex"]))
        ok("newest statement wins the six months they share",
           s3["opex"][-12:] == [200.0] * 12 and s3["opex"][:6] == [100.0] * 6,
           s3["opex"])
        ok("scope published once for the run", s3["expense_scope"] == "total",
           s3["expense_scope"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()

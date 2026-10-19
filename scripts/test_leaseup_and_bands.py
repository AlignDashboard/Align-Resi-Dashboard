#!/usr/bin/env python3
"""Guard tests for three grading rules settled 2026-10-19.

  - H3: `% Increase` is graded on its two-sided band. +4.0% to +7.0% exceeds,
    above +7.0% drops back to in range, and the top of the exceeding range is
    read off the band's own label rather than typed in as a constant.
  - B8: a property in lease-up does not have its Total Delinquency graded, and a
    cell that stops being graded carries the workbook's symbol again rather than
    the grade an earlier run gave it.
  - B6: Closing Ratio and # of Renewals are trailing-one-month measures, and
    their published definition says so, with the sheet's wording kept.

Fixture-free: the scorecard and the export are built in a temp dir, except one
check that reads the band actually published in docs/scorecard.json, so a
reworded band there fails here rather than on the page.
Run: python scripts/test_leaseup_and_bands.py
"""

import copy
import csv
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import populate_building_metrics as pbm  # noqa: E402
import populate_scorecard as ps  # noqa: E402

PASS = FAIL = 0
TOTAL, INC, CLOSE, RENEW = ps.KPI_TOTAL, "% Increase", "Closing Ratio", "# of Renewals"


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"   PASS {name}")
    else:
        FAIL += 1
        print(f"   FAIL {name}\n        got  {got!r}\n        want {want!r}")


# The four bands as the extractor publishes them, wording and all.
BANDS = {
    INC: {"direction": "Band (two-sided)", "exceeding": "+4.0% – +7.0%",
          "in_range": "+1.0% – +3.9%, or > +7.0%", "below": "< +1.0%",
          "green_cutoff": 0.04, "red_cutoff": 0.01,
          "how": "Average renewal rent increase %, trailing 3 months"},
    CLOSE: {"direction": "Higher is better", "exceeding": "≥ 30.0%",
            "green_cutoff": 0.3, "red_cutoff": 0.2,
            "how": "Signed leases / tours, trailing 3 months"},
    RENEW: {"direction": "Higher is better", "exceeding": "≥ 60.0%",
            "green_cutoff": 0.6, "red_cutoff": 0.45,
            "how": "Renewals signed / lease expirations in the period "
                   "(renewal conversion rate)"},
    TOTAL: {"direction": "Lower is better", "exceeding": "≤ 1.0%",
            "green_cutoff": 0.01, "red_cutoff": 0.03,
            "how": "Total gross resident AR balance / one month's billed rent"},
}

print("H3: the two-sided band")
band = BANDS[INC]
check("the top of the exceeding range is read off the label",
      ps.band_upper(band), 0.07)
for value, want in ((0.055, "exceeding"), (0.04, "exceeding"), (0.07, "exceeding"),
                    (0.2072, "in_range"), (0.0701, "in_range"), (0.02, "in_range"),
                    (0.005, "below")):
    check(f"{value:.2%} grades {want}", ps.classify(value, band), want)

reworded = dict(band, exceeding="+4.0% and up")
check("a label with one figure leaves the cell ungraded, not graded upward",
      ps.classify(0.2072, reworded), None)
shifted = dict(band, exceeding="+5.0% – +7.0%")
check("a label whose low end is not the green cutoff is not trusted",
      ps.classify(0.2072, shifted), None)
check("higher-is-better is unchanged", [ps.classify(v, BANDS[CLOSE])
                                        for v in (0.35, 0.25, 0.1)],
      ["exceeding", "in_range", "below"])
check("lower-is-better is unchanged", [ps.classify(v, BANDS[TOTAL])
                                       for v in (0.005, 0.02, 0.05)],
      ["exceeding", "in_range", "below"])

published = json.load(open(os.path.join(HERE, "..", "docs", "scorecard.json")))
check("the band docs/scorecard.json publishes grades 20.7% in range",
      ps.classify(0.2072, (published.get("thresholds") or {}).get(INC)), "in_range")

print("B8: restore_workbook_status")
p = {"statuses": {TOTAL: "below"}, "status_workbook": {TOTAL: "in_range"}}
ps.restore_workbook_status(p, TOTAL)
check("the workbook's symbol goes back on the cell", p["statuses"][TOTAL], "in_range")
check("and comes off status_workbook", TOTAL in p["status_workbook"], False)
p = {"statuses": {TOTAL: "in_range"}}
ps.restore_workbook_status(p, TOTAL)
check("a cell never restated is left alone", p["statuses"][TOTAL], "in_range")


def scorecard():
    """335 Third as main had it on 2026-10-19: its delinquency graded below
    over a workbook that said in range. The Landing stabilised."""
    names = [TOTAL, INC, CLOSE, RENEW]
    return {
        "metrics": [{"name": n, "group": "G"} for n in names],
        "groups": [{"name": "G", "metrics": names}],
        "unscored": [],
        "thresholds": copy.deepcopy(BANDS),
        "properties": [
            {"slug": "335-third-street", "label": "335 Third",
             "statuses": {TOTAL: "below", INC: "in_range", CLOSE: "in_range",
                          RENEW: "in_range"},
             "values": {TOTAL: {"raw": 0.2212, "display": "22.1%"}},
             "status_source": {TOTAL: "measured"},
             "status_workbook": {TOTAL: "in_range"}},
            {"slug": "the-landing", "label": "Landing",
             "statuses": {TOTAL: "below", INC: "exceeding", CLOSE: "in_range",
                          RENEW: "in_range"},
             "values": {}, "status_source": {}},
        ],
        "portfolio": {},
        "meta": {"note": "stub"},
        "measured": {},
    }


def export(path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Property", "Occupancy Rate (Period End)", "Delinquency Rate",
                    "Avg Rent Increase Executed (%)", "Tour Attended to Lease Signed Rate",
                    "Renewal Rate"])
        w.writerow(["335 3rd Street", "13.2", "22.12", "", "0", ""])
        w.writerow(["The Landing", "98.9", "7.57", "20.72", "22.73", "63.64"])


def run(tmp, out, csv_path, *extra):
    r = subprocess.run([sys.executable, os.path.join(HERE, "populate_building_metrics.py"),
                        csv_path, "--out", out, *extra],
                       capture_output=True, text=True, cwd=tmp)
    check(f"populate_building_metrics {' '.join(extra)} exits cleanly".replace("  ", " "),
          r.returncode, 0)
    if r.returncode:
        print(r.stdout[-2000:], r.stderr[-2000:])
    return json.load(open(out))


def prop(sc, slug):
    return next(x for x in sc["properties"] if x["slug"] == slug)


with tempfile.TemporaryDirectory() as tmp:
    out = os.path.join(tmp, "scorecard.json")
    with open(out, "w") as f:
        json.dump(scorecard(), f)
    csv_path = os.path.join(tmp, "metrics-building-2026-10-19.csv")
    export(csv_path)

    print("--dry-run first")
    before = open(out).read()
    run(tmp, out, csv_path, "--dry-run")
    check("a dry run writes nothing", open(out).read(), before)

    print("B8: a building in lease-up")
    sc = run(tmp, out, csv_path)
    tp = prop(sc, "335-third-street")
    check("its delinquency is still published", tp["values"][TOTAL]["display"], "22.1%")
    check("as value only", tp["status_source"][TOTAL], "value_only")
    check("coloured by the workbook's symbol, not the old grade",
          tp["statuses"][TOTAL], "in_range")
    check("and out of the tally", (tp["scored"], tp["below_metrics"]), (0, []))

    print("B8: a stabilised building")
    lp = prop(sc, "the-landing")
    check("its delinquency is graded", (lp["status_source"][TOTAL], lp["statuses"][TOTAL]),
          ("measured", "below"))

    print("H3, end to end")
    check("The Landing's 20.7% increase grades in range",
          (lp["values"][INC]["display"], lp["statuses"][INC]), ("20.7%", "in_range"))
    check("the workbook's exceeding is kept beside it",
          lp["status_workbook"].get(INC), "exceeding")

    print("B6: trailing-one-month definitions")
    t = sc["thresholds"]
    check("Closing Ratio's definition names the trailing month",
          t[CLOSE]["how"], pbm.T1_HOW[CLOSE])
    check("# of Renewals' definition names the trailing month",
          t[RENEW]["how"], pbm.T1_HOW[RENEW])
    check("the sheet's wording is kept",
          (t[CLOSE].get("how_workbook"), t[RENEW].get("how_workbook")),
          (BANDS[CLOSE]["how"], BANDS[RENEW]["how"]))
    check("the cutoffs are untouched",
          [(t[k]["green_cutoff"], t[k]["red_cutoff"]) for k in (CLOSE, RENEW)],
          [(0.3, 0.2), (0.6, 0.45)])
    check("% Increase's definition is left alone (its window is B10's question)",
          ("how_workbook" in t[INC], t[INC]["how"]), (False, BANDS[INC]["how"]))

    print("the next day's run")
    sc = run(tmp, out, csv_path)
    t = sc["thresholds"]
    check("how_workbook still holds the sheet's wording, not the restated text",
          t[CLOSE].get("how_workbook"), BANDS[CLOSE]["how"])
    tp = prop(sc, "335-third-street")
    check("the lease-up cell stays on the workbook's symbol",
          (tp["status_source"][TOTAL], tp["statuses"][TOTAL]), ("value_only", "in_range"))

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)

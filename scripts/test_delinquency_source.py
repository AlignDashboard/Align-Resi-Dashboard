#!/usr/bin/env python3
"""Guard tests for who fills Total Deliquency.

Owner's call, 2026-09-29 (closing B4): the EliseAI building-metrics export's
`Delinquency Rate` is the outstanding-balance figure, so it fills Total
Deliquency for every property it covers. The Yardi AR report keeps the
30/60/90 split, which the export does not carry, and keeps the rate only for a
property the export does not cover (Palma).

Two writers touch the cell, and the daily run calls them in this order:
populate_scorecard --from-pipeline, then populate_building_metrics. Four
halves:

  - the covered list is one list: AR_FROM_EXPORT equals the export's own
    HEADING_TO_SLUG, so a property added to the export cannot be left with
    both writers claiming its rate, or neither.
  - --from-pipeline for a covered property writes the split and NOT the rate,
    and records only the split under delq_kpis -- naming the rate there would
    claim it back from the export.
  - populate_building_metrics then takes the rate even though delq_ once
    owned it, and takes it off delq_kpis.
  - for Palma, --from-pipeline still writes both.

Fixture-free: the scorecard, the AR store and the export are built in a temp
dir. Run: python scripts/test_delinquency_source.py
"""

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
TOTAL, SPLIT = ps.KPI_TOTAL, ps.KPI_SPLIT


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"   PASS {name}")
    else:
        FAIL += 1
        print(f"   FAIL {name}\n        got  {got!r}\n        want {want!r}")


def scorecard():
    """Landing's rate as the Yardi report left it before 2026-09-29, and Palma."""
    return {
        "metrics": [{"name": TOTAL, "group": "Finance"}, {"name": SPLIT, "group": "Finance"}],
        "groups": [{"name": "Finance", "metrics": [TOTAL, SPLIT]}],
        "unscored": [SPLIT],
        "thresholds": {TOTAL: {"direction": "Lower is better",
                               "green_cutoff": 0.02, "red_cutoff": 0.05}},
        "properties": [
            {"slug": "the-landing", "label": "Landing", "statuses": {TOTAL: "below", SPLIT: None},
             "values": {TOTAL: {"raw": 0.102, "display": "10.2%"}},
             "status_source": {TOTAL: "measured"}},
            {"slug": "palma", "label": "Palma", "statuses": {TOTAL: "below", SPLIT: None},
             "values": {}, "status_source": {TOTAL: "measured"}},
        ],
        "portfolio": {},
        "meta": {"note": "stub"},
        "measured": {"the-landing": {"delq_kpis": [SPLIT, TOTAL]}},
    }


def ar_store(tmp, slug):
    d = os.path.join(tmp, "data", slug)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "delinquency.json"), "w") as f:
        json.dump({"as_of": "2026-09-08", "landed_at": "2026-09-08T23:28:43Z",
                   "source_file": f"rs_rp_DelinquencySummaryReport - {slug}.xlsx",
                   "summary": {"gross_owed": 3000.0,
                               "aging": {"d31_60": 500.0, "d61_90": 250.0, "over90": 100.0}}},
                  f)


def export(path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Property", "Occupancy Rate (Period End)", "Delinquency Rate"])
        w.writerow(["The Landing", "99.2", "7.74"])


def run(tmp, *args):
    r = subprocess.run([sys.executable, *args], capture_output=True, text=True, cwd=tmp)
    check(f"{os.path.basename(args[0])} {' '.join(args[1:3])} exits cleanly",
          r.returncode, 0)
    if r.returncode:
        print(r.stdout[-2000:], r.stderr[-2000:])
    return json.load(open(os.path.join(tmp, "scorecard.json")))


def prop(sc, slug):
    return next(p for p in sc["properties"] if p["slug"] == slug)


print("one list of covered properties")
check("AR_FROM_EXPORT is the export's own HEADING_TO_SLUG",
      set(pbm.HEADING_TO_SLUG.values()), set(ps.AR_FROM_EXPORT))
check("Palma is not covered, so it keeps the Yardi rate", "palma" in ps.AR_FROM_EXPORT, False)

with tempfile.TemporaryDirectory() as tmp:
    out = os.path.join(tmp, "scorecard.json")
    with open(out, "w") as f:
        json.dump(scorecard(), f)
    for slug in ("the-landing", "palma"):
        ar_store(tmp, slug)
    pop = os.path.join(HERE, "populate_scorecard.py")

    print("--from-pipeline, a covered property")
    sc = run(tmp, pop, "--from-pipeline", "the-landing", "--monthly-rent", "100000",
             "--out", out)
    lp = prop(sc, "the-landing")
    check("the rate is left as the export will fill it, not rewritten",
          lp["values"][TOTAL]["display"], "10.2%")
    check("the split is written", lp["values"][SPLIT]["display"], "500/250/100")
    check("delq_kpis names the split only",
          sc["measured"]["the-landing"].get("delq_kpis"), [SPLIT])

    print("--from-pipeline, Palma")
    sc = run(tmp, pop, "--from-pipeline", "palma", "--monthly-rent", "100000", "--out", out)
    pp = prop(sc, "palma")
    check("Palma's rate is the report's gross AR over the month",
          pp["values"][TOTAL]["display"], "3.0%")
    check("Palma's delq_kpis names both", sc["measured"]["palma"].get("delq_kpis"),
          sorted([SPLIT, TOTAL]))

    print("populate_building_metrics, after it")
    csv_path = os.path.join(tmp, "metrics-building-2026-09-28.csv")
    export(csv_path)
    sc = run(tmp, os.path.join(HERE, "populate_building_metrics.py"), csv_path, "--out", out)
    lp = prop(sc, "the-landing")
    check("the export's Delinquency Rate fills the cell", lp["values"][TOTAL]["display"], "7.7%")
    check("bldg_kpis names it", TOTAL in sc["measured"]["the-landing"].get("bldg_kpis", []), True)
    check("delq_kpis no longer does", sc["measured"]["the-landing"].get("delq_kpis"), [SPLIT])
    check("the split is untouched", lp["values"][SPLIT]["display"], "500/250/100")
    check("Palma is untouched", prop(sc, "palma")["values"][TOTAL]["display"], "3.0%")

    print("--from-pipeline again, the next day")
    sc = run(tmp, pop, "--from-pipeline", "the-landing", "--monthly-rent", "100000",
             "--out", out)
    check("the export's figure survives the report's next run",
          prop(sc, "the-landing")["values"][TOTAL]["display"], "7.7%")
    check("and bldg_kpis still names it",
          TOTAL in sc["measured"]["the-landing"].get("bldg_kpis", []), True)

print("populate_building_metrics first, over a stale delq_kpis")
# The state on main before the first run after this change: delq_kpis still
# names the rate. The export must take it anyway and take it off that list --
# without the exemption, rule 1 ("never take a cell another feed owns") skips it
# and the Yardi figure stays for as long as the list is stale.
with tempfile.TemporaryDirectory() as tmp:
    with open(os.path.join(tmp, "scorecard.json"), "w") as f:
        json.dump(scorecard(), f)
    csv_path = os.path.join(tmp, "metrics-building-2026-09-28.csv")
    export(csv_path)
    sc = run(tmp, os.path.join(HERE, "populate_building_metrics.py"), csv_path,
             "--out", os.path.join(tmp, "scorecard.json"))
    check("the export takes the rate a stale list still names",
          prop(sc, "the-landing")["values"][TOTAL]["display"], "7.7%")
    check("and takes it off that list", sc["measured"]["the-landing"].get("delq_kpis"), [SPLIT])

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)

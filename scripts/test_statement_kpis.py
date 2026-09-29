#!/usr/bin/env python3
"""Guard tests for open item H2: the scorecard cells that used to wait on Excel.

NOI Margin %, Concession Load % and Month to Month Leases were read from
docs/landing.json -- the analyst workbook, refreshed by hand -- so they stood
still at its last extract however many statements and rent rolls arrived. They
are now the same formulas pointed at the pipeline's own published blocks in
docs/metrics.json (`monthly_pl`, `rent_capture`, `rent_roll`), so each moves
when its report does. Four halves:

  - each figure is the formula over the PUBLISHED block, and the workbook's own
    reading of the same thing -- planted here with different numbers -- is not
    what reaches the cell.
  - provenance follows the source: the statement's cells under t12_, month to
    month under rentroll_ beside loss to lease, and no unprefixed family, which
    would date the cells by a workbook extract that no longer feeds one of them.
  - --from-pipeline after --from-landing (the daily run's order) leaves the file
    exactly as it was: both paths fill month to month from the one aggregate.
  - a gap in the source is a gap on the page, not a zero: a month with no
    revenue is skipped, and a non-positive concession denominator publishes
    nothing.

Fixture-free: every input is built in a temp dir.
Run: python scripts/test_statement_kpis.py
"""

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import populate_scorecard as ps  # noqa: E402

PASS = FAIL = 0
NOI, CONC, MTM, LTL = ps.KPI_NOI, ps.KPI_CONC, ps.KPI_MTM, ps.KPI_LTL
SLUG = "the-landing"


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"   PASS {name}")
    else:
        FAIL += 1
        print(f"   FAIL {name}\n        got  {got!r}\n        want {want!r}")


MONTHS = [f"2025-{m:02d}" for m in range(9, 13)] + [f"2026-{m:02d}" for m in range(1, 9)]


def metrics(revenue_last=1000.0, noi_last=700.0, vac_last=10.0):
    rev = [900.0] * 11 + [revenue_last]
    noi = [600.0] * 11 + [noi_last]
    return {
        "monthly_pl": {"properties": [{"slug": SLUG, "months": MONTHS, "revenue": rev,
                                       "noi": noi, "opex": [None if r is None else r - n for r, n in zip(rev, noi)],
                                       "expense_scope": "total"}]},
        "rent_capture": {"properties": [{"slug": SLUG, "months": MONTHS,
                                         "market_potential": [2000.0] * 12,
                                         "loss_to_lease": [500.0] * 12,
                                         "vacancy_loss": [10.0] * 11 + [vac_last],
                                         "concessions": [3.0] * 11 + [6.0]}]},
        "rent_roll": {"properties": [{"slug": SLUG, "as_of": "2026-09-21",
                                      "source_file": "RentRoll09_21_2026.xlsx",
                                      "landed_at": "2026-09-22T00:00:00Z",
                                      "occupied": 200, "loss_to_lease_pct": 0.3,
                                      "loss_to_lease": 1.0, "market_rent_occupied": 1.0,
                                      "actual_rent_occupied": 1.0,
                                      "holdovers": {"units": 20, "share_of_occupied": 0.1}}]},
        "unit_directory": {"properties": [{"slug": SLUG, "residential_units": 250}]},
    }


def landing():
    """The workbook's readings, deliberately different from the pipeline's."""
    return {"meta": {"units": 250, "generated_at": "2026-08-03T00:00:00Z"},
            "delinquency": {"aging": []},
            "rent_capture": {"months": ["2026-07"], "ltl_pct": [0.27],
                             "concessions": [99.0], "market_potential": [100.0],
                             "loss_to_lease": [0.0], "vacancy_loss": [0.0]},
            "expense_noi": {"months": ["2026-07"], "noi_margin": [0.11],
                            "ttm": {"noi_margin": 0.22}},
            "units": [{"status": "Holdover"}] * 99 + [{"status": "Current"}]}


def scorecard():
    kpis = [NOI, CONC, MTM, LTL]
    return {
        "metrics": [{"name": k, "group": "Ops"} for k in kpis],
        "groups": [{"name": "Ops", "metrics": kpis}],
        "thresholds": {NOI: {"direction": "Higher is better", "green_cutoff": 0.6,
                             "red_cutoff": 0.5},
                       CONC: {"direction": "Lower is better", "green_cutoff": 0.01,
                              "red_cutoff": 0.02},
                       MTM: {"direction": "Lower is better", "green_cutoff": 0.03,
                             "red_cutoff": 0.05}},
        "properties": [{"slug": SLUG, "label": "Landing",
                        "statuses": {k: None for k in kpis}, "values": {}}],
        "portfolio": {}, "meta": {"note": "stub"}, "measured": {},
    }


def build(tmp, m):
    os.makedirs(os.path.join(tmp, "docs"), exist_ok=True)
    for name, doc in (("metrics.json", m), ("landing.json", landing()),
                      ("scorecard.json", scorecard())):
        with open(os.path.join(tmp, "docs", name), "w") as f:
            json.dump(doc, f)
    d = os.path.join(tmp, "data", SLUG)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "monthly_pl.json"), "w") as f:
        json.dump({"points": [{"period_end": "Aug 2026", "landed_at": "2026-09-14T22:09:04Z",
                               "source_files": ["12_Month_Statement_Accrual.xlsx"]}]}, f)


def run(tmp, *args):
    r = subprocess.run([sys.executable, os.path.join(HERE, "populate_scorecard.py"), *args],
                       capture_output=True, text=True, cwd=tmp)
    check(f"populate_scorecard {' '.join(args)} exits cleanly", r.returncode, 0)
    if r.returncode:
        print(r.stdout[-2000:], r.stderr[-2000:])
    return json.load(open(os.path.join(tmp, "docs", "scorecard.json")))


def cell(sc, kpi):
    return (sc["properties"][0]["values"].get(kpi) or {}).get("display")


with tempfile.TemporaryDirectory() as tmp:
    build(tmp, metrics())
    print("--from-landing reads the pipeline, not the workbook")
    sc = run(tmp, "--from-landing")
    check("NOI margin is the newest month's NOI over revenue (700/1000)", cell(sc, NOI), "70.0%")
    m = sc["measured"][SLUG]
    check("its month is the statement's newest", m.get("noi_margin_month"), "2026-08")
    check("the T12 beside it is twelve months of NOI over revenue",
          round(m.get("noi_margin_ttm"), 6), round((600 * 11 + 700) / (900 * 11 + 1000), 6))
    check("concession load is concessions over GPR less L2L less vacancy (6/1490)",
          cell(sc, CONC), f"{6 / 1490 * 100:.2f}%")
    check("month to month is the rent roll's holdover count and share", cell(sc, MTM), "20/10.0%")
    check("the basis names the roll it was read from",
          "rent roll of 2026-09-21" in (m.get("mtm_basis") or ""), True)

    print("provenance follows the source")
    check("the statement's cells are the t12_ family's",
          m.get("t12_kpis"), sorted([CONC, NOI]))
    check("dated by the statement's arrival", m.get("t12_received_at"), "2026-09-14T22:09:04Z")
    check("month to month sits beside loss to lease under rentroll_",
          m.get("rentroll_kpis"), [LTL, MTM])
    check("no unprefixed family is written for a workbook that fed nothing",
          [k for k in ("source", "kpis", "received_at") if k in m], [])

    print("--from-pipeline afterwards, the daily run's order")
    before = json.load(open(os.path.join(tmp, "docs", "scorecard.json")))
    after = run(tmp, "--from-pipeline", SLUG)
    check("leaves the file exactly as --from-landing wrote it", after, before)

with tempfile.TemporaryDirectory() as tmp:
    print("a gap in the source is a gap, not a zero")
    m = metrics(revenue_last=None, noi_last=None, vac_last=1600.0)
    build(tmp, m)
    sc = run(tmp, "--from-landing")
    check("a month with no revenue is skipped; the one before it is graded",
          (cell(sc, NOI), sc["measured"][SLUG].get("noi_margin_month")), ("66.7%", "2026-07"))
    check("with eleven months usable there is no T12 figure",
          sc["measured"][SLUG].get("noi_margin_ttm"), None)
    check("a non-positive concession denominator publishes nothing", cell(sc, CONC), None)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)

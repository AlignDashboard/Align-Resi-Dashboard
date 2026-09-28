#!/usr/bin/env python3
"""Guard tests for status_workbook -- the workbook's own symbol, kept.

When a measurement restates a cell's status, the writer keeps the symbol the
workbook's grid carried beside it, and the data page prints it as "Workbook
had". Only the first restatement since extraction knows what that symbol was:
from the second on, the status being replaced is the previous run's grade.

All three writers used to record it on every change, so the second time a
grade moved the entry was overwritten with a grade the workbook never set. By
2026-09-28 six cells quoted one -- Chorus's Leased % read "Workbook had:
in range" over a workbook that said below -- and nothing looked wrong, because
a plausible symbol is exactly what the column is supposed to hold.

`populate_scorecard.keep_workbook_status` is now the one place it is written,
and it never replaces an entry. Three halves:

  - the helper itself: a second restatement leaves the first entry alone.
  - end to end through populate_building_metrics, over three exports that
    grade one cell below, then exceeding, then back in range: the entry must
    still read the workbook's symbol after all three.
  - no writer keeps its own copy of the assignment -- a fourth copy of the
    old line is how this would come back.

Fixture-free: the scorecard and the exports are built in a temp dir, and the
only repo files read are the writers' own sources.

Run: python scripts/test_status_workbook.py
"""

import csv
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import populate_scorecard as ps

PASS = FAIL = 0


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"   PASS {name}")
    else:
        FAIL += 1
        print(f"   FAIL {name}\n        got  {got!r}\n        want {want!r}")


KPI = "Leased %"
WORKBOOK = "in_range"


def scorecard():
    """One property, one KPI, the workbook's symbol in statuses and no entry yet."""
    return {
        "metrics": [{"name": KPI, "group": "Revenue Metrics"}],
        "groups": [{"name": "Revenue Metrics", "metrics": [KPI]}],
        "thresholds": {KPI: {"direction": "Higher is better",
                             "green_cutoff": 0.99, "red_cutoff": 0.95}},
        "properties": [{"slug": "chorus", "label": "Chorus",
                        "statuses": {KPI: WORKBOOK}, "values": {}}],
        "portfolio": {},
        "measured": {},
    }


def export(path, exposure):
    """A building-metrics export carrying only what Leased % reads."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Property", "Occupancy Rate (Period End)",
                    "Exposure Rate (Period End)", "Vacant Units (Period End)"])
        w.writerow(["Chorus", "96.0", str(exposure), "16"])


print("keep_workbook_status")
p = {"statuses": {KPI: WORKBOOK}}
ps.keep_workbook_status(p, KPI, WORKBOOK)
check("the first restatement records the symbol it replaced",
      p.get("status_workbook"), {KPI: WORKBOOK})
ps.keep_workbook_status(p, KPI, "below")
check("a second restatement leaves the first entry alone",
      p["status_workbook"], {KPI: WORKBOOK})
p = {"statuses": {}, "status_workbook": {"Other": "below"}}
ps.keep_workbook_status(p, KPI, "exceeding")
check("an entry for another KPI does not block this one",
      p["status_workbook"], {"Other": "below", KPI: "exceeding"})

print("populate_building_metrics, three exports in a row")
with tempfile.TemporaryDirectory() as tmp:
    out = os.path.join(tmp, "scorecard.json")
    with open(out, "w") as f:
        json.dump(scorecard(), f)
    # 100 - exposure is the leased figure: 92% below, 99.5% exceeding, 97% in range
    runs = [("20260901", 8.0, "below"), ("20260908", 0.5, "exceeding"),
            ("20260915", 3.0, "in_range")]
    for stamp, exposure, want in runs:
        csv_path = os.path.join(tmp, f"metricsbuilding{stamp}.csv")
        export(csv_path, exposure)
        r = subprocess.run([sys.executable, os.path.join(HERE, "populate_building_metrics.py"),
                            csv_path, "--out", out], capture_output=True, text=True, cwd=tmp)
        if r.returncode:
            print(r.stdout, r.stderr)
        prop = json.load(open(out))["properties"][0]
        check(f"{stamp}: {100 - exposure:g}% grades {want}", prop["statuses"][KPI], want)
        check(f"{stamp}: Workbook had still reads the workbook's {WORKBOOK}",
              (prop.get("status_workbook") or {}).get(KPI), WORKBOOK)

print("no writer keeps its own copy")
own_copy = re.compile(r"""\[\s*["']status_workbook["']\s*\]\s*\[|"""
                      r"""setdefault\(\s*["']status_workbook["']\s*,\s*\{\}\s*\)\s*\[""")
for name in ("populate_scorecard.py", "populate_eliseai.py", "populate_building_metrics.py"):
    src = open(os.path.join(HERE, name)).read()
    check(f"{name} assigns no status_workbook entry directly",
          own_copy.findall(src), [])
    if name != "populate_scorecard.py":
        check(f"{name} restates through keep_workbook_status",
              "keep_workbook_status(prop," in src, True)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)

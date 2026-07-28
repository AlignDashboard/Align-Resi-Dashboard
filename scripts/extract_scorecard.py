#!/usr/bin/env python3
"""Build docs/scorecard.json — the KPI health scorecard.

Reads the "KPI (Flipped Axis)" sheet of the KPI scorecard workbook, which
carries one more metric than the MVP sheet and defines the metric groups in
its merged header row.

Statuses today are the literal symbols the workbook holds (set by hand).
The numeric ranges that decide green/yellow/red are not in the workbook yet;
when they arrive, add them under "thresholds" and compute "status" from the
measured value. The dashboard reads status only, so it will not need changing.

Usage: python scripts/extract_scorecard.py <path-to-KPI_Scorecard.xlsx>
"""
import datetime
import json
import sys

import openpyxl
from openpyxl.utils import get_column_letter

SRC = sys.argv[1] if len(sys.argv) > 1 else "KPI_Scorecard_Formatted_V4.xlsx"
OUT = "docs/scorecard.json"
SHEET = "KPI (Flipped Axis)"

HEADER_GROUP_ROW = 7
HEADER_METRIC_ROW = 8
FIRST_DATA_ROW = 9
FIRST_METRIC_COL = 3          # C

# From the workbook's own legend cells (C4/G4/K4) — do not re-invent these.
LEGEND = [
    {"symbol": "▲", "state": "exceeding", "label": "Exceeding KPI target range",
     "color": "green", "xlsx_fill": "FF00B050"},
    {"symbol": "●", "state": "in_range", "label": "In KPI target range",
     "color": "yellow", "xlsx_fill": "FFFFC000"},
    {"symbol": "▼", "state": "below", "label": "Below KPI target range",
     "color": "red", "xlsx_fill": "FFFF0000"},
]
STATE_BY_SYMBOL = {l["symbol"]: l["state"] for l in LEGEND}

# Scorecard property label -> slug in config/properties.json. 2177 Third is on
# the scorecard but not in the property master, so it maps to None and renders
# without a link to a view that does not exist. Any slug named here that is
# missing from the master is reported below and downgraded to None, so this map
# cannot silently drift out of sync with the config.
SLUGS = {
    "Chorus": "chorus",
    "Landing": "the-landing",
    "335 Third": "335-third-street",
    "Madelon": "madelon",
    "Fitzgerald": "fitzgerald",
    "Palma": "palma",
    "2177 Third": None,
}

try:
    KNOWN_SLUGS = {p["slug"] for p in json.load(open("config/properties.json"))["properties"]}
except OSError:
    KNOWN_SLUGS = None                      # run from elsewhere; skip the check

STALE = sorted(s for s in SLUGS.values()
               if s and KNOWN_SLUGS is not None and s not in KNOWN_SLUGS)
for label, slug in SLUGS.items():
    if slug in STALE:
        SLUGS[label] = None

wb = openpyxl.load_workbook(SRC, data_only=True)
ws = wb[SHEET]

# ---- metrics, in sheet order, tagged with the group that spans them ----
metrics, group = [], None
for col in range(FIRST_METRIC_COL, ws.max_column + 1):
    g = ws.cell(row=HEADER_GROUP_ROW, column=col).value
    if g:
        group = str(g).strip()
    name = ws.cell(row=HEADER_METRIC_ROW, column=col).value
    if not name:
        continue
    metrics.append({"name": str(name).strip(), "group": group,
                    "col": get_column_letter(col)})

# ---- one record per property ----
properties = []
for row in range(FIRST_DATA_ROW, ws.max_row + 1):
    label = ws.cell(row=row, column=2).value
    if not label:
        continue
    label = str(label).strip()
    statuses, counts = {}, {"exceeding": 0, "in_range": 0, "below": 0, "missing": 0}
    for i, m in enumerate(metrics):
        sym = ws.cell(row=row, column=FIRST_METRIC_COL + i).value
        state = STATE_BY_SYMBOL.get(str(sym).strip()) if sym else None
        statuses[m["name"]] = state
        counts[state or "missing"] += 1
    scored = counts["exceeding"] + counts["in_range"] + counts["below"]
    properties.append({
        "label": label,
        "slug": SLUGS.get(label),
        "statuses": statuses,
        "counts": counts,
        "scored": scored,
        # share of scored metrics that are at or above target
        "at_or_above": round((counts["exceeding"] + counts["in_range"]) / scored, 4) if scored else None,
        "below_metrics": [m["name"] for m in metrics if statuses[m["name"]] == "below"],
    })

# ---- portfolio roll-up ----
total = {"exceeding": 0, "in_range": 0, "below": 0, "missing": 0}
for p in properties:
    for k in total:
        total[k] += p["counts"][k]
scored_total = total["exceeding"] + total["in_range"] + total["below"]

# Per-metric roll-up: which KPIs are weakest across the portfolio.
by_metric = []
for m in metrics:
    c = {"exceeding": 0, "in_range": 0, "below": 0}
    for p in properties:
        s = p["statuses"][m["name"]]
        if s in c:
            c[s] += 1
    by_metric.append({"name": m["name"], "group": m["group"], "counts": c})

data = {
    "meta": {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source_workbook": SRC.split("/")[-1],
        "source_sheet": SHEET,
        "note": ("Statuses are set by hand in the workbook. The numeric ranges behind "
                 "green/yellow/red are not published yet — see \"thresholds\"."),
    },
    "legend": LEGEND,
    "groups": [{"name": g, "metrics": [m["name"] for m in metrics if m["group"] == g]}
               for g in dict.fromkeys(m["group"] for m in metrics)],
    "metrics": [{"name": m["name"], "group": m["group"]} for m in metrics],
    "properties": properties,
    "portfolio": {
        "property_count": len(properties),
        "metric_count": len(metrics),
        "counts": total,
        "scored": scored_total,
        "at_or_above": round((total["exceeding"] + total["in_range"]) / scored_total, 4) if scored_total else None,
        "by_metric": by_metric,
    },
    # Placeholder for the ranges that will define each status. Expected shape:
    #   {"Leased %": {"green": [0.95, null], "yellow": [0.90, 0.95], "red": [null, 0.90],
    #                 "unit": "pct", "direction": "higher_is_better"}}
    "thresholds": None,
}

with open(OUT, "w") as f:
    json.dump(data, f, separators=(",", ":"))

import os
print(f"wrote {OUT} ({os.path.getsize(OUT)} bytes)")
print(f"  {len(properties)} properties x {len(metrics)} metrics = {scored_total} scored cells")
print("  " + "  ".join(f"{k}={v}" for k, v in total.items()))
unmapped = [p["label"] for p in properties if not p["slug"]]
if unmapped:
    print("  no property view / not in the master: " + ", ".join(unmapped))
if STALE:
    print("  WARNING: slugs mapped here but missing from config/properties.json: "
          + ", ".join(STALE))

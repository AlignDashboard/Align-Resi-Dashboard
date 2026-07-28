#!/usr/bin/env python3
"""Build docs/landing.json — data for the property deep-dive view (View 2).

Currently extracts from the analyst workbook (The_Landing_Dashboard_V26.xlsx),
whose own sources are the same Yardi reports the Drive pipeline pulls:
rent roll, GL/T12 statements, delinquency. When those feeds are wired up,
this script should be replaced/extended to compute the same JSON shape
directly from data/ — the dashboard only depends on the JSON contract.

Usage: python scripts/extract_landing.py <path-to-workbook.xlsx>
"""
import json, sys, datetime
import openpyxl

SRC = sys.argv[1] if len(sys.argv) > 1 else "The_Landing_Dashboard_V26.xlsx"
OUT = "docs/landing.json"

wb = openpyxl.load_workbook(SRC, data_only=True)

def cell(ws, r, c):
    v = ws.cell(row=r, column=c).value
    if isinstance(v, datetime.datetime):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, float):
        return round(v, 6)
    return v

def rows(ws, r1, r2, cols):
    out = []
    for r in range(r1, r2 + 1):
        rec = [cell(ws, r, c) for c in cols]
        if all(v is None for v in rec):
            continue
        out.append(rec)
    return out

data = {}

# ---------------- meta / inputs ----------------
inp = wb["Inputs"]
data["meta"] = {
    "property": cell(inp, 5, 3),
    "units": cell(inp, 6, 3),
    "rentable_sqft": cell(inp, 7, 3),
    "rent_roll_as_of": cell(inp, 15, 3),
    "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "source_workbook": SRC.split("/")[-1],
    "source_reports": ["rent roll", "GL / T12 statements", "delinquency"],
    "note": ("Extracted from the analyst workbook. Same underlying Yardi report "
             "types as the Drive pipeline; refresh by re-running scripts/extract_landing.py "
             "until the direct feed is built."),
}
data["inputs"] = {
    "target_econ_occupancy": cell(inp, 9, 3),
    "yardi_market_psf": cell(inp, 10, 3),
    "inplace_psf": cell(inp, 11, 3),
    "capture_rate": cell(inp, 22, 3),
    "turnover_cost_ttm": cell(inp, 13, 3),
    "mgmt_fee_pct": cell(inp, 14, 3),
    "make_ready_per_moveout": cell(inp, 20, 3),
    "downtime_months": cell(inp, 23, 3),
    "concession_per_lease": cell(inp, 24, 3),
    "leasing_cost_per_lease": cell(inp, 25, 3),
    "cap_rate": cell(wb["Renewal Pipeline"], 8, 3),
}

# ---------------- rent capture (monthly, Jan25..Jul26 + TTM) ----------------
MON = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
def norm_month(v):
    """'Jan 2025' or datetime or '2026-08' -> '2025-01' style."""
    s = str(v).strip()
    if s[:4].isdigit():
        return s[:7]
    name, year = s.split()
    return f"{year}-{MON[name[:3]]:02d}"

rc = wb["Rent Capture"]
months = [norm_month(cell(rc, 5, c)) for c in range(4, 23)]
def series(ws, r, c1=4, c2=22):
    return [cell(ws, r, c) for c in range(c1, c2 + 1)]
data["rent_capture"] = {
    "months": months,
    "market_potential": series(rc, 7),
    "loss_to_lease": series(rc, 9),
    "vacancy_loss": [-(v or 0) for v in series(rc, 10)],
    "employee_allowance": [-(v or 0) for v in series(rc, 11)],
    "concessions": [-(v or 0) for v in series(rc, 12)],
    "rental_income": series(rc, 13),
    "ltl_pct": series(rc, 19),
    "capture_rate": series(rc, 23),
    "econ_occupancy": series(rc, 24),
    "ttm": {"market_potential": cell(rc, 7, 23), "rental_income": cell(rc, 13, 23),
            "capture_rate": cell(rc, 23, 23), "econ_occupancy": cell(rc, 24, 23),
            "ltl_pct": cell(rc, 19, 23)},
}

# ---------------- expense & NOI (monthly) ----------------
en = wb["Expense & NOI"]
data["expense_noi"] = {
    "months": months,
    "revenue": series(en, 10, 4, 22),
    "opex": series(en, 25, 4, 22),
    "noi": series(en, 27, 4, 22),
    "opex_ratio": series(en, 32, 4, 22),
    "noi_margin": series(en, 33, 4, 22),
    "controllable": series(en, 39, 4, 22),
    "non_controllable": series(en, 38, 4, 22),
    "ttm": {"revenue": cell(en, 10, 23), "opex": cell(en, 25, 23), "noi": cell(en, 27, 23),
            "operating_noi": cell(en, 29, 23), "opex_ratio": cell(en, 32, 23),
            "noi_margin": cell(en, 33, 23),
            "revenue_per_unit": cell(en, 43, 23), "opex_per_unit": cell(en, 44, 23),
            "noi_per_unit": cell(en, 45, 23)},
    "tax_note": ("April 2026 real estate tax true-up distorts that month; "
                 "TTM run-rate for taxes is ~172.5k/mo."),
}

# ---------------- expense deep dive ----------------
eo = wb["Expense Overview"]
data["expense_overview"] = {
    "period_note": cell(eo, 3, 2),
    "buckets": [dict(zip(
        ["name", "p2025", "p2026", "change", "ttm", "per_unit", "share", "status", "read"],
        r)) for r in rows(eo, 5, 15, [2, 3, 4, 5, 6, 7, 8, 9, 10])],
    "opportunities": [dict(zip(["name", "basis", "saving", "value", "difficulty"], r))
                      for r in rows(eo, 22, 28, [2, 3, 4, 5, 6])],
    "revenue_compare": [dict(zip(["name", "saving", "value"], r))
                        for r in rows(eo, 32, 36, [2, 4, 5])],
}

# ---------------- delinquency ----------------
dq = wb["Delinquency"]
det = []
for r in range(32, 84):
    u = cell(dq, r, 2)
    if u is None:
        continue
    owed = cell(dq, r, 4)
    if owed is None or owed <= 0:
        continue
    if str(u).upper().startswith("NONRES"):   # retail is summarised separately
        continue
    det.append({"unit": str(u), "resident": cell(dq, r, 3), "owed": owed,
                "d30": cell(dq, r, 5), "d60": cell(dq, r, 6),
                "d90": cell(dq, r, 7), "over90": cell(dq, r, 8)})
det.sort(key=lambda x: -x["owed"])
data["delinquency"] = {
    "as_of": "2026-07-20",
    "units_with_balance": cell(dq, 7, 3), "gross_owed": cell(dq, 8, 3),
    "credits": cell(dq, 9, 3), "net": cell(dq, 10, 3),
    "pct_month_rent": cell(dq, 11, 3), "occupied_units": cell(dq, 12, 3),
    "share_with_balance": cell(dq, 13, 3),
    "retail_balance": cell(dq, 16, 3), "retail_over90": cell(dq, 17, 3),
    "total_all": cell(dq, 19, 3),
    "aging": [dict(zip(["bucket", "amount", "pct_owed", "pct_rent", "status"], r))
              for r in rows(dq, 23, 26, [2, 3, 4, 5, 6])],
    "top": det[:12],
}

# ---------------- holdovers ----------------
ho = wb["Holdovers"]
data["holdovers"] = {
    "summary": {"units": cell(ho, 10, 3), "inplace_mo": cell(ho, 11, 3),
                "market_mo": cell(ho, 12, 3), "gap_mo": cell(ho, 13, 3),
                "gap_yr": cell(ho, 14, 3), "cohort_below_mkt": cell(ho, 15, 3),
                "property_below_mkt": cell(ho, 16, 3),
                "share_of_ltl": cell(ho, 19, 3), "share_of_units": cell(ho, 20, 3)},
    "distribution": [dict(zip(["band", "units", "gap_yr", "share", "flag"], r))
                     for r in rows(ho, 28, 33, [2, 3, 4, 5, 6])],
    "threshold_default": cell(ho, 38, 3),
    "units": [dict(zip(["rank", "unit", "type", "sqft", "inplace", "market", "gap_mo",
                        "gap_yr", "pct_below", "expired", "months_expired",
                        "inc_default"], r))
              for r in rows(ho, 93, 123, [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 16])],
    "workbook_reprice": {"increase_wtd": cell(ho, 68, 3), "recurring_noi": cell(ho, 74, 3),
                         "value": cell(ho, 86, 3)},
}

# ---------------- renewal pipeline ----------------
rp = wb["Renewal Pipeline"]
mo_rows = []
for r in range(17, 25):
    mo_rows.append({
        "month": str(cell(rp, r, 2))[:7], "inc": cell(rp, r, 3), "ret": cell(rp, r, 4),
        "expiring": cell(rp, r, 5), "on_notice": cell(rp, r, 6),
        "var_units": cell(rp, r, 7), "sqft": cell(rp, r, 8),
        "inplace_var": cell(rp, r, 9), "market_var": cell(rp, r, 10),
        "inplace_on": cell(rp, r, 11), "market_on": cell(rp, r, 12),
        "basis": cell(rp, r, 28),
    })
data["renewal"] = {
    "months": mo_rows,
    "ttm_operating_noi": cell(rp, 34, 3),
    "ftm_value": cell(rp, 45, 3),
    "workbook_rollup": {"incremental_yr": cell(rp, 31, 3), "recurring_noi": cell(rp, 33, 3),
                        "noi_uplift": cell(rp, 36, 3), "value_at_cap": cell(rp, 37, 3),
                        "one_time_costs": cell(rp, 43, 3), "net_value": cell(rp, 44, 3),
                        "total_value_at_sale": cell(rp, 46, 3)},
    "model_note": ("Recomputed live from unit level. One-time lease-up costs on months "
                   "with on-notice units are approximate (the workbook re-leases those at "
                   "unit-specific July market rents; variance is under 0.1% of net value)."),
}

# ---------------- unit-level gap data (powers renewal recompute + top gaps) ----------------
ug = wb["Unit Gap Analysis"]
units = []
for r in range(6, 340):
    u = cell(ug, r, 2)
    if u is None:
        continue
    units.append({"unit": str(u), "type": cell(ug, r, 3), "sqft": cell(ug, r, 4),
                  "market": cell(ug, r, 5), "inplace": cell(ug, r, 6),
                  "gap": cell(ug, r, 7), "gap_pct": cell(ug, r, 8),
                  "expiry_key": cell(ug, r, 12), "status": cell(ug, r, 13),
                  "market_assum": cell(ug, r, 21)})
data["units"] = units

# ---------------- rate vs occupancy ----------------
ro = wb["Rate vs Occupancy"]
data["rate_occ"] = {
    "market_rent_yr": cell(ro, 4, 3), "cur_ltl": cell(ro, 6, 3),
    "cur_vacancy": cell(ro, 7, 3), "inplace_yr": cell(ro, 9, 3),
    "target_occupancy": cell(ro, 10, 3), "breakeven_ltl": cell(ro, 13, 3),
    "scenario_ltl": cell(ro, 26, 3), "scenario_vac": cell(ro, 27, 3),
    "ttm_value_today": cell(ro, 37, 3),
    "grid_vac": [cell(ro, 17, c) for c in range(3, 8)],
    "grid_ltl": [cell(ro, r, 2) for r in range(18, 24)],
    "grid": [[cell(ro, r, c) for c in range(3, 8)] for r in range(18, 24)],
}

# ---------------- leasing / trade-outs ----------------
ld = wb["Lease Detail"]
leases = []
for r in range(5, 45):
    d = cell(ld, r, 2)
    if d is None:
        continue
    leases.append({"date": d, "unit": str(cell(ld, r, 3)), "sqft": cell(ld, r, 4),
                   "term": cell(ld, r, 5), "rent": cell(ld, r, 6), "psf": cell(ld, r, 7),
                   "prior": cell(ld, r, 8), "tradeout": cell(ld, r, 9),
                   "term_type": cell(ld, r, 11), "capture": cell(ld, r, 16),
                   "status": cell(ld, r, 17)})
data["leasing"] = {
    "leases": leases,
    "summary": {"executed": cell(ld, 47, 3), "wtd_psf": cell(ld, 50, 3),
                "wtd_tradeout": cell(ld, 55, 3), "avg_tradeout_exec": cell(ld, 57, 3),
                "below_prior": cell(ld, 58, 3), "capture_at_signing": cell(ld, 61, 3),
                "capture_vs_july": cell(ld, 63, 3)},
    "bands": [dict(zip(["band", "range", "leases", "sqft", "achieved_psf"], r))
              for r in rows(ld, 67, 70, [2, 3, 4, 5, 6])],
    "renewal_activity": {"renewals_signed": cell(ld, 77, 3), "new_signed": cell(ld, 78, 3),
                         "avg_increase": cell(ld, 80, 3), "leased_pct": cell(ld, 81, 3),
                         "spread_psf": cell(ld, 83, 3)},
}

# ---------------- floorplans + rollover ----------------
fp = wb["Floorplan & Rollover"]
data["floorplans"] = {
    "rows": [dict(zip(["plan", "units", "sqft", "avg_sqft", "market", "inplace",
                       "gap_mo", "gap_pct", "market_psf", "inplace_psf"], r))
             for r in rows(fp, 7, 47, [2, 3, 4, 5, 6, 7, 8, 9, 10, 11])],
    "total": dict(zip(["units", "sqft", "avg_sqft", "market", "inplace", "gap_mo",
                       "gap_pct", "market_psf", "inplace_psf"],
                      [cell(fp, 48, c) for c in [3, 4, 5, 6, 7, 8, 9, 10, 11]])),
}
data["rollover"] = [dict(zip(["month", "units", "pct", "sqft", "inplace", "market",
                              "uncaptured", "cum_units", "cum_pct"], r))
                    for r in rows(fp, 54, 70, [2, 3, 4, 5, 6, 7, 8, 9, 10])]

with open(OUT, "w") as f:
    json.dump(data, f, separators=(",", ":"))
print(f"wrote {OUT}")
import os
print("size:", os.path.getsize(OUT), "bytes")

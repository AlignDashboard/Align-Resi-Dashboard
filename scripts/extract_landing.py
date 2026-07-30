#!/usr/bin/env python3
"""Build docs/landing.json — data for The Landing's property view.

Reads the analyst workbook's computed output tabs. Those tabs are fed by the
grey "Source *" tabs, which are pasted from the Yardi/RealPage reports listed on
the workbook's own Data Lineage tab:

    Source CY25 / Aug25-Jul26  <- 12_Month_Statement_<code>_Accrual  (T12 Expenses)
    Source Rent Roll Jul / Jun <- SPV PM Deliverable Package, Rent Roll tab
    Source Delinquency         <- rs_rp_DelinquencySummaryReport
    Lease Detail               <- RealPage rental rate tracker (TYPED IN, not a grey tab)

To refresh: paste the new reports into the grey tabs, let Excel recalculate,
save, then run this script. It re-derives everything, so nothing is carried
over from the previous run.

Everything is located by label rather than by cell coordinate (see
xlsx_anchors.py), because row and column counts move every period — a month is
added, a lease is signed, a holdover is repriced. Validation runs at the end and
exits non-zero on anything that would put wrong numbers on the dashboard.

Usage:
  python scripts/extract_landing.py <workbook.xlsx> [--out docs/landing.json] [--allow-warnings]
"""
import argparse
import datetime
import json
import os
import sys

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xlsx_anchors import (LayoutError, block, cell, find_row, is_stale,  # noqa: E402
                          labelled_series, month_axis, norm, parse_month, scalar,
                          series)

ap = argparse.ArgumentParser()
ap.add_argument("workbook")
ap.add_argument("--out", default="docs/landing.json")
ap.add_argument("--allow-warnings", action="store_true",
                help="exit 0 even if soft checks fail (fatal checks still fail)")
args = ap.parse_args()

wb = openpyxl.load_workbook(args.workbook, data_only=True)

FATAL, WARN = [], []
def fatal(msg): FATAL.append(msg)
def warn(msg): WARN.append(msg)
def check(ok, msg, hard=True):
    if not ok:
        (fatal if hard else warn)(msg)
    return ok

REQUIRED_SHEETS = ["Inputs", "Rent Capture", "Expense & NOI", "Expense Overview",
                   "Delinquency", "Holdovers", "Renewal Pipeline", "Unit Gap Analysis",
                   "Rate vs Occupancy", "Lease Detail", "Floorplan & Rollover"]
missing_sheets = [s for s in REQUIRED_SHEETS if s not in wb.sheetnames]
if missing_sheets:
    print("FATAL: workbook is missing required tabs: " + ", ".join(missing_sheets),
          file=sys.stderr)
    sys.exit(2)

inp = wb["Inputs"]; rc = wb["Rent Capture"]; en = wb["Expense & NOI"]
eo = wb["Expense Overview"]; dq = wb["Delinquency"]; ho = wb["Holdovers"]
rp = wb["Renewal Pipeline"]; ug = wb["Unit Gap Analysis"]; ro = wb["Rate vs Occupancy"]
ld = wb["Lease Detail"]; fp = wb["Floorplan & Rollover"]

# ---- stale-workbook guard -------------------------------------------------
# If Excel has not recalculated, every formula reads None and the whole file
# would come out null. Fail here rather than publish that.
missing, total = is_stale(None, [
    (rc, "Total rental income (accrual basis)", 23),
    (en, "Total operating expense", 23),
    (ho, "Holdover units", 3),
    (inp, "Total units", 3),
])
if missing == total:
    print(f"FATAL: no cached formula results ({missing}/{total} probes empty). The "
          "workbook was saved without recalculating — open it in Excel, let it "
          "recalculate, save, and re-run.", file=sys.stderr)
    sys.exit(2)
check(missing == 0, f"{missing} of {total} probe cells are empty — the workbook may "
                    "be partially stale", hard=False)

data = {}

# ---- meta / inputs -------------------------------------------------------
UNITS = scalar(inp, "Total units")
data["meta"] = {
    "property": scalar(inp, "Property"),
    "units": UNITS,
    "rentable_sqft": scalar(inp, "Total rentable sq ft"),
    "rent_roll_as_of": scalar(inp, "Rent roll as-of date"),
    "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "source_workbook": os.path.basename(args.workbook),
    "source_reports": ["12-month accrual statement (T12)", "rent roll",
                       "delinquency summary", "RealPage rate tracker (typed in)"],
    "note": ("Derived from the analyst workbook, which is fed by the same Yardi/RealPage "
             "reports the Drive pipeline collects. Refresh by pasting new reports into "
             "the workbook's grey Source tabs, recalculating in Excel, and re-running "
             "scripts/extract_landing.py."),
}
data["inputs"] = {
    "target_econ_occupancy": scalar(inp, "Target economic occupancy"),
    "yardi_market_psf": scalar(inp, "Yardi market rent $/sqft (weighted)"),
    "inplace_psf": scalar(inp, "In-place rent $/sqft (weighted)"),
    "capture_rate": scalar(inp, "SELECTED capture rate - same unit, market at signing"),
    "turnover_cost_ttm": scalar(inp, "Turnover cost, TTM"),
    "mgmt_fee_pct": scalar(inp, "Management fee as % of revenue"),
    "make_ready_per_moveout": scalar(inp, "Direct make-ready cost per move-out"),
    "downtime_months": scalar(inp, "Downtime per move-out (months)"),
    "concession_per_lease": scalar(inp, "Concession per new lease ($)"),
    "leasing_cost_per_lease": scalar(inp, "Leasing and marketing cost per new lease ($)"),
    "cap_rate": scalar(rp, "Cap rate"),
}

# ---- rent capture --------------------------------------------------------
rc_hdr = find_row(rc, "Line item")
rc_pct_hdr = find_row(rc, "AS % OF MARKET RENT POTENTIAL")
months, rc_cols, rc_ttm = month_axis(rc, rc_hdr)
S = lambda label, **kw: labelled_series(rc, label, rc_cols, **kw)
data["rent_capture"] = {
    "months": months,
    "market_potential": S("Market rent potential (Yardi)"),
    "loss_to_lease": S("Loss to lease (positive = in-place below market)"),
    "vacancy_loss": [-(v or 0) for v in S("Vacancy loss", before=rc_pct_hdr)],
    "employee_allowance": [-(v or 0) for v in S("Employee rent allowance", before=rc_pct_hdr)],
    "concessions": [-(v or 0) for v in S("Rental concessions", before=rc_pct_hdr)],
    "rental_income": S("Total rental income (accrual basis)"),
    "ltl_pct": S("Loss to lease", after=rc_pct_hdr),
    "capture_rate": S("Rent capture rate (accrued income / potential, before credit loss)"),
    "econ_occupancy": S("Economic occupancy"),
    "ttm": {
        "market_potential": scalar(rc, "Market rent potential (Yardi)", value_col=rc_ttm),
        "rental_income": scalar(rc, "Total rental income (accrual basis)", value_col=rc_ttm),
        "capture_rate": scalar(rc, "Rent capture rate (accrued income / potential, before credit loss)", value_col=rc_ttm),
        "econ_occupancy": scalar(rc, "Economic occupancy", value_col=rc_ttm),
        "ltl_pct": scalar(rc, "Loss to lease", value_col=rc_ttm, after=rc_pct_hdr),
    },
}

# ---- expense & NOI ------------------------------------------------------
en_hdr = find_row(en, "Line item")
en_norm_hdr = find_row(en, "NORMALISED VIEW - April 2026 real estate tax true-up smoothed",
                       exact=False, required=False) or en.max_row
en_months, en_cols, en_ttm = month_axis(en, en_hdr)
E = lambda label, **kw: labelled_series(en, label, en_cols, **kw)
data["expense_noi"] = {
    "months": en_months,
    "revenue": E("Total revenue"),
    "opex": E("Total operating expense", before=en_norm_hdr),
    "noi": E("Net operating income"),
    "opex_ratio": E("Operating expense ratio", before=en_norm_hdr),
    "noi_margin": E("NOI margin", before=en_norm_hdr),
    "controllable": E("Controllable"),
    "non_controllable": E("Non-controllable (taxes, insurance, mgmt fee)"),
    "ttm": {
        "revenue": scalar(en, "Total revenue", value_col=en_ttm),
        "opex": scalar(en, "Total operating expense", value_col=en_ttm, before=en_norm_hdr),
        "noi": scalar(en, "Net operating income", value_col=en_ttm),
        "operating_noi": scalar(en, "Operating NOI (excl. interest income)", value_col=en_ttm),
        "opex_ratio": scalar(en, "Operating expense ratio", value_col=en_ttm, before=en_norm_hdr),
        "noi_margin": scalar(en, "NOI margin", value_col=en_ttm, before=en_norm_hdr),
        "revenue_per_unit": scalar(en, "Revenue per unit", value_col=en_ttm),
        "opex_per_unit": scalar(en, "Operating expense per unit", value_col=en_ttm),
        "noi_per_unit": scalar(en, "NOI per unit", value_col=en_ttm),
    },
    "tax_note": ("April 2026 real estate tax true-up distorts that month; "
                 "TTM run-rate for taxes is ~172.5k/mo."),
}

# ---- expense deep dive --------------------------------------------------
eo_hdr = find_row(eo, "Bucket")
data["expense_overview"] = {
    "period_note": cell(eo, find_row(eo, "Matching periods", exact=False), 2),
    "buckets": [dict(zip(["name", "p2025", "p2026", "change", "ttm", "per_unit",
                          "share", "status", "read"], r))
                for r in block(eo, eo_hdr, cols=range(2, 11))],
    "opportunities": [dict(zip(["name", "basis", "saving", "value", "difficulty"], r))
                      for r in block(eo, find_row(eo, "Opportunity"), cols=range(2, 7),
                                     stop_on_blank=False, max_rows=10,
                                     keep=lambda v: v[0] and v[2] is not None)],
    "revenue_compare": [dict(zip(["name", "saving", "value"], r))
                        for r in block(eo, find_row(eo, "For comparison - the revenue side",
                                                    exact=False),
                                       cols=[2, 4, 5], stop_on_blank=False, max_rows=8,
                                       # the last line carries a value but no annual
                                       # saving, so accept either
                                       keep=lambda v: v[0] and (v[1] is not None
                                                                or v[2] is not None))],
}

# ---- delinquency -------------------------------------------------------
def _dq_as_of():
    """Pull the snapshot date out of the tab's own intro sentence."""
    import re as _re
    txt = str(cell(dq, find_row(dq, "Resident balances", exact=False), 2) or "")
    m = _re.search(r"as of (\d{1,2}) (\w+) (\d{4})", txt)
    if not m:
        warn("delinquency as-of date not found in the tab's intro text")
        return None
    mon = ["january", "february", "march", "april", "may", "june", "july",
           "august", "september", "october", "november", "december"]
    return f"{m.group(3)}-{mon.index(m.group(2).lower()) + 1:02d}-{int(m.group(1)):02d}"

dq_aging_hdr = find_row(dq, "Bucket")
dq_detail_hdr = find_row(dq, "Unit")
# Resident names are deliberately NOT extracted. The published JSON sits on a
# public URL, and a surname next to a unit number and an amount past due is
# identifiable personal financial data. No chart needs it — the aging bars use
# amounts only — so the unit number alone identifies the row for anyone who
# needs to act on it. Column 3 (the name) is skipped in the column list below.
detail = block(dq, dq_detail_hdr, cols=[2, 4, 5, 6, 7, 8], stop_on_blank=False, max_rows=200,
               keep=lambda v: isinstance(v[1], (int, float)) and v[1] > 0
                              and not str(v[0]).upper().startswith("NONRES"))
detail.sort(key=lambda r: -r[1])
data["delinquency"] = {
    "as_of": _dq_as_of(),
    "units_with_balance": scalar(dq, "Units with a balance owed"),
    "gross_owed": scalar(dq, "Total owed (gross)"),
    "credits": scalar(dq, "Credits and prepayments"),
    "net": scalar(dq, "Net position"),
    "pct_month_rent": scalar(dq, "Total owed as % of one month rental income"),
    "occupied_units": scalar(dq, "Occupied units"),
    "share_with_balance": scalar(dq, "Share of residents carrying a balance"),
    "retail_balance": scalar(dq, "Retail balance outstanding"),
    "retail_over90": scalar(dq, "of which over 90 days", exact=False)
                     if find_row(dq, "of which over 90 days", exact=False, required=False) else None,
    "total_all": scalar(dq, "TOTAL DELINQUENCY - residential and retail"),
    "aging": [dict(zip(["bucket", "amount", "pct_owed", "pct_rent", "status"], r))
              for r in block(dq, dq_aging_hdr, cols=range(2, 7))],
    "top": [dict(zip(["unit", "owed", "d30", "d60", "d90", "over90"],
                     [str(r[0])] + r[1:])) for r in detail[:12]],
}

# ---- holdovers ---------------------------------------------------------
ho_dist_hdr = find_row(ho, "Gap versus market")
ho_unit_hdr = find_row(ho, "Rank")
ho_units = block(ho, ho_unit_hdr, cols=[2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 16],
                 keep=lambda v: isinstance(v[1], (int, float, str)) and v[3] is not None)
data["holdovers"] = {
    "summary": {"units": scalar(ho, "Holdover units"),
                "inplace_mo": scalar(ho, "Their in-place rent, monthly"),
                "market_mo": scalar(ho, "Their market rent, monthly"),
                "gap_mo": scalar(ho, "Gap, monthly"),
                "gap_yr": scalar(ho, "Gap, annualised"),
                "cohort_below_mkt": scalar(ho, "Cohort is below market by"),
                "property_below_mkt": scalar(ho, "Whole property is below market by"),
                "share_of_ltl": scalar(ho, "Share of the total loss to lease they represent"),
                "share_of_units": scalar(ho, "Share of total units at the property")},
    "distribution": [dict(zip(["band", "units", "gap_yr", "share", "flag"], r))
                     for r in block(ho, ho_dist_hdr, cols=range(2, 7))],
    "threshold_default": scalar(ho, "Minimum gap % to include"),
    "units": [dict(zip(["rank", "unit", "type", "sqft", "inplace", "market", "gap_mo",
                        "gap_yr", "pct_below", "expired", "months_expired", "inc_default"],
                       [r[0], str(r[1])] + r[2:])) for r in ho_units],
    "workbook_reprice": {
        "increase_wtd": scalar(ho, "Weighted average rent increase applied"),
        "recurring_noi": scalar(ho, "Recurring additional NOI"),
        "value": scalar(ho, "NET VALUE AT SALE")},
}

# ---- renewal pipeline --------------------------------------------------
rp_hdr = find_row(rp, "Month")
rp_rows = block(rp, rp_hdr, cols=list(range(2, 15)) + [28],
                keep=lambda v: parse_month(v[0]) is not None)
data["renewal"] = {
    "months": [{"month": parse_month(r[0]), "inc": r[1], "ret": r[2], "expiring": r[3],
                "on_notice": r[4], "var_units": r[5], "sqft": r[6], "inplace_var": r[7],
                "market_var": r[8], "inplace_on": r[9], "market_on": r[10],
                "basis": r[13]} for r in rp_rows],
    "ttm_operating_noi": scalar(rp, "TTM operating NOI (ex-interest)"),
    "ftm_value": scalar(rp, "FTM Value (July (adj) NOI x 12 / 5% cap rate)", required=False),
    "workbook_rollup": {
        "incremental_yr": scalar(rp, "Incremental rent, annualised"),
        "recurring_noi": scalar(rp, "Recurring change in NOI"),
        "noi_uplift": scalar(rp, "NOI uplift %"),
        "value_at_cap": scalar(rp, "Value of the recurring NOI change at the cap rate"),
        "one_time_costs": scalar(rp, "Less: total one-time lease-up costs (not capitalised)"),
        "net_value": scalar(rp, "Net additional value at sale"),
        "total_value_at_sale": scalar(rp, "Total Value at Sale", required=False)},
    "model_note": ("Recomputed live from unit level. One-time lease-up costs on months "
                   "with on-notice units are approximate (the workbook re-leases those at "
                   "unit-specific July market rents; variance is under 0.1% of net value)."),
}

# ---- unit-level gap data ----------------------------------------------
ug_hdr = find_row(ug, "Unit")
ug_rows = block(ug, ug_hdr, cols=[2, 3, 4, 5, 6, 7, 8, 12, 13, 21],
                stop_on_blank=False, max_rows=600,
                # a real unit has a numeric size and market rent; the summary
                # blocks further down the sheet put labels in the same column
                keep=lambda v: isinstance(v[2], (int, float)) and v[2]
                               and isinstance(v[3], (int, float)) and v[3])
data["units"] = [{"unit": str(r[0]), "type": r[1], "sqft": r[2], "market": r[3],
                  "inplace": r[4], "gap": r[5], "gap_pct": r[6], "expiry_key": r[7],
                  "status": r[8], "market_assum": r[9]} for r in ug_rows]

# ---- rate vs occupancy ------------------------------------------------
ro_grid_hdr = find_row(ro, "Loss to lease", after=find_row(ro, "SCENARIO GRID", exact=False))
grid_vac_cols = [c for c in range(3, ro.max_column + 1)
                 if isinstance(cell(ro, ro_grid_hdr, c), (int, float))]
grid_rows = block(ro, ro_grid_hdr, cols=[2] + grid_vac_cols,
                  keep=lambda v: isinstance(v[0], (int, float)))
data["rate_occ"] = {
    "market_rent_yr": scalar(ro, "Market rent, annualised (rent roll 14 Jul 2026)", exact=False),
    "cur_ltl": scalar(ro, "Current loss to lease"),
    "cur_vacancy": scalar(ro, "Current vacancy (market rent on vacant units)"),
    "inplace_yr": scalar(ro, "Current in-place rent, annualised"),
    "target_occupancy": scalar(ro, "Target economic occupancy"),
    "breakeven_ltl": scalar(ro, "Loss to lease required to break even"),
    "scenario_ltl": scalar(ro, "Scenario: loss to lease narrows to"),
    "scenario_vac": scalar(ro, "Scenario: economic vacancy rises to"),
    "ttm_value_today": scalar(ro, "TTM Value Today"),
    "grid_vac": [cell(ro, ro_grid_hdr, c) for c in grid_vac_cols],
    "grid_ltl": [r[0] for r in grid_rows],
    "grid": [r[1:] for r in grid_rows],
}

# ---- leasing / trade-outs ---------------------------------------------
ld_hdr = find_row(ld, "Lease date")
ld_rows = block(ld, ld_hdr, cols=[2, 3, 4, 5, 6, 7, 8, 9, 11, 16, 17],
                keep=lambda v: v[0] is not None and str(v[0])[:4].isdigit())
band_hdr = find_row(ld, "Band")
data["leasing"] = {
    "leases": [{"date": r[0], "unit": str(r[1]), "sqft": r[2], "term": r[3], "rent": r[4],
                "psf": r[5], "prior": r[6], "tradeout": r[7], "term_type": r[8],
                "capture": r[9], "status": r[10]} for r in ld_rows],
    "summary": {
        "executed": scalar(ld, "Leases (executed)"),
        "wtd_psf": scalar(ld, "Weighted $/sqft - all leases"),
        "wtd_tradeout": scalar(ld, "Dollar-weighted trade-out"),
        # this label appears twice (psf block and trade-out block) — scope it
        "avg_tradeout_exec": scalar(ld, "executed leases only",
                                    after=find_row(ld, "Dollar-weighted trade-out")),
        "below_prior": scalar(ld, "Leases below prior rent"),
        "capture_at_signing": scalar(ld, "CAPTURE RATE - same unit, market at signing", exact=False),
        "capture_vs_july": scalar(ld, "same unit vs July market only", exact=False)},
    "bands": [dict(zip(["band", "range", "leases", "sqft", "achieved_psf"], r))
              for r in block(ld, band_hdr, cols=range(2, 7),
                             keep=lambda v: isinstance(v[0], (int, float)))],
    "renewal_activity": {
        "renewals_signed": scalar(ld, "Renewals signed"),
        "new_signed": scalar(ld, "New leases signed"),
        "avg_increase": scalar(ld, "Average renewal increase"),
        "leased_pct": scalar(ld, "Leased %"),
        "spread_psf": scalar(ld, "Spread - new lease less renewal ($/sqft)")},
}

# ---- floorplans + rollover -------------------------------------------
fp_hdr = find_row(fp, "Floorplan")
fp_rows = block(fp, fp_hdr, cols=range(2, 12), keep=lambda v: isinstance(v[1], (int, float)))
fp_total_row = find_row(fp, "Total", after=fp_hdr)
roll_hdr = find_row(fp, "Month", after=find_row(fp, "ROLLOVER SCHEDULE", exact=False))
data["floorplans"] = {
    "rows": [dict(zip(["plan", "units", "sqft", "avg_sqft", "market", "inplace",
                       "gap_mo", "gap_pct", "market_psf", "inplace_psf"], r))
             for r in fp_rows],
    "total": dict(zip(["units", "sqft", "avg_sqft", "market", "inplace", "gap_mo",
                       "gap_pct", "market_psf", "inplace_psf"],
                      [cell(fp, fp_total_row, c) for c in range(3, 12)])),
}
data["rollover"] = [dict(zip(["month", "units", "pct", "sqft", "inplace", "market",
                              "uncaptured", "cum_units", "cum_pct"], r))
                    for r in block(fp, roll_hdr, cols=range(2, 11),
                                   keep=lambda v: isinstance(v[1], (int, float)))]

# =========================== VALIDATION ===============================
# Each check guards a way the extraction could go quietly wrong.
V = []
def record(name, ok, detail, hard=True):
    V.append((name, ok, detail))
    check(ok, f"{name}: {detail}", hard=hard)

record("month axis aligned",
       data["rent_capture"]["months"] == data["expense_noi"]["months"],
       f"Rent Capture has {len(months)} months ending {months[-1]}, "
       f"Expense & NOI has {len(en_months)} ending {en_months[-1]}")

record("month count sane", len(months) >= 12,
       f"{len(months)} month columns found (expected 12 or more)")

n_units = len(data["units"])
record("unit count matches Inputs", n_units == UNITS,
       f"{n_units} unit rows read, Inputs says {UNITS} total units")

record("no summary rows in units",
       all(u["sqft"] and u["market"] for u in data["units"]),
       "every unit row has a numeric sq ft and market rent")

tie_rc = labelled_series(rc, "Check vs statement (should be nil)", rc_cols)
tie_rev = labelled_series(en, "Check vs statement (should be nil)", en_cols,
                          before=find_row(en, "OPERATING EXPENSES"))
tie_opex = labelled_series(en, "Check vs statement (should be nil)", en_cols,
                           after=find_row(en, "OPERATING EXPENSES"))
worst_tie = max(abs(v or 0) for v in tie_rc + tie_rev + tie_opex)
record("statement tie-outs nil", worst_tie < 1,
       f"largest tie-out variance is {worst_tie:.2f} (must be under 1.00)")

hd = data["holdovers"]
record("holdover rows match summary", len(hd["units"]) == hd["summary"]["units"],
       f"{len(hd['units'])} holdover rows read, summary says {hd['summary']['units']}")

record("no Total row in holdovers",
       all(norm(u["unit"]) != "total" for u in hd["units"]),
       "no 'Total' row leaked into the holdover unit list")

dist_total = sum(d["gap_yr"] or 0 for d in hd["distribution"])
record("holdover distribution ties to gap",
       abs(dist_total - (hd["summary"]["gap_yr"] or 0)) < 1,
       f"distribution sums to {dist_total:,.0f} vs summary gap {hd['summary']['gap_yr']:,.0f}")

fpt = data["floorplans"]["total"]
record("floorplan total matches Inputs", fpt["units"] == UNITS,
       f"floorplan total is {fpt['units']} units, Inputs says {UNITS}")
record("floorplan rows sum to total",
       sum(r["units"] or 0 for r in data["floorplans"]["rows"]) == fpt["units"],
       f"{len(data['floorplans']['rows'])} floorplan rows sum to "
       f"{sum(r['units'] or 0 for r in data['floorplans']['rows'])} vs total {fpt['units']}")

ag = sum(a["amount"] or 0 for a in data["delinquency"]["aging"])
record("delinquency aging ties to gross",
       abs(ag - (data["delinquency"]["gross_owed"] or 0)) < 1,
       f"aging buckets sum to {ag:,.2f} vs gross owed {data['delinquency']['gross_owed']:,.2f}")

ex = [l for l in data["leasing"]["leases"] if l["status"] == "Executed"]
record("executed lease count matches summary",
       len(ex) == data["leasing"]["summary"]["executed"],
       f"{len(ex)} executed leases read, summary says {data['leasing']['summary']['executed']}")

# The renewal card recomputes from unit level; if no units match a month's
# expiry key the card would silently show zero incremental rent.
by_key = {}
for u in data["units"]:
    if u["status"] == "Current":
        by_key.setdefault(u["expiry_key"], []).append(u)
empty_months = [m["month"] for m in data["renewal"]["months"]
                if not by_key.get(int(m["month"].replace("-", "")))]
record("renewal months resolve to units", not empty_months,
       "no units matched expiry months " + ", ".join(empty_months) if empty_months
       else f"all {len(data['renewal']['months'])} months matched unit rows")

# Reproduce the workbook's own roll-up from the unit-level data we emit.
mgmt = data["inputs"]["mgmt_fee_pct"]
incr = 0.0
for m in data["renewal"]["months"]:
    key = int(m["month"].replace("-", ""))
    capped = sum(min(u["inplace"] * (1 + m["inc"]), u["market_assum"])
                 for u in by_key.get(key, []))
    new = capped * m["ret"] + m["market_var"] * (1 - m["ret"]) + m["market_on"]
    incr += (new - (m["inplace_var"] + m["inplace_on"])) * 12
wb_incr = data["renewal"]["workbook_rollup"]["incremental_yr"] or 0
record("renewal model reproduces workbook",
       abs(incr - wb_incr) < max(1000, abs(wb_incr) * 0.002),
       f"recomputed incremental rent {incr:,.0f} vs workbook {wb_incr:,.0f}")

nulls = [k for k, v in data["inputs"].items() if v is None]
record("all inputs resolved", not nulls,
       "inputs with no value: " + ", ".join(nulls) if nulls else "all inputs found",
       hard=False)

# ---- report --------------------------------------------------------------
print(f"{'check':38} result")
print("-" * 78)
for name, ok, detail in V:
    print(f"{name:38} {'PASS' if ok else 'FAIL'}  {detail}")

if FATAL:
    print("\nFATAL — not writing " + args.out, file=sys.stderr)
    for m in FATAL:
        print("  * " + m, file=sys.stderr)
    print("\nThe workbook layout moved in a way that would put wrong numbers on the "
          "dashboard. Fix the workbook or update the anchors in this script.",
          file=sys.stderr)
    sys.exit(1)

with open(args.out, "w") as f:
    json.dump(data, f, separators=(",", ":"))

print(f"\nwrote {args.out} ({os.path.getsize(args.out)} bytes)")
print(f"  {len(data['units'])} units · {len(months)} months ({months[0]}..{months[-1]}) "
      f"· {len(data['holdovers']['units'])} holdovers · {len(ex)} executed leases "
      f"· {len(data['rollover'])} rollover rows")
if WARN:
    print("\nwarnings:")
    for m in WARN:
        print("  ! " + m)
    if not args.allow_warnings:
        sys.exit(3)

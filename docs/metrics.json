"""
build_metrics.py
----------------
Runs after fetch_drive.py. For every downloaded file in _downloads/manifest.json:
  1. runs the file's parser
  2. routes the result to a property (via property code -> config/properties.json)
  3. appends to that property's per-metric history in data/  (keyed by period,
     so re-processing the same statement overwrites rather than duplicates)
Then regenerates docs/metrics.json from the accumulated history in data/.

If no manifest exists (e.g. running locally without Drive), it will just
rebuild docs/metrics.json from whatever is already in data/.

The history store in data/ IS the database -- versioned in git, no external DB.
"""

import os
import json
import glob
import importlib
import pathlib
import sys

sys.path.insert(0, os.path.dirname(__file__))

DATA = pathlib.Path("data")
DOCS = pathlib.Path("docs")


# ---- config helpers -------------------------------------------------------

def load_properties():
    cfg = json.load(open("config/properties.json"))
    code_to_prop = {}
    for p in cfg["properties"]:
        for c in p["codes"]:
            # normalize codes to lowercase for matching robustness
            code_to_prop[c.lower()] = p
    return cfg["properties"], code_to_prop


# ---- period ordering ------------------------------------------------------

_MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

def period_key(label):
    # "Jun 2026" -> sortable (2026, 6)
    try:
        mon, yr = label.split()
        return (int(yr), _MON.index(mon) + 1)
    except Exception:
        return (0, 0)


# ---- accumulation ---------------------------------------------------------

def store_expense_ratio(prop, parsed):
    """Append/replace one rolling-T12 point for this property, keyed by period_end."""
    d = DATA / prop["slug"]
    d.mkdir(parents=True, exist_ok=True)
    fp = d / "expense_ratio.json"
    hist = json.load(open(fp)) if fp.exists() else {"points": []}

    point = {
        "period_end": parsed["period_end"],
        "ratio_t12": parsed["expense_ratio_t12"],
        "revenue_t12": parsed["revenue_t12"],
        "opex_recoverable_t12": parsed["opex_recoverable_t12"],
        # keep the latest statement's monthly detail too
        "labels": parsed["labels"],
        "monthly_ratio": parsed["expense_ratio_monthly"],
    }
    # replace if same period already stored, else append
    hist["points"] = [p for p in hist["points"]
                      if p["period_end"] != point["period_end"]]
    hist["points"].append(point)
    hist["points"].sort(key=lambda p: period_key(p["period_end"]))
    json.dump(hist, open(fp, "w"), indent=2)
    return hist


def process_manifest():
    mpath = pathlib.Path("_downloads/manifest.json")
    if not mpath.exists():
        print("[info] no manifest; rebuilding metrics from existing data/ only")
        return
    manifest = json.load(open(mpath))
    _, code_to_prop = load_properties()

    for item in manifest:
        if item["report_type"] != "t12_statement":
            print(f"[skip] {item['name']} (no accumulator for {item['report_type']} yet)")
            continue
        mod = importlib.import_module(item["parser"])
        parsed = mod.parse_t12(item["path"])
        code = parsed.get("property_code")
        prop = code_to_prop.get(code.lower()) if code else None
        if not prop:
            print(f"[warn] unknown property code '{code}' in {item['name']} -- "
                  f"add it to config/properties.json; skipping")
            continue
        if not prop.get("active", True):
            print(f"[skip] {prop['name']} is inactive (code '{code}'); "
                  f"stored to history but not shown on dashboard")
        store_expense_ratio(prop, parsed)
        print(f"[ok] stored expense_ratio for {prop['name']} ({parsed['period_end']})")


# ---- metrics.json generation ---------------------------------------------

def build_metrics_json():
    props, _ = load_properties()

    # Assemble per-property expense_ratio series from history (active only)
    expense_ratio_props = []
    for p in props:
        if not p.get("active", True):
            continue
        fp = DATA / p["slug"] / "expense_ratio.json"
        if not fp.exists():
            continue
        hist = json.load(open(fp))
        pts = hist["points"]
        if not pts:
            continue
        latest = pts[-1]
        expense_ratio_props.append({
            "slug": p["slug"],
            "name": p["name"],
            "ratio_t12": latest["ratio_t12"],
            "trend_labels": [pt["period_end"] for pt in pts],
            "trend_values": [pt["ratio_t12"] for pt in pts],
            "latest_monthly_labels": latest["labels"],
            "latest_monthly_ratio": latest["monthly_ratio"],
        })

    # Load existing metrics.json to preserve the other (manual/demo) blocks
    mpath = DOCS / "metrics.json"
    metrics = json.load(open(mpath)) if mpath.exists() else {}

    if expense_ratio_props:
        metrics["expense_ratio"] = {
            "available": True,
            "basis": "Recoverable Opex \u00f7 Operating Revenue (T12)",
            "properties": expense_ratio_props,
            "footnote": "Rolling T12 expense ratio per property; one point per monthly "
                        "statement. Monthly ratios within a statement are volatile on an "
                        "accrual basis \u2014 the T12 figure is the reliable KPI.",
        }
    else:
        # No property history found. Leave any existing expense_ratio block
        # untouched rather than wiping it with an empty one.
        print("[info] no property history yet; leaving existing metrics.json expense_ratio as-is")

    from datetime import datetime, timezone
    metrics.setdefault("meta", {})["generated_at"] = datetime.now(timezone.utc).isoformat()

    json.dump(metrics, open(mpath, "w"), indent=2)
    print(f"[ok] wrote {mpath} with expense_ratio for "
          f"{len(expense_ratio_props)} propert(ies)")


if __name__ == "__main__":
    process_manifest()
    build_metrics_json()

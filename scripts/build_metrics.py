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


def store_monthly_revenue(prop, t12_parses):
    """data/<slug>/monthly_revenue.json — the latest month's total operating
    revenue, summed across this property's codes (Palma = rspalman + rspalmas).

    This exists to give ratio KPIs a denominator: the scorecard's Total
    Deliquency is gross resident AR over one month's billed rent, and a
    delinquency report does not carry the rent. The nearest thing the pipeline
    holds is GL 4999-9999, which is total operating revenue rather than billed
    rent alone — close, and honest as long as the basis is recorded.

    Per code, only the statement with the latest period end counts (the Drive
    folder often holds superseded copies of the same statement).
    """
    latest = {}                          # code -> parse with the newest period
    for p in t12_parses:
        c = p["property_code"]
        if c not in latest or period_key(p["period_end"]) > period_key(latest[c]["period_end"]):
            latest[c] = p
    codes = {}
    for c, p in sorted(latest.items()):
        # last month with a non-zero value; a statement can end on an empty month
        rev = p["revenue_monthly"]
        idx = max((i for i, v in enumerate(rev) if v), default=None)
        if idx is None:
            continue
        codes[c] = {"month": p["labels"][idx], "revenue": rev[idx],
                    "period_end": p["period_end"]}
    out = {
        "revenue_month": round(sum(v["revenue"] for v in codes.values()), 2),
        "basis": "GL 4999-9999 total operating revenue, latest reported month per code",
        "codes": codes,
    }
    d = DATA / prop["slug"]
    d.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(d / "monthly_revenue.json", "w"), indent=2)
    print(f"[ok] stored monthly_revenue for {prop['name']}: "
          f"{out['revenue_month']:,.2f}/mo across {'+'.join(codes) or 'no codes'}")
    return out


# Personal fields stripped from every report before anything is written to
# disk. Parsers read them because the source reports contain them (the rent roll
# needs resident_code to tell an occupied unit from a vacant one), but nothing
# persists them. Scrubbing here rather than per-report means a new parser is
# covered by default instead of by remembering.
PII_FIELDS = ("resident_name", "resident_code", "resident", "tenant_name",
              "tenant", "name")


def scrub(obj):
    """Recursively drop PII keys from dicts and lists."""
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items() if k not in PII_FIELDS}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    return obj


def store_report(prop, parsed, filename, keys):
    """Write the latest parse of a report to data/<slug>/<filename>.

    One file per property per report, overwritten each run: these reports are
    point-in-time snapshots, not a series, so history lives in git rather than
    inside the file. PII is stripped on the way out — see PII_FIELDS.
    """
    d = DATA / prop["slug"]
    d.mkdir(parents=True, exist_ok=True)
    fp = d / filename
    out = {k: scrub(parsed.get(k)) for k in keys}
    out["source_file"] = parsed.get("source_file")
    # When the file landed in Drive, set by process_manifest from the manifest.
    # This is the dashboard's "data last updated" for a Drive-fed report, and is
    # deliberately separate from as_of, the period the report covers. Absent for
    # a report parsed from a local path rather than pulled from Drive.
    out["landed_at"] = parsed.get("landed_at")
    out["checks"] = parsed.get("checks")
    json.dump(out, open(fp, "w"), indent=2, default=str)
    return fp


def store_rent_roll(prop, parsed):
    return store_report(prop, parsed, "rent_roll.json",
                        ["report_type", "property", "property_code", "as_of",
                         "totals", "units"])


def store_delinquency(prop, parsed):
    return store_report(prop, parsed, "delinquency.json",
                        ["report_type", "property", "property_code", "as_of",
                         "summary", "residents"])


# report_type -> what to do with a successful parse
ACCUMULATORS = {
    "t12_statement": None,          # handled inline (needs the book/period checks)
    "rent_roll": store_rent_roll,
    "ar_analytics": store_delinquency,
}


def process_manifest():
    mpath = pathlib.Path("_downloads/manifest.json")
    if not mpath.exists():
        print("[info] no manifest; rebuilding metrics from existing data/ only")
        return
    manifest = json.load(open(mpath))
    _, code_to_prop = load_properties()

    # Deterministic order: sort by filename so date-prefixed files process
    # oldest-to-newest and the newest file wins any same-period collision.
    manifest.sort(key=lambda x: x["name"])

    t12_by_slug = {}                 # slug -> (prop, [t12 parse, ...])

    for item in manifest:
        if item["report_type"] not in ACCUMULATORS:
            print(f"[skip] {item['name']} (no accumulator for {item['report_type']} yet)")
            continue
        try:
            mod = importlib.import_module(item["parser"])
            # every parser exposes parse(path); parse_t12 kept as an alias
            parsed = (mod.parse if hasattr(mod, "parse") else mod.parse_t12)(item["path"])
        except Exception as e:
            print(f"[error] failed to parse {item['name']}: {e} -- skipping this file")
            continue

        # carry Drive's arrival time onto the parse, so store_report can record
        # when the report landed rather than only what period it covers. Set
        # before the multi-section split below, which copies the parse.
        parsed["landed_at"] = item.get("landed_at")

        if item["report_type"] != "t12_statement":
            # One export can cover several property codes (Palma arrives as
            # rspalman + rspalmas). Group the sections by the property they
            # resolve to, so each property gets one record built from its own
            # rows rather than the file's combined total.
            groups = {}                      # slug -> (prop, [section, ...])
            for sec in parsed.get("sections") or []:
                c = (sec.get("property_code") or "").lower()
                p = code_to_prop.get(c)
                if not p:
                    print(f"[warn] unknown property code '{sec.get('property_code')}' "
                          f"in {item['name']} -- add it to config/properties.json; "
                          f"that section is skipped")
                    continue
                groups.setdefault(p["slug"], (p, []))[1].append(sec)

            if not groups:
                # no sections (an older single-property parser shape)
                code = parsed.get("property_code")
                prop = code_to_prop.get(code.lower()) if code else None
                if not prop:
                    print(f"[warn] unknown property code '{code}' in {item['name']} -- "
                          f"add it to config/properties.json; skipping")
                    continue
                ACCUMULATORS[item["report_type"]](prop, parsed)
                print(f"[ok] stored {item['report_type']} for {prop['name']} "
                      f"(as of {parsed.get('as_of') or 'unknown date'})")
                continue

            for slug, (prop, secs) in groups.items():
                rows = [r for s in secs for r in (s.get("residents") or [])]
                one = dict(parsed)
                one["property"] = prop["name"]
                one["property_code"] = secs[0].get("property_code")
                one["property_codes"] = [s.get("property_code") for s in secs]
                one["residents"] = rows
                one["sections"] = [{k: v for k, v in s.items() if k != "residents"}
                                   for s in secs]
                if len(secs) > 1 and hasattr(mod, "summarise"):
                    one["summary"] = mod.summarise(rows)
                elif len(secs) == 1:
                    one["summary"] = secs[0].get("summary") or parsed.get("summary")
                ACCUMULATORS[item["report_type"]](prop, one)
                codes = "+".join(c for c in one["property_codes"] if c)
                print(f"[ok] stored {item['report_type']} for {prop['name']} "
                      f"from {codes} (as of {parsed.get('as_of') or 'unknown date'})")
            continue

        book = (parsed.get("book") or "").strip().lower()
        if book and book != "accrual":
            print(f"[skip] {item['name']} is book '{parsed.get('book')}' -- "
                  f"only Accrual statements feed the dashboard")
            continue

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
        print(f"[ok] stored expense_ratio for {prop['name']} ({parsed['period_end']}) "
              f"from code '{code}'")
        t12_by_slug.setdefault(prop["slug"], (prop, []))[1].append(parsed)

    # One month's operating revenue per property, for the ratio KPIs.
    for slug, (prop, parses) in t12_by_slug.items():
        store_monthly_revenue(prop, parses)


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

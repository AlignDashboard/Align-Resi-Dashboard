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
        # aliases are the names third-party exports use where Yardi would use a
        # code ("335 3rd Street"); both route the same way
        for c in list(p["codes"]) + list(p.get("aliases") or []):
            # normalize to lowercase for matching robustness
            code_to_prop[c.lower()] = p
    return cfg["properties"], code_to_prop


def quarantined(prop, report_type, period_end=None):
    """True when a property's source for this report type is known to be wrong.

    A report that reaches the pipeline is normally trusted -- the parsers tie
    out against the report's own totals, which catches a misread file but not a
    file that is internally consistent and about the wrong building. That is a
    judgement about provenance, so it is recorded in config/properties.json with
    its reason rather than inferred here, and the affected figures are dropped
    instead of published while the source is corrected.

    "through_period" scopes it: a statement whose period ends AFTER that month
    flows normally. This is how a brand-new property whose only statement is
    dummy data starts publishing by itself the day a real statement lands,
    instead of waiting for someone to remember to lift the block.
    """
    q = prop.get("quarantine") or {}
    if report_type not in (q.get("report_types") or []):
        return False
    through = q.get("through_period")
    if through and period_end and period_key(period_end) > period_key(through):
        return False
    return True


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

def latest_per_code(t12_parses):
    """One statement per building code. The Drive folder often holds superseded
    copies of the same statement, so keep the newest period per code, and on a
    tie the last one processed -- the manifest is filename-sorted, so that is
    the newest copy of a period the folder holds more than once.
    """
    latest = {}
    for p in t12_parses:
        c = p["property_code"]
        if (c not in latest
                or period_key(p["period_end"]) >= period_key(latest[c]["period_end"])):
            latest[c] = p
    return latest


def store_expense_ratio(prop, t12_parses):
    """Append/replace this property's rolling-T12 points, keyed by period_end.

    A property can report under several building codes (Palma = rspalman +
    rspalmas). The ratio describes the property, so the codes are summed before
    it is taken. Storing one code's statement as the property's point published
    a single building as if it were the whole: Palma's ratio read 127.3% off
    Palma South alone, whose lease-up revenue is near zero, while Palma North
    was billing $264k that month and was not in the figure at all.
    """
    # Grouped by period, so codes are only ever summed with each other when
    # they cover the same twelve months. Codes reporting different periods
    # yield a point each rather than nothing -- "source_codes" is then what
    # shows the point speaks for part of the property.
    by_period = {}
    for code, p in sorted(latest_per_code(t12_parses).items()):
        by_period.setdefault(p["period_end"], []).append((code, p))

    d = DATA / prop["slug"]
    d.mkdir(parents=True, exist_ok=True)
    fp = d / "expense_ratio.json"
    hist = json.load(open(fp)) if fp.exists() else {"points": []}

    for period_end, group in by_period.items():
        codes = sorted({c2 for c, p in group for c2 in (p.get("property_codes") or [c])})
        rev_t12 = sum(p["revenue_t12"] for _, p in group)
        opex_t12 = sum(p["opex_recoverable_t12"] for _, p in group)

        # The monthly detail sums position by position, so the month columns
        # have to line up. They do for one period end; if that ever stops
        # holding, say so and publish the leading code's detail unsummed rather
        # than adding March to April.
        labels = group[0][1]["labels"]
        mismatched = next((c for c, p in group[1:] if p["labels"] != labels), None)
        if mismatched:
            print(f"[warn] {prop['name']} {period_end}: code '{mismatched}' has "
                  f"different month labels than '{codes[0]}' -- monthly detail "
                  f"is from '{codes[0]}' alone for this period")
            monthly = group[0][1]["expense_ratio_monthly"]
        else:
            rev_m = [sum(p["revenue_monthly"][i] for _, p in group) for i in range(12)]
            opex_m = [sum(p["opex_recoverable_monthly"][i] for _, p in group)
                      for i in range(12)]
            monthly = [round(100 * opex_m[i] / rev_m[i], 1) if rev_m[i] else None
                       for i in range(12)]

        point = {
            "period_end": period_end,
            "ratio_t12": round(100 * opex_t12 / rev_t12, 1) if rev_t12 else None,
            "revenue_t12": round(rev_t12, 2),
            "opex_recoverable_t12": round(opex_t12, 2),
            # Which building codes the point was built from. Without this a
            # point cannot be told apart from one stored against the wrong
            # property, which is how a statement for 335 Third sat in Palma's
            # series as an "Apr 2026" point until the figures were compared.
            "source_codes": codes,
            "labels": labels,
            "monthly_ratio": monthly,
        }
        # replace if same period already stored, else append
        hist["points"] = [p for p in hist["points"] if p["period_end"] != period_end]
        hist["points"].append(point)
        print(f"[ok] stored expense_ratio for {prop['name']} ({period_end}) "
              f"from {'+'.join(codes)}")

    hist["points"].sort(key=lambda p: period_key(p["period_end"]))
    json.dump(hist, open(fp, "w"), indent=2)
    return hist


def store_expense_buckets(prop, t12_parses):
    """data/<slug>/expense_buckets.json — monthly expense dollars by bucket,
    classified from the statement's GL detail (see parse_t12_statement), summed
    across the property's codes per period like the ratio is. Aggregates only;
    a GL account label is not personal data.

    A parse whose buckets were refused (tie-out failure) is skipped loudly and
    the ratio still stores — the two must not share a fate.
    """
    by_period = {}
    for code, pr in sorted(latest_per_code(t12_parses).items()):
        if not pr.get("expense_buckets"):
            if pr.get("expense_buckets_error"):
                print(f"[warn] {prop['name']} {pr.get('period_end')} code '{code}': "
                      f"expense buckets refused -- {pr['expense_buckets_error']}")
            continue
        by_period.setdefault(pr["period_end"], []).append((code, pr))
    if not by_period:
        return None

    d = DATA / prop["slug"]
    d.mkdir(parents=True, exist_ok=True)
    fp = d / "expense_buckets.json"
    hist = json.load(open(fp)) if fp.exists() else {"points": []}

    for period_end, group in by_period.items():
        codes = sorted({c2 for c, pr in group for c2 in (pr.get("property_codes") or [c])})
        labels = group[0][1]["labels"]
        if any(pr["labels"] != labels for _, pr in group[1:]):
            print(f"[warn] {prop['name']} {period_end}: month labels differ across "
                  f"codes -- buckets from '{codes[0]}' alone for this period")
            group = group[:1]
        merged, others = {}, []
        for _, pr in group:
            eb = pr["expense_buckets"]
            for name, vals in eb["buckets"].items():
                tgt = merged.setdefault(name, [0.0] * 12)
                for i, v in enumerate(vals):
                    tgt[i] += v
            others.extend(l for l in eb.get("other_labels", []) if l not in others)
        if others:
            print(f"[note] {prop['name']} {period_end}: unclassified expense "
                  f"lines went to '{'Other / unclassified'}': {others}")
        unmapped = sorted({a for _, pr in group
                           for a in (pr["expense_buckets"].get("unmapped_accounts") or [])})
        if unmapped:
            print(f"[note] {prop['name']} {period_end}: {len(unmapped)} JPM account(s) "
                  f"not in the COA mapping, grouped by their own labels -- extend the "
                  f"COA workbook to settle them: {unmapped}")
        # Once a building code has fed this property's expenses, its absence
        # from a later statement is worth a loud line: a re-export that quietly
        # drops one of The Landing's four codes would understate every bucket.
        prior = {c for pt in hist["points"] if pt["period_end"] != period_end
                 for c in pt.get("source_codes", [])}
        missing = sorted(prior - set(codes))
        if missing:
            print(f"[warn] {prop['name']} {period_end}: previously reported "
                  f"code(s) absent from this statement: {', '.join(missing)} -- "
                  f"expenses may be understated if those codes still have activity")
        point = {
            "period_end": period_end,
            "labels": labels,
            "source_codes": codes,
            "buckets": {k: [round(v, 2) for v in vs] for k, vs in sorted(merged.items())},
            "grouping": group[0][1]["expense_buckets"].get("grouping") or "align_keywords",
            "unmapped_accounts": unmapped,
            "codes_missing_vs_history": missing,
            "basis": ("Align-tree groupings via config/coa_map.json, tied out against "
                      "the statement's own total expenses per month"
                      if group[0][1]["expense_buckets"].get("grouping")
                      else "GL leaf lines classified by keyword into the workbook's "
                           "buckets; recoverable side tied out against 5999-9998 "
                           "per month; financing/non-cash/capital lines excluded"),
        }
        hist["points"] = [pt for pt in hist["points"] if pt["period_end"] != period_end]
        hist["points"].append(point)
        print(f"[ok] stored expense_buckets for {prop['name']} ({period_end}) "
              f"from {'+'.join(codes)}: {len(merged)} bucket(s)")

    hist["points"].sort(key=lambda pt: period_key(pt["period_end"]))
    json.dump(hist, open(fp, "w"), indent=2)
    return hist


def store_monthly_pl(prop, t12_parses):
    """data/<slug>/monthly_pl.json — operating revenue, operating expense and
    the NOI between them, month by month, summed across the property's codes
    like the ratio is. Aggregates only.

    NOI here is revenue minus operating expense, not the statement's own NOI
    line: on the JPM tree that line also carries non-operating expense
    (financing-adjacent items below 519999-9999), so using it would leave a
    three-row card whose first two rows do not reconcile to its third. The
    basis string says which anchors were used, and the card prints it.
    """
    by_period = {}
    for code, pr in sorted(latest_per_code(t12_parses).items()):
        by_period.setdefault(pr["period_end"], []).append((code, pr))

    d = DATA / prop["slug"]
    d.mkdir(parents=True, exist_ok=True)
    fp = d / "monthly_pl.json"
    hist = json.load(open(fp)) if fp.exists() else {"points": []}

    for period_end, group in by_period.items():
        codes = sorted({c2 for c, pr in group for c2 in (pr.get("property_codes") or [c])})
        labels = group[0][1]["labels"]
        if any(pr["labels"] != labels for _, pr in group[1:]):
            print(f"[warn] {prop['name']} {period_end}: month labels differ across "
                  f"codes -- monthly P&L from '{group[0][0]}' alone for this period")
            group = group[:1]
        rev = [sum(pr["revenue_monthly"][i] for _, pr in group) for i in range(12)]
        opex = [sum(pr["opex_recoverable_monthly"][i] for _, pr in group) for i in range(12)]
        point = {
            "period_end": period_end,
            "labels": labels,
            "source_codes": codes,
            "revenue": [round(v, 2) for v in rev],
            "opex": [round(v, 2) for v in opex],
            "noi": [round(rev[i] - opex[i], 2) for i in range(12)],
            "basis": group[0][1].get("opex_basis"),
        }
        hist["points"] = [pt for pt in hist["points"] if pt["period_end"] != period_end]
        hist["points"].append(point)
        print(f"[ok] stored monthly_pl for {prop['name']} ({period_end}) "
              f"from {'+'.join(codes)}")

    hist["points"].sort(key=lambda pt: period_key(pt["period_end"]))
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
    codes = {}
    for c, p in sorted(latest_per_code(t12_parses).items()):
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


def store_leasing_funnel(prop, parsed):
    """data/<slug>/leasing_funnel.json — this community's funnel series.

    The parse arrives through the multi-section router, so the community's own
    fields sit in sections[0]; lift them to the top so the stored file reads as
    one property's report. Aggregate counts and rates only — the export carries
    no person-level data at all (verified by the inspector on two exports).
    """
    sec = (parsed.get("sections") or [{}])[0]
    flat = dict(parsed)
    for k in ("community", "property_id", "service_start", "to_date", "by_month"):
        flat[k] = sec.get(k)
    return store_report(prop, flat, "leasing_funnel.json",
                        ["report_type", "property", "property_code", "community",
                         "property_id", "as_of", "service_start", "to_date",
                         "by_month"])


def store_concessions(prop, parsed):
    """data/<slug>/concessions.json — aggregates only, per the repo rule that
    committed files carry no unit-level detail. The per-unit rows stay in the
    parse for tie-outs but are not persisted. The export carries one section
    per property block; the routed section's own figures sit in sections[0]."""
    sec = (parsed.get("sections") or [{}])[0]
    flat = dict(parsed)
    for k in ("label", "unit_count", "totals"):
        if k in sec:
            flat[k] = sec[k]
    return store_report(prop, flat, "concessions.json",
                        ["report_type", "as_of", "coverage", "label",
                         "unit_count", "totals"])


# report_type -> what to do with a successful parse
ACCUMULATORS = {
    "t12_statement": None,          # handled inline (needs the book/period checks)
    "rent_roll": store_rent_roll,
    "ar_analytics": store_delinquency,
    "leasing_funnel": store_leasing_funnel,
    "concession_burnoff": store_concessions,
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
                    if parsed.get("unattributed"):
                        # the file itself names no property (the concession
                        # burn-off says only "For Selected Properties"), so
                        # this is an export-settings problem, not a config one
                        print(f"[warn] {item['name']} names no property "
                              f"({parsed.get('coverage')!r}) -- parsed and tied "
                              f"out, but stored nowhere until the owner settles "
                              f"which property the export covers")
                        continue
                    print(f"[warn] unknown property code '{code}' in {item['name']} -- "
                          f"add it to config/properties.json; skipping")
                    continue
                if quarantined(prop, item["report_type"]):
                    print(f"[quarantined] {item['name']} -> {prop['name']}: "
                          f"{prop['quarantine']['reason']}")
                    continue
                ACCUMULATORS[item["report_type"]](prop, parsed)
                print(f"[ok] stored {item['report_type']} for {prop['name']} "
                      f"(as of {parsed.get('as_of') or 'unknown date'})")
                continue

            for slug, (prop, secs) in groups.items():
                if quarantined(prop, item["report_type"]):
                    print(f"[quarantined] {item['name']} -> {prop['name']}: "
                          f"{prop['quarantine']['reason']}")
                    continue
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
        if quarantined(prop, item["report_type"], parsed.get("period_end")):
            print(f"[quarantined] {item['name']} -> {prop['name']}: "
                  f"{prop['quarantine']['reason']}")
            continue
        if not prop.get("active", True):
            print(f"[skip] {prop['name']} is inactive (code '{code}'); "
                  f"stored to history but not shown on dashboard")
        print(f"[ok] parsed T12 for {prop['name']} ({parsed['period_end']}) "
              f"from code '{code}'")
        t12_by_slug.setdefault(prop["slug"], (prop, []))[1].append(parsed)

    # Both of these describe the property as a whole, so they are stored once
    # per property from all of its statements rather than once per file -- a
    # per-file call let the last code processed overwrite the others.
    for slug, (prop, parses) in t12_by_slug.items():
        store_expense_ratio(prop, parses)
        store_monthly_revenue(prop, parses)
        store_expense_buckets(prop, parses)
        store_monthly_pl(prop, parses)


# ---- metrics.json generation ---------------------------------------------

def stitch_monthly_pl(points):
    """Every statement's twelve columns merged into one continuous month series.

    Consecutive T12 statements overlap -- a new one repeats eleven months of the
    last -- so months are keyed by their absolute index and the newest statement
    wins where two disagree, a restated month being a correction rather than a
    second reading. Only the contiguous run ending at the newest month is
    returned: a gap between statements would otherwise shift every month left of
    it onto the wrong label.

    The operating-summary card compares a trailing window against the window
    before it, so a T3 comparison needs six months and a T12 comparison
    twenty-four. One statement carries twelve; this is what lets those windows
    reach past it as more statements arrive.
    """
    cells = {}
    for pt in points:                       # oldest first, so newest overwrites
        yr, mon = period_key(pt["period_end"])
        if not yr:
            continue
        end = yr * 12 + (mon - 1)
        n = len(pt["revenue"])
        for i in range(n):
            cells[end - (n - 1 - i)] = (pt["revenue"][i], pt["opex"][i],
                                        pt["noi"][i], pt.get("basis"))
    if not cells:
        return None
    hi = max(cells)
    start = hi
    while start - 1 in cells:
        start -= 1
    idx = list(range(start, hi + 1))
    return {
        "labels": [_MON[i % 12] for i in idx],
        "months": [f"{i // 12}-{i % 12 + 1:02d}" for i in idx],
        "revenue": [cells[i][0] for i in idx],
        "opex": [cells[i][1] for i in idx],
        "noi": [cells[i][2] for i in idx],
        "basis": cells[hi][3],
    }


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

    # Latest expense-bucket point per property, for the Deep Dive's monthly
    # view. The card renders only when its property has a point, so shipping
    # the block empty is the honest "awaiting the statement" state.
    bucket_props = []
    for p in props:
        if not p.get("active", True):
            continue
        fp = DATA / p["slug"] / "expense_buckets.json"
        if not fp.exists():
            continue
        pts = json.load(open(fp))["points"]
        if not pts:
            continue
        latest = pts[-1]
        bucket_props.append({"slug": p["slug"], "name": p["name"],
                             "period_end": latest["period_end"],
                             "labels": latest["labels"],
                             "buckets": latest["buckets"],
                             "basis": latest.get("basis")})
    metrics["expense_buckets"] = {
        "available": bool(bucket_props),
        "properties": bucket_props,
    }

    # Latest monthly P&L point per property, for the operating-summary card.
    pl_props = []
    for p in props:
        if not p.get("active", True):
            continue
        fp = DATA / p["slug"] / "monthly_pl.json"
        if not fp.exists():
            continue
        pts = json.load(open(fp))["points"]
        if not pts:
            continue
        latest = pts[-1]
        series = stitch_monthly_pl(pts)
        if series is None:
            continue
        if len(series["revenue"]) > len(latest["revenue"]):
            print(f"[ok] {p['name']} monthly P&L spans "
                  f"{len(series['revenue'])} months across "
                  f"{len(pts)} statements")
        pl_props.append({"slug": p["slug"], "name": p["name"],
                         "period_end": latest["period_end"],
                         "labels": series["labels"],
                         "months": series["months"],
                         "revenue": series["revenue"], "opex": series["opex"],
                         "noi": series["noi"],
                         "source_codes": latest.get("source_codes"),
                         "basis": series["basis"] or latest.get("basis")})
    metrics["monthly_pl"] = {"available": bool(pl_props), "properties": pl_props}

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

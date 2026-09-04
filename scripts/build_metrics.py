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


def arrival(group):
    """When the statements behind a period point landed, and what they were called.

    A point is built from every code's statement for that period, so the
    arrival is the newest of them. Recorded on the point because the data-flow
    page reports arrival separately from the period the data covers, and a
    period end cannot answer "has this feed stopped running".
    """
    landed = [pr.get("landed_at") for _, pr in group if pr.get("landed_at")]
    names = sorted({pr.get("source_file") for _, pr in group if pr.get("source_file")})
    return (max(landed) if landed else None), names


def ratio_trend(points, label=""):
    """The run of ratio points the card can plot as one line.

    One point per statement period, drawn as a line -- so a point measured on a
    different expense anchor than the newest would draw the anchor change as a
    move in the ratio. Only the trailing run measured the same way as the newest
    point is returned, and it re-lengthens as statements re-arrive on the
    current anchor. Points stored before `expense_scope` existed are the
    operating-slice ones, so an absent value counts as "operating" rather than
    as "matches whatever is newest".
    """
    scope_of = lambda pt: pt.get("expense_scope") or "operating"
    scope = scope_of(points[-1])
    run = points
    while len(run) > 1 and scope_of(run[0]) != scope:
        run = run[1:]
    if len(run) < len(points):
        print(f"[warn] {label or 'expense-ratio'} trend cut to {len(run)} of "
              f"{len(points)} point(s): earlier periods are on a different "
              f"expense anchor than '{scope}'")
    return run, scope


def ratio_basis(scope, anchor):
    """The prose the Expense Ratio card prints under its own property.

    Composed here rather than reused from the parse's `basis`, which describes
    the expense row alone and not the quotient the card is showing.
    """
    # Kept close to the length of the operating line it replaced: this string
    # is the card's eyebrow, and a longer one knocks the property select off the
    # title row at 1440 and wraps to five lines at 390. What the anchor spans is
    # in the footnote, which has room for it.
    if scope == "total":
        return f"Total expenses ({anchor}) \u00f7 Total revenue (T12)"
    return "Recoverable opex \u00f7 Operating revenue (T12)"


def expense_anchor_for(prop, period_end, group):
    """Which expense row this period's codes are measured on.

    The statement carries two expense totals and the dashboard reads the outer
    one: TOTAL EXPENSES (jpm 549999-9999), operating plus the non-operating
    52xxxx region. Statements on the Align tree have no such row -- below their
    5999-9998 recoverable total sit the NOI line and then 6xxx sections with no
    grand total -- so those fall back to the operating anchor.

    All-or-nothing across the property's building codes, and that is the point of
    hoisting this out of the two stores that need it: adding one building's total
    expenses to another's operating expenses gives a figure that is neither, and
    nothing downstream could tell. One rule, one warning, both stores.

    Returns (scope, anchor, basis, t12_key, monthly_key) -- the last two naming
    the parse fields to read, so callers sum one series or the other without
    branching twice.
    """
    anchors = {pr.get("expenses_total_anchor") for _, pr in group}
    if len(anchors) == 1 and None not in anchors:
        return ("total", anchors.pop(), group[0][1].get("expenses_total_basis"),
                "expenses_total_t12", "expenses_total_monthly")
    if anchors != {None}:
        print(f"[warn] {prop['name']} {period_end}: codes disagree on the "
              f"total-expense anchor {sorted(str(a) for a in anchors)} -- "
              f"falling back to operating expenses for this period")
    return ("operating", None, group[0][1].get("opex_basis"),
            "opex_recoverable_t12", "opex_recoverable_monthly")


def store_expense_ratio(prop, t12_parses):
    """Append/replace this property's rolling-T12 points, keyed by period_end.

    A property can report under several building codes (Palma = rspalman +
    rspalmas). The ratio describes the property, so the codes are summed before
    it is taken. Storing one code's statement as the property's point published
    a single building as if it were the whole: Palma's ratio read 127.3% off
    Palma South alone, whose lease-up revenue is near zero, while Palma North
    was billing $264k that month and was not in the figure at all.

    The numerator is the statement's TOTAL EXPENSES row (jpm 549999-9999) where
    the statement has one, matching the Operating Summary card. This departs
    from the Align definition of the ratio, which is the recoverable/operating
    line over operating revenue; it is the owner's call, made 2026-09-03, so
    that the two cards drawing the same statement stop reporting two different
    expense loads. The Landing reads 33.3% on the total anchor against 32.7% on
    the operating one.

    A statement with no total-expense row keeps the operating anchor, so the
    ratio is not comparable across properties on different account trees --
    Palma's 56.1% is recoverable opex, The Landing's 33.3% is total expenses.
    `expense_scope` and `expense_anchor` on the point are what let the card say
    so per property instead of printing one basis over both.
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
        scope, anchor, exp_basis, t12_key, monthly_key = \
            expense_anchor_for(prop, period_end, group)
        rev_t12 = sum(p["revenue_t12"] for _, p in group)
        exp_t12 = sum(p[t12_key] for _, p in group)

        # The monthly detail sums position by position, so the month columns
        # have to line up. They do for one period end; if that ever stops
        # holding, say so and publish the leading code's detail unsummed rather
        # than adding March to April. Computed from the chosen anchor either
        # way, rather than from the parse's own precomputed ratio, so the
        # monthly detail can never sit on a different row than ratio_t12.
        pct = lambda e, r: round(100 * e / r, 1) if r else None
        labels = group[0][1]["labels"]
        mismatched = next((c for c, p in group[1:] if p["labels"] != labels), None)
        if mismatched:
            print(f"[warn] {prop['name']} {period_end}: code '{mismatched}' has "
                  f"different month labels than '{codes[0]}' -- monthly detail "
                  f"is from '{codes[0]}' alone for this period")
            lead = group[0][1]
            monthly = [pct(lead[monthly_key][i], lead["revenue_monthly"][i])
                       for i in range(12)]
        else:
            rev_m = [sum(p["revenue_monthly"][i] for _, p in group) for i in range(12)]
            exp_m = [sum(p[monthly_key][i] for _, p in group) for i in range(12)]
            monthly = [pct(exp_m[i], rev_m[i]) for i in range(12)]

        landed_at, source_files = arrival(group)
        point = {
            "period_end": period_end,
            "landed_at": landed_at,
            "source_files": source_files,
            "ratio_t12": pct(exp_t12, rev_t12),
            "revenue_t12": round(rev_t12, 2),
            # Named for what it is rather than for the anchor it used to be:
            # on the total anchor this is not recoverable opex.
            "expense_t12": round(exp_t12, 2),
            "expense_scope": scope,
            "expense_anchor": anchor,
            "basis": exp_basis,
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
        landed_at, source_files = arrival(group)
        point = {
            "period_end": period_end,
            "landed_at": landed_at,
            "source_files": source_files,
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
    """data/<slug>/monthly_pl.json — operating revenue, the statement's expense
    total and the NOI between them, month by month, summed across the
    property's codes like the ratio is. Aggregates only.

    The expense row anchors on the statement's TOTAL EXPENSES line
    (jpm 549999-9999), which carries the non-operating 52xxxx region as well as
    operating expense, and not on TOTAL OPERATING EXPENSES (519999-9999) as it
    once did. For The Landing that is ~$4.4k a month for most of the year and
    $55k in Jul 2026, so the two anchors are not interchangeable: the summary is
    now the whole expense load rather than the operating slice of it. The
    Expense Ratio card was moved onto the same anchor on 2026-09-03, so the two
    cards drawing this statement no longer report two different expense loads.

    `expense_scope` says which anchor a point used ("total" or "operating") and
    `expense_anchor` names the code -- chosen by expense_anchor_for, which the
    ratio store shares. The page picks its row labels off the scope rather than
    parsing the basis prose.

    NOI stays revenue minus that expense row rather than the statement's own NOI
    line, so the card's three rows reconcile by construction. On the JPM tree
    the two now agree: 549999-9999 is the row immediately above
    599999-9999 TOTAL NET OPERATING INCOME, so subtracting it reproduces that
    line instead of falling short of it by the non-operating region.
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

        # Same anchor rule as the ratio, in one place: see expense_anchor_for.
        scope, anchor, basis, _, monthly_key = \
            expense_anchor_for(prop, period_end, group)
        expense = [sum(pr[monthly_key][i] for _, pr in group) for i in range(12)]

        landed_at, source_files = arrival(group)
        point = {
            "period_end": period_end,
            "landed_at": landed_at,
            "source_files": source_files,
            "labels": labels,
            "source_codes": codes,
            "revenue": [round(v, 2) for v in rev],
            # Kept under "opex" so the key that metrics.json, data.html and the
            # card already read does not move; "expense_scope" is what says
            # whether it is the operating slice or the whole expense load.
            "opex": [round(v, 2) for v in expense],
            "noi": [round(rev[i] - expense[i], 2) for i in range(12)],
            "expense_scope": scope,
            "expense_anchor": anchor,
            "basis": basis,
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
    landed, names = arrival([(c, p) for c, p in latest_per_code(t12_parses).items()])
    out = {
        "revenue_month": round(sum(v["revenue"] for v in codes.values()), 2),
        "basis": "GL 4999-9999 total operating revenue, latest reported month per code",
        "landed_at": landed,
        "source_files": names,
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


def store_unit_directory(prop, parsed):
    """data/<slug>/unit_directory.json — the building's fixed description.

    The floorplan table is what the property page joins a unit's plan code to
    when it needs bedrooms or the plan's square footage; the rent roll and the
    analyst workbook both name the plan but neither says how many bedrooms it
    has. Sections stay separate per building code, since a property reporting
    under several codes has a separate directory for each, and the merged plan
    table is built from them with a collision check rather than assumed unique.

    No resident, no lease, no name — a unit directory carries none. It still
    goes through store_report, so the central scrub covers it like everything
    else rather than by remembering that this one is safe.
    """
    secs = parsed.get("sections") or []
    plans, clash = {}, []
    for sec in secs:
        for code, plan in (sec.get("plans") or {}).items():
            if code in plans and plans[code] != plan:
                clash.append(f"plan '{code}' differs between building codes")
            plans[code] = plan
    merged = dict(parsed)
    merged["plans"] = plans
    merged["units"] = sum(s.get("units") or 0 for s in secs)
    merged["residential_units"] = sum(s.get("residential_units") or 0 for s in secs)
    merged["placeholder_units"] = sum(s.get("placeholder_units") or 0 for s in secs)
    merged["problems"] = (parsed.get("problems") or []) + clash
    for pr in merged["problems"]:
        print(f"[warn] {prop['name']} unit directory: {pr}")
    return store_report(prop, merged, "unit_directory.json",
                        ["report_type", "property", "property_code",
                         "property_codes", "as_of", "units",
                         "residential_units", "placeholder_units", "plans",
                         "sections", "problems"])


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


def store_budget(prop, parsed):
    """data/<slug>/budget.json — the year's plan, in the T12 statement's shape.

    Monthly revenue and operating-expense lines plus the Align-grouped expense
    buckets, exactly as the actuals' expense_buckets are grouped, so the
    scorecard's Budget Variance fill compares one basket against itself. A
    budget carries no resident, but it goes through store_report like every
    other feed so the central scrub covers it by default.
    """
    return store_report(prop, parsed, "budget.json",
                        ["report_type", "property", "property_code",
                         "property_codes", "tree", "year", "as_of", "labels",
                         "revenue_monthly", "opex_operating_monthly",
                         "buckets", "buckets_unmapped", "buckets_tieout_gap",
                         "buckets_error"])


# report_type -> what to do with a successful parse
ACCUMULATORS = {
    "t12_statement": None,          # handled inline (needs the book/period checks)
    "rent_roll": store_rent_roll,
    "ar_analytics": store_delinquency,
    "leasing_funnel": store_leasing_funnel,
    "concession_burnoff": store_concessions,
    "unit_directory": store_unit_directory,
    "budget": store_budget,
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
        # setdefault, not assignment: a parser that names its own source (the
        # unit directory, the funnel) knows the name it was filed under, which
        # can differ from Drive's date-prefixed copy.
        parsed.setdefault("source_file", item.get("name"))

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

def stitch_monthly_pl(points, label=""):
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

    The run also stops where the expense scope changes. Points stored before the
    card moved to the statement's TOTAL EXPENSES anchor carry the operating
    slice instead, and a window straddling the switch would read the ~$4.4k a
    month between the two anchors as a real swing in spending. So the series is
    the run of months measured the same way as the newest one, and it grows back
    to full length as statements re-arrive on the new anchor.
    """
    cells = {}
    for pt in points:                       # oldest first, so newest overwrites
        yr, mon = period_key(pt["period_end"])
        if not yr:
            continue
        end = yr * 12 + (mon - 1)
        n = len(pt["revenue"])
        for i in range(n):
            cells[end - (n - 1 - i)] = {
                "revenue": pt["revenue"][i], "opex": pt["opex"][i],
                "noi": pt["noi"][i], "basis": pt.get("basis"),
                "anchor": pt.get("expense_anchor"),
                # Absent on points stored before the anchor moved, and those are
                # exactly the operating-slice ones.
                "scope": pt.get("expense_scope") or "operating",
            }
    if not cells:
        return None
    hi = max(cells)
    scope = cells[hi]["scope"]
    start = hi
    while start - 1 in cells and cells[start - 1]["scope"] == scope:
        start -= 1
    if start - 1 in cells:
        print(f"[warn] {label or 'monthly P&L'}: series cut at "
              f"{_MON[start % 12]} {start // 12} -- earlier months are on the "
              f"'{cells[start - 1]['scope']}' expense anchor, the newest is on "
              f"'{scope}' -- mixing them would show the anchor change as a "
              f"spending change")
    idx = list(range(start, hi + 1))
    return {
        "labels": [_MON[i % 12] for i in idx],
        "months": [f"{i // 12}-{i % 12 + 1:02d}" for i in idx],
        "revenue": [cells[i]["revenue"] for i in idx],
        "opex": [cells[i]["opex"] for i in idx],
        "noi": [cells[i]["noi"] for i in idx],
        "expense_scope": scope,
        "expense_anchor": cells[hi]["anchor"],
        "basis": cells[hi]["basis"],
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
        # The trend is one point per statement period, and the card plots it as
        # a line -- so a point measured on a different expense anchor than the
        # newest would draw the anchor change as a move in the ratio. Keep the
        # trailing run measured the same way as the newest point; the line
        # re-lengthens as statements re-arrive on the current anchor. Points
        # stored before expense_scope existed are the operating-slice ones.
        trend, scope = ratio_trend(pts, f"{p['name']} expense-ratio")
        expense_ratio_props.append({
            "slug": p["slug"],
            "name": p["name"],
            "ratio_t12": latest["ratio_t12"],
            "trend_labels": [pt["period_end"] for pt in trend],
            "trend_values": [pt["ratio_t12"] for pt in trend],
            "latest_monthly_labels": latest["labels"],
            "latest_monthly_ratio": latest["monthly_ratio"],
            # Per property, not per block: two properties on different account
            # trees are on different anchors, and one basis line over both
            # would describe only whichever sorted first.
            "expense_scope": scope,
            "expense_anchor": latest.get("expense_anchor"),
            "basis": ratio_basis(scope, latest.get("expense_anchor")),
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

    # The floorplan table per property, for joining a unit's plan code to its
    # bedroom count. Static description of the building, refreshed when a new
    # directory lands rather than daily.
    ud_props = []
    for p in props:
        if not p.get("active", True):
            continue
        fp = DATA / p["slug"] / "unit_directory.json"
        if not fp.exists():
            continue
        ud = json.load(open(fp))
        ud_props.append({"slug": p["slug"], "name": p["name"],
                         "as_of": ud.get("as_of"),
                         "landed_at": ud.get("landed_at"),
                         "source_file": ud.get("source_file"),
                         "units": ud.get("units"),
                         "residential_units": ud.get("residential_units"),
                         "codes": [s.get("property_code") for s in ud.get("sections") or []],
                         "plans": ud.get("plans") or {}})
    metrics["unit_directory"] = {"available": bool(ud_props), "properties": ud_props}

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
        series = stitch_monthly_pl(pts, f"{p['name']} monthly P&L")
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
                         # Which expense row the "opex" series is: the page reads
                         # this to label the expense and NOI rows, since "total"
                         # and "operating" are not the same number.
                         "expense_scope": series["expense_scope"],
                         "expense_anchor": series["expense_anchor"],
                         "source_codes": latest.get("source_codes"),
                         "basis": series["basis"] or latest.get("basis")})
    metrics["monthly_pl"] = {"available": bool(pl_props), "properties": pl_props}

    if expense_ratio_props:
        metrics["expense_ratio"] = {
            "available": True,
            # A fallback only: each property carries its own basis, because
            # the anchor depends on which account tree its statement is on.
            "basis": "Statement expenses \u00f7 Operating revenue (T12)",
            "properties": expense_ratio_props,
            "footnote": "Rolling T12 expense ratio per property; one point per monthly "
                        "statement. Monthly ratios within a statement are volatile on an "
                        "accrual basis \u2014 the T12 figure is the reliable KPI. The "
                        "numerator is the statement's total expenses row where it has "
                        "one (the same figure the Operating Summary card shows), and its "
                        "recoverable operating total where it does not \u2014 so the "
                        "ratio is not comparable between properties whose statements are "
                        "on different account trees \u2014 the basis above the chart is "
                        "the selected property's own.",
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

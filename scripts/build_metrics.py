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


# The residential rental-income series the Loss to Lease card draws, named in
# one place so the store, the stitch and the publish cannot drift apart. Sign
# convention is the analyst workbook's: a deduction is a positive number.
RENT_CAPTURE_KEYS = ("market_potential", "loss_to_lease", "vacancy_loss",
                     "employee_allowance", "concessions", "other",
                     "rental_income")

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


def store_rent_capture(prop, t12_parses):
    """data/<slug>/rent_capture.json -- the statement's residential rental
    income, month by month, summed across the property's codes like the rest.

    This is what the Loss to Lease card draws. It was read off the analyst
    workbook until 2026-09-11, when the same six series turned out to be
    sitting in the T12 statement the pipeline already fetches daily -- gross
    market rent potential, the four deductions, and the accrued total -- tying
    to the cent against the workbook over all twelve overlapping months. So the
    card needs no rent roll: its figures are a property-level P&L section, not
    a per-unit comparison, which is why it can live on the Drive-only tab while
    the unit-level cards beside it cannot.

    A parse whose section was refused (tie-out failure) is skipped loudly, the
    way refused buckets are: the stores must not share a fate.
    """
    by_period = {}
    for code, pr in sorted(latest_per_code(t12_parses).items()):
        if not pr.get("rent_capture"):
            if pr.get("rent_capture_error"):
                print(f"[warn] {prop['name']} {pr.get('period_end')} code '{code}': "
                      f"rent capture refused -- {pr['rent_capture_error']}")
            continue
        by_period.setdefault(pr["period_end"], []).append((code, pr))
    if not by_period:
        return None

    d = DATA / prop["slug"]
    d.mkdir(parents=True, exist_ok=True)
    fp = d / "rent_capture.json"
    hist = json.load(open(fp)) if fp.exists() else {"points": []}

    for period_end, group in by_period.items():
        codes = sorted({c2 for c, pr in group for c2 in (pr.get("property_codes") or [c])})
        labels = group[0][1]["labels"]
        if any(pr["labels"] != labels for _, pr in group[1:]):
            print(f"[warn] {prop['name']} {period_end}: month labels differ across "
                  f"codes -- rent capture from '{group[0][0]}' alone for this period")
            group = group[:1]
        bases = {pr["rent_capture"]["basis"] for _, pr in group}
        if len(bases) > 1:
            print(f"[warn] {prop['name']} {period_end}: codes report rental income "
                  f"on different bases ({sorted(bases)}) -- rent capture skipped "
                  f"for this period rather than summing unlike sections")
            continue
        merged = {k: [sum(pr["rent_capture"][k][i] for _, pr in group)
                      for i in range(len(labels))]
                  for k in RENT_CAPTURE_KEYS}
        gaps = [pr["rent_capture"].get("tieout_max_gap") for _, pr in group]
        problems = sorted({x for _, pr in group
                           for x in (pr["rent_capture"].get("problems") or [])})
        for x in problems:
            print(f"[note] {prop['name']} {period_end} rent capture: {x}")
        landed_at, source_files = arrival(group)
        point = {
            "period_end": period_end,
            "landed_at": landed_at,
            "source_files": source_files,
            "labels": labels,
            "source_codes": codes,
            **{k: [round(v, 2) for v in vs] for k, vs in merged.items()},
            "basis": bases.pop(),
            "tieout_max_gap": (max(g for g in gaps if g is not None)
                               if any(g is not None for g in gaps) else None),
            "problems": problems,
        }
        hist["points"] = [pt for pt in hist["points"] if pt["period_end"] != period_end]
        hist["points"].append(point)
        print(f"[ok] stored rent_capture for {prop['name']} ({period_end}) "
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
    merged["non_residential_units"] = sum(s.get("non_residential_units") or 0
                                          for s in secs)
    merged["non_residential"] = [n for s in secs for n in (s.get("non_residential") or [])]
    # The floorplan table is what every per-unit figure on the page is drawn or
    # divided by, so it has to account for exactly the apartments and no more.
    # Anything else means a placeholder or a commercial record has found its way
    # back in, and the numbers would shift by a hair rather than break.
    plan_units = sum(p.get("units") or 0 for p in plans.values())
    if plan_units != merged["residential_units"]:
        clash.append(f"floorplans sum to {plan_units} units but the sections "
                     f"count {merged['residential_units']} apartments")
    merged["problems"] = (parsed.get("problems") or []) + clash
    if merged["non_residential"]:
        print(f"[note] {prop['name']}: {merged['non_residential_units']} non-apartment "
              f"record(s) excluded from every published figure: "
              f"{', '.join(merged['non_residential'])}")
    for pr in merged["problems"]:
        print(f"[warn] {prop['name']} unit directory: {pr}")
    return store_report(prop, merged, "unit_directory.json",
                        ["report_type", "property", "property_code",
                         "property_codes", "as_of", "units",
                         "residential_units", "placeholder_units",
                         "non_residential_units", "non_residential", "plans",
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


BUDGET_KEYS = ["report_type", "property", "property_code", "property_codes",
               "tree", "year", "as_of", "labels", "revenue_monthly",
               "opex_operating_monthly", "buckets", "buckets_unmapped",
               "buckets_tieout_gap", "buckets_error"]


def store_budget(prop, parsed):
    """data/<slug>/budget.json — the plans, one point per budget YEAR.

    Monthly revenue and operating-expense lines plus the Align-grouped expense
    buckets, exactly as the actuals' expense_buckets are grouped, so the
    scorecard's Budget Variance fill compares one basket against itself. A
    budget carries no resident, but it goes through store_report like every
    other feed so the central scrub covers it by default.

    Keyed on the year and ACCUMULATED rather than overwritten, the way
    expense_buckets keeps a point per statement period. A budget is a calendar
    year and the T12 window the dashboard draws is not: the actuals run Sep-Aug
    today, so a store that held only the newest year would leave four months of
    that window with no plan to compare against, and the Budget vs Actual card
    would report a gap where the file that answers it was simply overwritten.
    Re-filing the same year replaces that year's point, so re-processing a
    re-export is idempotent.
    """
    year = parsed.get("year")
    if year is None:
        print(f"[warn] {prop['name']}: budget carries no year -- not stored")
        return None

    d = DATA / prop["slug"]
    d.mkdir(parents=True, exist_ok=True)
    fp = d / "budget.json"
    hist = json.load(open(fp)) if fp.exists() else {}
    # Files written before budgets were kept per year are a single flat plan.
    # Carry that one in as its own year rather than dropping it on the floor.
    years = hist.get("years")
    if years is None:
        years = [hist] if hist.get("year") is not None else []

    point = {k: scrub(parsed.get(k)) for k in BUDGET_KEYS}
    point["source_file"] = parsed.get("source_file")
    point["landed_at"] = parsed.get("landed_at")
    point["checks"] = parsed.get("checks")

    years = [y for y in years if y.get("year") != year]
    years.append(point)
    years.sort(key=lambda y: y["year"])
    json.dump({"years": years}, open(fp, "w"), indent=2, default=str)
    print(f"[ok] stored budget for {prop['name']} ({year}) from "
          f"{parsed.get('source_file')}: {len(point.get('buckets') or {})} bucket(s), "
          f"{len(years)} year(s) on file")
    return fp


def rent_roll_summary(rr):
    """The published aggregates behind the Drive tab's rent-roll cards.

    A rent roll is a point-in-time snapshot, so everything here is "as of" its
    own date rather than a series. Three things are computed once, here, rather
    than in the page, because each one is a judgement the page should not be
    making twice:

      * Occupancy is the parser's own `occupied` flag (a resident code AND a
        non-zero rent), never the presence of a resident code alone. Yardi
        carries a code on vacant units too -- this export has one on all 263 --
        so a code-only test reads 100% occupancy on a property that is at 97.7%.
      * Loss to lease is measured on OCCUPIED units only. A vacant unit has a
        market rent and no in-place rent, so counting it books the whole asking
        rent as loss to lease and overstates the gap -- 38.1% against 36.5% on
        this roll.
      * Holdovers are occupied units whose lease expired before the as-of date.
        The rent roll has no month-to-month state of its own, which is why this
        is derived from the expiry rather than read off a column.
    """
    from datetime import date

    def to_date(v):
        try:
            return date.fromisoformat(str(v)[:10])
        except (TypeError, ValueError):
            return None

    units = rr.get("units") or []
    as_of = to_date(rr.get("as_of"))
    occ = [u for u in units if u.get("occupied")]
    vac = [u for u in units if not u.get("occupied")]
    mk = sum(u.get("market_rent") or 0 for u in occ)
    ac = sum(u.get("actual_rent") or 0 for u in occ)

    def gap_yr(us):
        return round(sum((u.get("market_rent") or 0) - (u.get("actual_rent") or 0)
                         for u in us) * 12, 2)

    # Rollover. Expired leases collapse into one bucket the page labels
    # "Holdover", matching the workbook-fed card on The Landing; everything else
    # is keyed by expiry month so the two cards read the same way.
    buckets = {}
    for u in occ:
        d = to_date(u.get("lease_expiration"))
        key = ("Expired" if as_of and d and d < as_of
               else d.strftime("%Y-%m") if d else None)
        if key is None:
            continue
        b = buckets.setdefault(key, {"month": key, "units": 0, "sqft": 0.0,
                                     "inplace": 0.0, "market": 0.0})
        b["units"] += 1
        b["sqft"] += u.get("sqft") or 0
        b["inplace"] += u.get("actual_rent") or 0
        b["market"] += u.get("market_rent") or 0
    rollover = ([buckets["Expired"]] if "Expired" in buckets else []) + [
        buckets[k] for k in sorted(k for k in buckets if k != "Expired")]
    run = 0
    for b in rollover:
        b["uncaptured"] = round(b["market"] - b["inplace"], 2)
        run += b["units"]
        b["cum_units"] = run
        b["cum_pct"] = round(run / len(occ), 6) if occ else None
        for k in ("sqft", "inplace", "market"):
            b[k] = round(b[k], 2)

    # Largest gaps, the per-unit table. Occupied only -- a vacant unit's "gap"
    # is its whole asking rent and would head the table on every roll. No
    # resident field reaches this: the parse is scrubbed before it is stored.
    ranked = sorted(occ, key=lambda u: (u.get("market_rent") or 0) - (u.get("actual_rent") or 0),
                    reverse=True)
    gaps = []
    for i, u in enumerate(ranked[:40], 1):
        m, a = u.get("market_rent") or 0, u.get("actual_rent") or 0
        d = to_date(u.get("lease_expiration"))
        gaps.append({
            "rank": i, "unit": u.get("unit"), "unit_type": u.get("unit_type"),
            "sqft": u.get("sqft"), "inplace": a, "market": m,
            "gap_mo": round(m - a, 2), "gap_yr": round((m - a) * 12, 2),
            "pct_below": round((m - a) / m, 6) if m else None,
            "expiry": u.get("lease_expiration"),
            "status": ("Holdover" if as_of and d and d < as_of
                       else "On notice" if u.get("on_notice") else "Current"),
        })

    hold = [u for u in occ if (d := to_date(u.get("lease_expiration"))) and as_of and d < as_of]

    # Leased and vacant per floorplan, which is what lets the Unit Inventory
    # card split its bars. The roll names the plan and the directory says how
    # many bedrooms a plan has, so the counts are published per plan and the
    # page rolls them onto bedroom groups -- neither report can do it alone.
    # Counts only: a plan with one unit says that plan has one unit, which the
    # directory already says in public, so this survives into metrics.json where
    # the rest of the per-unit roll cannot.
    by_plan = {}
    for u in units:
        code = str(u.get("unit_type") or "").strip() or "(no plan)"
        b = by_plan.setdefault(code, {"units": 0, "leased": 0, "vacant": 0})
        b["units"] += 1
        b["leased" if u.get("occupied") else "vacant"] += 1

    return {
        "as_of": rr.get("as_of"),
        "landed_at": rr.get("landed_at"),
        "source_file": rr.get("source_file"),
        "units": len(units),
        "occupied": len(occ),
        "vacant": len(vac),
        "on_notice": sum(1 for u in occ if u.get("on_notice")),
        "occupancy": round(len(occ) / len(units), 6) if units else None,
        "sqft": round(sum(u.get("sqft") or 0 for u in units), 2),
        # *_total rather than market_rent/actual_rent: those two are per-unit
        # field names on a rent roll, and a `name` key sitting beside them is
        # what check_no_pii's structural pass reads as a resident row. Naming
        # the sums for what they are keeps the check strict and the block clear
        # beside the _occupied pair below.
        "market_rent_total": round(sum(u.get("market_rent") or 0 for u in units), 2),
        "actual_rent_total": round(sum(u.get("actual_rent") or 0 for u in units), 2),
        # the pair the loss-to-lease figure is actually computed on
        "market_rent_occupied": round(mk, 2),
        "actual_rent_occupied": round(ac, 2),
        "loss_to_lease": round(mk - ac, 2),
        "loss_to_lease_pct": round((mk - ac) / mk, 6) if mk else None,
        "market_psf": round(mk / sum(u.get("sqft") or 0 for u in occ), 4) if occ else None,
        "inplace_psf": round(ac / sum(u.get("sqft") or 0 for u in occ), 4) if occ else None,
        "holdovers": {
            "units": len(hold),
            "share_of_occupied": round(len(hold) / len(occ), 6) if occ else None,
            "inplace": round(sum(u.get("actual_rent") or 0 for u in hold), 2),
            "market": round(sum(u.get("market_rent") or 0 for u in hold), 2),
            "gap_yr": gap_yr(hold),
        },
        "by_plan": dict(sorted(by_plan.items())),
        "rollover": rollover,
        "gaps": gaps,
        "undated_leases": sum(1 for u in occ if not to_date(u.get("lease_expiration"))),
        "basis": ("Occupied units only for loss to lease and the gap table; a vacant "
                  "unit has an asking rent and no in-place rent, so counting it books "
                  "the whole asking rent as loss to lease."),
        "checks": rr.get("checks"),
    }


def store_daily_leasing(prop, parsed):
    """data/<slug>/leasing_detail.json — the new-lease trade-outs, by week.

    Accumulated rather than overwritten, because each file is a single week and
    the Trade-outs card plots months: one file is one bar's worth of leases.
    Keyed on the week-ending date so re-processing a week replaces it instead of
    doubling it, which matters because the filer keeps several copies of the
    same week (the 9.13.26 week arrived on the 8th, 9th and 10th).

    The lease rows carry no resident — the NEW LEASES block has no name column.
    The leasing associate's first name is dropped here rather than stored: it
    identifies a person, it is nobody's business on a published page, and the
    dashboard has no use for it.
    """
    if not parsed.get("as_of"):
        print(f"[warn] {parsed.get('source_file')}: no week-ending date — "
              f"skipped, since its leases cannot be placed in a month")
        return None
    d = DATA / prop["slug"]
    d.mkdir(parents=True, exist_ok=True)
    fp = d / "leasing_detail.json"
    hist = json.load(open(fp)) if fp.exists() else {"weeks": []}

    keep = ("unit", "unit_type", "floor_plan", "beds_baths", "sqft", "lease_rent",
            "prior_rent", "tradeout_amount", "tradeout_pct", "concession",
            "net_rent", "move_in", "term")
    week = {
        "week_ending": parsed["as_of"],
        "source_file": parsed.get("source_file"),
        "landed_at": parsed.get("landed_at"),
        "totals": parsed.get("totals"),
        "leases": [scrub({k: l.get(k) for k in keep}) for l in parsed.get("leases") or []],
        "checks": parsed.get("checks"),
        "problems": parsed.get("problems"),
    }
    hist["weeks"] = [w for w in hist["weeks"]
                     if w.get("week_ending") != week["week_ending"]] + [week]
    hist["weeks"].sort(key=lambda w: w["week_ending"])
    json.dump(hist, open(fp, "w"), indent=2, default=str)
    print(f"[ok] stored leasing detail for {prop['name']}: "
          f"{len(week['leases'])} lease(s) for the week ending {week['week_ending']} "
          f"({len(hist['weeks'])} week(s) on file)")
    return fp


def store_lease_tradeout(prop, parsed):
    """data/<slug>/lease_tradeout.json — new-lease trade-outs, accumulated.

    Accumulated by lease rather than overwritten, because the window is chosen
    at export time: this report is run "From x To y" and the next one may be
    wider, narrower or offset. Taking the newest file whole would throw away
    every lease outside whatever range that export happened to ask for.

    The key is (unit, signed date, previous lease start). A unit turns over
    more than once inside one window -- 102 appears twice in the first file --
    so unit and date alone are not unique, and the previous lease is what makes
    a given turnover that turnover. Re-filing a window therefore replaces its
    leases instead of doubling them.

    Each file's own period and tie-out are kept in `files`, because the tie-out
    is a statement about that export against its own Grand Total row and stops
    meaning anything once several are merged.

    No resident, no name — the report has no such column. It still goes through
    the central scrub, like the unit directory.
    """
    fp = DATA / prop["slug"] / "lease_tradeout.json"
    fp.parent.mkdir(parents=True, exist_ok=True)
    hist = json.load(open(fp)) if fp.exists() else {"files": [], "leases": []}

    key = lambda l: (l.get("unit"), l.get("signed"), l.get("prev_start"))  # noqa: E731
    fresh = {key(l): scrub(l) for l in parsed.get("leases") or []}
    kept = [l for l in hist.get("leases", []) if key(l) not in fresh]
    hist["leases"] = sorted(kept + list(fresh.values()),
                            key=lambda l: (l.get("signed") or "", l.get("unit") or ""))

    rec = {k: parsed.get(k) for k in
           ("source_file", "landed_at", "period_start", "period_end", "rate_type",
            "lease_date_basis", "tradeout_basis", "checks", "problems")}
    rec["leases"] = len(fresh)
    hist["files"] = [f for f in hist.get("files", [])
                     if f.get("source_file") != rec["source_file"]] + [rec]
    hist["files"].sort(key=lambda f: f.get("period_end") or "")

    for k in ("report_type", "property", "rate_type", "lease_date_basis",
              "tradeout_basis"):
        hist[k] = parsed.get(k)
    hist["as_of"] = max(f.get("period_end") or "" for f in hist["files"]) or None
    hist["landed_at"] = parsed.get("landed_at")
    hist["source_file"] = parsed.get("source_file")

    json.dump(hist, open(fp, "w"), indent=2, default=str)
    print(f"[ok] stored lease trade-outs for {prop['name']}: "
          f"{len(fresh)} lease(s) from {parsed.get('source_file')} "
          f"({parsed.get('period_start')}..{parsed.get('period_end')}), "
          f"{len(hist['leases'])} on file")
    return fp


def store_renewal_tracker(prop, parsed):
    """data/<slug>/renewal_tracker.json — the whole tracker, overwritten.

    The opposite of the weekly leasing store: one tracker file carries every
    month from January 2024 forward, so the newest file supersedes the last
    rather than adding to it. The MTM roster's per-unit rows go through the
    central scrub, which is what drops the Yardi tenant code the sheet carries
    beside each unit.
    """
    return store_report(prop, parsed, "renewal_tracker.json",
                        ["report_type", "property", "as_of", "covers", "months",
                         "mtm", "unread_sheets", "problems"])


def store_comps(prop, parsed):
    """data/<slug>/comps.json — this property's view of its own submarket.

    Overwritten rather than accumulated, like the renewal tracker and unlike
    the trade-out report: one comp export carries three years of listings, so
    the newest file is a superset of the last rather than the next slice of a
    window. Nothing is lost by taking it whole.

    The section is already aggregates — medians, counts and shares. The listing
    rows behind them are a licensed vendor dataset and stay out of `data/` for
    the same reason resident names do: everything here is served to anyone with
    the URL.
    """
    section = (parsed.get("sections") or [{}])[0]
    out = dict(section)
    out.update({
        "report_type": parsed.get("report_type"),
        "vendor": parsed.get("vendor"),
        "market": parsed.get("market"),
        "properties_in_file": parsed.get("properties_in_file"),
        "listings_in_file": parsed.get("listings_in_file"),
        "source_file": parsed.get("source_file"),
        "landed_at": parsed.get("landed_at"),
        "checks": parsed.get("checks"),
        "problems": (parsed.get("problems") or []) + (section.get("problems") or []),
    })
    fp = DATA / prop["slug"] / "comps.json"
    fp.parent.mkdir(parents=True, exist_ok=True)
    json.dump(scrub(out), open(fp, "w"), indent=2, default=str)
    ring = next((r for r in section.get("rings") or [] if r.get("primary")), {})
    print(f"[ok] stored market comps for {prop['name']}: {ring.get('properties', 0)} "
          f"comp propert(ies) within {section.get('primary_radius_mi')} mi, "
          f"{ring.get('listings', 0)} listing(s) as of {section.get('as_of')}")
    return fp


# report_type -> what to do with a successful parse
ACCUMULATORS = {
    "t12_statement": None,          # handled inline (needs the book/period checks)
    "rent_roll": store_rent_roll,
    "ar_analytics": store_delinquency,
    "leasing_funnel": store_leasing_funnel,
    "concession_burnoff": store_concessions,
    "unit_directory": store_unit_directory,
    "budget": store_budget,
    "daily_leasing_report": store_daily_leasing,
    "renewal_tracker": store_renewal_tracker,
    "lease_tradeout": store_lease_tradeout,
    "market_comps": store_comps,
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
        # A parser may claim a file and then decline to read it: the comp
        # export arrives as a pair of near-identical names, one machine-readable
        # and one formatted for the eye. That is a skip with a reason, not a
        # failure -- the entry claims everything in its folder on purpose, so a
        # renamed export cannot go unread, and this is what keeps the log
        # honest about the file it is not reading.
        if parsed.get("skip"):
            print(f"[skip] {item['name']}: {parsed['skip']}")
            continue

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
        store_rent_capture(prop, parses)


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


def stitch_rent_capture(points, label=""):
    """Successive statements' rental-income sections merged into one month run.

    Same rule as stitch_monthly_pl -- absolute month index, newest statement
    wins an overlapping month, only the contiguous run ending at the newest
    month is returned -- so the card lengthens past twelve months as statements
    accumulate instead of resetting to each new file's window.

    The run also stops where the basis changes. A section read off the
    statement's own total row and one derived from its lines (the Align tree
    has no such row) are not the same measurement, and a chart spanning both
    would draw the change as a movement in rent.
    """
    cells = {}
    for pt in points:                       # oldest first, so newest overwrites
        yr, mon = period_key(pt["period_end"])
        if not yr:
            continue
        end = yr * 12 + (mon - 1)
        n = len(pt["market_potential"])
        for i in range(n):
            cells[end - (n - 1 - i)] = {
                **{k: pt[k][i] for k in RENT_CAPTURE_KEYS},
                "basis": pt.get("basis"),
            }
    if not cells:
        return None
    hi = max(cells)
    basis = cells[hi]["basis"]
    start = hi
    while start - 1 in cells and cells[start - 1]["basis"] == basis:
        start -= 1
    if start - 1 in cells:
        print(f"[warn] {label or 'rent capture'}: series cut at "
              f"{_MON[start % 12]} {start // 12} -- earlier months are on the "
              f"'{cells[start - 1]['basis']}' basis, the newest is on "
              f"'{basis}'")
    idx = list(range(start, hi + 1))
    out = {
        "labels": [_MON[i % 12] for i in idx],
        "months": [f"{i // 12}-{i % 12 + 1:02d}" for i in idx],
        **{k: [cells[i][k] for i in idx] for k in RENT_CAPTURE_KEYS},
        "basis": basis,
    }
    # The card's footnote quotes a trailing-twelve figure, so it is computed
    # from the series rather than from the newest statement's Total column --
    # those agree today and would not once the run runs past one statement.
    t = idx[-12:]
    pot = sum(cells[i]["market_potential"] for i in t)
    inc = sum(cells[i]["rental_income"] for i in t)
    ltl = sum(cells[i]["loss_to_lease"] for i in t)
    out["ttm"] = {
        "months": len(t),
        "market_potential": round(pot, 2),
        "rental_income": round(inc, 2),
        "capture_rate": round(inc / pot, 6) if pot else None,
        "ltl_pct": round(ltl / pot, 6) if pot else None,
    }
    return out


MONTHS_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def month_label(key):
    """'2025-08' -> 'Aug 25'.

    The year is not decoration here. monthly_pl's own labels are the bare
    month, which is unambiguous over one statement's twelve columns; this
    axis is the union of several properties' windows and already spans
    fourteen months, so it carries two Julys and a bare label would put them
    on the same tick in the reader's head.
    """
    y, m = key.split("-")
    return f"{MONTHS_ABBR[int(m) - 1]} {y[2:]}"


def expense_trend(pl_props):
    """metrics.json's expense_trend block -- every property's expense line.

    Two things this has to get right, and both would be invisible in the
    numbers:

    * **The axis is the union of the properties' months, keyed on YYYY-MM.**
      The statements do not cover the same window -- The Landing's runs
      Aug 25-Aug 26 and Palma's Jul 25-Jun 26 -- so lining the series up by
      position would plot Palma's July against The Landing's August and draw
      the offset as a swing in spending. A property with no statement for a
      month gets null, and the card breaks its line there rather than joining
      across it.

    * **The lines are not all the same expense row.** The Landing's is total
      expenses (jpm 549999-9999); Palma's is recoverable operating opex,
      because the Align tree has no counterpart to that row -- see
      expense_anchor_for(). Two different expense loads on one axis, so each
      line carries its own scope and anchor and the block flags the
      disagreement rather than printing one basis over both.
    """
    months = sorted({m for p in pl_props for m in p["months"]})
    out = []
    for p in pl_props:
        by_month = dict(zip(p["months"], p["opex"]))
        out.append({
            "slug": p["slug"],
            "name": p["name"],
            "data": [by_month.get(m) for m in months],
            "first_month": p["months"][0] if p["months"] else None,
            "last_month": p["months"][-1] if p["months"] else None,
            "period_end": p["period_end"],
            "expense_scope": p["expense_scope"],
            "expense_anchor": p["expense_anchor"],
            "basis": p["basis"],
        })
    scopes = {p["expense_scope"] for p in out}
    return {
        "available": bool(out),
        "months": months,
        "labels": [month_label(m) for m in months],
        "properties": out,
        # True where the lines are not the same expense row, which the card
        # has to say out loud: it is the same trap the Expense Ratio card
        # carries a per-property basis for.
        "mixed_scope": len(scopes) > 1,
        "basis": "Monthly expenses per property, from each property's own "
                 "12-month accrual statement",
    }


# A bedroom type needs this many current comp listings before the market is
# allowed to set a rent for it. Below it the building's own Yardi figure is
# kept and the bedroom is NAMED as unverified -- The Landing's 16 three-beds
# have two comparable listings in the whole submarket, and two listings is a
# pair of asking prices rather than a market.
MIN_BED_FOR_IMPLIED = 5


def bedroom_mix(ud_prop):
    """Units, floor area and the Yardi market rent, per bedroom count.

    The unit directory is the only feed that says how many bedrooms a floorplan
    has, which is what makes a building comparable to a market at all: a comp
    median is per bedroom, and the rent roll names plans without defining them.

    The rent here is the midpoint of each plan's published min/max times its
    units, so it is an ESTIMATE of the directory's market rent table and says
    so wherever it is published. The exact per-unit sum is not in the stored
    directory; the statement's own gross potential rent is the tied-out twin of
    this figure and is published beside it for exactly that reason.
    """
    mix, no_rent = {}, []
    for code, pl in sorted((ud_prop.get("plans") or {}).items()):
        bed, units = pl.get("bedrooms"), pl.get("units") or 0
        if bed is None or not units:
            continue
        m = mix.setdefault(bed, {"bed": bed, "units": 0, "sqft": 0.0,
                                 "yardi_rent": 0.0, "plans": 0, "priced": 0})
        m["units"] += units
        m["sqft"] += (pl.get("sqft_avg") or 0) * units
        m["plans"] += 1
        lo, hi = pl.get("rent_min"), pl.get("rent_max")
        if lo is None or hi is None:
            no_rent.append(code)
        else:
            m["yardi_rent"] += (lo + hi) / 2 * units
            m["priced"] += units
    return mix, no_rent


def comp_implied(mix, ring, premium):
    """What this building's whole market rent table would be at comp asking.

    Per bedroom, because that is the unit the market quotes in and the one
    size-match can be checked on. The subject's own long-run premium to the
    ring is applied rather than nothing: a comp median is the middle of the
    submarket, and a building that has asked 6% over that middle for three
    years is worth 6% over it today. Withholding the premium would understate
    the answer exactly as much as ignoring the comps overstates it, so both
    are published — `premium` is a field here, not a constant.
    """
    rows, total, unverified = [], 0.0, []
    for bed in sorted(mix):
        m = mix[bed]
        c = ((ring or {}).get("by_bed") or {}).get(str(bed))
        subject_sqft = m["sqft"] / m["units"] if m["units"] else None
        if c and c["n"] >= MIN_BED_FOR_IMPLIED:
            rent, source = c["median_rent"] * (1 + premium), "comps"
        else:
            rent = m["yardi_rent"] / m["priced"] if m["priced"] else None
            source, _ = "yardi", unverified.append(bed)
        if rent is None:
            continue
        total += rent * m["units"]
        rows.append({
            "bed": bed, "units": m["units"],
            "subject_sqft": round(subject_sqft, 1) if subject_sqft else None,
            "comp_sqft": c["median_sqft"] if c else None,
            "comp_n": c["n"] if c else 0,
            "comp_median_rent": c["median_rent"] if c else None,
            "size_gap": (round(subject_sqft / c["median_sqft"] - 1, 4)
                         if c and subject_sqft and c["median_sqft"] else None),
            "yardi_rent": (round(m["yardi_rent"] / m["priced"], 2)
                           if m["priced"] else None),
            "rent": round(rent, 2), "total": round(rent * m["units"], 2),
            "source": source,
        })
    return {"rows": rows, "total": round(total, 2), "unverified_beds": unverified,
            "premium": premium}


def comps_verification(section, ud_prop, rr_prop, rc_prop):
    """The Yardi market rent table, measured against the market it claims.

    Four figures for one number, and the point of the card is that three of
    them agree. Two are Yardi's own (the rent roll's market rent column and the
    unit directory's table), one is the general ledger's copy of it (the
    statement's gross market rent potential, which is the same table booked as
    revenue), and one is the market's. Where the three Yardi figures disagree
    with EACH OTHER, the disagreement dates the change — which is what a single
    comparison against the comps could never do.

    Returns None when the property has no directory, since without a bedroom
    mix there is nothing to apply a comp median to.
    """
    if not ud_prop or not (ud_prop.get("plans") or {}):
        return None
    mix, no_rent = bedroom_mix(ud_prop)
    if not mix:
        return None
    premium = ((section.get("premium") or {}).get("median")) or 0.0
    rings = section.get("rings") or []
    primary = next((r for r in rings if r.get("primary")), None)
    implied = comp_implied(mix, primary, premium)
    if not implied["rows"]:
        return None

    sources, base = [], implied["total"]
    gap = lambda v: round(v / base - 1, 4) if base else None      # noqa: E731

    if rr_prop and rr_prop.get("market_rent_total"):
        sources.append({
            "key": "rent_roll", "label": "Rent roll",
            "detail": "the market rent column, unit by unit",
            "as_of": rr_prop.get("as_of"), "source_file": rr_prop.get("source_file"),
            "market_rent": rr_prop["market_rent_total"],
            "units": rr_prop.get("units"), "psf": rr_prop.get("market_psf"),
            "gap": gap(rr_prop["market_rent_total"]), "exact": True,
        })
    directory_total = sum(m["yardi_rent"] for m in mix.values())
    if directory_total:
        sources.append({
            "key": "unit_directory", "label": "Unit directory",
            "detail": "each plan's published market rent, midpoint of its range",
            "as_of": ud_prop.get("as_of"), "source_file": ud_prop.get("source_file"),
            "market_rent": round(directory_total, 2),
            "units": sum(m["priced"] for m in mix.values()),
            "gap": gap(directory_total), "exact": False,
        })
    if rc_prop and rc_prop.get("market_potential"):
        pot = rc_prop["market_potential"][-1]
        sources.append({
            "key": "statement", "label": "T12 statement",
            "detail": "gross market rent potential, the same table booked as revenue",
            "as_of": rc_prop.get("period_end"),
            "month": (rc_prop.get("months") or [None])[-1],
            "market_rent": pot, "gap": gap(pot), "exact": True,
        })
    sources.append({
        "key": "comp_implied", "label": "Comp-implied",
        "detail": (f"comp median asking rent by bedroom, plus this building's own "
                   f"{premium:+.1%} long-run premium to its submarket"),
        "as_of": section.get("as_of"), "market_rent": implied["total"],
        "gap": 0.0, "exact": False,
    })

    # The same build-up at every ring the export was cut into, so the answer
    # carries its own sensitivity: a gap that survives three comp sets is a
    # finding, and one that does not is a choice of radius.
    sensitivity = []
    for r in rings:
        alt = comp_implied(mix, r, premium)
        if not alt["rows"]:
            continue
        rr = (rr_prop or {}).get("market_rent_total")
        sensitivity.append({
            "radius_mi": r.get("radius_mi"), "primary": bool(r.get("primary")),
            "properties": r.get("properties"), "listings": r.get("listings"),
            "implied": alt["total"],
            "gap": round(rr / alt["total"] - 1, 4) if rr and alt["total"] else None,
        })

    # The headline is the newest Yardi reading of the table, which is normally
    # the rent roll -- it is the one that is per-unit, current and used as the
    # denominator of loss to lease. A property with no roll in the pipeline
    # still has a table worth checking, so the directory stands in and the card
    # names which one it is rather than going blank on a property that has one
    # fewer feed.
    headline = next((s for s in sources if s["key"] == "rent_roll"), None) \
        or next((s for s in sources if s["key"] == "unit_directory"), None)
    out = {
        "implied": implied,
        "sources": sources,
        "sensitivity": sensitivity,
        "unpriced_plans": no_rent,
        "basis": (f"Comp median asking rent per bedroom on the "
                  f"{section.get('primary_radius_mi')} mi ring, times the "
                  f"subject's own median premium to that ring, applied to the "
                  f"unit directory's bedroom mix"),
    }
    if headline:
        over = headline["market_rent"] - implied["total"]
        out["headline"] = {
            "gap": headline["gap"], "dollars": round(over, 2),
            "annual": round(over * 12, 2), "source": headline["key"],
            "label": headline["label"], "exact": headline.get("exact"),
            "as_of": headline["as_of"], "source_file": headline.get("source_file"),
        }
        # What the published loss to lease becomes on a market rent the comps
        # support. The occupied share is the roll's own -- market rent is not
        # flat across units, so scaling the total by it beats assuming it is.
        occ_share = (((rr_prop or {}).get("market_rent_occupied") or 0)
                     / ((rr_prop or {}).get("market_rent_total") or 1))
        inplace = (rr_prop or {}).get("actual_rent_occupied")
        occ_market = implied["total"] * occ_share
        if inplace and occ_market:
            out["headline"]["ltl_published"] = (rr_prop or {}).get("loss_to_lease_pct")
            out["headline"]["ltl_restated"] = round(
                (occ_market - inplace) / occ_market, 4)
    return out


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

    # The budgeted twin of the block above, for the Portfolio tab's Budget vs
    # Actual card. Published on explicit YYYY-MM month keys rather than on the
    # statement's bare "Aug".."Jul" labels, because this series spans calendar
    # years by construction -- the whole point of it is to line a plan up
    # against a T12 window that starts in one year and ends in the next, and
    # bare labels cannot say which year a month belongs to.
    budget_props = []
    for p_ in props:
        if not p_.get("active", True):
            continue
        fp = DATA / p_["slug"] / "budget.json"
        if not fp.exists():
            continue
        raw = json.load(open(fp))
        years = raw.get("years")
        if years is None:                      # pre-per-year file: one flat plan
            years = [raw] if raw.get("year") is not None else []
        years = [y for y in years if y.get("buckets") and y.get("year") is not None]
        if not years:
            continue
        years.sort(key=lambda y: y["year"])
        lo, hi = years[0]["year"], years[-1]["year"]
        months = [f"{y}-{m:02d}" for y in range(lo, hi + 1) for m in range(1, 13)]
        by_year = {y["year"]: y for y in years}
        # A category a covered year does not carry is a real zero -- that year's
        # buckets tie out against its own TOTAL EXPENSES, so nothing is missing
        # from it. A month in a year with NO budget on file is null, and the
        # card draws no bar there rather than a plan of nothing.
        names = sorted({n for y in years for n in y["buckets"]})
        buckets = {n: [] for n in names}
        revenue, opex = [], []
        for key in months:
            yr, mo = int(key[:4]), int(key[5:]) - 1
            y = by_year.get(yr)
            for n in names:
                buckets[n].append(None if y is None
                                  else round((y["buckets"].get(n) or [0.0] * 12)[mo], 2))
            revenue.append(None if y is None else (y.get("revenue_monthly") or [None] * 12)[mo])
            opex.append(None if y is None else (y.get("opex_operating_monthly") or [None] * 12)[mo])
        missing = sorted(set(range(lo, hi + 1)) - set(by_year))
        if missing:
            print(f"[warn] {p_['name']}: no budget on file for "
                  f"{', '.join(str(y) for y in missing)} -- those months publish "
                  f"as unplanned rather than as zero")
        budget_props.append({
            "slug": p_["slug"], "name": p_["name"],
            "months": months,
            "buckets": buckets,
            "revenue": revenue,
            "opex_operating": opex,
            "years": [{"year": y["year"], "source_file": y.get("source_file"),
                       "landed_at": y.get("landed_at"), "as_of": y.get("as_of"),
                       "tieout_gap": y.get("buckets_tieout_gap")} for y in years],
            "years_missing": missing,
            "basis": ("Yardi 12-month budget accrual, grouped on the Align account "
                      "tree through config/coa_map.json and tied out against each "
                      "file's own total expenses month by month -- the same basket "
                      "the actuals' expense buckets carry"),
        })
        print(f"[ok] budget for {p_['name']}: {len(years)} year(s) "
              f"({lo}-{hi}), {len(names)} bucket(s)")
    metrics["budget"] = {"available": bool(budget_props),
                         "properties": budget_props}

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
                         "placeholder_units": ud.get("placeholder_units"),
                         # What the export lists that the dashboard does not
                         # count, named — the gap between the export's own total
                         # and the building has to be explainable on the page.
                         "non_residential_units": ud.get("non_residential_units"),
                         "non_residential": ud.get("non_residential") or [],
                         "codes": [s.get("property_code") for s in ud.get("sections") or []],
                         "plans": ud.get("plans") or {}})
    metrics["unit_directory"] = {"available": bool(ud_props), "properties": ud_props}

    # The rent roll, as aggregates and a top-gap table. data/<slug>/rent_roll.json
    # is gitignored because it is per-unit and arrives with resident names; what
    # is published here is the scrubbed roll-up the cards draw, in the same shape
    # the workbook-fed Landing tab publishes its own (per-unit rows, no names).
    rr_props = []
    for p in props:
        if not p.get("active", True):
            continue
        fp = DATA / p["slug"] / "rent_roll.json"
        if not fp.exists():
            continue
        summary = rent_roll_summary(json.load(open(fp)))
        summary.update({"slug": p["slug"], "name": p["name"]})
        rr_props.append(summary)
        print(f"[ok] rent roll for {p['name']}: {summary['occupied']}/{summary['units']} "
              f"occupied, loss to lease {summary['loss_to_lease_pct']:.1%} "
              f"as of {summary['as_of']}")
    if rr_props:
        metrics["rent_roll"] = {"available": True, "properties": rr_props}
    elif "rent_roll" in metrics:
        # No roll on disk this run (it is gitignored, so a fresh clone has none
        # until fetch_drive runs). Keep the last published block rather than
        # blanking three cards on a checkout that simply has not fetched yet.
        print("[info] no rent_roll.json on disk; leaving existing metrics.json block as-is")

    # New-lease trade-outs and renewal offers, by month, for the Trade-outs
    # card on the Drive tab. Two feeds, one block: the weekly leasing workbook
    # accumulates a week at a time and the renewal tracker arrives whole.
    leasing_props = []
    for p in props:
        if not p.get("active", True):
            continue
        slug = p["slug"]
        entry = {"slug": slug, "name": p["name"]}

        fp = DATA / slug / "leasing_detail.json"
        if fp.exists():
            weeks = json.load(open(fp)).get("weeks") or []
            # Bucketed by the month of the WEEK the lease was signed, not by
            # its scheduled move-in: the card plots when the rent was struck,
            # and a lease signed in August for a September move-in belongs to
            # August's trade-out. The workbook-fed card uses its lease date the
            # same way.
            months = {}
            for w in weeks:
                key = (w.get("week_ending") or "")[:7]
                if not key:
                    continue
                b = months.setdefault(key, {"month": key, "leases": 0,
                                            "lease_rent": 0.0, "prior_rent": 0.0,
                                            "tradeouts": []})
                for lease in w.get("leases") or []:
                    if lease.get("tradeout_pct") is None:
                        continue
                    b["leases"] += 1
                    b["lease_rent"] += lease.get("lease_rent") or 0
                    b["prior_rent"] += lease.get("prior_rent") or 0
                    b["tradeouts"].append(lease["tradeout_pct"])
            rows = []
            for key in sorted(months):
                b = months[key]
                if not b["leases"]:
                    continue
                rows.append({
                    "month": key, "leases": b["leases"],
                    "lease_rent": round(b["lease_rent"], 2),
                    "prior_rent": round(b["prior_rent"], 2),
                    # both averages, named: the plain mean is what the chart
                    # draws, the rent-weighted one is what a dollar-weighted
                    # read would give, and they are not the same number
                    "mean_tradeout": round(sum(b["tradeouts"]) / b["leases"], 6),
                    "wtd_tradeout": (round(b["lease_rent"] / b["prior_rent"] - 1, 6)
                                     if b["prior_rent"] else None),
                })
            allto = [t for b in months.values() for t in b["tradeouts"]]
            newest = max((w.get("week_ending") or "") for w in weeks) if weeks else None
            entry["new_leases"] = {
                "weeks": len(weeks), "as_of": newest,
                "landed_at": max((w.get("landed_at") or "") for w in weeks) or None
                             if weeks else None,
                "source_file": next((w.get("source_file") for w in reversed(weeks)
                                     if w.get("week_ending") == newest), None),
                "months": rows,
                "leases": len(allto),
                "mean_tradeout": round(sum(allto) / len(allto), 6) if allto else None,
            }

        fp = DATA / slug / "renewal_tracker.json"
        if fp.exists():
            rt = json.load(open(fp))
            mtm = rt.get("mtm") or {}
            entry["renewals"] = {
                "as_of": rt.get("as_of"), "covers": rt.get("covers"),
                "landed_at": rt.get("landed_at"), "source_file": rt.get("source_file"),
                "months": [{k: m.get(k) for k in
                            ("month", "leases", "mean_increase", "wtd_increase",
                             "current_rent", "offered_rent", "statuses")}
                           for m in rt.get("months") or []],
                # roster aggregates only; the per-unit rows stay in data/
                "mtm": {k: mtm.get(k) for k in
                        ("units", "current_rent", "market_rent", "statuses",
                         "rows_without_rent")} if mtm else None,
            }

        if "new_leases" in entry or "renewals" in entry:
            leasing_props.append(entry)
            nl = entry.get("new_leases") or {}
            rn = entry.get("renewals") or {}
            print(f"[ok] leasing for {p['name']}: {nl.get('leases', 0)} new lease(s) "
                  f"over {len(nl.get('months') or [])} month(s), "
                  f"{len(rn.get('months') or [])} month(s) of renewal offers")
    metrics["leasing"] = {"available": bool(leasing_props), "properties": leasing_props}

    # Lease trade-outs from the Yardi Lease Tradeout Report, which is the only
    # feed carrying a trade-out with its own history: one row per new lease with
    # the lease it replaced beside it. Published as the monthly series and a few
    # trailing windows rather than the rows themselves -- the rows are in
    # data/<slug>/lease_tradeout.json, and nothing on the page draws them one at
    # a time.
    #
    # `pct` everywhere here is the report's OWN definition: total current
    # effective rent over total previous effective rent. The mean of the
    # per-lease percentages is published beside it as `mean_pct` and is not
    # interchangeable -- concessions push a previous effective rent toward zero
    # (one lease on The Landing reads $86 against a $62,716 concession and
    # prints 6,136%), so the mean runs 70.1% where the weighted figure is 23.4%.
    to_props = []
    for p in props:
        if not p.get("active", True):
            continue
        fp = DATA / p["slug"] / "lease_tradeout.json"
        if not fp.exists():
            continue
        held = json.load(open(fp))
        leases = held.get("leases") or []
        if not leases:
            continue
        mod = importlib.import_module("parse_lease_tradeout")
        files = held.get("files") or []
        entry = {
            "slug": p["slug"], "name": p["name"],
            "as_of": held.get("as_of"),
            "period_start": min((f.get("period_start") or "") for f in files) or None,
            "period_end": held.get("as_of"),
            "rate_type": held.get("rate_type"),
            "lease_date_basis": held.get("lease_date_basis"),
            "tradeout_basis": held.get("tradeout_basis"),
            "source_file": held.get("source_file"),
            "landed_at": held.get("landed_at"),
            "files": len(files),
            "all": mod.summarise(leases),
            "windows": {f"t{n}": mod.window(leases, n) for n in (3, 6, 12)},
        }
        entry["months"] = (entry["all"] or {}).pop("months", [])
        to_props.append(entry)
        a, w = entry["all"], entry["windows"].get("t3") or {}
        print(f"[ok] lease trade-outs for {p['name']}: {a['leases']} lease(s) "
              f"{entry['period_start']}..{entry['period_end']}, "
              f"{a['pct']:.1%} weighted over the whole window, "
              f"{w.get('pct', 0):.1%} over the trailing 3 months")
    metrics["lease_tradeout"] = {"available": bool(to_props), "properties": to_props}

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

    # The Portfolio tab's Expense Trend card: one total-expense line per
    # property on one axis, so the buildings are read against each other
    # rather than one at a time. Derived from pl_props above rather than
    # re-read from disk, so a month here and the same month on the Operating
    # Summary cannot disagree.
    metrics["expense_trend"] = expense_trend(pl_props)

    # Residential rental income, for the Loss to Lease card. Same shape as the
    # analyst workbook's rent_capture block on purpose: the page renders either
    # source through one renderer rather than two that can drift.
    rc_props = []
    for p in props:
        if not p.get("active", True):
            continue
        fp = DATA / p["slug"] / "rent_capture.json"
        if not fp.exists():
            continue
        pts = json.load(open(fp))["points"]
        if not pts:
            continue
        latest = pts[-1]
        series = stitch_rent_capture(pts, f"{p['name']} rent capture")
        if series is None:
            continue
        rc_props.append({"slug": p["slug"], "name": p["name"],
                         "period_end": latest["period_end"],
                         **series,
                         "source_codes": latest.get("source_codes"),
                         "tieout_max_gap": latest.get("tieout_max_gap"),
                         "problems": latest.get("problems") or []})
    metrics["rent_capture"] = {"available": bool(rc_props), "properties": rc_props}

    # The market, and the Yardi market rent table measured against it. The three
    # blocks the verification joins are read back out of `metrics` rather than
    # from `data/`, because the rent roll's store is gitignored (per-unit, it
    # arrives with resident names) and so exists only during a pipeline run --
    # the published aggregate is what a fresh clone has, and it carries every
    # figure this needs. Same reasoning as rent_roll_ltl() in populate_scorecard.
    comps_props = []
    by_slug = lambda block, slug: next(                                # noqa: E731
        (x for x in ((metrics.get(block) or {}).get("properties") or [])
         if x.get("slug") == slug), None)
    for p in props:
        if not p.get("active", True):
            continue
        fp = DATA / p["slug"] / "comps.json"
        if not fp.exists():
            continue
        c = json.load(open(fp))
        ver = comps_verification(c, by_slug("unit_directory", p["slug"]),
                                 by_slug("rent_roll", p["slug"]),
                                 by_slug("rent_capture", p["slug"]))
        comps_props.append({"slug": p["slug"], "name": p["name"],
                            **{k: v for k, v in c.items()
                               if k not in ("report_type", "property_code")},
                            "verification": ver})
        if ver and ver.get("headline"):
            h = ver["headline"]
            print(f"[ok] market comps for {p['name']}: {h.get('label', 'Yardi')} "
                  f"market rent is {h['gap']:+.1%} against the comp-implied "
                  f"figure (${h['dollars']:,.0f}/mo)")
        else:
            print(f"[ok] market comps for {p['name']}: market side only "
                  f"(no unit directory or no rent roll to verify against)")
    metrics["comps"] = {"available": bool(comps_props), "properties": comps_props}

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

"""
parse_comps.py
--------------
Parses the **HelloData market-comp export** (Drive `Comps`) into the comp
aggregates behind the `Market Comps` tab — the first feed on this dashboard
that describes the market rather than the buildings.

It exists because the Yardi *market rent* column is set by the property team
and nothing in the pipeline could tell whether it was right. Every other feed
here is a statement about Align's own buildings; this one is a statement about
what everyone else is asking, which is the only thing a market rent can be
checked against.

The export arrives as two files with near-identical names:

  * ``HelloData - Simple - …xlsx`` — two flat tables, ``Property Data`` (one
    row per building) and ``Availability`` (one row per listing, back three
    years). This is the one the pipeline reads.
  * ``HelloData - Full - …xlsx`` — the same market as a twenty-sheet formatted
    workbook for reading by eye, with no parseable table in it. It has no
    parser, and is **skipped by name of its own layout** rather than half-read
    or failed on: see ``_pick_tables``. Both files are filed into `Comps` on
    purpose, so the entry claims everything in the folder (a HelloData export
    renamed tomorrow is still read) and this one file says in one log line why
    it is not being read, instead of reading as a broken feed.

What it publishes is **aggregates only** — medians, counts and shares by
bedroom and by month. The listing rows themselves are a licensed vendor
dataset, and `docs/` is served to anyone with the URL (see the PII note in
CLAUDE.md: there is no "on the page but not downloadable" on a static site).
The same reasoning that keeps residents out of `data/` keeps HelloData's rows
out of it.

**There is no total row to tie out against.** Every other parser here checks
itself against the report's own arithmetic; a comp export has none, so two
structural reconciliations stand in, and both are real failures rather than
formalities:

  * **Every building in `Availability` must be described in `Property Data`.**
    The comp ring is built by distance, and the coordinates live only in
    `Property Data` — so a listing whose building is missing from it is
    silently dropped from every ring, and the comp set quietly shrinks to
    whatever happened to be described. Refused.
  * **`Days on Market` must reconcile to the listing's own dates.** It is
    ``(removed − first listed) + 1`` on all 6,334 closed listings in the first
    file, inclusive of both ends. If that stops holding, the column means
    something else and the days-on-market comparison — which is half the
    evidence that an asking rent is too high — is measuring nothing. Refused
    below 99% agreement rather than published.

Four things it is careful about, each of which would publish a wrong number:

  * **Align's own buildings are not comps.** Chorus, The Madelon and The
    Landing are all in this file, because HelloData scrapes whatever is in the
    market. Leaving them in lets one Align property's pricing validate
    another's, and at three of thirty-six buildings that is not a rounding
    error. They are excluded by resolving each building against
    `config/properties.json` — the property master, not the export's own
    ``Management Company`` string, which is a free-text field that changes when
    a management company renames itself.
  * **A floorplan row is not a unit.** ``Is Floorplan`` marks plan-level
    summary rows that repeat their plan's units; counting them alongside the
    unit rows weights a building by how many plans it publishes. Skipped, and
    counted, so the number that was skipped is visible.
  * **A listing is only current on the file's own as-of date.** Every row
    carries the ``As Of`` of the snapshot that observed it, three years deep.
    Reading the whole sheet as "the market today" blends 2023 prices into a
    2026 median — and the market in this file moved +64% over that span, so it
    is not a small error. The current set is ``As Of == the file's newest`` and
    not yet removed.
  * **The premium baseline is a median, not a mean.** The subject's premium to
    its ring is what turns a comp median into an expected rent for *this*
    building, and it is taken across every quarter the file covers. A median
    is what lets the current quarter be measured against the baseline while
    still being inside it: one anomalous quarter moves a 14-quarter median by
    a fraction of a point and a mean by whatever it likes.

Usage:
    from parse_comps import parse
    result = parse("path/to/HelloData - Simple - ….xlsx")
"""
import json
import math
import os
import re
import statistics
import sys

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xlsx_anchors import LayoutError, norm  # noqa: E402

REPORT_TYPE = "market_comps"

# The rings the export is cut into. The primary one is the submarket the
# subject actually competes in; the others are published beside it so the
# answer carries its own sensitivity rather than resting on one radius.
# 1.35 miles is Dogpatch plus Mission Bay for The Landing -- past that the
# product and the market both change (Mid-Market, Hayes Valley), which is
# visible in the figures: the same building reads +11% against this ring and
# +20% against everything in the file.
PRIMARY_RADIUS_MI = 1.35
RINGS = (0.75, 1.35, None)          # None = every building in the file

# A quarter counts toward the premium baseline only when both sides put enough
# listings on the market to have a median worth taking, and a BEDROOM counts
# toward that quarter's premium only on the same terms -- one listing is a
# price, not a median, and the subject puts a single three-bed on the market
# in half the quarters in the first file.
MIN_QUARTER_LISTINGS = 5
MIN_BED_LISTINGS = 3
# Days on market is read over a trailing window rather than the whole file:
# it is a statement about how the building is leasing now.
DOM_WINDOW_MONTHS = 12
# Below this, the `Days on Market` column no longer means what the dates say.
DOM_TIEOUT_MIN = 0.99
# A bedroom comparison is only like-for-like while the two sides are the same
# size. Past this the page says so rather than letting the median stand.
SIZE_GAP_TOLERANCE = 0.10

PROPERTY_SHEET = "Property Data"
LISTING_SHEET = "Availability"

PROPERTY_COLUMNS = ("Building Name", "Street Address", "City", "Zip Code",
                    "Latitude", "Longitude", "# Units", "Year Built", "As Of")
LISTING_COLUMNS = ("Building Name", "Is Floorplan", "Bed", "First Listed",
                   "Listing Removed", "Days on Market", "Sqft", "Mkt Price",
                   "Eff Price", "As Of")


# ---- small helpers --------------------------------------------------------

def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.replace(",", "").replace("$", "").strip()
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _date(v):
    """A YYYY-MM-DD string, or None. Dates arrive as text in this export."""
    if v is None:
        return None
    s = str(v)[:10]
    return s if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else None


def _days(a, b):
    """Whole days from a to b, on two YYYY-MM-DD strings."""
    import datetime as dt
    d = lambda s: dt.date(int(s[:4]), int(s[5:7]), int(s[8:10]))  # noqa: E731
    return (d(b) - d(a)).days


def _shift_months(key, back):
    """YYYY-MM moved back N months."""
    y, m = int(key[:4]), int(key[5:7])
    total = y * 12 + (m - 1) - back
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def _quarter(day):
    return f"{day[:4]}Q{(int(day[5:7]) - 1) // 3 + 1}"


def _median(vals):
    vals = [v for v in vals if v is not None]
    return statistics.median(vals) if vals else None


def _miles(a, b):
    """Great-circle miles between two (lat, lng) pairs."""
    lat1, lng1 = math.radians(a[0]), math.radians(a[1])
    lat2, lng2 = math.radians(b[0]), math.radians(b[1])
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2)
    return 2 * 3958.8 * math.asin(min(1.0, math.sqrt(h)))


def _rows(ws, required, sheet_name):
    """The sheet as dicts keyed by its header row."""
    it = ws.iter_rows(values_only=True)
    try:
        header = [str(h).strip() if h is not None else None for h in next(it)]
    except StopIteration:
        raise LayoutError(f"{sheet_name!r} is empty")
    missing = [c for c in required if c not in header]
    if missing:
        raise LayoutError(f"{sheet_name!r} is missing column(s): "
                          f"{', '.join(missing)}")
    out = []
    for r in it:
        if r is None or r[0] is None or str(r[0]).strip() == "":
            continue
        out.append(dict(zip(header, r)))
    return out


def _align_buildings(config=None):
    """Normalised building name -> Align property name, from the master.

    Read from `config/properties.json` rather than from the export's own
    management-company column: the master is what every other feed routes
    through, so a property added there is excluded from the comp sets (and
    picked up as a subject) without anyone remembering this file exists.
    """
    if config is None:
        config = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "..", "config", "properties.json")
    out = {}
    for p in json.load(open(config))["properties"]:
        for w in [p["name"]] + list(p.get("aliases") or []):
            out[norm(w)] = p["name"]
    return out


def _pick_tables(wb):
    """The two flat tables, or None when this is the formatted workbook.

    None is a skip rather than an error, and the difference matters in the
    log: this file is not a broken export, it is the other half of a pair the
    filer is right to put here. `parse` turns it into one line saying so.
    """
    names = set(wb.sheetnames)
    if PROPERTY_SHEET in names and LISTING_SHEET in names:
        return wb[PROPERTY_SHEET], wb[LISTING_SHEET]
    return None


# ---- the per-subject cut --------------------------------------------------

def _bed_stats(listings, bed):
    ls = [x for x in listings if x["bed"] == bed]
    if not ls:
        return None
    return {
        "n": len(ls),
        "median_rent": round(_median([x["rent"] for x in ls]), 2),
        "mean_rent": round(sum(x["rent"] for x in ls) / len(ls), 2),
        "median_sqft": round(_median([x["sqft"] for x in ls]), 1),
        "median_psf": round(_median([x["rent"] / x["sqft"] for x in ls]), 4),
    }


def _series(subject_rows, comp_rows, beds, key_of, detail=False):
    """Median asking $/sqft per period, subject against the ring.

    Keyed on when a unit was **first listed**, not on the snapshot that saw it:
    a listing that sits for five months would otherwise report its April price
    in every month to September, which is the shape of the very problem this
    series exists to show.

    The two `_psf` figures are pooled across bedroom types, because that is
    what a reader wants a line to be. **The premium is not**: it is taken per
    bedroom and then weighted back together by how many units the subject
    listed, since a pooled ratio moves with the unit MIX as much as with
    price. A quarter in which the subject happened to list mostly one-beds
    reads high on pooled $/sqft and says nothing about pricing -- 2025Q1 is
    that quarter in the first file, pooled −16.0% against a bed-weighted
    −3.6%, and it is the baseline this whole feed is measured against.
    """
    out = {}
    for label, rows in (("subject", subject_rows), ("comp", comp_rows)):
        for x in rows:
            if x["bed"] not in beds or not x["first_listed"]:
                continue
            out.setdefault(key_of(x["first_listed"]), {}) \
               .setdefault(label, {}).setdefault(x["bed"], []) \
               .append(x["rent"] / x["sqft"])
    points = []
    for key in sorted(out):
        s_by, c_by = out[key].get("subject", {}), out[key].get("comp", {})
        s = [p for v in s_by.values() for p in v]
        c = [p for v in c_by.values() for p in v]
        sm, cm = _median(s), _median(c)
        num = den = 0
        by_bed = {}
        for bed in sorted(s_by):
            sv, cv = s_by[bed], c_by.get(bed, [])
            if len(sv) < MIN_BED_LISTINGS or len(cv) < MIN_BED_LISTINGS:
                continue
            ratio = _median(sv) / _median(cv) - 1
            by_bed[str(bed)] = {"premium": round(ratio, 4), "subject_n": len(sv),
                                "comp_n": len(cv)}
            num += ratio * len(sv)
            den += len(sv)
        pt = {
            "key": key,
            "subject_psf": round(sm, 4) if sm else None,
            "subject_n": len(s),
            "comp_psf": round(cm, 4) if cm else None,
            "comp_n": len(c),
            "premium": round(num / den, 4) if den else None,
            "premium_beds": len(by_bed),
        }
        if detail:
            pt["by_bed"] = by_bed
        points.append(pt)
    return points


def _cut(subject, buildings, listings, as_of, related):
    """One Align property's view of the market."""
    here = (subject["lat"], subject["lng"])
    for b in buildings.values():
        b["miles"] = round(_miles(here, (b["lat"], b["lng"])), 3)

    sub_rows = [x for x in listings if x["building"] == subject["key"]]
    # Every building that is not Align's own. `related` is the whole master,
    # so a second Align building in this market is out of the comp set the day
    # it is added to config/properties.json rather than the day someone
    # remembers this file.
    comp_keys = {k for k, b in buildings.items() if k not in related}
    comp_rows = [x for x in listings if x["building"] in comp_keys]

    def ring_keys(radius):
        return {k for k in comp_keys
                if radius is None or buildings[k]["miles"] <= radius}

    current = lambda rows: [x for x in rows if x["current"]]          # noqa: E731
    sub_now = current(sub_rows)
    beds_present = sorted({x["bed"] for x in sub_rows})
    # The RING is cut on every bedroom the market has, not only the ones the
    # subject happens to have listed. The build-up in build_metrics needs a
    # comp median for every bedroom the BUILDING owns, and a building can go
    # three years without listing one of them -- The Landing's sixteen
    # three-beds turned over twice. Falling back to the building's own rent
    # because nobody collected the market is a different thing from falling
    # back because the market is too thin to read, and only the second is a
    # finding.
    market_beds = sorted({x["bed"] for x in comp_rows} | set(beds_present))

    rings = []
    for radius in RINGS:
        keys = ring_keys(radius)
        now = [x for x in comp_rows if x["building"] in keys and x["current"]]
        rings.append({
            "radius_mi": radius,
            "primary": radius == PRIMARY_RADIUS_MI,
            "properties": len(keys),
            "listings": len(now),
            "by_bed": {str(b): _bed_stats(now, b) for b in market_beds
                       if _bed_stats(now, b)},
        })

    primary = ring_keys(PRIMARY_RADIUS_MI)
    prim_rows = [x for x in comp_rows if x["building"] in primary]
    prim_now = [x for x in prim_rows if x["current"]]

    # The beds the trend can honestly be drawn on: both sides have to have put
    # enough units on the market over the file's span for a monthly median to
    # mean anything. Computed rather than hardcoded, so a building of studios
    # gets its own answer.
    trend_beds = sorted(
        b for b in beds_present
        if sum(1 for x in sub_rows if x["bed"] == b) >= 10
        and sum(1 for x in prim_rows if x["bed"] == b) >= 10)

    quarters = _series(sub_rows, prim_rows, trend_beds, _quarter, detail=True)
    months = _series(sub_rows, prim_rows, trend_beds, lambda d: d[:7])

    graded = [q["premium"] for q in quarters
              if q["premium"] is not None
              and q["subject_n"] >= MIN_QUARTER_LISTINGS
              and q["comp_n"] >= MIN_QUARTER_LISTINGS]
    premium = {
        "median": round(statistics.median(graded), 4) if graded else None,
        "quarters": len(graded),
        "first": quarters[0]["key"] if quarters else None,
        "last": quarters[-1]["key"] if quarters else None,
        "beds": trend_beds,
        "basis": (f"median of the quarterly premium in asking $/sqft over "
                  f"{len(graded)} quarter(s) where both sides listed at least "
                  f"{MIN_QUARTER_LISTINGS} units, each quarter taken per "
                  f"bedroom and weighted back together by the subject's own "
                  f"listing counts"),
    }

    since = _shift_months(as_of[:7], DOM_WINDOW_MONTHS) + "-01"
    dom = {}
    for label, rows in (("subject", sub_rows), ("comp", prim_rows)):
        d = [x["dom"] for x in rows
             if x["dom"] is not None and x["removed"]
             and x["first_listed"] and x["first_listed"] >= since]
        dom[label + "_median"] = _median(d)
        dom[label + "_n"] = len(d)
    dom["since"] = since

    conc = {}
    for label, rows in (("subject", sub_now), ("comp", prim_now)):
        with_conc = [x for x in rows if x["eff"] is not None and x["eff"] < x["rent"]]
        conc[label + "_share"] = round(len(with_conc) / len(rows), 4) if rows else None
        conc[label + "_n"] = len(rows)

    # Size match, per bed, on the primary ring. A median rent is like-for-like
    # only while the two sides are the same size; past the tolerance the page
    # prints the gap instead of the comparison.
    size = {}
    for b in beds_present:
        s, c = _bed_stats(sub_now, b), _bed_stats(prim_now, b)
        if not s or not c:
            continue
        size[str(b)] = {
            "subject_sqft": s["median_sqft"], "comp_sqft": c["median_sqft"],
            "gap": round(s["median_sqft"] / c["median_sqft"] - 1, 4),
            "like_for_like": abs(s["median_sqft"] / c["median_sqft"] - 1) <= SIZE_GAP_TOLERANCE,
        }

    # The per-comp table wants a rent and a count, not the whole stat block:
    # this list is one row per building on the card, and the ring above it is
    # where the medians that get quoted live.
    def brief(rows, bed):
        s = _bed_stats(rows, bed)
        return {"n": s["n"], "median_rent": s["median_rent"],
                "median_sqft": s["median_sqft"]} if s else None

    return {
        "property_code": subject["building"],  # routes through `aliases`
        "subject": {k: subject[k] for k in
                    ("building", "address", "city", "zip", "units", "year_built",
                     "lat", "lng")},
        "as_of": as_of,
        "primary_radius_mi": PRIMARY_RADIUS_MI,
        "excluded_related": sorted(
            buildings[k]["building"] for k in related
            if k in buildings and k != subject["key"]),
        "subject_by_bed": {str(b): _bed_stats(sub_now, b) for b in beds_present
                           if _bed_stats(sub_now, b)},
        "rings": rings,
        "size_match": size,
        "premium": premium,
        "quarters": quarters,
        "months": months,
        "days_on_market": dom,
        "concessions": conc,
        "comps": sorted(
            ({"building": buildings[k]["building"], "address": buildings[k]["address"],
              "year_built": buildings[k]["year_built"],
              "units": buildings[k]["units"], "miles": buildings[k]["miles"],
              "listings": sum(1 for x in prim_now if x["building"] == k),
              "by_bed": {str(b): brief(
                  [x for x in prim_now if x["building"] == k], b)
                  for b in market_beds
                  if brief([x for x in prim_now if x["building"] == k], b)}}
             for k in primary),
            # Sorted on the NAME as well as the distance: `primary` is a set,
            # so ties broke in whatever order it happened to iterate and two
            # comps at the same distance swapped places between runs. That is a
            # spurious diff in data/<slug>/comps.json on every pipeline run,
            # which makes "did the comp set change?" unanswerable from a diff.
            key=lambda c: (c["miles"], c["building"])),
        "subject_listings": {
            "current": len(sub_now),
            "oldest_days": max((_days(x["first_listed"], as_of)
                                for x in sub_now if x["first_listed"]), default=None),
            "by_bed": {str(b): sum(1 for x in sub_now if x["bed"] == b)
                       for b in beds_present},
        },
    }


# ---- the parse ------------------------------------------------------------

def parse(path, strict=True):
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    tables = _pick_tables(wb)
    if tables is None:
        return {
            "report_type": REPORT_TYPE,
            "source_file": os.path.basename(path),
            "sections": [],
            "skip": (f"no {PROPERTY_SHEET!r}/{LISTING_SHEET!r} tables in "
                     f"{len(wb.sheetnames)} sheet(s) -- this is HelloData's "
                     f"formatted workbook, and the pipeline reads the 'Simple' "
                     f"export, which carries the same market as two flat "
                     f"tables. Both are filed in Comps on purpose; nothing is "
                     f"missing"),
            "checks": [], "problems": [],
        }
    pws, lws = tables
    prop_rows = _rows(pws, PROPERTY_COLUMNS, PROPERTY_SHEET)
    list_rows = _rows(lws, LISTING_COLUMNS, LISTING_SHEET)

    checks, problems = [], []

    buildings = {}
    for r in prop_rows:
        lat, lng = _num(r["Latitude"]), _num(r["Longitude"])
        if lat is None or lng is None:
            problems.append(f"{r['Building Name']!r} has no coordinates and "
                            f"cannot be placed in a ring")
            continue
        key = norm(r["Building Name"])
        buildings[key] = {
            "key": key,
            # NOT "name": that key is in build_metrics.PII_FIELDS and the
            # central scrub drops it from everything on its way to data/.
            # These are buildings, so call them buildings -- weakening a scrub
            # that exists to keep residents out of a public file, in order to
            # publish a comp table, would be the wrong way round.
            "building": str(r["Building Name"]).strip(),
            "address": str(r["Street Address"] or "").strip(),
            "city": str(r["City"] or "").strip(),
            "zip": str(r["Zip Code"] or "").strip(),
            "units": int(_num(r["# Units"]) or 0) or None,
            "year_built": int(_num(r["Year Built"]) or 0) or None,
            "lat": lat, "lng": lng,
        }

    # --- the coverage reconciliation. A listing whose building is not
    # described has no coordinates, so it falls out of every ring silently and
    # the comp set becomes whatever happened to be described.
    unknown = sorted({str(r["Building Name"]).strip() for r in list_rows
                      if norm(r["Building Name"]) not in buildings})
    checks.append({"check": "every listed building is described in "
                            f"{PROPERTY_SHEET!r}",
                   "ok": not unknown, "buildings": len(buildings),
                   "missing": unknown[:5]})
    if unknown and strict:
        raise LayoutError(
            f"{len(unknown)} building(s) in {LISTING_SHEET!r} are not in "
            f"{PROPERTY_SHEET!r} ({', '.join(unknown[:3])}) -- their listings "
            f"carry no coordinates and would drop out of every comp ring")

    as_of = max((_date(r["As Of"]) for r in list_rows if _date(r["As Of"])),
                default=None)
    if not as_of:
        raise LayoutError(f"no readable 'As Of' date in {LISTING_SHEET!r}")

    plans = skipped = 0
    listings, dom_ok, dom_seen = [], 0, 0
    for r in list_rows:
        if r["Is Floorplan"]:
            plans += 1
            continue
        rent, sqft = _num(r["Mkt Price"]), _num(r["Sqft"])
        first, removed = _date(r["First Listed"]), _date(r["Listing Removed"])
        dom = _num(r["Days on Market"])
        if first and removed and dom is not None:
            dom_seen += 1
            if _days(first, removed) + 1 == dom:
                dom_ok += 1
        if not rent or not sqft or r["Bed"] is None:
            skipped += 1
            continue
        listings.append({
            "building": norm(r["Building Name"]),
            "bed": int(_num(r["Bed"]) or 0),
            "rent": rent, "sqft": sqft, "eff": _num(r["Eff Price"]),
            "first_listed": first, "removed": removed, "dom": dom,
            "current": removed is None and _date(r["As Of"]) == as_of,
        })

    rate = dom_ok / dom_seen if dom_seen else 1.0
    checks.append({"check": "days on market reconciles to the listing's own dates",
                   "ok": rate >= DOM_TIEOUT_MIN, "closed_listings": dom_seen,
                   "agree": dom_ok, "rate": round(rate, 4),
                   "note": "(removed - first listed) + 1, inclusive of both ends"})
    if dom_seen and rate < DOM_TIEOUT_MIN and strict:
        raise LayoutError(
            f"'Days on Market' reconciles to its own dates on only "
            f"{rate:.1%} of {dom_seen} closed listings -- the column no longer "
            f"means days between listing and removal, so nothing on this feed "
            f"should be read as one")

    checks.append({"check": "floorplan summary rows are not counted as units",
                   "ok": True, "skipped": plans, "units_read": len(listings)})
    checks.append({"check": "listings with no price or no size are excluded",
                   "ok": True, "excluded": skipped})
    checks.append({"check": "the current set is the file's own as-of date",
                   "ok": True, "as_of": as_of,
                   "current": sum(1 for x in listings if x["current"])})

    related_map = _align_buildings()
    related = {k for k in buildings if k in related_map}
    checks.append({"check": "Align's own buildings are out of the comp set",
                   "ok": True,
                   "excluded": sorted(buildings[k]["building"] for k in related)})

    sections = []
    for key in sorted(related):
        sections.append(_cut(buildings[key], dict(buildings), listings, as_of,
                             related))
    if not sections:
        problems.append("no building in this export resolves to a property in "
                        "config/properties.json, so there is no subject to "
                        "measure the market against")

    return {
        "report_type": REPORT_TYPE,
        "vendor": "HelloData",
        "as_of": as_of,
        "source_file": os.path.basename(path),
        "market": str(prop_rows[0].get("MSA") or "").strip() or None,
        "properties_in_file": len(buildings),
        "listings_in_file": len(listings),
        "sections": sections,
        "checks": checks,
        "problems": problems,
    }


if __name__ == "__main__":
    out = parse(sys.argv[1])
    slim = dict(out)
    slim["sections"] = [{k: v for k, v in s.items()
                         if k not in ("comps", "months", "quarters")}
                        for s in out["sections"]]
    print(json.dumps(slim, indent=2, default=str))

#!/usr/bin/env python3
"""Guard tests for the market-comp feed behind the Market Comps tab.

This feed is different from every other one here: it is the only report about
the MARKET rather than about an Align building, and the number it exists to
check -- the Yardi market rent column -- is set by hand by the property team.
So a comp export that parses cleanly and reads slightly wrong does not produce
an obviously broken page; it produces a confident second opinion that happens
to be worthless, which is worse.

There is also no total row to tie out against. Every other parser here checks
itself against the report's own arithmetic; this one cannot, so two structural
reconciliations stand in and both are tested below.

What is checked, and what each one would cost if it broke:

  * **Every listed building must be described.** The rings are built from the
    Property Data table's coordinates, so a listing whose building is missing
    falls out of every ring -- and the comp set silently shrinks to whatever
    happened to be described.
  * **Days on market must reconcile to its own dates.** It is half the evidence
    that an asking rent is too high. If the column stops meaning days between
    listing and removal, the comparison measures nothing and says nothing.
  * **A floorplan row is not a unit**, and an OLD snapshot is not today. Either
    one quietly moves the median that the whole verification rests on.
  * **Align's own buildings are not comps.** Three of the buildings in the real
    file are Align's. Leaving them in lets one Align property's pricing
    validate another's.
  * **The premium is bed-weighted.** It is the yardstick that turns a comp
    median into an expected rent for this building. A pooled ratio moves with
    the unit MIX as much as with price, so a quarter in which mostly one-beds
    were listed reads as a price change that never happened.
  * **A bedroom the ring cannot price keeps the building's own rent**, rather
    than being extrapolated from two listings.
  * **The formatted twin of the export is skipped, not failed.** Both files are
    filed into the same folder on purpose.

Fixture-free and offline: every workbook is built in a temp dir. The real
export is a licensed vendor dataset and is gitignored along with every other
.xlsx, so there is nothing to check in even if it were safe to.

Run: python scripts/test_comps.py
"""
import json
import os
import pathlib
import shutil
import sys
import tempfile

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_metrics as bm      # noqa: E402
import parse_comps as pc        # noqa: E402
from xlsx_anchors import LayoutError  # noqa: E402

PASS = FAIL = 0


def ok(name, cond, detail=None):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"\n        {detail}" if detail is not None else ""))


# The subject is The Landing, because it is the one the property master knows
# and therefore the one the parser will cut a section for. Coordinates are the
# real ones; the comps sit at made-up offsets so the rings are predictable.
SUBJECT = ("The Landing", "1395 22nd Street", "94107", 37.75697, -122.3947, 263, 2019)
NEAR = ("Nearby Apartments", "1 Near Street", "94107", 37.7600, -122.3947, 200, 2018)
FAR = ("Distant Apartments", "9 Far Street", "94103", 37.7800, -122.4200, 300, 2016)
ALIGN2 = ("Chorus", "30 Otis Street", "94103", 37.7728, -122.4195, 416, 2021)

PROP_HEAD = ["Building Name", "Street Address", "City", "State", "Zip Code",
             "Latitude", "Longitude", "MSA", "# Units", "Year Built", "As Of"]
LIST_HEAD = ["Building Name", "Street Address", "City", "State", "Zip Code",
             "Is Floorplan", "Floorplan", "Unit", "Floor", "Bed", "Bath",
             "Partial Bath", "First Listed", "Listing Removed",
             "Days on Market", "Min Sqft", "Sqft", "Max Sqft", "Min Mkt Price",
             "Mkt Price", "Max Mkt Price", "Min Eff Price", "Eff Price",
             "Max Eff Price", "Availability", "As Of"]

AS_OF = "2026-09-15"


def build(path, props, listings, sheets=None):
    """A HelloData 'Simple' export: two flat tables, headers on row 1."""
    wb = openpyxl.Workbook()
    if sheets is not None:                     # the formatted twin
        wb.remove(wb.active)
        for s in sheets:
            wb.create_sheet(s)
        wb.save(path)
        return path
    ws = wb.active
    ws.title = pc.PROPERTY_SHEET
    ws.append(PROP_HEAD)
    for name, addr, zp, lat, lng, units, built in props:
        ws.append([name, addr, "San Francisco", "CA", zp, lat, lng,
                   "San Francisco-Oakland-Hayward, CA", units, built, AS_OF])
    ls = wb.create_sheet(pc.LISTING_SHEET)
    ls.append(LIST_HEAD)
    for r in listings:
        ls.append(r)
    wb.save(path)
    return path


def listing(building, bed, sqft, rent, first, removed=None, dom=None,
            as_of=AS_OF, is_plan=False, eff=None):
    """One Availability row. `dom` defaults to the file's own convention."""
    if removed and dom is None:
        dom = pc._days(first, removed) + 1
    return [building, "addr", "San Francisco", "CA", "94107", is_plan, "A1",
            "101", 1, bed, 1, None, first, removed, dom, None, sqft, None,
            None, rent, None, None, eff if eff is not None else rent, None,
            None, as_of]


def spread(building, bed, sqft, rent, quarters, per_quarter=6):
    """Listings across several quarters, so the premium baseline has quarters
    with enough on both sides to count."""
    out = []
    for q in quarters:
        for i in range(per_quarter):
            out.append(listing(building, bed, sqft, rent, q))
    return out


QUARTERS = ["2025-01-15", "2025-04-15", "2025-07-15", "2025-10-15",
            "2026-01-15", "2026-04-15"]


def base_listings():
    """A market where the subject asks exactly 10% over the ring, on both
    bedrooms and in every quarter -- so the premium is a known number.

    Plus TWO three-bed listings in the ring and none from the subject: that is
    the shape the real submarket has, and the one that makes MIN_BED_FOR_IMPLIED
    the thing that decides rather than an empty set.
    """
    rows = []
    for q in QUARTERS:
        rows += spread("The Landing", 1, 600, 5500, [q])
        rows += spread("The Landing", 2, 1000, 8800, [q])
        rows += spread("Nearby Apartments", 1, 600, 5000, [q])
        rows += spread("Nearby Apartments", 2, 1000, 8000, [q])
    rows += spread("Nearby Apartments", 3, 1400, 14000, ["2026-04-15"], 2)
    return rows


def main():
    global PASS, FAIL
    tmp = tempfile.mkdtemp(prefix="comps-")
    try:
        print("the shape of the export")
        p = build(os.path.join(tmp, "simple.xlsx"), [SUBJECT, NEAR], base_listings())
        out = pc.parse(p)
        ok("it parses and names its subject",
           [s["property_code"] for s in out["sections"]] == ["The Landing"],
           [s["property_code"] for s in out["sections"]])
        sec = out["sections"][0]
        ok("the as-of date is the newest snapshot in the file",
           out["as_of"] == AS_OF, out["as_of"])
        ok("the subject is described from Property Data",
           sec["subject"]["units"] == 263 and sec["subject"]["year_built"] == 2019,
           sec["subject"])
        ok("the building name is NOT published under a key the PII scrub drops",
           "name" not in sec["subject"] and "building" in sec["subject"],
           sorted(sec["subject"]))
        stored = bm.scrub(sec)
        ok("...so it survives build_metrics.scrub, which the real file proved",
           stored["subject"].get("building") == "The Landing",
           stored["subject"])

        print("\nthe premium is the yardstick, so it is taken per bedroom")
        ok("a market the subject leads by a flat 10% reads +10%",
           abs(sec["premium"]["median"] - 0.10) < 0.005, sec["premium"])
        # Same prices, but in the last quarter the subject lists ONLY one-beds
        # (the cheaper $/sqft type) and the ring lists both. A pooled median
        # would read that mix change as a price cut.
        mix = base_listings()
        mix += spread("The Landing", 1, 600, 5500, ["2026-07-15"], 8)
        mix += spread("Nearby Apartments", 1, 600, 5000, ["2026-07-15"], 8)
        mix += spread("Nearby Apartments", 2, 1000, 8000, ["2026-07-15"], 8)
        p2 = build(os.path.join(tmp, "mix.xlsx"), [SUBJECT, NEAR], mix)
        sec2 = pc.parse(p2)["sections"][0]
        last = sec2["quarters"][-1]
        ok("a quarter where only one bedroom type was listed still reads +10%",
           abs(last["premium"] - 0.10) < 0.005, last)
        pooled = last["subject_psf"] / last["comp_psf"] - 1
        ok("...where the pooled ratio of the same quarter does not",
           abs(pooled - 0.10) > 0.01,
           f"pooled {pooled:.4f} vs bed-weighted {last['premium']:.4f}")
        ok("and the quarter says how many bedrooms went into it",
           last["premium_beds"] == 1, last)

        print("\nwhat must not reach a median")
        # a floorplan summary row at an absurd rent
        plan_rows = base_listings() + [
            listing("Nearby Apartments", 1, 600, 99000, "2026-04-15", is_plan=True)]
        p3 = build(os.path.join(tmp, "plan.xlsx"), [SUBJECT, NEAR], plan_rows)
        o3 = pc.parse(p3)
        ring3 = [r for r in o3["sections"][0]["rings"] if r["primary"]][0]
        ok("a floorplan summary row is skipped, not averaged",
           ring3["by_bed"]["1"]["median_rent"] == 5000,
           ring3["by_bed"]["1"])
        ok("...and the count of skipped rows is published",
           any(c.get("skipped") == 1 for c in o3["checks"]),
           o3["checks"])
        # an old snapshot of a cheap listing, still open
        old_rows = base_listings() + [
            listing("Nearby Apartments", 1, 600, 1000, "2023-04-15", as_of="2023-04-20")]
        p4 = build(os.path.join(tmp, "old.xlsx"), [SUBJECT, NEAR], old_rows)
        o4 = pc.parse(p4)
        ring4 = [r for r in o4["sections"][0]["rings"] if r["primary"]][0]
        base_n = [r for r in sec["rings"] if r["primary"]][0]["by_bed"]["1"]["n"]
        ok("a listing observed on an older snapshot is not current",
           ring4["by_bed"]["1"]["n"] == base_n
           and ring4["by_bed"]["1"]["median_rent"] == 5000,
           (base_n, ring4["by_bed"]["1"]))
        # a removed listing, still on the file's own as-of date
        gone_rows = base_listings() + [
            listing("Nearby Apartments", 1, 600, 1000, "2026-04-15",
                    removed="2026-05-01")]
        p5 = build(os.path.join(tmp, "gone.xlsx"), [SUBJECT, NEAR], gone_rows)
        ring5 = [r for r in pc.parse(p5)["sections"][0]["rings"] if r["primary"]][0]
        ok("a listing that has been taken down is not current either",
           ring5["by_bed"]["1"]["median_rent"] == 5000, ring5["by_bed"]["1"])
        # no price, no size
        junk = base_listings() + [listing("Nearby Apartments", 1, None, 5000, "2026-04-15"),
                                  listing("Nearby Apartments", 1, 600, None, "2026-04-15")]
        p6 = build(os.path.join(tmp, "junk.xlsx"), [SUBJECT, NEAR], junk)
        o6 = pc.parse(p6)
        ok("a listing with no price or no size is excluded and counted",
           any(c.get("excluded") == 2 for c in o6["checks"]), o6["checks"])

        print("\nAlign's own buildings are not comps")
        p7 = build(os.path.join(tmp, "align.xlsx"), [SUBJECT, NEAR, ALIGN2],
                   base_listings() + spread("Chorus", 1, 600, 9999, ["2026-04-15"]))
        o7 = pc.parse(p7)
        landing = [s for s in o7["sections"] if s["property_code"] == "The Landing"][0]
        ring7 = [r for r in landing["rings"] if r["primary"]][0]
        ok("a second Align building is excluded from the comp set",
           ring7["by_bed"]["1"]["median_rent"] == 5000, ring7["by_bed"]["1"])
        ok("...and is named on the section rather than silently dropped",
           landing["excluded_related"] == ["Chorus"], landing["excluded_related"])
        ok("it still gets a section of its own, as a subject",
           sorted(s["property_code"] for s in o7["sections"]) == ["Chorus", "The Landing"],
           [s["property_code"] for s in o7["sections"]])

        print("\nthe rings")
        p8 = build(os.path.join(tmp, "rings.xlsx"), [SUBJECT, NEAR, FAR],
                   base_listings() + spread("Distant Apartments", 1, 600, 3000,
                                            ["2026-04-15"]))
        sec8 = pc.parse(p8)["sections"][0]
        tight = [r for r in sec8["rings"] if r["radius_mi"] == 0.75][0]
        every = [r for r in sec8["rings"] if r["radius_mi"] is None][0]
        ok("a building outside the radius is out of the tight ring",
           tight["by_bed"]["1"]["median_rent"] == 5000, tight["by_bed"]["1"])
        ok("...and inside the ring that takes every building",
           every["properties"] == 2
           and every["by_bed"]["1"]["n"] > tight["by_bed"]["1"]["n"]
           and every["by_bed"]["1"]["mean_rent"] < tight["by_bed"]["1"]["mean_rent"],
           (tight["by_bed"]["1"], every["by_bed"]["1"]))

        print("\nthe two reconciliations that stand in for a total row")
        rogue = base_listings() + [listing("Unlisted Towers", 1, 600, 5000, "2026-04-15")]
        p9 = build(os.path.join(tmp, "rogue.xlsx"), [SUBJECT, NEAR], rogue)
        try:
            pc.parse(p9)
            ok("a listing whose building is not described is refused", False)
        except LayoutError as e:
            ok("a listing whose building is not described is refused",
               "Unlisted Towers" in str(e), str(e))
        ok("...and reported without raising when strict is off",
           any(c["check"].startswith("every listed building")
               and not c["ok"] for c in pc.parse(p9, strict=False)["checks"]))

        bad_dom = base_listings() + [
            listing("Nearby Apartments", 1, 600, 5000, "2026-01-05",
                    removed="2026-02-05", dom=999)]
        p10 = build(os.path.join(tmp, "dom.xlsx"), [SUBJECT, NEAR], bad_dom)
        o10 = pc.parse(p10, strict=False)
        dom_check = [c for c in o10["checks"] if c["check"].startswith("days on market")][0]
        ok("days on market is reconciled against each listing's own dates",
           dom_check["closed_listings"] == 1 and dom_check["agree"] == 0,
           dom_check)
        many = base_listings()
        for i in range(200):
            many.append(listing("Nearby Apartments", 1, 600, 5000, "2026-01-05",
                                removed="2026-02-05", dom=999))
        p11 = build(os.path.join(tmp, "dom2.xlsx"), [SUBJECT, NEAR], many)
        try:
            pc.parse(p11)
            ok("a file whose column stops meaning days is refused", False)
        except LayoutError as e:
            ok("a file whose column stops meaning days is refused",
               "Days on Market" in str(e), str(e))

        print("\nthe formatted twin of the export")
        p12 = build(os.path.join(tmp, "full.xlsx"), None, None,
                    sheets=["Intro", "Rent Comps", "Unit Mix", "Pro Forma Model"])
        o12 = pc.parse(p12)
        ok("it is skipped rather than failed", bool(o12.get("skip")), o12.get("skip"))
        ok("...and the skip says which file it is and why nothing is missing",
           "Simple" in o12["skip"] and "nothing is missing" in o12["skip"],
           o12.get("skip"))
        ok("...and produces no sections to store", o12["sections"] == [])

        print("\nthe build-up: comp medians onto the building's own mix")
        # 100 one-beds at 600 sqft, 50 two-beds at 1000, 4 three-beds the ring
        # cannot price. Yardi's own rents are deliberately high.
        plans = {"a1": {"bedrooms": 1, "units": 100, "sqft_avg": 600,
                        "rent_min": 6000, "rent_max": 6000},
                 "b1": {"bedrooms": 2, "units": 50, "sqft_avg": 1000,
                        "rent_min": 9500, "rent_max": 9500},
                 "c1": {"bedrooms": 3, "units": 4, "sqft_avg": 1400,
                        "rent_min": 12000, "rent_max": 12000}}
        ud_prop = {"slug": "the-landing", "as_of": "2026-08-25",
                   "source_file": "UnitDirectory.xlsx", "plans": plans}
        mix_, no_rent = bm.bedroom_mix(ud_prop)
        ok("the mix is read per bedroom, not per plan",
           mix_[1]["units"] == 100 and mix_[2]["units"] == 50, mix_)
        ok("a plan with no published rent is named rather than counted as zero",
           no_rent == [], no_rent)

        ring = [r for r in sec["rings"] if r["primary"]][0]
        im = bm.comp_implied(mix_, ring, 0.10)
        one = [r for r in im["rows"] if r["bed"] == 1][0]
        ok("a bedroom the ring prices takes the comp median plus the premium",
           abs(one["rent"] - 5000 * 1.10) < 0.01, one)
        three = [r for r in im["rows"] if r["bed"] == 3][0]
        ok("a bedroom the ring has only two listings for keeps the "
           "building's own rent",
           three["rent"] == 12000 and three["source"] == "yardi"
           and (ring["by_bed"].get("3") or {}).get("n") == 2,
           (three, ring["by_bed"].get("3")))
        ok("...and is named as unverified", im["unverified_beds"] == [3],
           im["unverified_beds"])
        want = 100 * 5500 + 50 * 8800 + 4 * 12000
        ok("the total is the mix at those rents",
           abs(im["total"] - want) < 1, (im["total"], want))
        ok("every row carries the size it was matched on",
           one["subject_sqft"] == 600 and one["comp_sqft"] == 600, one)

        print("\nthe check: four readings of one number")
        rr_prop = {"slug": "the-landing", "as_of": "2026-09-11",
                   "source_file": "RentRoll.xlsx", "units": 154,
                   "market_rent_total": want * 1.10, "market_psf": 9.0,
                   "market_rent_occupied": want * 1.10, "actual_rent_occupied": want * 0.80,
                   "loss_to_lease_pct": 0.2727}
        rc_prop = {"slug": "the-landing", "period_end": "Aug 2026",
                   "months": ["2026-08"], "market_potential": [want]}
        ver = bm.comps_verification(sec, ud_prop, rr_prop, rc_prop)
        keys = [s["key"] for s in ver["sources"]]
        ok("all four readings are published",
           keys == ["rent_roll", "unit_directory", "statement", "comp_implied"], keys)
        ok("the rent roll's gap is measured against the comp-implied figure",
           abs(ver["headline"]["gap"] - 0.10) < 0.002, ver["headline"])
        ok("the dollar gap is the monthly difference",
           abs(ver["headline"]["dollars"] - want * 0.10) < 1, ver["headline"])
        ok("and the annual one is twelve of them",
           abs(ver["headline"]["annual"] - ver["headline"]["dollars"] * 12) < 1,
           ver["headline"])
        stmt = [s for s in ver["sources"] if s["key"] == "statement"][0]
        ok("a statement that agrees with the comps reads a gap of nothing",
           abs(stmt["gap"]) < 0.001, stmt)
        ok("the exact sources are marked apart from the estimates",
           [s["key"] for s in ver["sources"] if s.get("exact")] == ["rent_roll", "statement"],
           [(s["key"], s.get("exact")) for s in ver["sources"]])
        ok("loss to lease is restated on a market rent the comps support",
           abs(ver["headline"]["ltl_restated"] - 0.20) < 0.005,
           ver["headline"])
        ok("...and the published figure is kept beside it",
           ver["headline"]["ltl_published"] == 0.2727, ver["headline"])
        ok("the sensitivity covers every ring the export was cut into",
           len(ver["sensitivity"]) == len(sec["rings"]), ver["sensitivity"])

        print("\nwithout the building's own feeds there is no check to make")
        ok("no unit directory means no verification rather than a guess",
           bm.comps_verification(sec, None, rr_prop, rc_prop) is None)
        no_roll = (bm.comps_verification(sec, ud_prop, None, rc_prop) or {}).get("headline")
        ok("no rent roll falls back to the directory's own copy of the table",
           no_roll and no_roll["source"] == "unit_directory", no_roll)
        ok("...and says which reading it measured, since it is not the roll's",
           (no_roll or {}).get("label") == "Unit directory", no_roll)
        ok("...with no restated loss to lease, which needs the roll",
           "ltl_restated" not in (no_roll or {}), no_roll)

        print("\nthe store keeps the newest VINTAGE, not the newest arrival")
        # These two are not the same thing in this folder and the gap is not
        # small: a copy that landed 2026-09-21 carries an as-of of 2026-08-05,
        # six weeks behind one that landed three days earlier. Every vintage on
        # file parses on every run, in whatever order the fetch wrote them, so
        # "whichever ran last" would publish a different month of the market
        # depending on nothing at all.
        was, bm.DATA = bm.DATA, pathlib.Path(tmp) / "data"
        try:
            prop = {"slug": "subject", "name": "The Landing"}
            newer = {"sections": [dict(sec, as_of="2026-09-20")],
                     "source_file": "landed-18th.xlsx"}
            older = {"sections": [dict(sec, as_of="2026-08-05")],
                     "source_file": "landed-21st.xlsx"}

            fp = bm.store_comps(prop, newer)
            bm.store_comps(prop, older)
            kept = json.load(open(fp))
            ok("a later arrival carrying an older vintage does not displace it",
               (kept["as_of"], kept["source_file"]) == ("2026-09-20",
                                                        "landed-18th.xlsx"),
               (kept["as_of"], kept["source_file"]))
            ok("...and the rejected vintage is still recorded",
               kept["vintages"] == ["2026-08-05", "2026-09-20"], kept["vintages"])

            shutil.rmtree(bm.DATA, ignore_errors=True)
            bm.store_comps(prop, older)
            bm.store_comps(prop, newer)
            kept = json.load(open(fp))
            ok("a genuinely newer vintage does displace the older one",
               (kept["as_of"], kept["source_file"]) == ("2026-09-20",
                                                        "landed-18th.xlsx"),
               (kept["as_of"], kept["source_file"]))

            bm.store_comps(prop, newer)
            bm.store_comps(prop, older)
            ok("re-reading the same folder every run adds no vintages",
               json.load(open(fp))["vintages"] == ["2026-08-05", "2026-09-20"],
               json.load(open(fp))["vintages"])
        finally:
            bm.DATA = was
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()

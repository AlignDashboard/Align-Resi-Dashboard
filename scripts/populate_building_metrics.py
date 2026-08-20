#!/usr/bin/env python3
"""Fill docs/scorecard.json from the EliseAI building-metrics CSV export.

The export ("metricsbuilding<YYYYMMDD>.csv") carries 79 columns of leasing,
occupancy, delinquency and automation metrics per property. This fills the
subset the scorecard can honestly take from it.

  # of Tours/Leads/Applications   tours/leads/apps as an xx/yy/zz triple, from
                                  Total Tours Attended / New Prospects /
                                  Applications Completed. VALUE ONLY — the
                                  published band is tours per available unit per
                                  MONTH, so a triple of raw counts cannot be
                                  graded against it (same rule the daily-email
                                  fill follows).
  Leased %                        100 − Exposure Rate. Exposure is the
                                  complement of leased, which matches the KPI's
                                  definition better than Occupancy Rate does.
  Trade-out %                     Combined Trade-Out (new + renewal blend).
  Closing Ratio                   Tour Attended to Lease Signed Rate.
  # of Renewals                   Renewal Rate (renewals ÷ expirations).
  % Increase                      Avg Rent Increase Executed (%), falling back
                                  to Offered (%) where executed is blank.
  Total Deliquency                Delinquency Rate.
  AI Containment Rate             Leasing Automation Rate (prospect side).
  Avg First Response Time         AI Response Time, assumed SECONDS. VALUE ONLY
                                  until the unit is confirmed — see UNIT note.

Deliberately NOT filled, and why:

  * Any cell another feed already owns. The Landing's and Palma's delinquency
    come from the workbook and the Drive AR report, whose bases are known and
    tied out; this export's delinquency basis is unstated and disagrees sharply
    (Landing: 11.2% here vs 4.6% published). 335 Third's T/L/A comes from the
    daily EliseAI emails, which carry a known 7-day window and a real arrival
    time, where this export's period is not stated anywhere in the file.
  * Chorus % Increase and Trade-out %. Chorus reports +119.78% executed against
    −3.74% offered on the same population, and a 16.24% combined trade-out would
    need renewals to carry 4% of the weight against a 64.1% renewal rate. The
    renewal component is not credible, so % Increase is skipped and Trade-out
    falls back to New Lease Trade-Out alone, recorded in the basis.
  * # of accepted/pending offers. The nearest column is App Completed to
    Approved Rate, but an application approval is a different event in a
    different funnel from a renewal offer being accepted.
  * A stabilised band applied to a property in lease-up. Where the export shows
    a property has not opened (0% occupancy, near-total exposure), the
    occupancy- and leasing-derived cells are filled but left ungraded rather
    than marked below target — see LEASEUP.

Idempotent and re-runnable. Run after extract_scorecard.py, like the other
populate steps, and after populate_eliseai.py so the daily feed keeps its cells.

Usage:
  python scripts/populate_building_metrics.py <export.csv> [--received-at ISO8601]
  python scripts/populate_building_metrics.py <export.csv> --dry-run
"""
import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from populate_scorecard import OUT, classify, recompute  # noqa: E402

# CSV property heading -> scorecard slug. A heading absent from here is reported
# rather than guessed at, so a new property in the export cannot land silently
# on the wrong row.
HEADING_TO_SLUG = {
    "Chorus": "chorus",
    "The Landing": "the-landing",
    "The Madelon": "madelon",
    "335 3rd Street": "335-third-street",
}

KPI_TLA = "# of Tours/Leads/Applications"
KPI_RESPONSE = "Avg First Response Time"

# AI Response Time is in DAYS, per the owner (2026-08-20). Taken at face value
# that puts every property at 35–37 days to first response, which is hard to
# square with an AI assistant answering prospects — so the figure is published
# in days as stated, but stays value-only rather than graded, and the number
# deserves a second look against a fresh export before anyone acts on it.
RESPONSE_UNIT = "days"

# The export is a snapshot taken on the date in the filename; the rate KPIs in
# it (trade-out, closing ratio, renewal rate) are on a trailing ONE month basis
# from that date, per the owner (2026-08-20). Note the scorecard's bands for
# those KPIs are written for a trailing THREE month basis, so a volatile month
# swings the grade more than the band's authors assumed.
EXPORT_BASIS = "snapshot on the filename date; rate KPIs trailing 1 month from it"

# Cells that carry a figure but no status. Either the band cannot apply to a
# count triple, or the basis behind the number is not yet confirmed.
VALUE_ONLY = {KPI_TLA, KPI_RESPONSE}

# A property this far below stabilised occupancy is still leasing up, and the
# stabilised bands would mark it below target for not having opened yet.
LEASEUP_OCCUPANCY_UNDER = 50.0

# In lease-up, only the occupancy- and rent-derived cells are left ungraded:
# their bands assume an operating asset, so an empty building scores red for not
# having opened. Automation and response-time KPIs are about conversation
# handling and grade the same whether the building is full or empty.
LEASEUP_UNGRADED = {"Leased %", "Trade-out %", "Closing Ratio",
                    "# of Renewals", "% Increase"}


def num(row, key):
    v = (row.get(key) or "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def as_of_from_name(path):
    """metricsbuilding20260819.csv -> 2026-08-19. The export states its period
    nowhere inside the file, so the filename is the only date available."""
    m = re.search(r"(20\d{2})(\d{2})(\d{2})", os.path.basename(path))
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def units(row):
    """Total / available units implied by the export, for the record."""
    occ, vac = num(row, "Occupancy Rate (Period End)"), num(row, "Vacant Units (Period End)")
    exp = num(row, "Exposure Rate (Period End)")
    total = None
    if occ not in (None, 0) and occ < 100 and vac is not None:
        total = vac / (1 - occ / 100)
    elif exp and vac is not None:
        total = vac / (exp / 100)
    avail = total * exp / 100 if (total is not None and exp is not None) else None
    return total, avail


def measurements(row, slug, owned):
    """{kpi: (value, display, basis, skip_reason)} for one property.

    `value` is what gets classified; `display` is what the cell prints. A KPI
    with a skip_reason is reported and not written. `owned` is the set of KPIs
    another feed already fills for this property.
    """
    out = {}
    occ = num(row, "Occupancy Rate (Period End)")
    leaseup = occ is not None and occ < LEASEUP_OCCUPANCY_UNDER

    def add(kpi, value, display, basis, skip=None):
        if kpi in owned and skip is None:
            skip = f"another feed already fills this cell for {slug}"
        out[kpi] = (value, display, basis, skip)

    # ---- tours / leads / applications, as xx/yy/zz ----------------------
    t = num(row, "Total Tours Attended")
    l = num(row, "New Prospects")
    a = num(row, "Applications Completed")
    if None not in (t, l, a):
        _total, avail = units(row)
        per = f"; {t:g} tours ÷ {avail:.1f} available units = {t / avail:.1f}/unit" \
              if avail else ""
        add(KPI_TLA, None, f"{t:g}/{l:g}/{a:g}",
            "Total Tours Attended / New Prospects / Applications Completed"
            f" over the export's period{per}")
    else:
        add(KPI_TLA, None, None, None, "tours, prospects or applications blank")

    # ---- leased % ------------------------------------------------------
    exp = num(row, "Exposure Rate (Period End)")
    add("Leased %", None if exp is None else (100 - exp) / 100,
        None if exp is None else f"{100 - exp:.1f}%",
        "100 − Exposure Rate (Period End); exposure is the complement of leased",
        None if exp is not None else "Exposure Rate blank")

    # ---- trade-out -----------------------------------------------------
    comb, new_to, ren_to = (num(row, "Combined Trade-Out"),
                            num(row, "New Lease Trade-Out"),
                            num(row, "Renewal Trade-Out"))
    # A renewal trade-out this large is not a rent increase, it is a bad cell,
    # and it contaminates the blend. Fall back to the new-lease side alone.
    if ren_to is not None and ren_to > 50 and new_to is not None:
        add("Trade-out %", new_to / 100, f"{new_to:.1f}%",
            f"New Lease Trade-Out only — Renewal Trade-Out reads {ren_to:.2f}%, "
            f"which is not credible and would contaminate the blend")
    elif comb is not None:
        add("Trade-out %", comb / 100, f"{comb:.1f}%",
            "Combined Trade-Out (new + renewal blend)")
    else:
        add("Trade-out %", None, None, None, "Combined Trade-Out blank")

    # ---- closing ratio -------------------------------------------------
    cr = num(row, "Tour Attended to Lease Signed Rate")
    add("Closing Ratio", None if cr is None else cr / 100,
        None if cr is None else f"{cr:.1f}%",
        "Tour Attended to Lease Signed Rate",
        None if cr is not None else "Tour Attended to Lease Signed Rate blank")

    # ---- renewals ------------------------------------------------------
    rr = num(row, "Renewal Rate")
    add("# of Renewals", None if rr is None else rr / 100,
        None if rr is None else f"{rr:.1f}%",
        "Renewal Rate (renewals signed ÷ expirations)",
        None if rr is not None else "Renewal Rate blank")

    # ---- % increase ----------------------------------------------------
    ex, off = num(row, "Avg Rent Increase Executed (%)"), num(row, "Avg Rent Increase Offered (%)")
    if ex is not None and ex > 50:
        add("% Increase", None, None, None,
            f"Avg Rent Increase Executed reads {ex:.2f}% against "
            f"{off if off is None else format(off, '.2f')}% offered — not credible")
    elif ex is not None:
        add("% Increase", ex / 100, f"{ex:.1f}%", "Avg Rent Increase Executed (%)")
    elif off is not None:
        add("% Increase", off / 100, f"{off:.1f}%",
            "Avg Rent Increase OFFERED (%) — executed is blank in the export, so "
            "this is the offer, not what residents accepted")
    else:
        add("% Increase", None, None, None, "neither executed nor offered increase populated")

    # ---- delinquency ---------------------------------------------------
    dq = num(row, "Delinquency Rate")
    add("Total Deliquency", None if dq is None else dq / 100,
        None if dq is None else f"{dq:.1f}%",
        "Delinquency Rate as reported; the export does not state whether this is "
        "gross resident AR over one month's billed rent, the basis the KPI defines",
        None if dq is not None else "Delinquency Rate blank")

    # ---- automation / response ----------------------------------------
    la = num(row, "Leasing Automation Rate")
    add("AI Containment Rate", None if la is None else la / 100,
        None if la is None else f"{la:.1f}%",
        "Leasing Automation Rate (prospect side, which is what the KPI defines)",
        None if la is not None else "Leasing Automation Rate blank")

    ai = num(row, "AI Response Time")
    add(KPI_RESPONSE, ai,
        None if ai is None else f"{ai:g} {RESPONSE_UNIT}",
        f"AI Response Time, in {RESPONSE_UNIT} per the owner (2026-08-20); "
        f"implausibly long for an AI first response, so value-only"
        if ai is not None else None,
        None if ai is not None else "AI Response Time blank")

    return out, leaseup


def owned_by_other_feeds(sc, slug):
    """KPIs another feed already fills for this property, from measured[slug]."""
    m = (sc.get("measured") or {}).get(slug) or {}
    owned = set()
    for key, val in m.items():
        if key.endswith("kpis") and not key.startswith("bldg_") and isinstance(val, list):
            owned.update(val)
    return owned


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path", help="the building-metrics CSV export")
    ap.add_argument("--received-at", metavar="ISO8601",
                    help="when this export arrived. Without it the scorecard falls "
                         "back to the as-of date and says so on hover.")
    ap.add_argument("--dry-run", action="store_true", help="report, write nothing")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()

    if a.received_at:
        try:
            datetime.fromisoformat(a.received_at.replace("Z", "+00:00"))
        except ValueError:
            sys.exit(f"--received-at {a.received_at!r} is not an ISO-8601 timestamp")

    as_of = as_of_from_name(a.csv_path)
    rows = list(csv.DictReader(open(a.csv_path)))
    sc = json.load(open(a.out))
    thresholds = sc.get("thresholds") or {}
    by_slug = {p["slug"]: p for p in sc["properties"] if p.get("slug")}

    print(f"source: {os.path.basename(a.csv_path)}  ·  as of {as_of or 'unknown'}  "
          f"·  {len(rows)} propert(ies) in the export")
    if a.received_at:
        print(f"arrived: {a.received_at}")
    else:
        print("arrived: not recorded — the page will fall back to the as-of date and "
              "say so. Pass --received-at to record one.")
    print()

    unknown = [r["Property"] for r in rows if r["Property"] not in HEADING_TO_SLUG]
    for h in unknown:
        print(f"[warn] '{h}' is not in HEADING_TO_SLUG — skipped rather than guessed at")

    total_filled = 0
    for row in rows:
        heading = row["Property"]
        slug = HEADING_TO_SLUG.get(heading)
        if not slug:
            continue
        prop = by_slug.get(slug)
        if not prop:
            print(f"[warn] slug {slug!r} is not on the scorecard — skipping {heading}")
            continue

        owned = owned_by_other_feeds(sc, slug)
        meas, leaseup = measurements(row, slug, owned)
        tot, avail = units(row)
        print(f"{heading}  ->  {prop['label']}  "
              f"(≈{tot and round(tot)} units, {avail and round(avail, 1)} available)"
              + ("   [LEASE-UP: stabilised bands not applied]" if leaseup else ""))

        filled, basis = [], {}
        for kpi, (value, display, why, skip) in meas.items():
            if kpi not in prop["statuses"]:
                continue
            if skip:
                print(f"    {kpi:32} {'—':>18}  skipped: {skip}")
                continue
            if display is None:
                continue

            rec = {"raw": round(value, 6) if value is not None else None,
                   "display": display}
            if kpi == KPI_TLA:
                rec["parts"] = [num(row, "Total Tours Attended"),
                                num(row, "New Prospects"),
                                num(row, "Applications Completed")]
                rec["parts_labels"] = ["tours", "leads", "apps"]

            was = prop["statuses"].get(kpi)
            band = None
            if kpi in VALUE_ONLY:
                note = "value only (band cannot grade this form)"
                prop.setdefault("status_source", {})[kpi] = "value_only"
            elif leaseup and kpi in LEASEUP_UNGRADED:
                note = "value only (property is in lease-up)"
                prop.setdefault("status_source", {})[kpi] = "value_only"
            else:
                band = classify(value, thresholds.get(kpi))
                if band and band != was:
                    prop.setdefault("status_workbook", {})[kpi] = was
                    prop["statuses"][kpi] = band
                    note = f"RESTATED {was} -> {band}"
                else:
                    note = "confirms the workbook" if band else "no band to grade against"
                prop.setdefault("status_source", {})[kpi] = "measured"

            if not a.dry_run:
                prop["values"][kpi] = rec
            filled.append(kpi)
            basis[kpi] = why
            print(f"    {kpi:32} {display:>18}  {note}")
        total_filled += len(filled)

        if not a.dry_run and filled:
            meas_block = sc.setdefault("measured", {}).setdefault(slug, {})
            meas_block.update({
                "bldg_source": f"EliseAI building metrics export "
                               f"({os.path.basename(a.csv_path)})",
                "bldg_as_of": as_of,
                "bldg_period": EXPORT_BASIS,
                "bldg_received_at": a.received_at,
                "bldg_received_what": "EliseAI building metrics export",
                "bldg_kpis": sorted(filled),
                "bldg_basis": basis,
            })
        print()

    if a.dry_run:
        print(f"dry run — nothing written ({total_filled} cell(s) would be filled)")
        return

    recompute(sc)
    json.dump(sc, open(a.out, "w"), indent=2)
    print(f"wrote {a.out}: {total_filled} cell(s) filled")
    for p in sc["properties"]:
        if p.get("slug") in {HEADING_TO_SLUG.get(r["Property"]) for r in rows}:
            print(f"  {p['label']}: {p['at_or_above']:.0%} at or above target "
                  f"({p['counts']['below']} below of {p['scored']})")
    print(f"  portfolio: {sc['portfolio']['at_or_above']:.2%} at or above target "
          f"({sc['portfolio']['counts']['below']} below of {sc['portfolio']['scored']})")


if __name__ == "__main__":
    main()

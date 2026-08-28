#!/usr/bin/env python3
"""Fill measured values into docs/scorecard.json from a delinquency report.

The scorecard grid carries hand-set symbols; since v10 the workbook also
publishes the numeric band behind each symbol ("thresholds"). Once a real
measurement exists, the symbol can be derived rather than asserted — so this
script writes the number AND reclassifies the status against the published band,
keeping the workbook's original symbol alongside it so nothing is lost.

Which KPIs a delinquency report can actually answer:

  Total Deliquency          gross resident AR / one month's billed rent
                            (needs the monthly rent too — a delinquency report
                            alone does not carry it, see --monthly-rent)
  Split Between 30/60/90    the report's three past-due buckets, printed as
                            31-60 / 61-90 / over-90 dollars. Reported, not
                            graded: a distribution has no single direction it can
                            be good or bad in, so the cell gets no status and no
                            colour (see UNSCORED in extract_scorecard.py).

--from-landing also fills one KPI a delinquency report cannot:

  Loss to Lease %           the current month's loss to lease over market rent
                            potential, from the workbook's Rent Capture series,
                            as a whole number of percent. The published basis is
                            the current rent roll, so the newest month answers it
                            rather than the TTM column.
  NOI Margin %              the current month's NOI over revenue, from the
                            Expense & NOI series behind that card. The published
                            band's basis is T12, and a single accrual month
                            swings well past it in both directions, so the TTM
                            figure is recorded alongside the graded month.
  Controllable OpEx/Unit    the current month's operating expense less taxes,
                            insurance and utilities, per unit, x12 for the band's
                            per-year basis. Numerator comes from the T12
                            statement's account groups (data/<slug>/
                            expense_buckets.json), since the workbook carries
                            only a total. Note the band's own "how" line excludes
                            the management fee rather than utilities.

"POs over 30 days" and "# of invoices processed" are accounts *payable*; a
resident AR report cannot speak to them and they are left alone.

Sources:
  --delinquency <report.xlsx>   a real rs_rp_DelinquencySummaryReport, parsed by
                                parse_delinquency (add --monthly-rent to enable
                                the Total Deliquency ratio)
  --from-landing                The Landing's figures out of docs/landing.json,
                                which the extractor already took from the
                                workbook's Source Delinquency tab (the same
                                report, pasted rather than fetched)

Derived roll-ups (per-property counts, at_or_above, the portfolio totals and
by_metric) are rebuilt from the statuses afterwards, so the matrix, the health
chart and the tally cannot drift apart from the cells.

NOTE ON ORDER: scripts/extract_scorecard.py rewrites docs/scorecard.json from
the workbook and resets every value to null. Re-run this script after it.

Usage:
  python scripts/populate_scorecard.py --from-landing
  python scripts/populate_scorecard.py --delinquency r.xlsx --property palma \
      --monthly-rent 812000
"""
import argparse
from datetime import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUT = "docs/scorecard.json"

# The grid spells it "Total Deliquency" (sic). Key off the grid's own spelling,
# because that is what the properties' status maps use.
KPI_TOTAL = "Total Deliquency"
KPI_SPLIT = "Split Between 30/60/90"
KPI_LTL = "Loss to Lease %"
KPI_NOI = "NOI Margin %"
KPI_CTRL = "Controllable OpEx/Unit"

# What a property manager cannot move inside a month. Matched by name against
# the T12 statement's own account groups rather than listed exactly, and all
# three must be found -- a renamed group that silently stopped matching would
# leave taxes inside "controllable" and the figure would read a third too high.
NOT_CONTROLLABLE = ("tax", "insurance", "utilit")


def pct1(v):
    return f"{v * 100:.1f}%"


def controllable_per_unit(slug, units):
    """This month's controllable operating expense per unit, annualized.

    The band is written per unit per year, so the month is multiplied by twelve.
    Source is data/<slug>/expense_buckets.json -- the property's own T12
    statement grouped on the Align account tree -- because the analyst workbook
    carries only a total and its own controllable cut, which excludes the
    management fee rather than utilities.
    """
    path = os.path.join("data", slug, "expense_buckets.json")
    if not units or not os.path.exists(path):
        return None, None, None
    pts = (json.load(open(path)) or {}).get("points") or []
    if not pts:
        return None, None, None
    pt = pts[-1]
    buckets = pt.get("buckets") or {}
    names = list(buckets)
    found = [k for k in NOT_CONTROLLABLE if any(k in n.lower() for n in names)]
    if len(found) != len(NOT_CONTROLLABLE):
        return None, None, ("the statement's account groups do not name "
                            + ", ".join(k for k in NOT_CONTROLLABLE if k not in found))
    i = len(pt["labels"]) - 1
    total = sum((b[i] or 0) for b in buckets.values())
    excluded = sum((b[i] or 0) for n, b in buckets.items()
                   if any(k in n.lower() for k in NOT_CONTROLLABLE))
    month = f"{pt['period_end']}"
    return (total - excluded) / units * 12, month, None


def pct0(v):
    """Loss to lease as a whole number of percent: a gap this wide is not a
    figure a tenth of a point changes the reading of."""
    return f"{v * 100:.0f}%"


def classify(value, t):
    """Status from the workbook's published band. None if it cannot be decided."""
    if value is None or not t:
        return None
    green, red = t.get("green_cutoff"), t.get("red_cutoff")
    if green is None or red is None:
        return None
    lower_better = "lower" in str(t.get("direction", "")).lower()
    if lower_better:
        if value <= green:
            return "exceeding"
        return "in_range" if value <= red else "below"
    if value >= green:
        return "exceeding"
    return "in_range" if value >= red else "below"


# the three past-due buckets, in the order they are printed
SPLIT_LABELS = ["31-60", "61-90", "90+"]


def facts_from_landing(path="docs/landing.json"):
    doc = json.load(open(path))
    d = doc["delinquency"]
    ag = {a["bucket"]: a["amount"] for a in d["aging"]}
    def bucket(*needles):
        for k, v in ag.items():
            if any(n in k.lower() for n in needles):
                return v
        return None
    # Loss to lease, from the workbook's Rent Capture series rather than its
    # TTM column: the KPI's published basis is the current rent roll, so the
    # newest month is the one that answers it. The TTM average would fold in a
    # year of older market-rent tables, which for this property differ sharply
    # from today's.
    rc = doc.get("rent_capture") or {}
    ltl_series, months = rc.get("ltl_pct") or [], rc.get("months") or []
    # NOI margin, likewise from the monthly series behind the Expense Load & NOI
    # card rather than its TTM column. Note the published band's own basis says
    # T12: a single accrual month swings hard (Apr 2026 reads 47.0% on that
    # month's tax true-up, Jul 2026 reads 72.6%), so both are recorded below and
    # which one the band is meant to grade is the owner's call.
    en = doc.get("expense_noi") or {}
    noi_series, noi_months = en.get("noi_margin") or [], en.get("months") or []
    units = (doc.get("meta") or {}).get("units")
    ctrl, ctrl_month, ctrl_why = controllable_per_unit("the-landing", units)
    return {
        "as_of": d.get("as_of"),
        "gross_owed": d.get("gross_owed"),
        "ltl_pct": ltl_series[-1] if ltl_series else None,
        "ltl_month": months[-1] if months else None,
        "noi_margin": noi_series[-1] if noi_series else None,
        "noi_margin_month": noi_months[-1] if noi_months else None,
        "noi_margin_ttm": (en.get("ttm") or {}).get("noi_margin"),
        "ctrl_per_unit_yr": ctrl,
        "ctrl_month": ctrl_month,
        "ctrl_units": units,
        "ctrl_why": ctrl_why,
        "split": [bucket("31 - 60", "31-60"), bucket("61 - 90", "61-90"),
                  bucket("over 90")],
        # the workbook computes this ratio itself, so use it rather than
        # re-deriving the denominator
        "total_delinq_pct": d.get("pct_month_rent"),
        "source": "workbook Source Delinquency tab, via docs/landing.json",
        # the workbook is refreshed by hand, so its "arrival" is when the
        # analyst last extracted it — landing.json's own generated_at
        "received_at": (doc.get("meta") or {}).get("generated_at"),
        "received_what": "analyst workbook extract",
    }


def facts_from_pipeline(slug, monthly_rent=None):
    """data/<slug>/delinquency.json, as build_metrics writes it from Drive.

    Already scrubbed of names. The delinquency report carries no rent, so the
    Total Deliquency ratio needs --monthly-rent; without it that KPI is left
    alone rather than guessed at.
    """
    path = os.path.join("data", slug, "delinquency.json")
    if not os.path.exists(path):
        return None
    d = json.load(open(path))
    s = d.get("summary") or {}
    a = s.get("aging") or {}
    gross = s.get("gross_owed")

    # Denominator: an explicit --monthly-rent wins; otherwise the latest month's
    # operating revenue that build_metrics derived from the property's T12
    # statements (GL 4999-9999 — total operating revenue rather than billed
    # rent alone, so the basis is recorded alongside the number).
    denom, denom_note = monthly_rent, "--monthly-rent"
    if not denom:
        mrpath = os.path.join("data", slug, "monthly_revenue.json")
        if os.path.exists(mrpath):
            mr = json.load(open(mrpath))
            if (mr.get("revenue_month") or 0) > 0:
                denom = mr["revenue_month"]
                months = sorted({c.get("month") for c in (mr.get("codes") or {}).values()})
                denom_note = (f"{mr['revenue_month']:,.0f}/mo operating revenue "
                              f"({'+'.join(sorted(mr.get('codes') or {}))}, "
                              f"{'/'.join(m for m in months if m)}; {mr.get('basis')})")

    return {
        "as_of": d.get("as_of"),
        # when the report landed in Drive, recorded by build_metrics from the
        # fetch manifest. None for data/ written before that was captured.
        "received_at": d.get("landed_at"),
        "received_what": "report in the Drive Residential AR Analytics folder",
        "gross_owed": gross,
        "split": [a.get("d31_60"), a.get("d61_90"), a.get("over90")],
        "total_delinq_pct": (gross / denom) if (gross and denom) else None,
        "denominator": denom,
        "denominator_note": denom_note if denom else None,
        "source": f"{d.get('source_file') or path}"
                  + (f" ({'+'.join(c for c in d.get('property_codes') or [] if c)})"
                     if d.get("property_codes") else ""),
    }


def facts_from_report(path, monthly_rent):
    import parse_delinquency
    parsed = parse_delinquency.parse(path)
    s = parsed["summary"]
    a = s["aging"]
    gross = s["gross_owed"]
    return {
        "as_of": parsed.get("as_of"),
        "gross_owed": gross,
        "split": [a.get("d31_60"), a.get("d61_90"), a.get("over90")],
        "total_delinq_pct": (gross / monthly_rent) if monthly_rent else None,
        "source": os.path.basename(path),
        # a report handed to the script directly did not come through Drive, so
        # there is no arrival time to record unless --received-at supplies one
        "received_at": None,
        "received_what": "report supplied by hand",
    }


def measurements(f):
    """{kpi: (value, display, why-it-is-missing)}.

    `value` is what gets classified against the band; an unscored KPI has a
    display but no classifiable value, which is why the two are separate.
    """
    out = {}
    if f.get("total_delinq_pct") is not None:
        v = f["total_delinq_pct"]
        out[KPI_TOTAL] = (v, pct1(v), None)
    else:
        out[KPI_TOTAL] = (None, None,
                          "needs one month's billed rent — pass --monthly-rent")

    if f.get("ltl_pct") is not None:
        out[KPI_LTL] = (f["ltl_pct"], pct0(f["ltl_pct"]), None)
    else:
        out[KPI_LTL] = (None, None,
                        "this source carries no market-rent-vs-in-place series")

    if f.get("noi_margin") is not None:
        out[KPI_NOI] = (f["noi_margin"], pct1(f["noi_margin"]), None)
    else:
        out[KPI_NOI] = (None, None,
                        "this source carries no monthly revenue-and-NOI series")

    if f.get("ctrl_per_unit_yr") is not None:
        v = f["ctrl_per_unit_yr"]
        out[KPI_CTRL] = (v, f"${v:,.0f}", None)
    else:
        out[KPI_CTRL] = (None, None,
                         f.get("ctrl_why")
                         or "no T12 statement grouped by account for this property")

    parts = f.get("split") or []
    if len(parts) == 3 and all(p is not None for p in parts):
        # xx/yy/zz in whole dollars, the report's own figures
        out[KPI_SPLIT] = (None, "/".join(f"{p:,.0f}" for p in parts), None)
    else:
        out[KPI_SPLIT] = (None, None, "report has no 30/60/90 aging buckets")
    return out


def graded(p, names):
    """The cells whose status was derived from a measurement.

    These are the only cells the dashboard colours and the only ones the tally
    counts. A cell the workbook coloured by hand but no report has ever supplied
    is not a result: counting those had the portfolio reporting 90% at or above
    target off 105 cells that had never been measured, and a property with no
    feed at all scoring a clean 100%.

    The workbook's own symbol is still published, in "statuses" and in
    "status_workbook" — it is the analyst's opinion, kept, but not evidence.
    """
    src = p.get("status_source") or {}
    return [n for n in names if src.get(n) == "measured"]


def coverage_of(p, names):
    """How much of a property's row is actually reported, in three parts that
    add up to every cell: graded, reported but not gradeable (a count triple
    against a per-unit band, an unconfirmed basis, a distribution), and nothing
    yet."""
    vals = p.get("values") or {}
    g = set(graded(p, names))
    reported = {n for n in names
                if (vals.get(n) or {}).get("display") is not None}
    return {"graded": len(g),
            "reported_ungraded": len(reported - g),
            "awaiting": len(set(names) - reported - g),
            "total": len(names)}


def recompute(sc):
    """Rebuild every derived figure from the per-property status maps."""
    names = [m["name"] for m in sc["metrics"]]
    for p in sc["properties"]:
        counts = {"exceeding": 0, "in_range": 0, "below": 0}
        for n in graded(p, names):
            st = p["statuses"].get(n)
            if st in counts:
                counts[st] += 1
        scored = sum(counts.values())
        p["counts"] = counts
        p["scored"] = scored
        p["at_or_above"] = (round((counts["exceeding"] + counts["in_range"]) / scored, 4)
                            if scored else None)
        p["below_metrics"] = [n for n in graded(p, names)
                              if p["statuses"].get(n) == "below"]
        p["coverage"] = coverage_of(p, names)

    total = {"exceeding": 0, "in_range": 0, "below": 0}
    cover = {"graded": 0, "reported_ungraded": 0, "awaiting": 0, "total": 0}
    for p in sc["properties"]:
        for k in total:
            total[k] += p["counts"][k]
        for k in cover:
            cover[k] += p["coverage"][k]
    scored_total = sum(total.values())
    by_metric = []
    for m in sc["metrics"]:
        c = {"exceeding": 0, "in_range": 0, "below": 0}
        for p in sc["properties"]:
            if m["name"] not in graded(p, names):
                continue
            s = p["statuses"].get(m["name"])
            if s in c:
                c[s] += 1
        by_metric.append({"name": m["name"], "group": m["group"], "counts": c})
    sc["portfolio"].update({
        "property_count": len(sc["properties"]),
        "metric_count": len(sc["metrics"]),
        "counts": total,
        "scored": scored_total,
        "at_or_above": (round((total["exceeding"] + total["in_range"]) / scored_total, 4)
                        if scored_total else None),
        "coverage": cover,
        "by_metric": by_metric,
    })


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delinquency", help="a delinquency report to parse")
    ap.add_argument("--from-landing", action="store_true",
                    help="use docs/landing.json's delinquency block (The Landing)")
    ap.add_argument("--from-pipeline", metavar="SLUG",
                    help="use data/<SLUG>/delinquency.json, as the Drive pipeline wrote it")
    ap.add_argument("--property", default="the-landing", help="property slug to fill")
    ap.add_argument("--received-at", metavar="ISO8601",
                    help="when this report actually arrived (e.g. 2026-08-10T14:05:00Z). "
                         "Overrides the arrival the source carries; needed for a "
                         "report handed over by hand, which has none of its own. "
                         "The scorecard shows it as the data's last-updated time.")
    ap.add_argument("--monthly-rent", type=float,
                    help="one month's billed rent, for the Total Deliquency ratio")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()

    if not (a.delinquency or a.from_landing or a.from_pipeline):
        sys.exit("give one of --delinquency <report.xlsx>, --from-landing, "
                 "--from-pipeline <slug>")

    if a.from_pipeline:
        slug = a.from_pipeline
        facts = facts_from_pipeline(slug, a.monthly_rent)
        if facts is None:
            print(f"no data/{slug}/delinquency.json — nothing to fill for {slug}")
            return
    elif a.delinquency:
        facts = facts_from_report(a.delinquency, a.monthly_rent)
        slug = a.property
    else:
        facts = facts_from_landing()
        slug = "the-landing"

    if a.received_at:
        try:
            datetime.fromisoformat(a.received_at.replace("Z", "+00:00"))
        except ValueError:
            sys.exit(f"--received-at {a.received_at!r} is not an ISO-8601 timestamp "
                     f"(want e.g. 2026-08-10T14:05:00Z)")
        facts["received_at"] = a.received_at
        facts["received_what"] = facts.get("received_what") or "report supplied by hand"

    sc = json.load(open(a.out))
    prop = next((p for p in sc["properties"] if p["slug"] == slug), None)
    if not prop:
        sys.exit(f"no property with slug {slug!r} on the scorecard "
                 f"(have: {[p['slug'] for p in sc['properties'] if p['slug']]})")
    thresholds = sc.get("thresholds") or {}

    print(f"source: {facts['source']}  ·  as of {facts['as_of']}  ·  "
          f"property: {prop['label']}")
    if facts.get("received_at"):
        print(f"arrived: {facts['received_at']}"
              + (f" ({facts['received_what']})" if facts.get("received_what") else ""))
    else:
        print("arrived: unknown — no arrival time on this source; the scorecard "
              "will fall back to the as-of date. Pass --received-at to record one.")
    print(f"{'KPI':26} {'measured':>18}  {'band says':<11} {'workbook had':<11} action")
    print("-" * 86)

    unscored = set(sc.get("unscored") or [])
    changed, filled = [], 0
    for kpi, (value, display, why) in measurements(facts).items():
        if kpi not in prop["statuses"]:
            print(f"{kpi:26} {'—':>18}  not on this scorecard")
            continue
        was = prop["statuses"].get(kpi)
        if display is None:
            print(f"{kpi:26} {'—':>18}  {'—':<11} {str(was):<11} skipped: {why}")
            continue

        rec = {"raw": round(value, 6) if value is not None else None,
               "display": display}
        if kpi == KPI_SPLIT:
            rec["parts"] = facts["split"]
            rec["parts_labels"] = SPLIT_LABELS
        prop["values"][kpi] = rec
        filled += 1

        if kpi in unscored:
            # reported, not graded: leave the status null so the cell shows the
            # figures with no symbol, no colour, and no place in the counts
            prop["statuses"][kpi] = None
            prop.setdefault("status_source", {})[kpi] = "unscored"
            print(f"{kpi:26} {display:>18}  {'—':<11} {str(was):<11} "
                  f"reported, not graded")
            continue

        band = classify(value, thresholds.get(kpi))
        # keep the workbook's own symbol beside the derived one
        if band and band != was:
            prop.setdefault("status_workbook", {})[kpi] = was
            prop.setdefault("status_source", {})[kpi] = "measured"
            prop["statuses"][kpi] = band
            changed.append((kpi, was, band, display))
            action = f"RESTATED {was} -> {band}"
        else:
            prop.setdefault("status_source", {})[kpi] = "measured"
            action = "confirms the workbook"
        print(f"{kpi:26} {display:>18}  {str(band):<11} {str(was):<11} {action}")

    recompute(sc)

    meas = sc.setdefault("measured", {})
    # update, not replace: another feed's keys for this property live in the
    # same dict under their own prefix (bldg_*, eliseai_*), and replacing it
    # wholesale dropped them whenever this script ran out of the documented
    # order -- taking their arrival times off the page with them.
    meas.setdefault(slug, {}).update({
                 "source": facts["source"], "as_of": facts["as_of"],
                 # arrival time, not coverage date: what the page reports as
                 # "data last updated". None when the source carries none.
                 "received_at": facts.get("received_at"),
                 "received_what": facts.get("received_what"),
                 # keyed on display, not raw: an unscored KPI has figures to
                 # show but no single number to classify
                 "kpis": sorted(k for k in measurements(facts)
                                if prop["values"].get(k, {}).get("display") is not None)})
    if facts.get("denominator_note"):
        meas[slug]["denominator"] = facts["denominator_note"]
    if facts.get("ltl_month"):
        meas[slug]["ltl_month"] = facts["ltl_month"]
    if facts.get("ctrl_month"):
        meas[slug]["controllable_basis"] = (
            f"{facts['ctrl_month']} operating expense less taxes, insurance and "
            f"utilities, over {facts['ctrl_units']} units, x12")
    if facts.get("noi_margin_month"):
        meas[slug]["noi_margin_month"] = facts["noi_margin_month"]
        # the T12 figure the band's own basis names, kept beside the month that
        # is graded so the difference between them is on the record
        meas[slug]["noi_margin_ttm"] = facts.get("noi_margin_ttm")
    sc["meta"]["note"] = (sc["meta"]["note"].split(" Measured values")[0] +
                          " Measured values, where present, are computed from the "
                          "underlying report and their status is derived from the "
                          "published band rather than set by hand.")

    with open(a.out, "w") as f:
        json.dump(sc, f, separators=(",", ":"))

    print(f"\nwrote {a.out}: {filled} value(s) filled for {prop['label']}")
    print(f"  {prop['label']}: {prop['at_or_above']:.0%} at or above target "
          f"({prop['counts']['below']} below of {prop['scored']})")
    print(f"  portfolio: {sc['portfolio']['at_or_above']:.2%} at or above target "
          f"({sc['portfolio']['counts']['below']} below of {sc['portfolio']['scored']})")
    if changed:
        print("\n  the measurement disagreed with the hand-set symbol:")
        for kpi, was, now, v in changed:
            t = thresholds.get(kpi, {})
            print(f"    {kpi}: {was} -> {now}  ({v}; "
                  f"exceeding {t.get('exceeding')}, in range {t.get('in_range')}, "
                  f"below {t.get('below')})")


if __name__ == "__main__":
    main()

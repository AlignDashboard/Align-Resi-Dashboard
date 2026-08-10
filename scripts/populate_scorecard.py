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
  Split Between 30/60/90    share of total AR aged 60+ days

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
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUT = "docs/scorecard.json"

# The grid spells it "Total Deliquency" (sic). Key off the grid's own spelling,
# because that is what the properties' status maps use.
KPI_TOTAL = "Total Deliquency"
KPI_SPLIT = "Split Between 30/60/90"


def pct1(v):
    return f"{v * 100:.1f}%"


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


def facts_from_landing(path="docs/landing.json"):
    d = json.load(open(path))["delinquency"]
    ag = {a["bucket"]: a["amount"] for a in d["aging"]}
    sixty = sum(v for k, v in ag.items()
                if "61" in k or "over 90" in k.lower())
    return {
        "as_of": d.get("as_of"),
        "gross_owed": d.get("gross_owed"),
        "aged_60_plus": sixty,
        # the workbook computes this ratio itself, so use it rather than
        # re-deriving the denominator
        "total_delinq_pct": d.get("pct_month_rent"),
        "source": "workbook Source Delinquency tab, via docs/landing.json",
    }


def facts_from_report(path, monthly_rent):
    import parse_delinquency
    parsed = parse_delinquency.parse(path)
    s = parsed["summary"]
    sixty = (s["aging"]["d61_90"] or 0) + (s["aging"]["over90"] or 0)
    gross = s["gross_owed"]
    return {
        "as_of": parsed.get("as_of"),
        "gross_owed": gross,
        "aged_60_plus": sixty,
        "total_delinq_pct": (gross / monthly_rent) if monthly_rent else None,
        "source": os.path.basename(path),
    }


def measurements(f):
    """{kpi: (value, why-it-is-missing)} for the KPIs a delinquency report covers."""
    out = {}
    if f.get("total_delinq_pct") is not None:
        out[KPI_TOTAL] = (f["total_delinq_pct"], None)
    else:
        out[KPI_TOTAL] = (None, "needs one month's billed rent — pass --monthly-rent")
    if f.get("gross_owed"):
        out[KPI_SPLIT] = (f["aged_60_plus"] / f["gross_owed"], None)
    else:
        out[KPI_SPLIT] = (None, "report has no gross AR balance to divide by")
    return out


def recompute(sc):
    """Rebuild every derived figure from the per-property status maps."""
    names = [m["name"] for m in sc["metrics"]]
    for p in sc["properties"]:
        counts = {"exceeding": 0, "in_range": 0, "below": 0, "missing": 0}
        for n in names:
            counts[p["statuses"].get(n) or "missing"] += 1
        scored = counts["exceeding"] + counts["in_range"] + counts["below"]
        p["counts"] = counts
        p["scored"] = scored
        p["at_or_above"] = (round((counts["exceeding"] + counts["in_range"]) / scored, 4)
                            if scored else None)
        p["below_metrics"] = [n for n in names if p["statuses"].get(n) == "below"]

    total = {"exceeding": 0, "in_range": 0, "below": 0, "missing": 0}
    for p in sc["properties"]:
        for k in total:
            total[k] += p["counts"][k]
    scored_total = total["exceeding"] + total["in_range"] + total["below"]
    by_metric = []
    for m in sc["metrics"]:
        c = {"exceeding": 0, "in_range": 0, "below": 0}
        for p in sc["properties"]:
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
        "by_metric": by_metric,
    })


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delinquency", help="a delinquency report to parse")
    ap.add_argument("--from-landing", action="store_true",
                    help="use docs/landing.json's delinquency block (The Landing)")
    ap.add_argument("--property", default="the-landing", help="property slug to fill")
    ap.add_argument("--monthly-rent", type=float,
                    help="one month's billed rent, for the Total Deliquency ratio")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()

    if not (a.delinquency or a.from_landing):
        sys.exit("give either --delinquency <report.xlsx> or --from-landing")

    facts = (facts_from_report(a.delinquency, a.monthly_rent) if a.delinquency
             else facts_from_landing())
    slug = "the-landing" if a.from_landing else a.property

    sc = json.load(open(a.out))
    prop = next((p for p in sc["properties"] if p["slug"] == slug), None)
    if not prop:
        sys.exit(f"no property with slug {slug!r} on the scorecard "
                 f"(have: {[p['slug'] for p in sc['properties'] if p['slug']]})")
    thresholds = sc.get("thresholds") or {}

    print(f"source: {facts['source']}  ·  as of {facts['as_of']}  ·  "
          f"property: {prop['label']}")
    print(f"{'KPI':26} {'measured':>10}  {'band says':<11} {'workbook had':<11} action")
    print("-" * 78)

    changed, filled = [], 0
    for kpi, (value, why) in measurements(facts).items():
        if kpi not in prop["statuses"]:
            print(f"{kpi:26} {'—':>10}  not on this scorecard")
            continue
        was = prop["statuses"].get(kpi)
        if value is None:
            print(f"{kpi:26} {'—':>10}  {'—':<11} {str(was):<11} skipped: {why}")
            continue
        band = classify(value, thresholds.get(kpi))
        prop["values"][kpi] = {"raw": round(value, 6), "display": pct1(value)}
        filled += 1
        # keep the workbook's own symbol beside the derived one
        if band and band != was:
            prop.setdefault("status_workbook", {})[kpi] = was
            prop.setdefault("status_source", {})[kpi] = "measured"
            prop["statuses"][kpi] = band
            changed.append((kpi, was, band, value))
            action = f"RESTATED {was} -> {band}"
        else:
            prop.setdefault("status_source", {})[kpi] = "measured"
            action = "confirms the workbook"
        print(f"{kpi:26} {pct1(value):>10}  {str(band):<11} {str(was):<11} {action}")

    recompute(sc)

    meas = sc.setdefault("measured", {})
    meas[slug] = {"source": facts["source"], "as_of": facts["as_of"],
                  "kpis": sorted(k for k in measurements(facts)
                                 if prop["values"].get(k, {}).get("raw") is not None)}
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
            print(f"    {kpi}: {was} -> {now}  ({pct1(v)}; "
                  f"exceeding {t.get('exceeding')}, in range {t.get('in_range')}, "
                  f"below {t.get('below')})")


if __name__ == "__main__":
    main()

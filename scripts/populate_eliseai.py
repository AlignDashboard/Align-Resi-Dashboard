#!/usr/bin/env python3
"""Fill the EliseAI leasing figures into docs/scorecard.json.

Reads data/<slug>/eliseai_daily.json — the counts-only series extracted from the
"Leasing AI Daily Report" emails (the emails themselves list prospects by name
and are never persisted; see the series file's own comment).

What a daily email can honestly answer:

  # of Tours/Leads/Applications   the latest day's tours/leads/applications as a
                                  T/L/A triple. VALUE ONLY — the published band
                                  grades tours per available unit per MONTH, and
                                  a single day cannot be held to a monthly band,
                                  so the workbook's hand-set symbol stays.
  Open Elise Tasks                the email's "Review N pieces of pending
                                  knowledge" count, graded against the band.
                                  ASSUMPTION: pending-knowledge items are the
                                  open EliseAI tasks the KPI means. If that
                                  mapping is wrong, drop OPEN_TASKS_FROM_KNOWLEDGE.

Closing Ratio, # of Renewals, offer and MTM KPIs need the weekly EliseAI report
(Drive: EliseAI Reports folder) as a baseline — not wired yet; the folder is
registered in report_map.json as pending.

Idempotent, and rebuilds the roll-ups via populate_scorecard.recompute so the
matrix, health chart and tally stay consistent.

Usage:
  python scripts/populate_eliseai.py --slug 335-third-street
  python scripts/populate_eliseai.py --slug 335-third-street --add \
      '{"date":"2026-08-14","new_leads":2,"tours_today":1}'   # then fills
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from populate_scorecard import OUT, classify, recompute  # noqa: E402

KPI_TLA = "# of Tours/Leads/Applications"
KPI_TASKS = "Open Elise Tasks"
OPEN_TASKS_FROM_KNOWLEDGE = True

# every count a day can carry; absent = zero (EliseAI omits empty sections)
DAY_FIELDS = ("new_leads", "tours_today", "tours_booked_since_yesterday",
              "applications", "cancelled_leads", "unsubscribed",
              "escalations_open", "pending_knowledge")


def series_path(slug):
    return os.path.join("data", slug, "eliseai_daily.json")


def load_series(slug):
    p = series_path(slug)
    return json.load(open(p)) if os.path.exists(p) else None


def add_day(slug, day_json):
    day = json.loads(day_json)
    if "date" not in day:
        sys.exit("--add needs at least {\"date\": \"YYYY-MM-DD\"}")
    unknown = sorted(set(day) - set(DAY_FIELDS) - {"date"})
    if unknown:
        sys.exit(f"unknown count field(s) {unknown}; allowed: {list(DAY_FIELDS)}")
    for k in DAY_FIELDS:
        day.setdefault(k, 0)
    ser = load_series(slug) or {"days": []}
    ser["days"] = [d for d in ser["days"] if d["date"] != day["date"]] + [day]
    ser["days"].sort(key=lambda d: d["date"])
    os.makedirs(os.path.dirname(series_path(slug)), exist_ok=True)
    json.dump(ser, open(series_path(slug), "w"), indent=2)
    print(f"recorded {day['date']} for {slug}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--add", help="JSON for one day's counts; recorded before filling")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()

    if a.add:
        add_day(a.slug, a.add)

    ser = load_series(a.slug)
    if not ser or not ser.get("days"):
        sys.exit(f"no {series_path(a.slug)} — nothing to fill")
    latest = max(ser["days"], key=lambda d: d["date"])

    sc = json.load(open(a.out))
    prop = next((p for p in sc["properties"] if p["slug"] == a.slug), None)
    if not prop:
        sys.exit(f"no property with slug {a.slug!r} on the scorecard")
    thresholds = sc.get("thresholds") or {}

    print(f"EliseAI daily for {prop['label']}, latest {latest['date']}")

    filled = []
    if KPI_TLA in prop["statuses"]:
        t, l, ap_ = (latest.get("tours_today") or 0, latest.get("new_leads") or 0,
                     latest.get("applications") or 0)
        prop["values"][KPI_TLA] = {
            "raw": None,
            "display": f"{t}/{l}/{ap_}",
            "parts": [t, l, ap_],
            "parts_labels": ["tours", "leads", "apps"],
        }
        # value only: the band is tours per available unit per month, and one
        # day's counts cannot be graded against it — the hand-set symbol stays
        prop.setdefault("status_source", {})[KPI_TLA] = "value_only"
        filled.append(KPI_TLA)
        print(f"  {KPI_TLA}: {t}/{l}/{ap_} (tours/leads/apps, {latest['date']}) — "
              f"value only, symbol unchanged ({prop['statuses'][KPI_TLA]})")

    if OPEN_TASKS_FROM_KNOWLEDGE and KPI_TASKS in prop["statuses"]:
        n = latest.get("pending_knowledge")
        if n is not None:
            was = prop["statuses"][KPI_TASKS]
            band = classify(float(n), thresholds.get(KPI_TASKS))
            prop["values"][KPI_TASKS] = {"raw": n, "display": str(n)}
            if band and band != was:
                prop.setdefault("status_workbook", {})[KPI_TASKS] = was
                prop["statuses"][KPI_TASKS] = band
            prop.setdefault("status_source", {})[KPI_TASKS] = "measured"
            filled.append(KPI_TASKS)
            print(f"  {KPI_TASKS}: {n} pending-knowledge items -> {band or was}"
                  + (f" (was {was})" if band and band != was else ""))

    recompute(sc)
    meas = sc.setdefault("measured", {})
    entry = meas.setdefault(a.slug, {})
    entry.update({
        "eliseai_source": "Leasing AI Daily Report email (counts only; the "
                          "prospect roster is never persisted)",
        "eliseai_as_of": latest["date"],
        "eliseai_kpis": filled,
        "eliseai_basis": "latest day's counts; the T/L/A cell is ungraded because "
                         "the band is monthly per-available-unit",
    })

    with open(a.out, "w") as f:
        json.dump(sc, f, separators=(",", ":"))
    print(f"wrote {a.out}: {len(filled)} cell(s) filled for {prop['label']}")
    print(f"  {prop['label']}: {prop['at_or_above']:.0%} at or above target "
          f"({prop['counts']['below']} below of {prop['scored']})")


if __name__ == "__main__":
    main()

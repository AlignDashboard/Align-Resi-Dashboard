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

  Loss to Lease %           market rent less in-place rent over market rent,
                            across OCCUPIED units, from the Drive rent roll --
                            which is what the band's own "how" always said, and
                            what the workbook fill never was. Owner's call,
                            2026-09-15 (open item A8). Filled on BOTH paths from
                            the same published aggregate, so neither run can
                            take the cell off the other.
  NOI Margin %              the current month's NOI over revenue, from the
                            Expense & NOI series behind that card. The published
                            band's basis is T12, and a single accrual month
                            swings well past it in both directions, so the TTM
                            figure is recorded alongside the graded month.
  Month to Month Leases     units past lease expiry and still occupied, printed
                            as "31/11.8%" -- the count and its share of occupied
                            units. The share is what the band grades, per its own
                            basis line. (The grid calls this column "# of month
                            to month"; see RENAMES in extract_scorecard.py.) The
                            renewal tracker's
                            MTM roster is not used: the workbook's reconciliation
                            finds most of it wrong, and the units it gets right
                            are already inside this cohort.
  Controllable OpEx/Unit    the current month's operating expense less taxes,
                            insurance, utilities and the management fee, per
                            unit, x12 for the band's per-year basis. Numerator
                            comes from the T12 statement's account groups
                            (data/<slug>/expense_buckets.json), since the
                            workbook carries only a total. The band's cutoffs are
                            the workbook's; its "how" line described an older
                            basket, so the fill restates it and keeps the sheet's
                            wording in "how_workbook".
  Budget Variance %         calendar-YTD (January through the statement's
                            newest month) actual controllable opex against the
                            same months of the year's budget, printed as
                            "$ nominal/% variance", signed, positive meaning
                            an overspend. Both sides are the same basket --
                            the Align-grouped buckets less NOT_CONTROLLABLE --
                            actuals from data/<slug>/expense_buckets.json,
                            plan from data/<slug>/budget.json (the Drive
                            Budgets folder). The band grades the ABSOLUTE
                            magnitude, per its own "how".
  Concession Load %         the current month's concessions over market rent
                            potential less loss to lease less vacancy loss --
                            the T12 statement's rent income before concessions
                            and the employee allowance -- from the same Rent
                            Capture series as Loss to Lease. Equation set by the
                            owner 2026-09-03; the ranges sheet's own "how" named
                            gross potential rent as the denominator and a
                            trailing-3-months window, so "how" is restated (the
                            sheet's wording kept in "how_workbook") and the
                            trailing-3 figure is recorded beside the graded
                            month.

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
import re
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
KPI_MTM = "Month to Month Leases"
KPI_CONC = "Concession Load %"
KPI_BV = "Budget Variance %"
KPI_TO = "Trade-out %"

# Which trailing window of the Lease Tradeout Report answers Trade-out %.
# THREE, because that is the basis the published band was written for -- the
# ranges sheet grades a trailing 3 months, and until this feed existed the cell
# came from the EliseAI export on a trailing ONE month (open item B6: "a
# volatile month swings the grade more than the bands assume"). The report
# carries every lease with its signed date, so the window is a choice here
# rather than whatever an export happened to cover. One constant to change.
TRADEOUT_WINDOW = 3

# The rent roll's own classification, as the workbook reads it: every unit is in
# exactly one of these. There is no separate month-to-month state, so a unit the
# rent roll calls month-to-month is already a holdover -- which is why the four
# units the renewal tracker and the rent roll agree on are inside this 31 rather
# than beside it.
MTM_STATUS = "Holdover"
OCCUPIED_STATUSES = ("Current", "On notice", "Holdover")

# What a property manager cannot move inside a month, per the owner. Matched by
# name against the T12 statement's own account groups rather than listed exactly,
# and every one must be found -- a renamed group that silently stopped matching
# would leave taxes inside "controllable" and the figure would read far too high.
NOT_CONTROLLABLE = ("tax", "insurance", "utilit", "management fee")
# The band's numeric cutoffs are the workbook's; the basket they are applied to
# is this. The workbook's ranges sheet still describes the older basket, so the
# fill restates "how" from what it actually excluded and keeps the sheet's own
# wording beside it, rather than publishing a definition the number does not
# follow.
# A9, owner 2026-09-21: "Rebracket". The published cutoffs ($7,200 / $8,600)
# were bracketed around the OLD basket's $7,784/unit T12 actual -- a basket that
# counted utilities as controllable. The basket has excluded utilities and the
# management fee since 2026-08-28, under which the same twelve months read
# $6,939/unit, so the band was grading a smaller basket against a bigger
# basket's yardstick and "exceeding" meant the basket had shrunk.
#
# The band is SHIFTED, not rescaled: both cutoffs move down by the same $845
# the basket itself moved ($7,784 - $6,939), keeping the band's $1,400 width.
# Width is a tolerance in dollars per unit per year, and taking a cost category
# out of the basket is not a statement about how much variance is acceptable.
# Rescaling by the ratio instead would give $6,419 / $7,666 and a $1,247 width;
# the two agree to within $70 on the green cutoff, so nothing here turns on the
# choice, but it is a choice and it is the owner's to overrule.
#
# Rounded to the nearest $100, as the workbook's own cutoffs are. The new actual
# sits in range exactly as the old actual did against the old band, which is the
# point: this restates the yardstick, it does not re-grade the building.
CONTROLLABLE_CUTOFFS = {"green": 6400, "red": 7800}
CONTROLLABLE_BAND_NOTE = (
    "Rebracketed 2026-09-21 (A9) to the basket the cell actually grades: the "
    "workbook's $7,200/$8,600 bracketed a $7,784/unit actual on a basket that "
    "counted utilities as controllable. Both cutoffs shift down by the $845 the "
    "basket moved, keeping the $1,400 width; The Landing's T12 on the live "
    "basket is $6,939/unit.")

CONTROLLABLE_HOW = ("Operating expense less taxes, insurance, utilities and the "
                    "management fee, per unit, current month x12")
# The owner's equation (2026-09-03): concessions over the T12 statement's rent
# income before concessions and the employee allowance. The ranges sheet's own
# "how" divided by gross potential rent over a trailing 3 months instead, so the
# published definition is restated to match the published number, with the
# sheet's wording kept in "how_workbook" -- same treatment as the controllable
# basket above.
CONCESSION_HOW = ("Concessions over market rent potential less loss to lease "
                  "less vacancy loss, current month")


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


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _controllable_sum(buckets, idx):
    """Controllable dollars over the given month indices, or (None, why) if a
    named exclusion group has gone missing -- the same all-must-be-found guard
    as controllable_per_unit, because a renamed group that silently stopped
    matching would count taxes as controllable."""
    names = list(buckets)
    found = [k for k in NOT_CONTROLLABLE if any(k in n.lower() for n in names)]
    if len(found) != len(NOT_CONTROLLABLE):
        return None, ("the account groups do not name "
                      + ", ".join(k for k in NOT_CONTROLLABLE if k not in found))
    total = sum(b[i] for b in buckets.values() for i in idx)
    excl = sum(b[i] for n, b in buckets.items()
               if any(k in n.lower() for k in NOT_CONTROLLABLE) for i in idx)
    return total - excl, None


def budget_variance_ytd(slug):
    """The calendar-YTD controllable-opex variance against the year's budget.

    Returns a dict: ``dollars``, ``pct``, ``window`` and the budget's own
    ``source``/``received_at`` when it can be computed, or ``why`` when it
    cannot. A dict rather than a tuple because the refusals carry provenance
    too -- the page says which budget file it declined to use, not just that
    something was missing.

    Both sides are the same basket: the Align-grouped expense buckets that sum
    to each file's own TOTAL EXPENSES, less the NOT_CONTROLLABLE groups. The
    budget comes from data/<slug>/budget.json (the Drive Budgets folder); the
    actuals from data/<slug>/expense_buckets.json (the T12 statement). Dollars
    are actual minus budget, so positive is an overspend; the band grades the
    absolute magnitude, per its own "how".
    """
    bpath = os.path.join("data", slug, "budget.json")
    epath = os.path.join("data", slug, "expense_buckets.json")
    if not os.path.exists(bpath):
        return {"why": "no budget in data/ for this property"}
    if not os.path.exists(epath):
        return {"why": "no T12 statement grouped by account for this property"}
    # budget.json holds one point per budget year (see build_metrics.store_budget);
    # files written before that change are a single flat plan, so read both.
    raw = json.load(open(bpath))
    years = raw.get("years") if isinstance(raw, dict) else None
    if years is None:
        years = [raw] if isinstance(raw, dict) and raw.get("year") is not None else []
    if not years:
        return {"why": "budget file carries no plan"}

    pts = (json.load(open(epath)) or {}).get("points") or []
    if not pts:
        return {"why": "no T12 statement grouped by account for this property"}
    pt = pts[-1]
    try:
        end_mon, end_year = pt["period_end"].split()
        n = MONTHS.index(end_mon) + 1              # Jul -> 7 months of YTD
    except (ValueError, KeyError, AttributeError):
        return {"why": f"cannot read the statement's period end "
                       f"({pt.get('period_end')!r})"}

    # The KPI is calendar-YTD, so the plan that answers it is the statement's
    # own year -- not simply the newest one on file. Since budgets are kept per
    # year, picking the wrong one would compare this year's actuals against
    # last year's plan and read the difference as a variance.
    bud = next((y for y in years if y.get("year") == int(end_year)), None)
    if bud is None:
        return {"source": years[-1].get("source_file"),
                "received_at": years[-1].get("landed_at"),
                "why": f"no {end_year} budget on file "
                       f"(held: {', '.join(str(y.get('year')) for y in years)})"}
    out = {"source": bud.get("source_file"), "received_at": bud.get("landed_at")}

    def no(why):
        return dict(out, why=why)

    if not bud.get("buckets"):
        return no("budget or statement carries no bucket detail")
    labels = pt.get("labels") or []
    if len(labels) < n or labels[-n] != "Jan":
        return no("the statement's last twelve months do not reach back to "
                  "January")
    act, why = _controllable_sum(pt["buckets"],
                                 range(len(labels) - n, len(labels)))
    if why:
        return no(f"actuals: {why}")
    if (bud.get("labels") or [None])[0] != "Jan":
        return no("budget months do not start in January")
    plan, why = _controllable_sum(bud["buckets"], range(n))
    if why:
        return no(f"budget: {why}")
    if not plan:
        return no("budget controllable YTD is zero")
    return dict(out, dollars=act - plan, pct=(act - plan) / plan,
                window=f"Jan-{end_mon} {end_year}")


def pct0(v):
    """Loss to lease as a whole number of percent: a gap this wide is not a
    figure a tenth of a point changes the reading of."""
    return f"{v * 100:.0f}%"


def restate_controllable_band(thresholds):
    """Put the rebracketed cutoffs (A9) on the threshold, keeping the sheet's.

    Restated here rather than edited into scorecard.json because
    extract_scorecard resets every band from the ranges sheet on each
    re-extraction, so a hand-edited band would silently revert -- the same
    reason the `how` is restated.

    MUST run before the classify loop. It did not, once: the band was rewritten
    in the post-fill block and the cells were still graded against the sheet's
    old cutoffs, so one run published $6,757 as "exceeding" beside a band whose
    own ceiling for exceeding was $6,400. A file that disagrees with itself is
    worse than either band alone.
    """
    t = (thresholds or {}).get(KPI_CTRL)
    if not t or t.get("green_cutoff") == CONTROLLABLE_CUTOFFS["green"]:
        return None
    for key in ("green_cutoff", "red_cutoff", "exceeding", "in_range", "below",
                "basis"):
        t.setdefault(key + "_workbook", t.get(key))
    g, r = CONTROLLABLE_CUTOFFS["green"], CONTROLLABLE_CUTOFFS["red"]
    t["green_cutoff"], t["red_cutoff"] = g, r
    t["exceeding"], t["in_range"], t["below"] = (
        f"\u2264 ${g:,}", f"${g:,} \u2013 ${r:,}", f"> ${r:,}")
    t["basis"] = CONTROLLABLE_BAND_NOTE
    return (t["green_cutoff_workbook"], t["red_cutoff_workbook"], g, r)


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


def lease_tradeout(slug, path="docs/metrics.json"):
    """Trade-out over the trailing TRADEOUT_WINDOW months, or (None, why).

    From the Yardi Lease Tradeout Report — the only feed with a trade-out
    history of its own, one row per new lease with the lease it replaced
    beside it. Read from the published aggregate in metrics.json, like the
    rent roll's loss to lease, so CI and a local run see the same figure.

    **Weighted, never the mean of the per-lease rates.** The report's own
    percentage is total current effective rent over total previous effective
    rent, and that is what is graded here. The mean of its per-lease column is
    a different number entirely -- 70.1% against the weighted 23.4% over The
    Landing's first file -- because a concession drives a previous effective
    rent toward zero and the ratio explodes: one lease reads $86 previous
    against a $62,716 concession and prints 6,136%. A mean of ratios over a
    denominator that can approach zero is not a rate. It is recorded beside
    the figure so the two are never mistaken for one another.
    """
    if not os.path.exists(path):
        return None, "no docs/metrics.json to read the trade-out report from"
    block = (json.load(open(path)) or {}).get("lease_tradeout") or {}
    pr = next((x for x in (block.get("properties") or [])
               if x.get("slug") == slug), None)
    if pr is None:
        return None, f"no lease tradeout report published for {slug}"
    win = (pr.get("windows") or {}).get(f"t{TRADEOUT_WINDOW}")
    if not win or win.get("pct") is None:
        return None, (f"the trade-out report holds no trailing "
                      f"{TRADEOUT_WINDOW} months for {slug}")
    allw = pr.get("all") or {}
    return {
        "pct": win["pct"],
        "leases": win["leases"],
        "window_start": win.get("window_start"),
        "window_end": win.get("window_end"),
        "complete": win.get("complete"),
        "months": TRADEOUT_WINDOW,
        "all_pct": allw.get("pct"),
        "all_leases": allw.get("leases"),
        "mean_pct": win.get("mean_pct"),
        "period_start": pr.get("period_start"),
        "period_end": pr.get("period_end"),
        "rate_type": pr.get("rate_type"),
        "tradeout_basis": pr.get("tradeout_basis"),
        "lease_date_basis": pr.get("lease_date_basis"),
        "source": pr.get("source_file"),
        "as_of": pr.get("as_of"),
        "received_at": pr.get("landed_at"),
    }, None


def rent_roll_ltl(slug, path="docs/metrics.json"):
    """Loss to lease from the rent roll, or (None, why).

    The owner's call, 2026-09-15 (open item A8): the rent roll is the source
    for this KPI. It is also the only source that matches the band's own
    published "how" -- "(Market rent - in-place rent) / market rent, current
    rent roll" -- which the workbook fill never did: that one was the T12
    statement's monthly revenue lines, a different measurement of a similarly
    named thing, and it read 27% against the roll's 36.5%.

    Read from the published aggregate in metrics.json rather than
    data/<slug>/rent_roll.json, which is gitignored (it is unit level and
    arrives with resident names) and therefore exists only during a pipeline
    run. build_metrics writes metrics.json before this script runs, and the
    block is committed, so the same figure is available in CI and locally.

    Occupied units only, per the parser's own basis: a vacant unit has an
    asking rent and no in-place rent, so counting it books the whole asking
    rent as a loss (38.1% against the 36.5% published).
    """
    if not os.path.exists(path):
        return None, "no docs/metrics.json to read the rent roll from"
    block = (json.load(open(path)) or {}).get("rent_roll") or {}
    pr = next((x for x in (block.get("properties") or [])
               if x.get("slug") == slug), None)
    if pr is None:
        return None, f"no rent roll published for {slug}"
    if pr.get("loss_to_lease_pct") is None:
        return None, "the rent roll carries no loss-to-lease figure"
    return {
        "pct": pr["loss_to_lease_pct"],
        "dollars": pr.get("loss_to_lease"),
        "market": pr.get("market_rent_occupied"),
        "actual": pr.get("actual_rent_occupied"),
        "occupied": pr.get("occupied"),
        "as_of": pr.get("as_of"),
        "received_at": pr.get("landed_at"),
        "source": pr.get("source_file"),
    }, None


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
    rr_ltl, rr_ltl_why = rent_roll_ltl("the-landing")
    # Trade-out %, from the Drive tradeout report. Like loss to lease it is
    # filled identically on both paths from one published aggregate, so
    # whichever run goes last writes the same number.
    to_win, to_why = lease_tradeout("the-landing")
    # NOI margin, likewise from the monthly series behind the Expense Load & NOI
    # card rather than its TTM column. Note the published band's own basis says
    # T12: a single accrual month swings hard (Apr 2026 reads 47.0% on that
    # month's tax true-up, Jul 2026 reads 72.6%), so both are recorded below and
    # which one the band is meant to grade is the owner's call.
    en = doc.get("expense_noi") or {}
    noi_series, noi_months = en.get("noi_margin") or [], en.get("months") or []
    # Concession load, from the same Rent Capture series as loss to lease. The
    # four series reconcile exactly to the workbook's own rental-income line
    # (GPR - L2L - vacancy - concessions - allowance = rental income, to the
    # cent), so the denominator is the statement's rent income before
    # concessions and the employee allowance. Vacancy loss can run negative in
    # a true-up month (Jul 2026 does), which per the equation ADDS to the
    # denominator rather than being clamped.
    conc = rc.get("concessions") or []
    mp = rc.get("market_potential") or []
    l2l = rc.get("loss_to_lease") or []
    vac = rc.get("vacancy_loss") or []
    n = min(len(conc), len(mp), len(l2l), len(vac))
    conc_load = conc_load_t3 = conc_parts = None
    if n:
        denom = mp[n - 1] - l2l[n - 1] - vac[n - 1]
        if denom > 0:
            conc_load = conc[n - 1] / denom
            conc_parts = (conc[n - 1], mp[n - 1], l2l[n - 1], vac[n - 1])
        k = min(3, n)
        d3 = sum(mp[n - k:n]) - sum(l2l[n - k:n]) - sum(vac[n - k:n])
        if d3 > 0:
            conc_load_t3 = sum(conc[n - k:n]) / d3
    units = (doc.get("meta") or {}).get("units")
    ctrl, ctrl_month, ctrl_why = controllable_per_unit("the-landing", units)
    bv = budget_variance_ytd("the-landing")

    # Month to month, as a share of occupied units -- the KPI is published as a
    # ratio despite being named "#". Both sides come from the same unit list, and
    # the occupied count is checked against the delinquency block's own figure so
    # a status the workbook renames cannot quietly shrink the denominator.
    rows = doc.get("units") or []
    mtm = sum(1 for u in rows if u.get("status") == MTM_STATUS)
    occupied = sum(1 for u in rows if u.get("status") in OCCUPIED_STATUSES)
    stated = (doc.get("delinquency") or {}).get("occupied_units")
    mtm_why = None
    if not rows:
        mtm_why = "this source carries no per-unit list"
    elif stated is not None and occupied != stated:
        mtm_why = (f"occupied units disagree: {occupied} by status against the "
                   f"delinquency block's {stated}")
        occupied = None
    return {
        # The AR cells are the Drive pipeline's, always (owner, 2026-09-21,
        # closing G3): "there shouldn't be anything pulling from a 6 week old
        # workbook". So this path publishes NEITHER of them -- no
        # total_delinq_pct and no split -- and `measurements` therefore leaves
        # both cells exactly as --from-pipeline last wrote them.
        #
        # Not filled-then-skipped but never read: a value this path must not
        # publish should not be in the facts at all, or the next person to add
        # a caller has to know not to trust it. The workbook's own figures stay
        # available in landing.json for anyone who wants to compare.
        #
        # This is also why as_of is the workbook's own extract date now rather
        # than the delinquency tab's: nothing this path publishes comes from
        # that tab any more, so dating the family by it would name a source
        # that no longer feeds a single cell here.
        "as_of": (doc.get("meta") or {}).get("as_of")
                 or (doc.get("meta") or {}).get("generated_at", "")[:10] or None,
        "gross_owed": d.get("gross_owed"),
        # The rent roll owns this cell (A8, owner 2026-09-15). The workbook's
        # own figure is kept beside it, never published, so the two readings of
        # a similarly named thing are on the record rather than confused.
        "rr_ltl": rr_ltl, "rr_ltl_why": rr_ltl_why,
        "tradeout": to_win, "tradeout_why": to_why,
        "ltl_workbook_pct": ltl_series[-1] if ltl_series else None,
        "ltl_workbook_month": months[-1] if months else None,
        "noi_margin": noi_series[-1] if noi_series else None,
        "noi_margin_month": noi_months[-1] if noi_months else None,
        "noi_margin_ttm": (en.get("ttm") or {}).get("noi_margin"),
        "concession_load": conc_load,
        "concession_load_month": months[-1] if months else None,
        "concession_load_t3": conc_load_t3,
        "concession_parts": conc_parts,
        "ctrl_per_unit_yr": ctrl,
        "ctrl_month": ctrl_month,
        "ctrl_units": units,
        "ctrl_why": ctrl_why,
        "bv": bv,
        "mtm_share": (mtm / occupied) if (occupied and not mtm_why) else None,
        "mtm_units": mtm,
        "mtm_occupied": occupied,
        "mtm_why": mtm_why,
        # "split" and "total_delinq_pct" are deliberately absent -- see the
        # note at the top of this return. The workbook's readings are recorded
        # below as a note, never as the cell.
        "delq_why": ("the Drive AR report owns this cell; the workbook no "
                     "longer fills it (G3, owner 2026-09-21)"),
        "delq_workbook": (
            None if d.get("pct_month_rent") is None else
            f"the workbook's Source Delinquency tab read "
            f"{d['pct_month_rent'] * 100:.1f}% as of {d.get('as_of')} "
            f"— not published; the Drive AR report owns this cell"),
        "source": "analyst workbook extract, via docs/landing.json",
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
    # The rent roll fills Loss to Lease % on both paths, from the same
    # published aggregate, so whichever run goes last writes the same number --
    # the mistake G3 records, designed out rather than sequenced around.
    rr_ltl, rr_ltl_why = rent_roll_ltl(slug)
    to_win, to_why = lease_tradeout(slug)

    path = os.path.join("data", slug, "delinquency.json")
    if not os.path.exists(path):
        if rr_ltl is None:
            return None
        # A property with a rent roll and no AR report still has a cell to
        # fill. "no_report" says the unprefixed family has nothing behind it
        # this run, so main() leaves whatever feed owns it alone: writing a
        # placeholder source here took a real AR report's arrival time off the
        # page while leaving its figure in place, which is precisely the
        # provenance damage G1 and G3 are about.
        return {"no_report": True, "source": None, "as_of": None,
                "received_at": None, "received_what": None,
                "rr_ltl": rr_ltl, "rr_ltl_why": rr_ltl_why,
                "tradeout": to_win, "tradeout_why": to_why}
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
        # This feed owns the two AR cells outright (owner, 2026-09-21, G3), so
        # it records them under its own "delq_" family rather than the
        # unprefixed one. Without that the two cells' provenance is whatever
        # ran LAST -- and since --from-landing still writes four workbook cells
        # into the unprefixed family, the page would hover the workbook's date
        # over this report's figures. Same over-report the tradeout cell hit.
        "delq_family": True,
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
        "rr_ltl": rr_ltl, "rr_ltl_why": rr_ltl_why,
        "tradeout": to_win, "tradeout_why": to_why,
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
        "delq_family": True,
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
                          f.get("delq_why")
                          or "needs one month's billed rent — pass --monthly-rent")

    rr = f.get("rr_ltl")
    if rr:
        out[KPI_LTL] = (rr["pct"], pct0(rr["pct"]), None)
    else:
        out[KPI_LTL] = (None, None,
                        f.get("rr_ltl_why") or "no rent roll published for this property")

    to = f.get("tradeout")
    if to:
        out[KPI_TO] = (to["pct"], pct1(to["pct"]), None)
    else:
        out[KPI_TO] = (None, None,
                       f.get("tradeout_why") or "no trade-out report for this property")

    if f.get("noi_margin") is not None:
        out[KPI_NOI] = (f["noi_margin"], pct1(f["noi_margin"]), None)
    else:
        out[KPI_NOI] = (None, None,
                        "this source carries no monthly revenue-and-NOI series")

    if f.get("concession_load") is not None:
        v = f["concession_load"]
        # two decimals: the whole band lives under 2%, and the property sits
        # near zero -- one decimal would print the difference between "none"
        # and "some" as the same figure
        out[KPI_CONC] = (v, f"{v * 100:.2f}%", None)
    else:
        out[KPI_CONC] = (None, None,
                         "this source carries no concessions series")

    if f.get("ctrl_per_unit_yr") is not None:
        v = f["ctrl_per_unit_yr"]
        out[KPI_CTRL] = (v, f"${v:,.0f}", None)
    else:
        out[KPI_CTRL] = (None, None,
                         f.get("ctrl_why")
                         or "no T12 statement grouped by account for this property")

    bv = f.get("bv") or {}
    if bv.get("pct") is not None:
        d, p = bv["dollars"], bv["pct"]
        # "$ nominal / % variance", signed -- positive is an overspend. The
        # band grades the ABSOLUTE magnitude (its own "how" says so: a 12%
        # underspend flags exactly like a 12% overrun), so the classified raw
        # is abs(pct); the signed figures are kept in measured[slug].
        sign = "+" if d >= 0 else "-"
        out[KPI_BV] = (abs(p), f"{sign}${abs(d):,.0f}/{sign}{abs(p) * 100:.1f}%",
                       None)
    else:
        out[KPI_BV] = (None, None,
                       bv.get("why") or "no budget for this property")

    if f.get("mtm_share") is not None:
        # count and share together: the KPI is named for a count and banded on a
        # ratio, and neither on its own says what the other does
        out[KPI_MTM] = (f["mtm_share"],
                        f"{f['mtm_units']}/{pct1(f['mtm_share'])}", None)
    else:
        out[KPI_MTM] = (None, None, f.get("mtm_why") or "no per-unit lease status")

    parts = f.get("split") or []
    if len(parts) == 3 and all(p is not None for p in parts):
        # xx/yy/zz in whole dollars, the report's own figures
        out[KPI_SPLIT] = (None, "/".join(f"{p:,.0f}" for p in parts), None)
    else:
        out[KPI_SPLIT] = (None, None,
                          f.get("delq_why")
                          or "report has no 30/60/90 aging buckets")
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


OMITTED_RE = re.compile(r"^OMITTED_METRICS\s*=\s*\{(.*?)\}", re.S | re.M)


def omitted_metrics():
    """OMITTED_METRICS, read out of extract_scorecard.py's source.

    Read rather than imported because that file has no __main__ guard: it opens
    the workbook at module level, so importing it here would demand the .xlsx
    the daily cron does not have. Reading the one list out of the one place it
    is defined still beats a second copy that can disagree with it -- the same
    reason test_routing.load_rules() parses ROUTING_RULES out of the .js.

    Returns None, not an empty set, when the block cannot be parsed: the caller
    must be able to tell "nothing is omitted" from "the list could not be read",
    since the second silently puts a dropped KPI back on the page.
    """
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "extract_scorecard.py")
    try:
        m = OMITTED_RE.search(open(src).read())
    except OSError:
        return None
    if not m:
        return None
    return set(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1)))


def prune_omitted(sc):
    """Drop OMITTED_METRICS from an already-published scorecard.

    extract_scorecard drops them at extraction, which is the real fix -- but
    that step needs the workbook and is run by hand, so a KPI removed today
    would otherwise sit on the live page until someone next re-extracts. This
    runs on every fill, including the daily cron, so the page catches up on its
    own. Re-extracting later is then a no-op rather than a correction.

    Everything derived is left to recompute(): this only removes the metric
    itself, so the coverage counts and by_metric cannot disagree with the grid.
    """
    omit = omitted_metrics()
    if omit is None:
        print("[warn] could not read OMITTED_METRICS out of extract_scorecard.py "
              "-- nothing pruned; a metric meant to be dropped may be published")
        return []
    present = [m["name"] for m in sc.get("metrics", []) if m["name"] in omit]
    if not present:
        return []
    sc["metrics"] = [m for m in sc["metrics"] if m["name"] not in omit]
    for g in sc.get("groups", []):
        g["metrics"] = [n for n in g["metrics"] if n not in omit]
    sc["groups"] = [g for g in sc.get("groups", []) if g["metrics"]]
    for key in ("thresholds",):
        block = sc.get(key) or {}
        for n in present:
            block.pop(n, None)
    sc["unscored"] = [n for n in (sc.get("unscored") or []) if n not in omit]
    for p in sc["properties"]:
        for key in ("statuses", "values", "status_source", "status_workbook"):
            block = p.get(key) or {}
            for n in present:
                block.pop(n, None)
    for slug, m in (sc.get("measured") or {}).items():
        for key in [k for k in m if k.endswith("kpis")]:
            m[key] = [n for n in m[key] if n not in omit]
    return present


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

    if facts.get("no_report"):
        print(f"source: the rent roll alone — no delinquency report for "
              f"{prop['label']}; the cells another feed owns are left as they are")
    else:
        print(f"source: {facts['source']}  ·  as of {facts['as_of']}  ·  "
              f"property: {prop['label']}")
    if facts.get("no_report"):
        pass
    elif facts.get("received_at"):
        print(f"arrived: {facts['received_at']}"
              + (f" ({facts['received_what']})" if facts.get("received_what") else ""))
    else:
        print("arrived: unknown — no arrival time on this source; the scorecard "
              "will fall back to the as-of date. Pass --received-at to record one.")
    print(f"{'KPI':26} {'measured':>18}  {'band says':<11} {'workbook had':<11} action")
    print("-" * 86)

    rebracket = restate_controllable_band(thresholds)
    if rebracket:
        og, orr, g, r = rebracket
        print(f"rebracketed {KPI_CTRL}: ${og:,}/${orr:,} -> ${g:,}/${r:,} "
              f"(A9; the sheet's own cutoffs are kept in *_workbook)")

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

    dropped = prune_omitted(sc)
    if dropped:
        print("omitted from the scorecard (OMITTED_METRICS): " + ", ".join(dropped))

    recompute(sc)

    meas = sc.setdefault("measured", {})
    # update, not replace: another feed's keys for this property live in the
    # same dict under their own prefix (bldg_*, eliseai_*), and replacing it
    # wholesale dropped them whenever this script ran out of the documented
    # order -- taking their arrival times off the page with them.
    meas.setdefault(slug, {})
    if not facts.get("no_report"):
        meas[slug].update({
                 "source": facts["source"], "as_of": facts["as_of"],
                 # arrival time, not coverage date: what the page reports as
                 # "data last updated". None when the source carries none.
                 "received_at": facts.get("received_at"),
                 "received_what": facts.get("received_what"),
                 # The cells THIS run filled, keyed on display (an unscored
                 # KPI has figures to show but no single number to classify).
                 #
                 # It used to test prop["values"], which earlier runs also
                 # wrote, so the list named every cell any run had ever filled
                 # and the page dated a cell by whichever feed ran last. That
                 # is open item G1, and with the AR cells moving to their own
                 # family (G3) it stopped being cosmetic: a --from-landing run
                 # would re-claim two Drive cells by naming them here.
                 "kpis": sorted(k for k, (_v, disp, _w) in measurements(facts).items()
                                if disp is not None)})
    if facts.get("delq_family") and not facts.get("no_report"):
        # The AR report's own family. Registered in SC_FEED_PREFIXES in
        # index.html and the matching list in data.html, and in
        # SCD_DRIVE_FEEDS so the Landing tab's Delinquency tile carries it.
        filled_here = sorted(k for k in (KPI_TOTAL, KPI_SPLIT)
                             if prop["values"].get(k, {}).get("display") is not None)
        meas[slug].update({
            "delq_source": facts["source"],
            "delq_as_of": facts["as_of"],
            "delq_received_at": facts.get("received_at"),
            "delq_received_what": facts.get("received_what"),
            "delq_kpis": filled_here,
        })
        # Take both cells off every other family's list, exactly as the
        # tradeout cell is taken off bldg_kpis: the page picks a cell's feed by
        # whichever family names it, so a stale mention is a wrong date on a
        # right number rather than a missing one.
        for key, names in list(meas[slug].items()):
            if (key.endswith("kpis") and key != "delq_kpis"
                    and isinstance(names, list)):
                meas[slug][key] = [n for n in names
                                   if n not in (KPI_TOTAL, KPI_SPLIT)]
    if facts.get("denominator_note"):
        meas[slug]["denominator"] = facts["denominator_note"]
    if facts.get("ltl_month"):
        meas[slug]["ltl_month"] = facts["ltl_month"]
    if facts.get("mtm_share") is not None:
        meas[slug]["mtm_basis"] = (
            f"{facts['mtm_units']} units past lease expiry and still occupied over "
            f"{facts['mtm_occupied']} occupied, at {facts['as_of']}")
    if facts.get("ctrl_month"):
        meas[slug]["controllable_basis"] = (
            f"{facts['ctrl_month']} operating expense less taxes, insurance, "
            f"utilities and the management fee, over {facts['ctrl_units']} units, x12")
        t = (sc.get("thresholds") or {}).get(KPI_CTRL)
        if t and t.get("how") != CONTROLLABLE_HOW:
            t.setdefault("how_workbook", t.get("how"))
            t["how"] = CONTROLLABLE_HOW

    rr = facts.get("rr_ltl")
    if rr:
        # Its own feed family: this cell is the rent roll's, not the workbook's
        # and not the AR report's, so its arrival and provenance are recorded
        # apart from the unprefixed family. "rentroll_" is in SC_FEED_PREFIXES
        # in index.html and the matching list in data.html.
        meas[slug].update({
            "rentroll_source": rr.get("source"),
            "rentroll_as_of": rr.get("as_of"),
            "rentroll_received_at": rr.get("received_at"),
            "rentroll_received_what": "rent roll in the Drive Rent Roll folder",
            "rentroll_kpis": [KPI_LTL],
            "ltl_basis": (
                f"${rr['dollars']:,.0f} market rent less in-place rent across "
                f"{rr['occupied']} occupied units (${rr['market']:,.0f} market, "
                f"${rr['actual']:,.0f} in place) on the rent roll of "
                f"{rr['as_of']}. Occupied units only: a vacant unit has an "
                f"asking rent and no in-place rent, so counting it would book "
                f"the whole asking rent as loss"),
        })
        # what the workbook's own series said for the same concept, kept so the
        # two readings are never mistaken for one another
        if facts.get("ltl_workbook_pct") is not None:
            meas[slug]["ltl_workbook"] = (
                f"{facts['ltl_workbook_pct'] * 100:.0f}% for "
                f"{facts['ltl_workbook_month']} on the T12 statement's monthly "
                f"revenue lines — a different measurement, not published")

    to = facts.get("tradeout")
    if to:
        # Its own feed family, for the same reason the rent roll has one: this
        # cell is the tradeout report's, not the EliseAI export's, so its
        # arrival and provenance are recorded apart. "tradeout_" is in
        # SC_FEED_PREFIXES in index.html and the matching list in data.html,
        # and in SCD_DRIVE_FEEDS so the Drive tab's tile carries it.
        meas[slug].update({
            "tradeout_source": to.get("source"),
            "tradeout_as_of": to.get("as_of"),
            "tradeout_received_at": to.get("received_at"),
            "tradeout_received_what":
                "lease tradeout report in the Drive Historical Tradeout Reports folder",
            "tradeout_kpis": [KPI_TO],
            # The window as a number as well as prose: the tile prints
            # "trailing 3 mo" from it rather than parsing the sentence, and
            # rather than repeating the constant in index.html where the two
            # could drift.
            "tradeout_months": to["months"],
            "tradeout_window": (
                f"{to['window_start']} to {to['window_end']} "
                f"(trailing {to['months']} months)"),
            "tradeout_basis": (
                f"{to['leases']} new lease(s) signed {to['window_start']}.."
                f"{to['window_end']}, trade-out weighted by rent: total current "
                f"effective rent over total previous effective rent, on the "
                f"report's own basis ({to.get('rate_type')} leases, trade-out on "
                f"{to.get('tradeout_basis')}, dated by "
                f"{to.get('lease_date_basis')}). Trailing "
                f"{to['months']} months because that is the window the published "
                f"band was written for"
                + ("" if to.get("complete") else
                   "; the window starts before the report does, so it covers "
                   "fewer months than it names")),
            # The whole file and the mean, recorded so neither is mistaken for
            # the graded figure. The mean is not a rate -- see lease_tradeout().
            "tradeout_all": (
                None if to.get("all_pct") is None else
                f"{to['all_pct'] * 100:.1f}% weighted across all "
                f"{to['all_leases']} leases in the report "
                f"({to.get('period_start')}..{to.get('period_end')})"),
            "tradeout_mean": (
                None if to.get("mean_pct") is None else
                f"{to['mean_pct'] * 100:.1f}% as the mean of the per-lease rates "
                f"over the same window — not published as the figure: a "
                f"concession drives a previous effective rent toward zero and "
                f"the ratio explodes"),
        })
        # Take the cell off every other family's list. populate_building_metrics
        # already refuses to WRITE a cell another feed owns, but its bldg_kpis
        # still NAMED this one from before this feed existed -- and the page
        # picks a cell's feed by whichever family lists it, so the tile went on
        # reading "EliseAI building-metrics export · as of 2026-08-31" over a
        # figure from the tradeout report of 2026-09-16. A list that names a
        # cell the feed no longer fills is the over-report CLAUDE.md warns
        # about; this is that list being kept true rather than worked around on
        # the page.
        for key, names in list(meas[slug].items()):
            if (key.endswith("kpis") and key != "tradeout_kpis"
                    and isinstance(names, list) and KPI_TO in names):
                meas[slug][key] = [n for n in names if n != KPI_TO]

    bv = facts.get("bv") or {}
    if bv.get("pct") is not None:
        # Its own feed family, because this cell is not the workbook's: both
        # sides come from Drive (the budget export and the T12 statement), so
        # its provenance and arrival are recorded apart from the unprefixed
        # family that --from-landing otherwise owns. "budget_" is in
        # SC_FEED_PREFIXES in index.html and the matching list in data.html.
        meas[slug].update({
            "budget_source": bv.get("source"),
            "budget_as_of": bv["window"],
            "budget_received_at": bv.get("received_at"),
            "budget_received_what": ("budget in the Drive Budgets folder, "
                                     "against the T12 statement"),
            "budget_kpis": [KPI_BV],
            "budget_variance_basis": (
                f"{bv['window']} actual controllable opex less the same "
                f"months' budget (Drive Budgets folder), on the controllable "
                f"basket; graded on absolute magnitude"),
            # the signed figures behind the graded abs value
            "budget_variance_dollars": round(bv["dollars"], 2),
            "budget_variance_pct": round(bv["pct"], 6),
        })
    if facts.get("concession_load") is not None:
        c, g, l, v = facts["concession_parts"]
        meas[slug]["concession_basis"] = (
            f"{facts['concession_load_month']}: ${c:,.0f} concessions over "
            f"${g:,.0f} market rent potential less ${l:,.0f} loss to lease "
            f"less ${v:,.0f} vacancy loss")
        # the window the ranges sheet itself names, kept beside the graded month
        if facts.get("concession_load_t3") is not None:
            meas[slug]["concession_load_t3"] = round(facts["concession_load_t3"], 6)
        t = thresholds.get(KPI_CONC)
        if t and t.get("how") != CONCESSION_HOW:
            t.setdefault("how_workbook", t.get("how"))
            t["how"] = CONCESSION_HOW
    if facts.get("delq_workbook"):
        meas[slug]["delq_workbook"] = facts["delq_workbook"]
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
    # Sealed data must be open before anything reads last run's output -- see
    # crypto_data.require_opened. Here, not in main(), which tests drive directly.
    import crypto_data
    crypto_data.require_opened("populate_scorecard")
    main()

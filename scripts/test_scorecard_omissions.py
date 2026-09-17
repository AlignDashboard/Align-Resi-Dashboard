#!/usr/bin/env python3
"""Guard tests for OMITTED_METRICS -- the KPIs the dashboard does not publish.

The list lives in extract_scorecard.py, which drops them when it rebuilds
docs/scorecard.json from the workbook. That step needs the .xlsx and is run by
hand, so populate_scorecard.prune_omitted applies the same list on every fill --
including the daily cron -- and the live page catches up without waiting for a
workbook refresh.

Two halves, two ways to fail quietly:

  - populate_scorecard cannot IMPORT the list (extract_scorecard has no
    __main__ guard and opens the workbook at module level), so it reads it out
    of the source. If that read ever stops matching, an empty set would prune
    nothing and put a removed KPI back on the page with every count still
    looking healthy. omitted_metrics() returns None on a failed read for
    exactly this reason, and prune_omitted says so rather than pruning nothing
    silently.
  - a partial prune -- the metric out of the grid but left in thresholds, or
    out of the cells but still counted in coverage -- reads as a working page
    with a KPI that has no home, which is what dropping it at extraction was
    meant to avoid in the first place.

Fixture-free: the scorecard is built in memory, and the only file read is the
repo's own extract_scorecard.py.

Run: python scripts/test_scorecard_omissions.py
"""

import copy
import io
import os
import sys
import contextlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import populate_scorecard as ps

PASS = FAIL = 0


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"   PASS {name}")
    else:
        FAIL += 1
        print(f"   FAIL {name}\n        got  {got!r}\n        want {want!r}")


OMIT = "# of dropped kpi"
KEEP = "Total Deliquency"


def scorecard():
    """A scorecard with one omitted metric and one kept, over two properties."""
    return {
        "unscored": [OMIT, KEEP],
        "groups": [
            {"name": "Group A", "metrics": [KEEP, OMIT]},
            {"name": "Group B", "metrics": [OMIT]},          # empties out
        ],
        "metrics": [{"name": KEEP, "group": "Group A"},
                    {"name": OMIT, "group": "Group A"}],
        "properties": [
            {"label": "One", "slug": "one",
             "statuses": {KEEP: "below", OMIT: "below"},
             "values": {KEEP: {"raw": 1, "display": "1"},
                        OMIT: {"raw": None, "display": None}},
             "status_source": {KEEP: "measured"},
             "status_workbook": {KEEP: "in_range", OMIT: "below"}},
            {"label": "Two", "slug": "two",
             "statuses": {KEEP: "exceeding", OMIT: "in_range"},
             "values": {KEEP: {"raw": 2, "display": "2"},
                        OMIT: {"raw": None, "display": None}},
             "status_source": {KEEP: "measured"},
             "status_workbook": {}},
        ],
        "portfolio": {},
        "thresholds": {KEEP: {"how": "kept"}, OMIT: {"how": "dropped"}},
        "measured": {"one": {"kpis": [KEEP, OMIT], "bldg_kpis": [OMIT]}},
    }


def run(sc, omit=(OMIT,)):
    """prune_omitted with omitted_metrics() stubbed, then recompute."""
    real = ps.omitted_metrics
    ps.omitted_metrics = lambda: (None if omit is None else set(omit))
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            dropped = ps.prune_omitted(sc)
        ps.recompute(sc)
        return dropped, buf.getvalue()
    finally:
        ps.omitted_metrics = real


print("1. the list is read out of extract_scorecard.py, not copied")
got = ps.omitted_metrics()
check("omitted_metrics() returns a set", isinstance(got, set), True)
check("it carries the real names",
      {"# of offers that are 30 days", "# of accepted/pending offers"} <= (got or set()),
      True)

print("\n2. an omitted metric leaves every block it was in")
sc = scorecard()
dropped, _ = run(sc)
check("reported as dropped", dropped, [OMIT])
check("out of metrics", [m["name"] for m in sc["metrics"]], [KEEP])
check("out of the group", sc["groups"][0]["metrics"], [KEEP])
check("a group left empty is removed", [g["name"] for g in sc["groups"]], ["Group A"])
check("out of thresholds", sorted(sc["thresholds"]), [KEEP])
check("out of unscored", sc["unscored"], [KEEP])
check("out of statuses", sorted(sc["properties"][0]["statuses"]), [KEEP])
check("out of values", sorted(sc["properties"][0]["values"]), [KEEP])
check("out of status_workbook", sorted(sc["properties"][0]["status_workbook"]), [KEEP])
check("out of every measured *kpis list",
      [sc["measured"]["one"]["kpis"], sc["measured"]["one"]["bldg_kpis"]],
      [[KEEP], []])
check("gone from the document entirely", OMIT in repr(sc), False)

print("\n3. the counts follow, and only where they should")
# The omitted cell was never measured, so no percentage may move -- that is what
# makes removing it a display change rather than a restatement.
before = scorecard()
ps.recompute(before)
after = scorecard()
run(after)
check("graded count unchanged", after["portfolio"]["scored"], before["portfolio"]["scored"])
check("at_or_above unchanged",
      after["portfolio"]["at_or_above"], before["portfolio"]["at_or_above"])
check("metric_count drops by one",
      after["portfolio"]["metric_count"], before["portfolio"]["metric_count"] - 1)
check("coverage total drops one cell per property",
      after["portfolio"]["coverage"]["total"],
      before["portfolio"]["coverage"]["total"] - len(before["properties"]))
check("the lost cells were awaiting ones",
      after["portfolio"]["coverage"]["awaiting"],
      before["portfolio"]["coverage"]["awaiting"] - len(before["properties"]))

print("\n4. a failed read prunes NOTHING, and says so")
# The warning is the load-bearing half, and mutation says so: returning an
# empty set instead of None prunes nothing either way, so the behaviour is
# identical and only the log differs. That is the whole failure -- the removal
# quietly stops working and the KPI stays published with every count adding up.
sc = scorecard()
dropped, out = run(sc, omit=None)
check("nothing dropped", dropped, [])
check("the metric is still there", any(m["name"] == OMIT for m in sc["metrics"]), True)
check("it warns", "could not read OMITTED_METRICS" in out, True)

print("\n5. running twice is a no-op")
sc = scorecard()
run(sc)
once = copy.deepcopy(sc)
dropped, _ = run(sc)
check("second run drops nothing", dropped, [])
check("and changes nothing", sc, once)

print()
if FAIL:
    print(f"FAIL: {FAIL} of {PASS + FAIL} checks")
    sys.exit(1)
print(f"PASS: {PASS} checks — an omitted KPI leaves every block, no graded "
      f"figure moves, and a list that cannot be read prunes nothing loudly.")

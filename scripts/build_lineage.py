#!/usr/bin/env python3
"""Write docs/lineage.json -- the chain from a report in Google Drive to a card
on the dashboard.

The dashboard's data tables page answers "what is the number"; this answers
"where did it come from". One row per source, each carrying the same six stages:

    source -> report -> pipeline step -> stored -> published -> dashboard card

Two halves, deliberately:

  * The **Drive side is derived**, not declared. Every entry in
    config/report_map.json produces a row whether or not anyone remembered to
    describe it, so a folder registered tomorrow shows up on the page by itself
    -- flagged as undocumented rather than silently missing.
  * The **downstream side is declared** here, in FLOWS. No file records that
    metrics.json's expense_buckets block is what the Expense Deep Dive card
    draws; that edge exists only in index.html's fetch calls, so it is written
    down once, here, and checked against the two pages on every run.

What is *evidence* rather than declaration is read from the repo as it stands:
which per-property files the pipeline actually wrote, what the newest source
file was called, when it landed in Drive, which scorecard cells a feed filled.
A declared flow with no evidence is reported as waiting, not as working.

The checks refuse to write a lineage that points at nothing -- a card anchor
index.html does not define, a table id data.html does not build, a parser
module that is not in scripts/. A lineage page that has quietly gone stale is
worse than none, because it is read as a map.

Usage:
  python scripts/build_lineage.py             # write docs/lineage.json
  python scripts/build_lineage.py --check     # verify only, write nothing
"""

import argparse
import fnmatch
import glob
import json
import os
import pathlib
import re
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
DATA = ROOT / "data"
DOCS = ROOT / "docs"
SCRIPTS = ROOT / "scripts"
OUT = DOCS / "lineage.json"

# The six stages every row is laid out on. The page renders them as columns in
# this order, so the labels live here rather than in the HTML.
STAGES = [
    {"key": "source", "label": "Source",
     "hint": "Where the file comes from — a Google Drive folder, the dashboard "
             "mailbox, or a workbook someone refreshes by hand."},
    {"key": "report", "label": "The report",
     "hint": "The export itself, and what it carries."},
    {"key": "step", "label": "Pipeline step",
     "hint": "The script that reads it, and what it checks before believing it."},
    {"key": "stored", "label": "Stored",
     "hint": "Scrubbed output kept in data/. Tenant names never get this far."},
    {"key": "published", "label": "Published",
     "hint": "The JSON the site fetches: metrics.json, landing.json, "
             "scorecard.json."},
    {"key": "dashboard", "label": "On the dashboard",
     "hint": "The card, chart or KPI cell the number ends up in."},
]

# Status vocabulary. The page colours by these, so they are fixed here.
#   live      — a file has arrived and something on the dashboard shows it
#   partial   — it parses and is stored, but nothing publishes it yet
#   waiting   — parser is written and registered; no file has ever arrived
#   no-parser — the folder is registered, the parser is not written
#   manual    — no feed at all; the numbers are hand-authored
LIVE, PARTIAL, WAITING, NO_PARSER, MANUAL = (
    "live", "partial", "waiting", "no-parser", "manual")


def _rel(p):
    return str(pathlib.Path(p).as_posix())


# ---------------------------------------------------------------------------
# The declared downstream, keyed by (drive_folder, report_type) for the Drive
# entries and by id for everything else. Keep the prose short: the page shows
# it verbatim.
# ---------------------------------------------------------------------------

DRIVE_FLOWS = {
    ("T12 Expenses", "t12_statement"): {
        "id": "t12",
        "example": '12_Month_Statement_Accrual.xlsx',
        "title": "12-month accrual statement",
        "carries": "Twelve months of GL revenue and expense for every building "
                   "code in one file, on the JPM account tree.",
        "steps": [
            {"script": "scripts/parse_t12_statement.py",
             "does": "Reads each building-code block, translates JPM leaves to "
                     "Align accounts through config/coa_map.json and groups "
                     "them by the Align tree's own families.",
             "checks": "Ties out against the statement's own TOTAL EXPENSES to "
                       "the cent, per month. Unmapped JPM accounts are grouped "
                       "by label and listed in the log (10 today, ~$115k)."},
            {"script": "scripts/build_metrics.py",
             "does": "Routes each code to its property, appends to that "
                     "property's history keyed by period, and stitches "
                     "successive statements into one continuous month series.",
             "checks": "A property whose source is known to be wrong is "
                       "quarantined in config/properties.json and dropped "
                       "rather than published (335 Third's dummy statement)."},
        ],
        "stores": ["data/<slug>/expense_ratio.json",
                   "data/<slug>/monthly_pl.json",
                   "data/<slug>/expense_buckets.json",
                   "data/<slug>/monthly_revenue.json"],
        "publishes": [
            {"file": "metrics.json", "key": "expense_ratio"},
            {"file": "metrics.json", "key": "monthly_pl"},
            {"file": "metrics.json", "key": "expense_buckets"},
            {"file": "scorecard.json", "key": "Controllable OpEx/Unit"},
        ],
        "dashboard": [
            {"card": "Expense Ratio", "tab": "Portfolio", "anchor": "cExpRatio",
             "tables": ["t-expratio-*"]},
            {"card": "Operating Summary", "tab": "The Landing", "anchor": "cOpSummary",
             "tables": ["t-monthlypl-*"]},
            {"card": "Expense Deep Dive", "tab": "The Landing", "anchor": "cExpDeep",
             "primary": "t-l-buckets",
             "tables": ["t-buckets-*", "t-l-opps"]},
            {"card": "Expense Load & NOI — controllable/door", "tab": "The Landing",
             "anchor": "cNoi", "primary": "t-l-noi", "tables": ["t-buckets-*"]},
            # The Drive-only tab. Same statement, same three cards, none of the
            # workbook: the Landing tab overlays the analyst numbers on these,
            # this one shows the statement on its own.
            {"card": "Operating Summary", "tab": "Landing (Drive)",
             "anchor": "cdOpSummary", "primary": "t-monthlypl-*",
             "tables": ["t-monthlypl-*"]},
            {"card": "Expense Load & NOI", "tab": "Landing (Drive)",
             "anchor": "cdNoi", "primary": "t-monthlypl-*",
             "tables": ["t-monthlypl-*", "t-buckets-*", "t-unitdir-*"]},
            {"card": "Expense Deep Dive", "tab": "Landing (Drive)",
             "anchor": "cdExpDeep", "primary": "t-buckets-*",
             "tables": ["t-buckets-*", "t-monthlypl-*"]},
            {"card": "What Feeds This Tab", "tab": "Landing (Drive)",
             "anchor": "cdFeeds", "tables": []},
        ],
        "tables": ["t-expratio-*"],
        "note": "The one Drive report that reaches the dashboard as a chart in "
                "its own right. Its monthly revenue also becomes the "
                "denominator under the delinquency KPI.",
        "open_item": "A10",
    },
    ("Rent Roll", "rent_roll"): {
        "id": "rent_roll",
        "example": '<date> RentRoll<MM_DD_YYYY>.xlsx',
        "title": "Rent roll (SPV PM Deliverable Package)",
        "carries": "Every unit: status, resident code, in-place and market "
                   "rent, square footage, lease dates.",
        "steps": [
            {"script": "scripts/parse_rent_roll.py",
             "does": "Reads unit rows until the section marker; keeps the "
                     "resident code only to tell an occupied unit from a "
                     "vacant one.",
             "checks": "Every published total ties to the report's own Total "
                       "row; refuses the file if that row is missing."},
            {"script": "scripts/build_metrics.py",
             "does": "Scrubs the parse through PII_FIELDS and writes it.",
             "checks": "scripts/check_no_pii.py re-reads the output and fails "
                       "the build if a person-shaped field survived."},
        ],
        "stores": ["data/<slug>/rent_roll.json  (gitignored — unit level)"],
        "publishes": [],
        "dashboard": [],
        "tables": [],
        "note": "Written, registered and never run: the registered Drive "
                "folder is empty and the actual file sits in the parent "
                "folder, which the fetcher does not scan. Every per-unit "
                "figure on the page therefore arrives through the analyst "
                "workbook instead. Moving the file is the whole fix.",
        "open_item": "C4",
        "force_status": WAITING,
    },
    ("Residential AR Analytics", "ar_analytics"): {
        "id": "delinquency",
        "example": 'rs_rp_DelinquencySummaryReport.xlsx',
        "title": "Delinquency summary",
        "carries": "Resident AR by unit, aged 0–30 / 31–60 / 61–90 / 90+.",
        "steps": [
            {"script": "scripts/parse_delinquency.py",
             "does": "Reads each property section and its aging buckets.",
             "checks": "Buckets sum to gross owed; each section ties to its own "
                       "Total row and the report's Grand Total."},
            {"script": "scripts/build_metrics.py",
             "does": "Scrubs names out and stores the aggregate per property.",
             "checks": "Central scrub in store_report, so a new parser is "
                       "covered without remembering."},
            {"script": "scripts/populate_scorecard.py --from-pipeline",
             "does": "Grades gross AR over one month's billed rent, taking the "
                     "denominator from the same property's T12 revenue.",
             "checks": "Merges into measured[slug] rather than replacing it, so "
                       "the other feeds' cells and arrival times survive."},
        ],
        "stores": ["data/<slug>/delinquency.json  (gitignored — unit level)"],
        "publishes": [
            {"file": "scorecard.json", "key": "Total Deliquency"},
            {"file": "scorecard.json", "key": "Split Between 30/60/90"},
        ],
        "dashboard": [
            {"card": "KPI Scorecard — Total Deliquency", "tab": "Scorecard",
             "anchor": "cScorecard", "primary": "t-sc-matrix",
             "tables": ["t-sc-measured", "t-sc-arrivals", "t-sc-props"]},
            {"card": "KPI Scorecard — Palma", "tab": "Palma",
             "anchor": "psc-palma", "primary": "t-sc-measured",
             "tables": ["t-sc-overrides", "t-sc-arrivals", "t-sc-matrix"]},
            # The Drive-only tab shows the rate and the 30/60/90 split -- the
            # two cells this report fills. The per-unit aging behind them stops
            # in data/, so that tab has no aging chart of its own.
            {"card": "Delinquency", "tab": "Landing (Drive)",
             "anchor": "cdDelq", "primary": "t-sc-measured",
             "tables": ["t-sc-measured", "t-sc-arrivals"]},
            {"card": "KPI Scorecard — Drive feeds only", "tab": "Landing (Drive)",
             "anchor": "cdScorecard", "primary": "t-sc-measured",
             "tables": ["t-sc-measured", "t-sc-arrivals", "t-sc-thresholds"]},
            {"card": "What Feeds This Tab", "tab": "Landing (Drive)",
             "anchor": "cdFeeds", "tables": []},
        ],
        "tables": ["t-sc-measured", "t-sc-arrivals"],
        "note": "The 30/60/90 split is reported, never graded: a distribution "
                "has no single direction it can be good or bad in.",
    },
    ("Delinquency", "ar_analytics"): {
        "id": "delinquency_alt",
        "example": 'rs_rp_DelinquencySummaryReport.xlsx',
        "title": "Delinquency summary (second folder)",
        "carries": "The same report, filed in a second folder by the PM.",
        "steps": [
            {"script": "scripts/parse_delinquency.py",
             "does": "Same parser, same route.",
             "checks": "A file present in both folders parses twice and the "
                       "second store overwrites the first with identical "
                       "content, which is harmless."},
        ],
        "stores": ["data/<slug>/delinquency.json  (gitignored — unit level)"],
        "publishes": [
            {"file": "scorecard.json", "key": "Total Deliquency"},
            {"file": "scorecard.json", "key": "Split Between 30/60/90"},
        ],
        "dashboard": [
            {"card": "KPI Scorecard — Total Deliquency", "tab": "Scorecard",
             "anchor": "cScorecard"},
        ],
        "tables": ["t-sc-measured"],
        "note": "Registered so a report filed here is not invisible. Nothing "
                "downstream is different.",
        "same_as": "delinquency",
    },
    ("EliseAI Reports", "bldg_metrics_csv"): {
        "id": "bldg_metrics",
        "example": 'metricsbuilding<YYYYMMDD>.csv',
        "title": "EliseAI building-metrics export",
        "carries": "79 columns per property — exposure, trade-out, closing "
                   "ratio, renewal rate, containment, response time.",
        "steps": [
            {"script": "scripts/populate_building_metrics.py",
             "does": "Fills nine KPIs where the export's column means what the "
                     "KPI means, for every property in the file. No parse or "
                     "accumulate step — it writes the scorecard directly.",
             "checks": "Never takes a cell another feed owns; a property under "
                       "50% occupancy is filled but left ungraded rather than "
                       "scored red for not having opened; implausible cells "
                       "(Chorus's +119.78% executed increase) are skipped and "
                       "the skip recorded in the basis."},
        ],
        "stores": [],
        "publishes": [
            {"file": "scorecard.json", "key": "Leased %"},
            {"file": "scorecard.json", "key": "Trade-out %"},
            {"file": "scorecard.json", "key": "Closing Ratio"},
            {"file": "scorecard.json", "key": "# of Renewals"},
            {"file": "scorecard.json", "key": "% Increase"},
            {"file": "scorecard.json", "key": "Total Deliquency"},
            {"file": "scorecard.json", "key": "AI Containment Rate"},
            {"file": "scorecard.json", "key": "Avg First Response Time"},
            {"file": "scorecard.json", "key": "# of Tours/Leads/Applications"},
        ],
        "dashboard": [
            {"card": "KPI Scorecard (all properties)", "tab": "Scorecard",
             "anchor": "cScorecard", "primary": "t-sc-matrix",
             "tables": ["t-sc-measured", "t-sc-arrivals", "t-sc-props"]},
            {"card": "KPI Scorecard — The Landing", "tab": "The Landing",
             "anchor": "cLandingScorecard", "primary": "t-sc-measured",
             "tables": ["t-sc-arrivals", "t-sc-matrix", "t-sc-thresholds"]},
            # Eight of the ten cells on the Drive-only tab's scorecard are this
            # export's; # of Renewals shows there as the rate alone, since the
            # count half of the published cell comes from the analyst workbook.
            {"card": "KPI Scorecard — Drive feeds only", "tab": "Landing (Drive)",
             "anchor": "cdScorecard", "primary": "t-sc-measured",
             "tables": ["t-sc-arrivals", "t-sc-matrix", "t-sc-thresholds"]},
            {"card": "What Feeds This Tab", "tab": "Landing (Drive)",
             "anchor": "cdFeeds", "tables": []},
            {"card": "KPI Scorecard — Chorus", "tab": "Chorus",
             "anchor": "psc-chorus", "primary": "t-sc-measured",
             "tables": ["t-sc-arrivals", "t-sc-matrix", "t-sc-thresholds"]},
            {"card": "KPI Scorecard — Madelon", "tab": "Madelon",
             "anchor": "psc-madelon", "primary": "t-sc-measured",
             "tables": ["t-sc-arrivals", "t-sc-matrix", "t-sc-thresholds"]},
            {"card": "KPI Scorecard — 335 Third St", "tab": "335 Third St",
             "anchor": "psc-335-third-street", "primary": "t-sc-measured",
             "tables": ["t-sc-arrivals", "t-sc-matrix", "t-sc-thresholds"]},
            # A tile in a row, not a card: it has no corner to hang a link in,
            # so it belongs on the flow page and not in the card index.
            {"card": "Leased tile", "tab": "The Landing", "anchor": "lkpis",
             "tile": True},
        ],
        "tables": ["t-sc-measured", "t-sc-arrivals"],
        "note": "The widest feed on the page: it is the only one that says "
                "anything at all about Chorus and Madelon.",
        "open_item": "B6",
    },
    ("EliseAI Reports", "leasing_funnel"): {
        "id": "funnel",
        "example": 'leasing_funnel_report_<YYYY-MM-DD>.xlsx',
        "title": "EliseAI weekly leasing funnel",
        "carries": "Per-community funnel counts — prospects engaged, "
                   "responses, follow-ups, appointments — by month.",
        "steps": [
            {"script": "scripts/parse_leasing_funnel.py",
             "does": "Reads the portfolio sheet and each community's section.",
             "checks": "Every published field is tied out portfolio-vs-"
                       "communities before it is stored."},
            {"script": "scripts/build_metrics.py",
             "does": "Routes the community label through each property's "
                     "aliases and stores its aggregates.",
             "checks": "Aggregates only — the export carries no person-level "
                       "data, verified on two exports."},
        ],
        "stores": ["data/<slug>/leasing_funnel.json"],
        "publishes": [],
        "dashboard": [],
        "tables": [],
        "note": "Parses, ties out and stops in data/. Nothing on the dashboard "
                "reads it yet — the daily emails and the building-metrics "
                "export answer the leasing KPIs it would fill.",
    },
    ("Weekly Leasing Reports", "leasing_funnel"): {
        "id": "funnel_alt",
        "example": 'leasing_funnel_report_<YYYY-MM-DD>.xlsx',
        "title": "Weekly leasing funnel (second folder)",
        "carries": "The same weekly export, wherever the Gmail filing drops it.",
        "steps": [
            {"script": "scripts/parse_leasing_funnel.py",
             "does": "Same parser, same route.",
             "checks": "The glob is anchored with a leading * so the filing "
                       "step's date prefix does not hide the file."},
        ],
        "stores": ["data/<slug>/leasing_funnel.json"],
        "publishes": [],
        "dashboard": [],
        "tables": [],
        "note": "Registered against both folders so the weeklies parse "
                "wherever they land.",
        "same_as": "funnel",
        "open_item": "C3",
    },
    ("Building Info", "unit_directory"): {
        "id": "unit_directory",
        "example": 'UnitDirectory<MM_DD_YYYY>.xlsx',
        "title": "Yardi unit directory",
        "carries": "Every unit's floorplan code, square footage, bedrooms and "
                   "baths, for all properties in one export.",
        "steps": [
            {"script": "scripts/parse_unit_directory.py",
             "does": "Splits the file on its property-code rows and reads each "
                     "section's floorplan table.",
             "checks": "Each section ties out against its own Total row on unit "
                       "count, rent and square footage, plus the file's Grand "
                       "Total. A plan whose rows disagree on bedrooms is "
                       "flagged, never averaged."},
            {"script": "scripts/build_metrics.py",
             "does": "Merges the sections into one plan table per property.",
             "checks": "Collision check across building codes rather than "
                       "assuming plan codes are unique."},
        ],
        "stores": ["data/<slug>/unit_directory.json"],
        "publishes": [{"file": "metrics.json", "key": "unit_directory"}],
        "dashboard": [
            {"card": "Largest Unit Gaps — beds and plan sq ft",
             "tab": "The Landing", "anchor": "cGaps", "primary": "t-l-units",
             "tables": ["t-unitdir-*"]},
            # On the Drive-only tab the directory is the whole card rather than
            # one join onto the workbook's unit list: floorplans, bedrooms,
            # square footage and the door count under controllable/door.
            {"card": "Unit Inventory", "tab": "Landing (Drive)",
             "anchor": "cdInventory", "primary": "t-unitdir-*",
             "tables": ["t-unitdir-*"]},
            {"card": "What Feeds This Tab", "tab": "Landing (Drive)",
             "anchor": "cdFeeds", "tables": []},
        ],
        "tables": ["t-l-units"],
        "note": "It exists because nothing else says how many bedrooms a "
                "floorplan has: the rent roll and the workbook both name the "
                "plan and neither defines it.",
        "open_item": "F3",
    },
    ("Concession Burnoff", "concession_burnoff"): {
        "id": "concessions",
        "example": 'Projection by Unit (concession burn-off).xlsx',
        "title": "Concession burn-off projection",
        "carries": "Recurring and one-time concessions by unit, with an as-of "
                   "date and the report's own totals.",
        "steps": [
            {"script": "scripts/parse_concession_burnoff.py",
             "does": "Walks the report as sections and totals the money.",
             "checks": "Ties out against the report's own total row every run; "
                       "resident names are read only to tell a data row from a "
                       "total row and are never emitted."},
        ],
        "stores": [],
        "publishes": [],
        "dashboard": [],
        "tables": [],
        "note": "Parses clean and is stored nowhere. The export says only "
                "\"For Selected Properties\" and names no property, so "
                "attribution would be guesswork — one building's concessions "
                "filed under another.",
        "open_item": "A6",
        "force_status": PARTIAL,
    },
}

# Everything that does not arrive through the Drive fetcher.
OTHER_FLOWS = [
    {
        "id": "eliseai_daily",
        "example": '"Leasing AI Daily Report" email',
        "title": "Leasing AI Daily Report emails",
        "origin_kind": "email",
        "source_label": "dashboard@alignrealestate.com",
        "source_detail": "One email a day from EliseAI, per property.",
        "carries": "Tours, leads and applications for the day, plus the "
                   "pending-knowledge and escalation queues. The email lists "
                   "prospects by name with email and phone.",
        "steps": [
            {"script": "by hand, via the Gmail connector",
             "does": "Counts are read out of the email and appended to the "
                     "series. CI has no mailbox access, so this step is not "
                     "automated.",
             "checks": "Only counts leave the mailbox — the prospect roster is "
                       "never written down. A section absent from an email "
                       "means zero that day; EliseAI omits empty sections."},
            {"script": "scripts/populate_eliseai.py",
             "does": "Sums the trailing seven days and fills the scorecard.",
             "checks": "Refuses a malformed arrival time and warns when one is "
                       "missing, because the arrival is what the page reports "
                       "as \"data last updated\"."},
        ],
        "stores": ["data/<slug>/eliseai_daily.json"],
        "publishes": [
            {"file": "scorecard.json", "key": "# of Tours/Leads/Applications"},
            {"file": "scorecard.json", "key": "Open Elise Tasks"},
        ],
        "dashboard": [
            {"card": "KPI Scorecard — 335 Third St", "tab": "Scorecard",
             "anchor": "cScorecard", "primary": "t-sc-matrix",
             "tables": ["t-sc-measured", "t-sc-arrivals"]},
            {"card": "KPI Scorecard — 335 Third St", "tab": "335 Third St",
             "anchor": "psc-335-third-street", "primary": "t-sc-measured",
             "tables": ["t-sc-arrivals"]},
        ],
        "tables": ["t-sc-measured", "t-sc-arrivals"],
        "note": "The T/L/A triple is shown and never graded: the published band "
                "is tours per available unit per month, which cannot grade a "
                "week's counts.",
        "open_item": "B3",
        "evidence_kind": "eliseai_daily",
    },
    {
        "id": "analyst_workbook",
        "example": 'The_Landing_Dashboard_V37.xlsx',
        "title": "The Landing analyst workbook",
        "origin_kind": "workbook",
        "source_label": "The_Landing_Dashboard_V37.xlsx",
        "source_detail": "Refreshed by hand: reports are pasted into the grey "
                         "Source tabs and Excel recalculates.",
        "carries": "The whole Landing view — rent capture, expense and NOI, "
                   "renewals, holdovers, unit-level gaps, delinquency, "
                   "trade-outs, insights.",
        "steps": [
            {"script": "scripts/extract_landing.py",
             "does": "Reads the workbook's cached formula results off the "
                     "anchor labels and writes docs/landing.json.",
             "checks": "Prints a check table and refuses to write on a shifted "
                       "month axis, a unit count that disagrees with Inputs, a "
                       "broken statement tie-out or a renamed anchor. A "
                       "workbook saved without recalculating has no cached "
                       "results and is refused rather than published as nulls."},
            {"script": "scripts/populate_scorecard.py --from-landing",
             "does": "Fills the four KPIs a report cannot answer directly.",
             "checks": "Every controllable-expense exclusion is matched by name "
                       "against the statement's account groups and all of them "
                       "must be found, or the figure goes unpublished."},
        ],
        "stores": [],
        "publishes": [
            {"file": "landing.json", "key": "the whole Landing view"},
            {"file": "scorecard.json", "key": "Loss to Lease %"},
            {"file": "scorecard.json", "key": "NOI Margin %"},
            {"file": "scorecard.json", "key": "Controllable OpEx/Unit"},
            {"file": "scorecard.json", "key": "Month to Month Leases"},
            {"file": "scorecard.json", "key": "Total Deliquency (The Landing)"},
            {"file": "scorecard.json", "key": "Split Between 30/60/90 (The Landing)"},
        ],
        "dashboard": [
            {"card": "Loss to Lease", "tab": "The Landing", "anchor": "cRentCapture",
             "tables": ["t-l-capture", "t-l-capture-ttm", "t-l-revcompare"]},
            {"card": "Trade-outs", "tab": "The Landing", "anchor": "cTradeOuts",
             "tables": ["t-l-leases", "t-l-offers", "t-l-lease-summary",
                        "t-l-renewact", "t-l-bands"]},
            {"card": "Rollover Schedule", "tab": "The Landing", "anchor": "cRollover",
             "tables": ["t-l-rollover"]},
            {"card": "Expense Load & NOI", "tab": "The Landing", "anchor": "cNoi",
             "tables": ["t-l-noi", "t-l-noi-ttm", "t-l-tax"]},
            {"card": "Largest Unit Gaps", "tab": "The Landing", "anchor": "cGaps",
             "tables": ["t-l-units", "t-l-hold-units", "t-l-hold-summary",
                        "t-l-inputs", "t-l-meta"]},
            {"card": "Delinquency", "tab": "The Landing", "anchor": "cDelinquency",
             "tables": ["t-l-delq-aging", "t-l-delq-top", "t-l-delq-summary",
                        "t-l-delq-531"]},
            {"card": "Insights Scorecard", "tab": "The Landing", "anchor": "cInsights",
             "tables": ["t-l-insights", "t-l-flags"]},
            {"card": "KPI Scorecard — The Landing", "tab": "The Landing",
             "anchor": "cLandingScorecard", "primary": "t-sc-measured",
             "tables": ["t-sc-arrivals", "t-sc-matrix"]},
        ],
        "tables": ["t-l-capture", "t-l-noi", "t-l-renewal", "t-l-units",
                   "t-l-delq-aging", "t-l-rollover", "t-l-insights", "t-l-meta"],
        "note": "The workbook is fed by the same Yardi reports the Drive "
                "pipeline collects — pasted in rather than fetched. It is why "
                "The Landing has a full view while the rent roll has never "
                "reached the pipeline.",
        "evidence_kind": "landing",
        "sub_sources": [
            {"tab": "Source CY25 / Source Aug25-Jul26", "report": "12-month accrual statement",
             "drive_folder": "T12 Expenses"},
            {"tab": "Source Rent Roll Jul / Jun", "report": "SPV PM Deliverable Package, Rent Roll tab",
             "drive_folder": "Rent Roll"},
            {"tab": "Source Delinquency", "report": "rs_rp_DelinquencySummaryReport",
             "drive_folder": "Residential AR Analytics"},
            {"tab": "Source Renewal Tracker", "report": "Landing 2025 Renewal Tracker",
             "drive_folder": None},
            {"tab": "Lease Detail", "report": "RealPage rate tracker — typed in, not pasted",
             "drive_folder": None},
        ],
    },
    {
        "id": "kpi_workbook",
        "example": 'KPI_Scorecard_Formatted_v10.xlsx',
        "title": "KPI scorecard workbook",
        "origin_kind": "workbook",
        "source_label": "KPI_Scorecard_Formatted_v10.xlsx",
        "source_detail": "The analyst's own grid: metric groups, hand-set "
                         "symbols, published target ranges.",
        "carries": "27 published KPIs across five groups, their bands, the "
                   "legend, and the Palma lease-up overrides.",
        "steps": [
            {"script": "scripts/extract_scorecard.py",
             "does": "Builds the scorecard skeleton — groups, metrics, bands, "
                     "legend — and resets every measured value to null, which "
                     "is why it runs before the populate steps.",
             "checks": "Fails loudly if the legend fills change rather than "
                       "publishing stale semantics; warns when an omitted or "
                       "renamed column stops matching."},
        ],
        "stores": [],
        "publishes": [
            {"file": "scorecard.json", "key": "metrics, groups, thresholds, legend"},
        ],
        "dashboard": [
            {"card": "KPI Scorecard", "tab": "Scorecard", "anchor": "cScorecard",
             "primary": "t-sc-matrix",
             "tables": ["t-sc-thresholds", "t-sc-props", "t-sc-metrics",
                        "t-sc-workbook"]},
            {"card": "KPI Scorecard", "tab": "Portfolio", "anchor": "cPortfolioScorecard",
             "primary": "t-sc-matrix",
             "tables": ["t-sc-props", "t-sc-metrics", "t-sc-thresholds",
                        "t-sc-measured", "t-sc-arrivals", "t-sc-workbook"]},
        ],
        "tables": ["t-sc-matrix", "t-sc-thresholds", "t-sc-workbook",
                   "t-sc-overrides"],
        "note": "The grid itself is not evidence: a cell carries colour and "
                "counts toward the tally only where a report supplied the "
                "number and the band could place it.",
        "evidence_kind": "scorecard_meta",
    },
    {
        "id": "handset",
        "example": 'docs/metrics.json',
        "title": "Hand-authored blocks in metrics.json",
        "origin_kind": "manual",
        "source_label": "docs/metrics.json, edited directly",
        "source_detail": "Blocks the pipeline preserves rather than "
                         "regenerates.",
        "carries": "Expense Trend's three series, the PSF comp set, the trade-"
                   "out placeholder, and the eleven planned-metric cards.",
        "steps": [
            {"script": "scripts/build_metrics.py",
             "does": "Loads the existing metrics.json and writes only the "
                     "blocks it derives, so these survive every run.",
             "checks": "None — nothing ties these out, which is the point of "
                       "listing them here."},
        ],
        "stores": [],
        "publishes": [
            {"file": "metrics.json", "key": "expense_trend"},
            {"file": "metrics.json", "key": "psf_vs_peers"},
            {"file": "metrics.json", "key": "trade_outs"},
            {"file": "metrics.json", "key": "placeholders"},
        ],
        "dashboard": [
            {"card": "Expense Trend", "tab": "Portfolio", "anchor": "cExpTrend",
             "tables": ["t-exptrend"]},
            {"card": "PSF vs Other Properties", "tab": "Portfolio", "anchor": "cPsf",
             "tables": ["t-psf"]},
            {"card": "Trade Outs", "tab": "Portfolio", "anchor": "cTradeOutsPortfolio",
             "tables": ["t-tradeouts"]},
            {"card": "Planned Metrics", "tab": "Portfolio", "anchor": "placeholderGrid",
             "tables": ["t-placeholders"]},
        ],
        "tables": ["t-exptrend", "t-psf", "t-tradeouts", "t-placeholders"],
        "note": "No feed stands behind these. The PSF figures are hand-entered "
                "with no known date and say so on the card; Trade Outs is an "
                "empty state waiting on AIRM and the weekly leasing report.",
        "open_item": "A4",
        "force_status": MANUAL,
    },
]

# Folders registered in report_map.json with no parser. They need no
# declaration — the report_map entry is the whole story — but the page says
# what each would feed if it existed.
PENDING_HINT = {
    "Property Status": "Month-to-month counts per property, which today are "
                       "derived from the rent roll instead.",
    "Weekly Leasing Reports": "The RealPage rate tracker behind the workbook's "
                              "Lease Detail tab — the one input still typed in "
                              "by hand.",
    "AIRM - Yardi Rev Management": "The market-rent and trade-out feed the "
                                   "Trade Outs card is waiting on.",
    "AP Analytics": "POs over 30 days and invoices processed — two scorecard "
                    "KPIs a resident AR report cannot answer.",
    "Workorders - Mainentance ": "The maintenance KPI group, which no feed "
                                 "reaches today.",
}


# ---------------------------------------------------------------------------
# evidence
# ---------------------------------------------------------------------------

def filing_rules():
    """folder -> the attachment-name patterns the Gmail filer routes there.

    Nothing in this repo puts files in Drive: an Apps Script reads the mailbox
    and files each attachment into a Report Lander subfolder. That rule is the
    front of every Drive chain -- it is what decides which data goes where --
    so the page shows it rather than starting at a folder that fills itself.

    Read through test_routing's own loader, so the flow page and the contract
    test cannot end up parsing the script differently. If the script's shape
    changes the loader exits; that is test_routing's failure to report, not
    this one's, so the lineage degrades to no filer line instead of refusing
    to build.
    """
    try:
        import test_routing
        return {folder: pats for folder, pats in test_routing.load_rules()}
    except SystemExit:
        print("[warn] could not read ROUTING_RULES from gmail_drive_filing.js "
              "-- run scripts/test_routing.py; the flow page omits the filer")
        return {}
    except Exception as e:                                  # noqa: BLE001
        print(f"[warn] filing rules unavailable: {e}")
        return {}


def _load_json(path):
    p = ROOT / path
    if not p.exists():
        return None
    try:
        return json.load(open(p))
    except Exception as e:                                  # noqa: BLE001
        print(f"[warn] could not read {path}: {e}")
        return None


def _slug_files(pattern):
    """data/<slug>/x.json -> [(slug, dict)] for every property that has one."""
    out = []
    for path in sorted(glob.glob(str(ROOT / pattern.replace("<slug>", "*")))):
        doc = _load_json(pathlib.Path(path).relative_to(ROOT))
        if doc is None:
            continue
        out.append((pathlib.Path(path).parent.name, doc))
    return out


def _points_evidence(slug, doc):
    """expense_ratio.json and friends keep a list of period points."""
    pts = doc.get("points") if isinstance(doc, dict) else None
    if not pts:
        return None
    last = pts[-1]
    return {"property": slug, "as_of": last.get("period_end"),
            "source_file": ", ".join(last.get("source_files") or []) or None,
            "landed_at": last.get("landed_at"),
            "detail": f"{len(pts)} statement period(s) accumulated"}


def evidence_for_store(store_paths):
    """What the pipeline actually wrote, for the stores a flow declares.

    One row per property, not per file: a T12 statement writes four files for
    the same building and listing them separately reads as four arrivals.
    """
    by_prop = {}
    for pattern in store_paths:
        clean = pattern.split("  ")[0].strip()
        if "<slug>" not in clean:
            continue
        for slug, doc in _slug_files(clean):
            if not isinstance(doc, dict):
                continue
            row = by_prop.setdefault(slug, {
                "property": slug, "file": None, "as_of": None,
                "source_file": None, "landed_at": None, "detail": None,
                "files": [],
            })
            row["files"].append(clean.replace("<slug>", slug))
            if "points" in doc:
                ev = _points_evidence(slug, doc)
                if ev:
                    row["as_of"] = row["as_of"] or ev["as_of"]
                    row["detail"] = row["detail"] or ev["detail"]
                    row["source_file"] = row["source_file"] or ev["source_file"]
                    row["landed_at"] = row["landed_at"] or ev["landed_at"]
                continue
            row["as_of"] = row["as_of"] or doc.get("as_of")
            row["source_file"] = row["source_file"] or doc.get("source_file")
            row["landed_at"] = row["landed_at"] or doc.get("landed_at")
    rows = []
    for slug, row in sorted(by_prop.items()):
        row["file"] = ", ".join(row.pop("files"))
        rows.append(row)
    return rows


def evidence_from_scorecard(prefix, want=None):
    """measured[slug] carries one feed family per prefix — see SC_FEED_PREFIXES.

    The unprefixed family is shared: The Landing's cells come from the analyst
    workbook and Palma's from the Drive AR report, and only received_what tells
    them apart. `want` is a substring of that, so each flow claims its own.
    """
    sc = _load_json("docs/scorecard.json") or {}
    labels = {p.get("slug"): p.get("label") for p in sc.get("properties") or []}
    rows = []
    for slug, m in (sc.get("measured") or {}).items():
        kpis = m.get(prefix + "kpis")
        if not kpis:
            continue
        if want and want.lower() not in str(m.get(prefix + "received_what") or "").lower():
            continue
        rows.append({
            "property": labels.get(slug) or slug,
            "file": m.get(prefix + "source"),
            "as_of": m.get(prefix + "as_of"),
            "source_file": m.get(prefix + "source"),
            "landed_at": m.get(prefix + "received_at"),
            "detail": f"{len(kpis)} KPI cell(s): " + ", ".join(sorted(kpis)),
        })
    return rows


def gather_evidence(flow):
    kind = flow.get("evidence_kind")
    if kind == "landing":
        lm = (_load_json("docs/landing.json") or {}).get("meta") or {}
        rows = []
        if lm:
            rows.append({"property": lm.get("property"),
                         "file": lm.get("source_workbook"),
                         "as_of": lm.get("rent_roll_as_of"),
                         "source_file": lm.get("source_workbook"),
                         "landed_at": lm.get("generated_at"),
                         "detail": "extract run; the workbook has no arrival "
                                   "time of its own, so this is when it was "
                                   "extracted"})
        rows += evidence_from_scorecard("", want="workbook")
        return rows
    if kind == "scorecard_meta":
        sm = (_load_json("docs/scorecard.json") or {}).get("meta") or {}
        if not sm:
            return []
        return [{"property": "all", "file": sm.get("source_workbook"),
                 "as_of": None, "source_file": sm.get("source_workbook"),
                 "landed_at": sm.get("generated_at"),
                 "detail": "sheet " + str(sm.get("source_sheet"))}]
    if kind == "eliseai_daily":
        rows = []
        for slug, doc in _slug_files("data/<slug>/eliseai_daily.json"):
            days = doc.get("days") or []
            if not days:
                continue
            last = days[-1]
            rows.append({"property": slug, "file": "data/%s/eliseai_daily.json" % slug,
                         "as_of": last.get("date"), "source_file": None,
                         "landed_at": last.get("received_at"),
                         "detail": f"{len(days)} day(s) recorded"})
        rows += evidence_from_scorecard("eliseai_")
        return rows
    if flow["id"] == "bldg_metrics":
        return evidence_from_scorecard("bldg_")
    if flow["id"] in ("delinquency", "delinquency_alt"):
        return evidence_from_scorecard("", want="Drive")
    if flow["id"] == "handset":
        m = _load_json("docs/metrics.json") or {}
        gen = (m.get("meta") or {}).get("generated_at")
        return [{"property": "portfolio", "file": "docs/metrics.json",
                 "as_of": None, "source_file": None, "landed_at": gen,
                 "detail": "carried through the last pipeline run untouched"}]
    return evidence_for_store(flow.get("stores") or [])


def derive_status(flow, evidence, registered_active):
    if flow.get("force_status"):
        return flow["force_status"]
    if not registered_active:
        return NO_PARSER
    if not evidence:
        return WAITING
    if not flow.get("dashboard"):
        return PARTIAL
    return LIVE


# ---------------------------------------------------------------------------
# checks — a lineage that points at nothing is worse than none
# ---------------------------------------------------------------------------

def page_ids(path, patterns):
    """Ids a page defines, read as text: these pages build most ids in JS."""
    text = (ROOT / path).read_text(encoding="utf-8")
    found = set()
    for pat in patterns:
        found.update(re.findall(pat, text))
    return found, text


def data_table_titles():
    """data.html table id -> its heading, for the card link's tooltip.

    Read out of the renderTable specs rather than restated here: a table that
    gets renamed should rename itself on the dashboard's links too.
    """
    text = (ROOT / "docs/data.html").read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r'id:\s*"([\w-]+)"(.{0,400}?)title:\s*"((?:[^"\\]|\\.)*)"',
                         text, re.S):
        out.setdefault(m.group(1), m.group(3).replace('\\"', '"'))
    # dynamic families are built as a prefix plus a slug; the prefix is what a
    # card links to, and data.html resolves it to the first table that exists
    for m in re.finditer(r'id:\s*"([\w-]+-)"\s*\+(.{0,240}?)title:\s*"((?:[^"\\]|\\.)*)"',
                         text, re.S):
        out.setdefault(m.group(1).rstrip("-"), m.group(3).replace('\\"', '"').strip(" \u2014-"))
    return out


def card_index(flows, titles):
    """anchor -> where that dashboard card's numbers live on data.html.

    index.html reads this to put a link in each card's corner. Several feeds
    can land on one card (four of them fill the scorecard), so the entry
    carries every flow behind it and the union of their tables, with the
    primary being the first table declared for that card.
    """
    cards = {}
    for f in flows:
        if f.get("same_as"):
            continue                     # an alias route, folded into its primary
        for d in f.get("dashboard") or []:
            # Not every surface a feed lands on is a card. The Leased tile is
            # real and fed by the export, but it is one tile in a row, not a
            # card with a corner to hang a link in -- so it stays on the flow
            # page and out of this index rather than sitting here inert.
            if d.get("tile"):
                continue
            e = cards.setdefault(d["anchor"], {
                "card": d["card"], "tab": d["tab"],
                "tables": [], "flows": [], "primary": None, "holds": None,
            })
            if f["id"] not in e["flows"]:
                e["flows"].append(f["id"])
            # An explicit primary beats table order. Several feeds land on one
            # card and the flows are sorted for the page's reading order, not
            # for which table a reader most wants -- without this, whichever
            # flow happens to sort first picks the link target.
            if d.get("primary"):
                e["primary_declared"] = d["primary"]
            # a card's own tables where declared, else the flow's
            for t in (d.get("tables") if d.get("tables") is not None
                      else (f.get("tables") or [])):
                if t not in e["tables"]:
                    e["tables"].append(t)
    for anchor, e in cards.items():
        # A wildcard is a family of per-property tables; the prefix is the
        # link target and data.html resolves it to the first one that exists.
        tables = [t[:-1].rstrip("-") if t.endswith("*") else t for t in e["tables"]]
        e["tables"] = tables
        # No table holds this card's numbers -- the placeholder cards, and any
        # card whose feed stops short -- so the link goes to the flow row that
        # explains why instead of nowhere.
        # A declared primary goes through the same wildcard stripping as the
        # table list: "t-buckets-*" names the family, and data.html resolves the
        # stem to the first table that exists. Left as-is it would be an href to
        # a literal asterisk -- a link to nowhere, which is the one thing the
        # corner link is not allowed to be.
        declared = e.pop("primary_declared", None)
        if declared and declared.endswith("*"):
            declared = declared[:-1].rstrip("-")
        e["primary"] = declared or (tables[0] if tables else "f-" + e["flows"][0])
        e["holds"] = titles.get(e["primary"])
    return cards


def run_checks(flows):
    problems, warnings = [], []

    idx_ids, idx_text = page_ids("docs/index.html", [r'id="([A-Za-z0-9_-]+)"'])
    # Cards built in JavaScript name themselves by concatenation
    # (sc.id = "psc-" + p.slug), so record the prefix and accept any anchor
    # under it -- otherwise every property tab's card reads as undefined.
    idx_prefixes = set(re.findall(r'\.id\s*=\s*"([A-Za-z0-9_-]+-)"\s*\+', idx_text))

    def index_defines(anchor):
        return anchor in idx_ids or any(anchor.startswith(p) and len(anchor) > len(p)
                                        for p in idx_prefixes)
    # data.html builds its table ids in renderTable specs: id: "t-…"
    data_ids, data_text = page_ids("docs/data.html", [r'id:\s*"([A-Za-z0-9_-]+)"'])

    for f in flows:
        for d in f.get("dashboard") or []:
            if not index_defines(d["anchor"]):
                problems.append(
                    f"{f['id']}: dashboard anchor '{d['anchor']}' "
                    f"({d['card']}) is not an id in docs/index.html")
        for d in f.get("dashboard") or []:
            for t in ([d["primary"]] if d.get("primary") else []) + (d.get("tables") or []):
                if t.endswith("*"):
                    stem = t[:-1]
                    if not any(i.startswith(stem) for i in data_ids) \
                            and ('"' + stem) not in data_text:
                        problems.append(
                            f"{f['id']}: card '{d['card']}' names table prefix "
                            f"'{stem}', which no table in docs/data.html starts with")
                elif t not in data_ids:
                    problems.append(
                        f"{f['id']}: card '{d['card']}' names table '{t}', "
                        f"which docs/data.html does not build")
        for t in f.get("tables") or []:
            if t.endswith("*"):
                stem = t[:-1]
                if not any(i.startswith(stem) for i in data_ids) \
                        and ('"' + stem) not in data_text:
                    problems.append(
                        f"{f['id']}: no table in docs/data.html starts with '{stem}'")
            elif t not in data_ids:
                problems.append(
                    f"{f['id']}: table '{t}' is not built by docs/data.html")
        for s in f.get("steps") or []:
            script = s.get("script", "").split()[0]
            if script.endswith(".py") and not (ROOT / script).exists():
                problems.append(f"{f['id']}: step names {script}, which does not exist")
        # A folder with no parser needs no declaration -- the report_map entry
        # is the whole story. One with a parser that nobody described is the
        # real risk: it is flowing, and the page cannot say where to.
        if (f.get("origin_kind") == "drive" and not f.get("documented")
                and f.get("registered") == "active"):
            warnings.append(
                f"{f['source_label']} ({f['report_type']}) is active in "
                f"report_map.json but has no entry in build_lineage.DRIVE_FLOWS "
                f"— the page shows it with an unknown downstream")

    # A registered folder with no filing rule fills only by hand. That is how a
    # folder sits empty for weeks looking healthy, so the page says so.
    rules = filing_rules()
    if rules:
        for f in flows:
            if f.get("origin_kind") == "drive" and not f.get("filed_by"):
                warnings.append(
                    f"nothing in gmail_drive_filing.js files reports into "
                    f"'{f['source_label']}' — it fills by hand only")

    # every parser the report map names must be a module in scripts/
    cfg = _load_json("config/report_map.json") or {}
    for e in cfg.get("subfolders") or []:
        if e.get("parser") and not (SCRIPTS / (e["parser"] + ".py")).exists():
            problems.append(f"report_map names parser '{e['parser']}', "
                            f"which is not in scripts/")

    return problems, warnings


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

def build():
    cfg = _load_json("config/report_map.json") or {}
    rules = filing_rules()
    flows = []

    for entry in cfg.get("subfolders") or []:
        folder, rtype = entry["drive_folder"], entry["report_type"]
        decl = DRIVE_FLOWS.get((folder, rtype))
        active = entry.get("status") == "active"
        base = {
            "id": (decl or {}).get("id") or re.sub(r"[^a-z0-9]+", "-",
                                                   (folder + "-" + rtype).lower()).strip("-"),
            "title": (decl or {}).get("title") or folder.strip(),
            "origin_kind": "drive",
            "source_label": folder,
            "source_detail": "Drive folder · " + (entry.get("file_glob") or "*"),
            "example": (decl or {}).get("example"),
            # report_map's own _comment describes a folder nobody has written a
            # flow for, so a newly registered one says something true about
            # itself instead of falling through to boilerplate
            "carries": (decl or {}).get("carries")
                       or PENDING_HINT.get(folder)
                       or (entry.get("_comment") or "").split(" -- ")[0]
                       or "No sample file has ever arrived, so nothing is known "
                          "about its shape yet.",
            # which email attachments the Apps Script files into this folder
            "filed_by": sorted(rules.get(folder) or []),
            "report_type": rtype,
            "parser": entry.get("parser"),
            "registered": entry.get("status"),
            "documented": decl is not None,
            "steps": (decl or {}).get("steps") or [],
            "stores": (decl or {}).get("stores") or [],
            "publishes": (decl or {}).get("publishes") or [],
            "dashboard": (decl or {}).get("dashboard") or [],
            "tables": (decl or {}).get("tables") or [],
            "note": (decl or {}).get("note")
                    or ("Registered so a file dropped here is visible to the "
                        "fetch log. A parser needs one sample file to write "
                        "against; none has arrived."),
            "open_item": (decl or {}).get("open_item"),
            "same_as": (decl or {}).get("same_as"),
            "force_status": (decl or {}).get("force_status"),
        }
        base["evidence"] = gather_evidence(base) if decl else []
        base["status"] = derive_status(base, base["evidence"], active)
        base.pop("force_status", None)
        flows.append(base)

    for decl in OTHER_FLOWS:
        f = dict(decl)
        f.setdefault("registered", None)
        f.setdefault("parser", None)
        f["documented"] = True
        f["evidence"] = gather_evidence(f)
        f["status"] = derive_status(f, f["evidence"], True)
        f.pop("force_status", None)
        f.pop("evidence_kind", None)
        flows.append(f)

    # Read order: Drive first (the question the page is answering), then the
    # mailbox, then the workbooks, then what has no feed at all; within each,
    # what is working before what is waiting. An alias route sorts next to the
    # flow it duplicates, since the page folds it in there.
    origin_rank = {"drive": 0, "email": 1, "workbook": 2, "manual": 3}
    status_rank = {LIVE: 0, PARTIAL: 1, WAITING: 2, NO_PARSER: 3, MANUAL: 4}
    primary = {f["id"]: f for f in flows}
    def sort_key(f):
        anchor = primary.get(f.get("same_as") or f["id"], f)
        return (origin_rank.get(anchor.get("origin_kind"), 9),
                status_rank.get(anchor.get("status"), 9),
                anchor["title"], 0 if f is anchor else 1, f["title"])
    flows.sort(key=sort_key)

    problems, warnings = run_checks(flows)

    counts = {}
    for f in flows:
        counts[f["status"]] = counts.get(f["status"], 0) + 1

    titles = data_table_titles()
    cards = card_index(flows, titles)

    return {
        "cards": cards,
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "note": "The chain from a report in Google Drive to a card on the "
                    "dashboard. The Drive side is derived from "
                    "config/report_map.json, so a newly registered folder "
                    "appears here by itself; the downstream edges are declared "
                    "in scripts/build_lineage.py and checked against "
                    "index.html and data.html on every run. Arrival times and "
                    "as-of dates are read from what the pipeline actually "
                    "wrote, not asserted.",
            "counts": counts,
            "warnings": warnings,
        },
        "stages": STAGES,
        "flows": flows,
    }, problems, warnings


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="verify the declarations and write nothing")
    a = ap.parse_args()

    doc, problems, warnings = build()

    print(f"{len(doc['flows'])} flow(s):")
    width = max(len(f["title"]) for f in doc["flows"])
    for f in doc["flows"]:
        dash = len(f.get("dashboard") or [])
        print(f"  {f['status']:<9}  {f['title']:<{width}}  "
              f"{len(f.get('evidence') or [])} evidence, {dash} card(s)")
    for w in warnings:
        print(f"[warn] {w}")

    if problems:
        print("\nREFUSING to write docs/lineage.json:")
        for p in problems:
            print(f"  - {p}")
        return 1

    if a.check:
        print("\n--check: declarations verified, nothing written.")
        return 0

    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"\nwrote {_rel(OUT.relative_to(ROOT))} "
          f"({OUT.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

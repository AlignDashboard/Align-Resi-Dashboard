"""
Guard tests for the Gmail -> Drive filing contract.

scripts/gmail_drive_filing.js decides which Drive folder a report lands in.
config/report_map.json decides which folder the pipeline reads. Nothing enforces
that the two agree, and when they disagree BOTH sides look healthy: Apps Script
creates any folder it is asked for, and fetch_drive just logs a folder it does
not recognise. The report simply never gets parsed.

That is what happened to the weekly EliseAI funnel -- filed to _Unsorted for six
weeks because no pattern matched "leasing_funnel_report_<date>.xlsx" -- and what
would have happened the first time an AIRM or work-order report arrived, since
those two rules named folders ("AIRM/Yardi Rev Management") that do not exist.

Checks, all fixture-free:

  - every routing rule's folder is a drive_folder in report_map.json
  - report_map folders with no rule are reported (a report nothing files there)
  - no folder name contains "/" (legal in Drive, so it fails silently)
  - every file_glob starts with "*" (the filer prefixes the arrival date)
  - real report filenames, verbatim from Drive, route where they belong
  - a file that is filed correctly today does not move

Run: python scripts/test_routing.py
"""

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "gmail_drive_filing.js"
REPORT_MAP = ROOT / "config" / "report_map.json"

UNSORTED = "_Unsorted"


# --------------------------------------------------------------------------
# Read ROUTING_RULES out of the Apps Script, so the test reads the same source
# of truth that gets pasted into script.google.com -- not a copy that can drift.
# --------------------------------------------------------------------------

def load_rules():
    text = SCRIPT.read_text()
    block = re.search(r"const ROUTING_RULES = \[(.*?)\n\];", text, re.S)
    if not block:
        sys.exit("FAIL: could not find ROUTING_RULES in " + str(SCRIPT))

    rules = []
    for m in re.finditer(r"\{\s*folder:\s*'((?:[^'\\]|\\.)*)'\s*,\s*patterns:\s*\[(.*?)\]\s*\}",
                         block.group(1), re.S):
        folder = m.group(1)
        patterns = re.findall(r"/((?:[^/\\]|\\.)+)/", m.group(2))
        rules.append((folder, patterns))
    if not rules:
        sys.exit("FAIL: ROUTING_RULES parsed to nothing -- has the format changed?")
    return rules


def normalize(s):
    """Mirror of normalize_() in the Apps Script."""
    return re.sub(r"[\s_\-.]", "", (s or "").lower())


def route(filename, rules, subject=""):
    """Mirror of routeFor_() in the Apps Script. First match wins."""
    for hay in (normalize(filename), normalize(subject)):
        if not hay:
            continue
        for folder, patterns in rules:
            for p in patterns:
                if re.search(p, hay):
                    return folder
    return UNSORTED


# --------------------------------------------------------------------------
# Real filenames, copied verbatim from Drive on 2026-08-31, and the folder each
# belongs in. Add a line here whenever a new report shape starts arriving.
# --------------------------------------------------------------------------

CASES = [
    # (filename, folder it must reach)
    ("2026-08-25 leasing_funnel_report_2026-08-25.xlsx",            "EliseAI Reports"),
    ("2026-08-18 leasing_funnel_report_2026-08-18.xlsx",            "EliseAI Reports"),
    ("leasing_funnel_report_2026-08-04.xlsx",                       "EliseAI Reports"),
    ("2026-08-31 Landing 2025 Renewal Tracker - Full (40).xlsx",    "Renewal Tracker"),
    ("2026-08-30 Renewals since 9.15.25 - (updated 8.30.26).xlsx",  "Renewal Tracker"),
    ("2026-08-31 BoxScoreSummary08_31_2026 - 30Days - The Landing.xlsx", "Property Status"),
    ("2026-08-31 BoxScoreSummary08_31_2026 - 60Days - The Landing.xlsx", "Property Status"),
    ("2026-08-30 8.24-8.30 Prospect and applicant Report  (1).xlsx", "Prospect Reports"),
    ("2026-08-31 Daily Report- Week Ending 8.30.26 (2).xlsx",       "Daily Leasing Reports"),
    ("2026-08-30 8.30.26 - The Madelon - Daily Report.xlsx",        "Daily Leasing Reports"),
    ("2026-08-28 08.24.2026- 08.30.2026- Chorus - Daily Report (3).xlsx", "Daily Leasing Reports"),
    ("2026-08-29 Daily Tracker  (14) (1) (43).xlsx",                "Daily Tracker"),
    ("2026-08-31 rs_sql_JPM_Demographics_Combined - The Landing (3).xlsx", "Demographics"),
    ("UnitDirectory08_25_2026.xlsx",                                "Building Info"),
    ("2026-08-26 UnitDirectory08_25_2026.xlsx",                     "Building Info"),
    # already filed correctly today -- these must not move
    ("12_Month_Statement_Accrual.xlsx",                             "T12 Expenses"),
    ("2026-07-16 12_Month_Statement_rs335_accrual.xlsx",            "T12 Expenses"),
    ("2026-08-10 ConcessionBurnOff08_10_2026.xlsx",                 "Concession Burnoff"),
    ("Delinquency_8_1_2026.xls.xlsx",                               "Delinquency"),
    ("2026-08-31 rs_rp_DelinquencySummaryReport - The Landing.xlsx", "Delinquency"),
    ("2026-07-14 RentRoll07_14_2026.xlsx",                          "Rent Roll"),
]


def main():
    rules = load_rules()
    cfg = json.loads(REPORT_MAP.read_text())
    mapped = {e["drive_folder"] for e in cfg["subfolders"]}
    rule_folders = [f for f, _ in rules]
    failures = []

    print(f"1. rule folders are known to the pipeline ({len(rules)} rule(s))")
    for folder in rule_folders:
        if folder in mapped:
            print(f"   PASS {folder!r}")
        else:
            print(f"   FAIL {folder!r} is not a drive_folder in report_map.json")
            failures.append(f"unmapped rule folder {folder!r}")

    print("\n2. pipeline folders that no rule files anything into")
    orphans = sorted(mapped - set(rule_folders))
    for folder in orphans:
        # Not a failure: a folder can be filled by hand or by another feed.
        # It IS worth seeing, because it usually means a missing rule.
        print(f"   note {folder!r} has no routing rule")
    if not orphans:
        print("   (none)")

    print("\n3. folder names Drive would accept but the pipeline would not")
    for folder in rule_folders:
        if "/" in folder:
            print(f"   FAIL {folder!r} contains '/' -- Drive allows it, so this "
                  f"silently creates a second folder")
            failures.append(f"slash in folder name {folder!r}")
    if not any("/" in f for f in rule_folders):
        print("   PASS no rule folder contains '/'")

    print("\n4. every file_glob tolerates the filer's date prefix")
    for e in cfg["subfolders"]:
        glob = e.get("file_glob") or "*"
        if glob.startswith("*"):
            print(f"   PASS {e['drive_folder']!r:32} {glob}")
        else:
            print(f"   FAIL {e['drive_folder']!r:32} {glob} -- would skip "
                  f"'<date> {glob.lstrip('*')}'")
            failures.append(f"anchored glob {glob!r} for {e['drive_folder']!r}")

    print(f"\n5. real filenames route where they belong ({len(CASES)} case(s))")
    for name, want in CASES:
        got = route(name, rules)
        if got == want:
            print(f"   PASS {want:24} <- {name[:56]}")
        else:
            print(f"   FAIL {name!r}\n        wanted {want!r}, got {got!r}")
            failures.append(f"{name!r} routed to {got!r}, wanted {want!r}")

    print()
    if failures:
        print(f"FAIL: {len(failures)} problem(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS: the filing script and report_map.json agree, and every known "
          "report routes to a folder the pipeline reads.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

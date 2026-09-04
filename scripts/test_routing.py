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
  - the script's EXTERNAL_FOLDERS and report_map's "tree": "reference" name the
    same folders -- the two ways of saying "this one is not in the drop tree"
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


def load_external():
    """Folder names the script resolves by absolute ID (outside the drop tree)."""
    text = SCRIPT.read_text()
    block = re.search(r"const EXTERNAL_FOLDERS = \{(.*?)\n\};", text, re.S)
    if not block:
        sys.exit("FAIL: could not find EXTERNAL_FOLDERS in " + str(SCRIPT))
    return dict(re.findall(r"'((?:[^'\\]|\\.)*)'\s*:\s*'((?:[^'\\]|\\.)*)'",
                           block.group(1)))


def load_property_words():
    """PROPERTY_WORDS from the Apps Script -- stripped before naming a report type."""
    text = SCRIPT.read_text()
    block = re.search(r"const PROPERTY_WORDS = \[(.*?)\n\];", text, re.S)
    if not block:
        sys.exit("FAIL: could not find PROPERTY_WORDS in " + str(SCRIPT))
    return re.findall(r'"((?:[^"\\]|\\.)*)"', block.group(1))


AUTO_EXTS = ("xlsx", "xls", "csv", "pdf", "docx", "doc")
AUTO_FILLER = r"(?:^|\s)(week ending|weekending|as of|since|thru|through|updated|copy of)(?=\s|$)"


def report_type(filename, words):
    """Mirror of reportTypeFor_() in the Apps Script. '' means 'cannot name it'."""
    s = str(filename or "")
    for _ in range(3):
        m = re.search(r"\.([A-Za-z0-9]+)$", s)
        if m and m.group(1).lower() in AUTO_EXTS:
            s = s[:m.start()]
        else:
            break
    s = re.sub(r"^\d{4}-\d{2}-\d{2}\s+", "", s)
    s = re.sub(r"\([^)]*\d[^)]*\)", " ", s)
    s = re.sub(r"_+", " ", s)
    s = re.sub(r"([A-Za-z])(\d)", r"\1 \2", s)
    s = re.sub(r"\b\d+\s*Days?\b", " ", s, flags=re.I)
    for w in words:
        s = re.sub(r"\b" + re.escape(w) + r"\b", " ", s, flags=re.I)
    for _ in range(3):
        s = re.sub(r"\b\d{1,4}[._\-/]\d{1,2}(?:[._\-/]\d{1,4})?\b", " ", s)
    s = re.sub(r"\b\d{1,8}\b", " ", s)
    s = re.sub(r"\s*[-\u2013\u2014]+\s*", " ", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" -\u2013\u2014_.")
    s = re.sub(AUTO_FILLER, " ", s, flags=re.I)
    s = re.sub(r"\s{2,}", " ", s).strip(" -\u2013\u2014_.")
    if len(s) < 4 or not re.search(r"[A-Za-z]{3}", s):
        return ""
    return s[:60].rstrip(" -\u2013\u2014_.")


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

# Filenames no routing rule claims, and the folder each should make for itself.
# "" means the name cannot be derived and the file belongs in _Unsorted.
NEW_TYPE_CASES = [
    ("2026-09-05 AP Aging Detail 09_05_2026 - Chorus.xlsx",        "AP Aging Detail"),
    ("2026-09-05 WorkOrder Summary - The Madelon (2).xlsx",        "WorkOrder Summary"),
    ("2026-09-05 8.24-8.30 Prospect and applicant Report  (1).xlsx", "Prospect and applicant Report"),
    ("2026-09-05 BoxScoreSummary09_05_2026 - 30Days - The Landing.xlsx", "BoxScoreSummary"),
    ("2026-09-05 BoxScoreSummary09_05_2026 - 60Days - The Landing.xlsx", "BoxScoreSummary"),
    # three spellings of one report must land on one folder, not three
    ("2026-09-05 8.30.26 - The Madelon - Daily Report.xlsx",        "Daily Report"),
    ("2026-09-05 08.24.2026- 08.30.2026- Chorus - Daily Report (3).xlsx", "Daily Report"),
    ("2026-09-05 Daily Report- Week Ending 8.30.26 (2).xlsx",       "Daily Report"),
    # nothing nameable survives the date, the copy suffix and the property name
    ("2026-09-05 (2).xlsx",                                        ""),
    ("2026-09-05 2026.xlsx",                                       ""),
    ("2026-09-05 The Landing.xlsx",                                ""),
    ("2026-09-05 08_31_2026.xlsx",                                 ""),
    # these two exist to exercise the "too short to be a name" floor itself:
    # both leave a real remnant, and both must still be refused
    ("2026-09-05 Ops.xlsx",                                        ""),
    ("2026-09-05 A B C - Chorus.xlsx",                             ""),
]

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
    ("12_Month_Budget_Accrual.xlsx",                                "Budgets"),
    ("2026-09-03 12_Month_Budget_Accrual.xlsx",                     "Budgets"),
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
    external = load_external()
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

    print("\n5. the two ways of saying \"not in the drop tree\" agree")
    trees = {}
    for e in cfg["subfolders"]:
        tree = e.get("tree", "reports")
        if tree not in ("reports", "reference"):
            print(f"   FAIL {e['drive_folder']!r} has tree {tree!r} -- "
                  f"fetch_drive knows only 'reports' and 'reference'")
            failures.append(f"unknown tree {tree!r} for {e['drive_folder']!r}")
        trees.setdefault(e["drive_folder"], set()).add(tree)
    referenced = {f for f, ts in trees.items() if "reference" in ts}
    for folder in sorted(set(external) | referenced):
        in_script = folder in external
        in_map = folder in referenced
        if in_script and in_map:
            print(f"   PASS {folder!r} external in both (script property "
                  f"{external[folder]})")
        elif in_script:
            print(f"   FAIL {folder!r} is EXTERNAL_FOLDERS in the script but not "
                  f'"tree": "reference" in report_map -- the fetcher would look '
                  f"for it in the drop tree")
            failures.append(f"{folder!r} external in script only")
        else:
            print(f"   FAIL {folder!r} is \"tree\": \"reference\" in report_map but "
                  f"not EXTERNAL_FOLDERS in the script -- the filer would create a "
                  f"second copy inside the drop tree")
            failures.append(f"{folder!r} reference in report_map only")
    for folder, ts in sorted(trees.items()):
        if ts == {"reports"} and folder in external:
            failures.append(f"{folder!r} split across trees")

    print(f"\n6. real filenames route where they belong ({len(CASES)} case(s))")
    for name, want in CASES:
        got = route(name, rules)
        if got == want:
            print(f"   PASS {want:24} <- {name[:56]}")
        else:
            print(f"   FAIL {name!r}\n        wanted {want!r}, got {got!r}")
            failures.append(f"{name!r} routed to {got!r}, wanted {want!r}")

    words = load_property_words()

    print("\n7. PROPERTY_WORDS still matches config/properties.json")
    props = json.loads((ROOT / "config" / "properties.json").read_text())["properties"]
    expected = ({a for x in props for a in x.get("aliases", [])}
                | {x["name"] for x in props}
                | {c for x in props for c in x.get("codes", [])})
    missing, extra = expected - set(words), set(words) - expected
    if missing:
        print(f"   FAIL {len(missing)} name(s) in properties.json are not in the script: "
              f"{sorted(missing)[:6]}")
        failures.append("PROPERTY_WORDS is missing names from properties.json")
    if extra:
        print(f"   FAIL the script strips {len(extra)} name(s) properties.json does not "
              f"know: {sorted(extra)[:6]}")
        failures.append("PROPERTY_WORDS has names properties.json does not")
    if not missing and not extra:
        print(f"   PASS all {len(words)} names, aliases and codes agree")

    print(f"\n8. a new report type names its own folder ({len(NEW_TYPE_CASES)} case(s))")
    for filename, want in NEW_TYPE_CASES:
        got = report_type(filename, words)
        label = repr(want) if want else "_Unsorted (refuses to guess)"
        if got == want:
            print(f"   PASS {label:33} <- {filename[:46]}")
        else:
            print(f"   FAIL {filename!r}\n        wanted {want!r}, got {got!r}")
            failures.append(f"{filename!r} named {got!r}, wanted {want!r}")

    print("\n9. auto-naming never steals a file a rule owns")
    stolen = 0
    for filename, want in CASES:
        got = route(filename, rules)
        if got != want:
            print(f"   FAIL {filename!r} routes to {got!r}, not {want!r}")
            failures.append(f"auto-naming hijacked {filename!r}")
            stolen += 1
    if not stolen:
        print(f"   PASS all {len(CASES)} rule-owned files still reach their rule")

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

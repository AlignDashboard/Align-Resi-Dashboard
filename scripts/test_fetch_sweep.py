"""
Guard tests for fetch_drive's two-pass routing.

Pass 1 reads each active entry's own folder, as it always has. Pass 2 sweeps the
rest of the drop tree for unclaimed files matching an entry's name_patterns, so a
report filed into the wrong folder still reaches its parser.

The second pass is the part that can do damage, and these tests are mostly about
what it must NOT touch:

  - Archive Reports. The owner archived a July rent roll there alongside four
    other July exports. Sweeping it would publish a seven-week-old rent roll as
    current. Excluded by tree AND by name, and both are tested.
  - A file two entries claim as different report types. Reported, never guessed.
  - A filename already downloaded, which would otherwise overwrite on disk and
    let the second parse win silently.
  - Files no parser can read (renewal trackers, prospect reports, box scores):
    they stay put and stay visible in the log.

Runs against a stubbed Drive mirroring the real 2026-08-31 layout -- no network,
no credentials, no fixtures.

Run: python scripts/test_fetch_sweep.py
"""

import json
import os
import pathlib
import shutil
import sys
import tempfile
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
FOLDER = "application/vnd.google-apps.folder"
FILE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _stub_google():
    """fetch_drive imports the Google client at module scope; it is never called."""
    for name in ("google", "google.oauth2", "googleapiclient",
                 "googleapiclient.discovery", "googleapiclient.http"):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["google.oauth2"].service_account = types.SimpleNamespace(
        Credentials=types.SimpleNamespace(from_service_account_info=lambda *a, **k: None))
    sys.modules["googleapiclient.discovery"].build = lambda *a, **k: None
    sys.modules["googleapiclient.http"].MediaIoBaseDownload = object


def run(fd, tree, reports="R", reference=None):
    """Run fetch_drive.main() against `tree` and return its manifest."""
    fd._service = lambda: None
    fd._list_children = lambda svc, pid, mime=None: [
        {"id": i, "name": n, "mimeType": m,
         "createdTime": "2026-09-01T10:00:00Z",
         "modifiedTime": "2026-09-01T10:00:00Z"}
        for m, n, i in tree.get(pid, [])]
    fd._download = lambda svc, fid, dest: (
        dest.parent.mkdir(parents=True, exist_ok=True), dest.write_text("stub"))
    os.environ["GDRIVE_FOLDER_ID"] = reports
    if reference:
        os.environ["GDRIVE_REFERENCE_FOLDER_ID"] = reference
    else:
        os.environ.pop("GDRIVE_REFERENCE_FOLDER_ID", None)
    shutil.rmtree("_downloads", ignore_errors=True)
    fd.main()
    return json.load(open("_downloads/manifest.json"))


# The drop tree as it really stood on 2026-08-31, plus the library.
LIVE = {
    "R": [(FOLDER, n, i) for n, i in [
        ("_Unsorted", "u"), ("Rent Roll", "rr"), ("T12 Expenses", "t12"),
        ("Delinquency", "dq"), ("EliseAI Reports", "el"),
        ("Concession Burnoff", "cb"), ("Residential AR Analytics", "ar"),
        ("Property Status", "ps")]],
    "L": [(FOLDER, "Building Info", "bi"), (FOLDER, "Archive Reports", "arch")],
    "t12": [(FILE, "12_Month_Statement_Accrual.xlsx", "t1")],
    "dq":  [(FILE, "Delinquency_8_1_2026.xls.xlsx", "d1")],
    "ar":  [(FILE, "2026-08-10 Delinquency_8_1_2026.xls.xlsx", "d3")],
    "el":  [(FILE, "leasing_funnel_report_2026-08-04.xlsx", "e1"),
            (FILE, "metrics-building-2026-08-31.csv", "e2")],
    "cb":  [(FILE, "2026-08-10 ConcessionBurnOff08_10_2026.xlsx", "c1")],
    "bi":  [(FILE, "UnitDirectory08_25_2026.xlsx", "b1")],
    "rr": [], "ps": [],
    # stranded in _Unsorted: two the pipeline can read, six it cannot
    "u": [(FILE, "2026-08-25 leasing_funnel_report_2026-08-25.xlsx", "f1"),
          (FILE, "2026-08-18 leasing_funnel_report_2026-08-18.xlsx", "f2"),
          (FILE, "2026-08-31 Landing 2025 Renewal Tracker - Full (40).xlsx", "f3"),
          (FILE, "2026-08-30 8.24-8.30 Prospect and applicant Report  (1).xlsx", "f4"),
          (FILE, "2026-08-31 Daily Report- Week Ending 8.30.26 (2).xlsx", "f5"),
          (FILE, "2026-08-29 Daily Tracker  (14) (1) (43).xlsx", "f6"),
          (FILE, "2026-08-31 BoxScoreSummary08_31_2026 - 30Days - The Landing.xlsx", "f7"),
          (FILE, "2026-08-31 rs_sql_JPM_Demographics_Combined - The Landing (3).xlsx", "f8")],
    # archived on purpose -- superseded copies of live report types
    "arch": [(FILE, "2026-07-14 RentRoll07_14_2026.xlsx", "a1"),
             (FILE, "2026-07-16 12_Month_Statement_rspalmas_accrual.xlsx", "a2"),
             (FILE, "2026-07-14 ConcessionBurnOff07_14_2026.xlsx", "a3")],
}

CHECKS = []


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(f"   {'PASS' if cond else 'FAIL'} {label}")


def main():
    _stub_google()
    sys.path.insert(0, str(ROOT / "scripts"))
    import fetch_drive as fd                                    # noqa: E402

    work = tempfile.mkdtemp()
    (pathlib.Path(work) / "config").symlink_to(ROOT / "config")
    os.chdir(work)

    print("1. the live layout: stranded reports rescued, archive untouched")
    man = run(fd, LIVE, reference="L")
    names = {e["name"] for e in man}
    rescued = {e["name"] for e in man if e.get("rescued_by_name")}

    check("both stranded funnel reports reach the pipeline",
          {"2026-08-25 leasing_funnel_report_2026-08-25.xlsx",
           "2026-08-18 leasing_funnel_report_2026-08-18.xlsx"} <= rescued)
    for archived in ("2026-07-14 RentRoll07_14_2026.xlsx",
                     "2026-07-16 12_Month_Statement_rspalmas_accrual.xlsx",
                     "2026-07-14 ConcessionBurnOff07_14_2026.xlsx"):
        check(f"archived {archived[:34]!r} stays archived", archived not in names)
    check("reports with no parser are left where they are",
          not any(k in n for n in names for k in
                  ("Renewal Tracker", "Prospect", "Daily Report", "Daily Tracker",
                   "BoxScore", "Demographics")))
    check("nothing downloaded twice", len(man) == len(names))
    check("folder-pass files are not flagged as rescued",
          all(not e.get("rescued_by_name")
              for e in man if e["found_in"] != "_Unsorted"))
    check("the unit directory still comes from the reference tree",
          any(e["report_type"] == "unit_directory" and e["found_in"] == "Building Info"
              for e in man))

    print("\n2. an archive inside the DROP tree is still never swept")
    man = run(fd, {"R": [(FOLDER, "Archive Reports", "arch"), (FOLDER, "Rent Roll", "rr")],
                   "arch": [(FILE, "2026-07-14 RentRoll07_14_2026.xlsx", "a1")],
                   "rr": []})
    check("NEVER_SWEEP holds even when the folder is in the drop tree", not man)

    print("\n3. the library is never swept, whatever its folders are called")
    # NEVER_SWEEP protects 'Archive Reports' by name. Tree scoping is what
    # protects everything ELSE the owner keeps in the library -- a folder named
    # anything at all, holding anything that happens to match a name pattern.
    # Without this check, removing the tree scoping still passes, because the
    # name guard covers for it.
    man = run(fd, {"R": [(FOLDER, "Rent Roll", "rr")], "rr": [],
                   "L": [(FOLDER, "Old Statements 2025", "old")],
                   "old": [(FILE, "12_Month_Statement_2025_superseded.xlsx", "o1")]},
              reference="L")
    check("a library folder with no special name is still not swept", not man)

    print("\n4. one filename, two report types -> reported, not guessed")
    real = json.loads((ROOT / "config" / "report_map.json").read_text())
    for e in real["subfolders"]:
        if e["report_type"] == "rent_roll":
            e["name_patterns"] = ["*delinquency*"]      # deliberate clash
    original = fd.json.load
    fd.json.load = lambda fh: (real if str(getattr(fh, "name", "")).endswith("report_map.json")
                               else original(fh))
    try:
        man = run(fd, {"R": [(FOLDER, "_Unsorted", "u"), (FOLDER, "Rent Roll", "rr"),
                             (FOLDER, "Delinquency", "dq")],
                       "u": [(FILE, "2026-08-31 Delinquency_odd.xlsx", "z1")],
                       "rr": [], "dq": []})
    finally:
        fd.json.load = original
    check("an ambiguous filename is refused", not man)

    print("\n5. the same filename in two folders does not overwrite on disk")
    man = run(fd, {"R": [(FOLDER, "Delinquency", "dq"), (FOLDER, "_Unsorted", "u")],
                   "dq": [(FILE, "Delinquency_8_1_2026.xls.xlsx", "d1")],
                   "u":  [(FILE, "Delinquency_8_1_2026.xls.xlsx", "d9")]})
    check("the duplicate name is skipped, the folder-pass copy kept", len(man) == 1)

    os.chdir(ROOT)
    shutil.rmtree(work, ignore_errors=True)

    failed = [label for label, ok in CHECKS if not ok]
    print()
    if failed:
        print(f"FAIL: {len(failed)} of {len(CHECKS)} check(s)")
        for label in failed:
            print(f"  - {label}")
        return 1
    print(f"PASS: {len(CHECKS)} checks — misfiled reports are rescued, and nothing "
          f"archived, ambiguous or duplicated is pulled in.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

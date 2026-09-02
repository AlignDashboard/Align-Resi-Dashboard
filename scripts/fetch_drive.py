"""
fetch_drive.py
--------------
Authenticates to Google Drive with a service account and downloads report
files from the configured subfolders into ./_downloads/<report_type>/.

Env vars (set as GitHub secrets):
  GDRIVE_SA_KEY      -- the full service-account JSON (as a string)
  GDRIVE_FOLDER_ID   -- the ID of the PARENT folder that holds the subfolders
                        ("Report Lander" -- where the Gmail filer drops reports)
  GDRIVE_REFERENCE_FOLDER_ID
                     -- optional. The ID of the LIBRARY folder ("Resi Dashboard")
                        holding hand-curated, long-lived material rather than
                        periodic report drops: keys, reference docs, the unit
                        directory. An entry in report_map.json with
                        "tree": "reference" is looked up here instead of under
                        GDRIVE_FOLDER_ID. Unset means those entries are skipped,
                        with a line in the log saying so.

Reads config/report_map.json to know which subfolders to pull and what
report_type to tag them with. Subfolders with status != "active" are skipped
(they have no parser yet) but logged so you can see what's waiting.

Two passes, in this order:

  1. THE FOLDER PASS. Every active entry's own folder, exactly as before. This
     is what the Gmail filer's organisation is for, and it is unchanged.

  2. THE RESCUE SWEEP. Then every other folder in the drop tree, including
     _Unsorted, looking for files nobody claimed that match an entry's
     name_patterns. A report that was filed into the wrong folder still reaches
     its parser, and the log says where it was found.

The point of the second pass is that folder organisation stops being the only
thing standing between a report and the pipeline. Before it existed, four weeks
of reports sat in _Unsorted because no routing rule matched their names, and
nothing downstream could tell. Organisation is still maintained -- it is just no
longer load-bearing.

The sweep is deliberately scoped and will not touch:
  - the reference tree, which is the owner's curated library. Archived copies of
    superseded reports live there; sweeping it would feed a seven-week-old rent
    roll back into today's numbers.
  - any folder named in NEVER_SWEEP, wherever it appears.
  - a file already claimed by the folder pass.
  - a file matching two entries with different report_types -- that is reported,
    not guessed at.
"""

import fnmatch
import os
import io
import json
import pathlib
import sys

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
DL_ROOT = pathlib.Path("_downloads")

# Folders the rescue sweep never reads, wherever they appear. An archive holds
# superseded copies of live reports on purpose: "2026-07-14 RentRoll…" next to
# four other July exports is a decision, not a misfile, and pulling it back in
# would publish stale figures as current.
NEVER_SWEEP = {"Archive Reports"}


def _service():
    key = json.loads(os.environ["GDRIVE_SA_KEY"])
    creds = service_account.Credentials.from_service_account_info(key, scopes=SCOPES)
    return build("drive", "v3", credentials=creds)


def _list_children(svc, parent_id, mime=None):
    q = f"'{parent_id}' in parents and trashed=false"
    if mime:
        q += f" and mimeType='{mime}'"
    out, token = [], None
    while True:
        resp = svc.files().list(
            q=q, spaces="drive",
            # createdTime/modifiedTime are what the dashboard reports as "data
            # last updated" for a Drive-fed report — when the file landed in the
            # folder, as distinct from the period the report covers.
            fields=("nextPageToken, files(id, name, mimeType, "
                    "createdTime, modifiedTime)"),
            pageToken=token,
            includeItemsFromAllDrives=True, supportsAllDrives=True,
        ).execute()
        out.extend(resp.get("files", []))
        token = resp.get("nextPageToken")
        if not token:
            break
    return out


def _download(svc, file_id, dest):
    req = svc.files().get_media(fileId=file_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with io.FileIO(dest, "wb") as fh:
        dl = MediaIoBaseDownload(fh, req)
        done = False
        while not done:
            _, done = dl.next_chunk()


def main():
    # --all also downloads folders that have no parser yet, into
    # _downloads/_pending/<folder>/. For inspecting a new report format; the
    # daily pipeline never passes it, so nothing unparsed reaches the build.
    fetch_pending = "--all" in sys.argv
    cfg = json.load(open("config/report_map.json"))
    svc = _service()
    parent = os.environ["GDRIVE_FOLDER_ID"]
    reference_parent = os.environ.get("GDRIVE_REFERENCE_FOLDER_ID") or None

    DL_ROOT.mkdir(parents=True, exist_ok=True)

    FOLDER_MIME = "application/vnd.google-apps.folder"

    # Two trees, because two kinds of thing live in Drive and they are not
    # organised alike. "reports" is the Gmail filer's drop folder, one subfolder
    # per report type, churning daily. "reference" is the library the owner
    # curates by hand -- keys, long-lived documents, the unit directory -- which
    # sits outside the drop tree on purpose, so automation does not churn it.
    # An entry names its tree; the default is reports.
    def subfolders_of(parent_id):
        return {f["name"]: f["id"] for f in _list_children(svc, parent_id)
                if f["mimeType"] == FOLDER_MIME}

    trees = {"reports": subfolders_of(parent), "reference": {}}
    print(f"[info] parent folder contains {len(trees['reports'])} subfolder(s): "
          f"{sorted(trees['reports'])}")
    if reference_parent:
        trees["reference"] = subfolders_of(reference_parent)
        print(f"[info] reference folder contains {len(trees['reference'])} "
              f"subfolder(s): {sorted(trees['reference'])}")
    else:
        print('[info] GDRIVE_REFERENCE_FOLDER_ID is not set -- entries marked '
              '"tree": "reference" are skipped this run')

    def folders_for(entry):
        return trees.get(entry.get("tree", "reports"), {})

    def contents(entry):
        return [f for f in _list_children(svc, folders_for(entry)[entry["drive_folder"]])
                if f["mimeType"] != FOLDER_MIME]

    manifest = []
    # Folders the config does not mention at all — a report dropped in one of
    # these is invisible to the pipeline, so say so rather than ignore it.
    # Only the reports tree is checked for strays: the library is the owner's to
    # arrange, and warning about every folder in it would be noise, not a finding.
    folders = trees["reports"]
    unmapped = sorted(set(folders) - {e["drive_folder"] for e in cfg["subfolders"]
                                      if e.get("tree", "reports") == "reports"})
    for name in unmapped:
        files = contents({"drive_folder": name})
        # The Gmail filer names a folder after the report type when nothing
        # matches a rule, so a folder appearing here is usually a NEW REPORT
        # TYPE arriving rather than a mistake. Say that plainly -- this line is
        # the daily prompt to add a parser.
        label = ("NEW REPORT TYPE" if name != "_Unsorted"
                 else "unnamed files")
        print(f"[warn] {label}: '{name}' is not in report_map.json — {len(files)} "
              f"file(s) not read by the pipeline (the name sweep below may still "
              f"rescue some): {[f['name'] for f in files]}")
        # --all (the inspect workflow) downloads even these, into _pending/, so
        # a file mis-filed into _Unsorted can have its structure read from the
        # inspect log. The daily pipeline still ignores unmapped folders.
        if fetch_pending:
            for f in files:
                dest = DL_ROOT / "_pending" / name / f["name"]
                _download(svc, f["id"], dest)
                print(f"[ok] downloaded (unmapped) {name}/{f['name']}")

    claimed = set()   # Drive file ids the folder pass took, so the sweep cannot double-count

    def take(entry, f, found_in, rescued=False):
        dest = DL_ROOT / entry["report_type"] / f["name"]
        if dest.exists():
            # Two folders holding the same filename would otherwise silently
            # overwrite each other on disk and the second parse would win.
            print(f"[note] {found_in}/{f['name']} skipped — a file of that name "
                  f"was already downloaded for {entry['report_type']}")
            return
        _download(svc, f["id"], dest)
        claimed.add(f["id"])
        # landed_at: when this report showed up in Drive. createdTime is the
        # arrival; modifiedTime is later only if someone edited it in place,
        # and an edited report is newer data, so take the later of the two.
        landed_at = max(x for x in (f.get("createdTime"), f.get("modifiedTime")) if x) \
            if (f.get("createdTime") or f.get("modifiedTime")) else None
        manifest.append({"report_type": entry["report_type"],
                         "parser": entry["parser"],
                         "path": str(dest), "name": f["name"],
                         "landed_at": landed_at,
                         "found_in": found_in,
                         "rescued_by_name": rescued,
                         "drive_created_time": f.get("createdTime"),
                         "drive_modified_time": f.get("modifiedTime")})
        print(f"[{'rescued' if rescued else 'ok'}] downloaded {found_in}/{f['name']}"
              + (f" (landed in Drive {landed_at})" if landed_at else "")
              + (f" — filed outside its own folder, matched on name as "
                 f"{entry['report_type']}" if rescued else ""))

    for entry in cfg["subfolders"]:
        name = entry["drive_folder"]
        folders = folders_for(entry)
        where = "" if entry.get("tree", "reports") == "reports" else " [reference]"
        if entry.get("status") != "active":
            # List it anyway. Skipping silently means a report can sit in a
            # pending folder for weeks with nothing in the log to show it, and
            # the filename usually carries the property code.
            if name in folders:
                files = contents(entry)
                print(f"[skip] '{name}'{where} (no parser yet) — {len(files)} "
                      f"file(s) waiting: {[f['name'] for f in files]}")
                if fetch_pending:
                    for f in files:
                        dest = DL_ROOT / "_pending" / name / f["name"]
                        _download(svc, f["id"], dest)
                        print(f"[ok] downloaded (unparsed) {name}/{f['name']}")
            else:
                print(f"[skip] '{name}' (no parser yet, folder absent)")
            continue
        if name not in folders:
            if entry.get("tree") == "reference" and not reference_parent:
                print(f"[skip] '{name}' [reference] — GDRIVE_REFERENCE_FOLDER_ID "
                      f"is not set, so the library was not scanned")
            else:
                print(f"[warn] subfolder '{name}'{where} not found in Drive parent")
            continue
        files = contents(entry)
        # file_glob splits a folder that holds more than one kind of file:
        # EliseAI Reports carries both the weekly funnel .xlsx and the
        # building-metrics .csv, each with its own report_type entry.
        glob = entry.get("file_glob") or "*"
        skipped = [f["name"] for f in files if not fnmatch.fnmatch(f["name"], glob)]
        files = [f for f in files if fnmatch.fnmatch(f["name"], glob)]
        print(f"[info] '{name}'{where} ({glob}) contains {len(files)} file(s): "
              f"{[f['name'] for f in files]}")
        if skipped:
            # a file that matches no entry's glob must stay visible in the log,
            # or it can sit in the folder for weeks with nothing to show for it
            print(f"[note] '{name}': {len(skipped)} file(s) outside this "
                  f"entry's glob: {skipped}")
        for f in files:
            take(entry, f, name)

    # ---------------------------------------------------------------- pass 2
    # Any file in the drop tree that nobody claimed, matched on its own name.
    named = [e for e in cfg["subfolders"]
             if e.get("status") == "active" and e.get("name_patterns")]
    if named:
        def matches(filename, entry):
            low = filename.lower()
            return any(fnmatch.fnmatch(low, pat.lower())
                       for pat in entry["name_patterns"])

        rescued = ambiguous = 0
        for folder_name, folder_id in sorted(trees["reports"].items()):
            if folder_name in NEVER_SWEEP:
                print(f"[info] sweep skips '{folder_name}' (NEVER_SWEEP: an archive "
                      f"of superseded reports is not a misfile)")
                continue
            for f in _list_children(svc, folder_id):
                if f["mimeType"] == FOLDER_MIME or f["id"] in claimed:
                    continue
                hits = [e for e in named if matches(f["name"], e)]
                # Entries that agree on report_type AND parser are the same claim
                # wearing two folder names (the funnel parses from two folders,
                # delinquency from two). Only a genuine disagreement is ambiguous.
                kinds = {(e["report_type"], e["parser"]) for e in hits}
                if not hits:
                    continue
                if len(kinds) > 1:
                    ambiguous += 1
                    print(f"[warn] '{folder_name}/{f['name']}' matches more than one "
                          f"report type ({sorted(k[0] for k in kinds)}) — not guessing; "
                          f"file it into the right folder or tighten name_patterns")
                    continue
                take(hits[0], f, folder_name, rescued=True)
                rescued += 1
        if rescued or ambiguous:
            print(f"[info] rescue sweep: {rescued} file(s) picked up outside their own "
                  f"folder, {ambiguous} ambiguous")
        else:
            print("[info] rescue sweep: nothing outside its own folder")

    json.dump(manifest, open("_downloads/manifest.json", "w"), indent=2)
    print(f"\n{len(manifest)} file(s) downloaded.")


if __name__ == "__main__":
    main()

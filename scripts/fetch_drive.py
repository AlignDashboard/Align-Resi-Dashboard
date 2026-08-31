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
        print(f"[warn] '{name}' is not in report_map.json — "
              f"{len(files)} file(s) ignored: {[f['name'] for f in files]}")
        # --all (the inspect workflow) downloads even these, into _pending/, so
        # a file mis-filed into _Unsorted can have its structure read from the
        # inspect log. The daily pipeline still ignores unmapped folders.
        if fetch_pending:
            for f in files:
                dest = DL_ROOT / "_pending" / name / f["name"]
                _download(svc, f["id"], dest)
                print(f"[ok] downloaded (unmapped) {name}/{f['name']}")

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
            dest = DL_ROOT / entry["report_type"] / f["name"]
            _download(svc, f["id"], dest)
            # landed_at: when this report showed up in Drive. createdTime is the
            # arrival; modifiedTime is later only if someone edited it in place,
            # and an edited report is newer data, so take the later of the two.
            landed_at = max(x for x in (f.get("createdTime"), f.get("modifiedTime")) if x) \
                if (f.get("createdTime") or f.get("modifiedTime")) else None
            manifest.append({"report_type": entry["report_type"],
                             "parser": entry["parser"],
                             "path": str(dest), "name": f["name"],
                             "landed_at": landed_at,
                             "drive_created_time": f.get("createdTime"),
                             "drive_modified_time": f.get("modifiedTime")})
            print(f"[ok] downloaded {name}/{f['name']}"
                  + (f" (landed in Drive {landed_at})" if landed_at else ""))

    json.dump(manifest, open("_downloads/manifest.json", "w"), indent=2)
    print(f"\n{len(manifest)} file(s) downloaded.")


if __name__ == "__main__":
    main()

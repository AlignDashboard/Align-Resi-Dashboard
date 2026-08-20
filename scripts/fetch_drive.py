"""
fetch_drive.py
--------------
Authenticates to Google Drive with a service account and downloads report
files from the configured subfolders into ./_downloads/<report_type>/.

Env vars (set as GitHub secrets):
  GDRIVE_SA_KEY      -- the full service-account JSON (as a string)
  GDRIVE_FOLDER_ID   -- the ID of the PARENT folder that holds the subfolders

Reads config/report_map.json to know which subfolders to pull and what
report_type to tag them with. Subfolders with status != "active" are skipped
(they have no parser yet) but logged so you can see what's waiting.
"""

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

    DL_ROOT.mkdir(parents=True, exist_ok=True)

    # map subfolder-name -> its Drive id
    all_children = _list_children(svc, parent)
    folders = {f["name"]: f["id"] for f in all_children
               if f["mimeType"] == "application/vnd.google-apps.folder"}
    print(f"[info] parent folder contains {len(folders)} subfolder(s): "
          f"{sorted(folders.keys())}")

    FOLDER_MIME = "application/vnd.google-apps.folder"

    def contents(folder_name):
        return [f for f in _list_children(svc, folders[folder_name])
                if f["mimeType"] != FOLDER_MIME]

    manifest = []
    # Folders the config does not mention at all — a report dropped in one of
    # these is invisible to the pipeline, so say so rather than ignore it.
    unmapped = sorted(set(folders) - {e["drive_folder"] for e in cfg["subfolders"]})
    for name in unmapped:
        files = contents(name)
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
        if entry.get("status") != "active":
            # List it anyway. Skipping silently means a report can sit in a
            # pending folder for weeks with nothing in the log to show it, and
            # the filename usually carries the property code.
            if name in folders:
                files = contents(name)
                print(f"[skip] '{name}' (no parser yet) — {len(files)} file(s) "
                      f"waiting: {[f['name'] for f in files]}")
                if fetch_pending:
                    for f in files:
                        dest = DL_ROOT / "_pending" / name / f["name"]
                        _download(svc, f["id"], dest)
                        print(f"[ok] downloaded (unparsed) {name}/{f['name']}")
            else:
                print(f"[skip] '{name}' (no parser yet, folder absent)")
            continue
        if name not in folders:
            print(f"[warn] subfolder '{name}' not found in Drive parent")
            continue
        files = contents(name)
        print(f"[info] '{name}' contains {len(files)} file(s): "
              f"{[f['name'] for f in files]}")
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

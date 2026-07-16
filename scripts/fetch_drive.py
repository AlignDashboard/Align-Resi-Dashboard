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
            fields="nextPageToken, files(id, name, mimeType)",
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
    manifest = []
    for entry in cfg["subfolders"]:
        name = entry["drive_folder"]
        if entry.get("status") != "active":
            print(f"[skip] '{name}' (no parser yet)")
            continue
        if name not in folders:
            print(f"[warn] subfolder '{name}' not found in Drive parent")
            continue
        files = [f for f in _list_children(svc, folders[name])
                 if f["mimeType"] != FOLDER_MIME]
        print(f"[info] '{name}' contains {len(files)} file(s): "
              f"{[f['name'] for f in files]}")
        for f in files:
            dest = DL_ROOT / entry["report_type"] / f["name"]
            _download(svc, f["id"], dest)
            manifest.append({"report_type": entry["report_type"],
                             "parser": entry["parser"],
                             "path": str(dest), "name": f["name"]})
            print(f"[ok] downloaded {name}/{f['name']}")

    json.dump(manifest, open("_downloads/manifest.json", "w"), indent=2)
    print(f"\n{len(manifest)} file(s) downloaded.")


if __name__ == "__main__":
    main()

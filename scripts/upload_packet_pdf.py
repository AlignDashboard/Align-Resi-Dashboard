#!/usr/bin/env python3
"""Put the rendered packet PDF in Drive, replacing the file already there.

Why a script and not a hand upload: the ask is a PDF that *stays* updated. A
Drive file whose content is replaced keeps its id, so the link handed to whoever
pulls the Yardi exports keeps working and always opens the current packet.
Uploading a new file each time would mint a new link every run, which is the
failure this avoids.

Needs two things beyond the pipeline's existing setup:

  1. GDRIVE_SA_KEY granted **Editor** on the destination folder. The fetch path
     asks for drive.readonly; this asks for drive.file, which only reaches
     files this service account itself created -- so it can maintain its own
     PDF and cannot touch a report.
  2. GDRIVE_PACKET_FOLDER_ID -- the destination. Kept in a secret like every
     other folder id, since this repo is public.

Absent either, it prints why and exits 0: a missing upload must not fail the
daily run that produced the metrics.
"""
import os
import sys

TITLE = "Landing (Drive) — report packet.pdf"
SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def main():
    pdf = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "build", "Landing-Drive-Packet.pdf")
    if not os.path.exists(pdf):
        sys.exit(f"FATAL: {pdf} not found — run scripts/publish_packet_pdf.py first")

    folder = os.environ.get("GDRIVE_PACKET_FOLDER_ID")
    key = os.environ.get("GDRIVE_SA_KEY")
    if not folder or not key:
        missing = [n for n, v in (("GDRIVE_PACKET_FOLDER_ID", folder),
                                  ("GDRIVE_SA_KEY", key)) if not v]
        print(f"[skip] {', '.join(missing)} not set — PDF not uploaded")
        return 0

    import json
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = service_account.Credentials.from_service_account_info(
        json.loads(key), scopes=SCOPES)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)

    # drive.file scope sees only what this account created, so this finds the
    # copy from the previous run and nothing else in the folder.
    q = (f"name = '{TITLE}' and '{folder}' in parents and trashed = false")
    found = drive.files().list(q=q, fields="files(id,name)",
                               supportsAllDrives=True,
                               includeItemsFromAllDrives=True).execute().get("files", [])

    media = MediaFileUpload(pdf, mimetype="application/pdf", resumable=False)
    if found:
        fid = found[0]["id"]
        drive.files().update(fileId=fid, media_body=media,
                             supportsAllDrives=True).execute()
        action = "replaced"
    else:
        fid = drive.files().create(
            body={"name": TITLE, "parents": [folder]},
            media_body=media, fields="id",
            supportsAllDrives=True).execute()["id"]
        action = "created"

    print(f"[ok] {action} {TITLE} — https://drive.google.com/file/d/{fid}/view")
    return 0


if __name__ == "__main__":
    sys.exit(main())

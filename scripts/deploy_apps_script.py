"""
deploy_apps_script.py
---------------------
Push scripts/gmail_drive_filing.js into the Apps Script project, by calling the
Apps Script REST API directly.

WHY NOT CLASP
  clasp is a wrapper around these two endpoints, and using it coupled the deploy
  to clasp's own CLI and on-disk credential format. Both bit us: `clasp pull
  --force` is not a valid flag, and a credential written by clasp 3.x (a
  {"default": {...}} profile store) is unreadable by clasp 2.4.2, which fails
  with "Cannot read properties of undefined (reading 'access_token')" and says
  nothing about why. Calling the API directly removes the version coupling, the
  npm install, and that whole class of surprise.

WHAT IT DOES
  1. Mints an access token from the refresh token in CLASPRC_JSON.
  2. GETs the project's current content.
  3. Replaces the source of the SERVER_JS file named CODE_FILE, leaving the
     manifest and every other file exactly as they are.
  4. PUTs the result back.

WHAT IT DELIBERATELY DOES NOT DO
  - It never writes the manifest. appsscript.json carries the timezone, runtime
    version and advanced services; it is read from the project and sent back
    byte for byte. A project with no manifest aborts rather than inventing one.
  - It never deletes a file. An unexpected extra file in the project is left
    alone, not tidied away.
  - It does not run previewRouting / checkFolders / resortExistingFiles. Those
    need the script's own Gmail and Drive scopes, a far larger grant than
    updating code, and reading the dry-run log before files move is the point.

Env:
  CLASPRC_JSON    contents of ~/.clasprc.json (any clasp version's layout)
  APPS_SCRIPT_ID  the Apps Script project id

Usage:
  python scripts/deploy_apps_script.py [--dry-run]
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://script.googleapis.com/v1/projects/{}/content"

SOURCE_FILE = "scripts/gmail_drive_filing.js"
CODE_FILE = "Code"          # the project's existing SERVER_JS file
MANIFEST = "appsscript"     # the project's JSON manifest


def find_credentials(raw):
    """
    Pull client_id / client_secret / refresh_token out of a clasp credential,
    whichever layout wrote it. clasp has used at least three:

      flat        {"access_token": ..., "refresh_token": ..., "clientId": ...}
      2.4.x       {"token": {...}, "oauth2ClientSettings": {"clientId": ...}}
      3.x profile {"default": {"client_id": ..., "refresh_token": ..., ...}}

    Rather than branch on version, walk the whole object and take the first of
    each field we recognise under any of its spellings.
    """
    try:
        blob = json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.exit(f"CLASPRC_JSON is not valid JSON — the copy was truncated or "
                 f"line-broken on the way into the secret: {exc}")

    wanted = {
        "client_id":     ("client_id", "clientId"),
        "client_secret": ("client_secret", "clientSecret"),
        "refresh_token": ("refresh_token", "refreshToken"),
    }
    found = {}

    def walk(node):
        if not isinstance(node, dict):
            return
        for field, spellings in wanted.items():
            if field in found:
                continue
            for spelling in spellings:
                value = node.get(spelling)
                if isinstance(value, str) and value:
                    found[field] = value
                    break
        for value in node.values():
            walk(value)

    walk(blob)

    missing = [f for f in wanted if f not in found]
    if missing:
        sys.exit(f"CLASPRC_JSON parsed, but these fields are nowhere in it: "
                 f"{', '.join(missing)}. Top-level keys were: "
                 f"{', '.join(blob) if isinstance(blob, dict) else type(blob).__name__}")
    return found


def _request(url, *, method="GET", token=None, data=None, form=None):
    if form is not None:
        body, ctype = urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded"
    elif data is not None:
        body, ctype = json.dumps(data).encode(), "application/json"
    else:
        body, ctype = None, None
    req = urllib.request.Request(url, data=body, method=method)
    if ctype:
        req.add_header("Content-Type", ctype)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:600]
        sys.exit(f"{method} {url.split('?')[0]} failed: HTTP {exc.code}\n{detail}")


def access_token(creds):
    got = _request(TOKEN_URL, method="POST", form={
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "refresh_token": creds["refresh_token"],
        "grant_type": "refresh_token",
    })
    if "access_token" not in got:
        sys.exit("the refresh token did not yield an access token")
    return got["access_token"]


def main():
    dry_run = "--dry-run" in sys.argv
    raw = os.environ.get("CLASPRC_JSON", "")
    script_id = os.environ.get("APPS_SCRIPT_ID", "")
    if not raw or not script_id:
        sys.exit("CLASPRC_JSON and APPS_SCRIPT_ID must both be set")

    source = open(SOURCE_FILE).read()
    creds = find_credentials(raw)
    print(f"[ok] credential carries client_id, client_secret and refresh_token")

    token = access_token(creds)
    print("[ok] minted an access token from the refresh token")

    url = API.format(script_id)
    content = _request(url, token=token)
    files = content.get("files", [])
    print(f"[info] project has {len(files)} file(s): "
          f"{[(f['name'], f['type']) for f in files]}")

    if not any(f["name"] == MANIFEST for f in files):
        sys.exit(f"the project has no {MANIFEST}.json manifest — refusing to push, "
                 f"because sending content without one would rewrite how the "
                 f"script runs")

    replaced = False
    for f in files:
        if f["name"] == CODE_FILE and f["type"] == "SERVER_JS":
            if f["source"] == source:
                print(f"[ok] {CODE_FILE} already matches the repo — nothing to push")
                return 0
            f["source"] = source
            replaced = True
    if not replaced:
        files.append({"name": CODE_FILE, "type": "SERVER_JS", "source": source})
        print(f"[info] {CODE_FILE} did not exist; adding it")

    print(f"[info] {len(source.splitlines())} lines of {SOURCE_FILE} -> "
          f"{CODE_FILE}.gs; manifest and all other files untouched")
    if dry_run:
        print("[dry-run] nothing was sent")
        return 0

    _request(url, method="PUT", token=token, data={"files": files})
    print("[ok] pushed. Run previewRouting and checkFolders in the editor "
          "before resortExistingFiles.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

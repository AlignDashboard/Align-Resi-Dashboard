"""
Guard tests for deploy_apps_script.py.

No network and no credentials: the HTTP layer is stubbed, so these check the
two things that can silently do damage —

  - reading the credential out of whichever layout clasp wrote it in, and
    failing loudly rather than half-working when a field is missing;
  - what actually gets PUT: the manifest must come back byte for byte, other
    files must survive, and only Code.gs may change.

Run: python scripts/test_deploy_apps_script.py
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import deploy_apps_script as dep                                  # noqa: E402

CHECKS = []


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(f"   {'PASS' if cond else 'FAIL'} {label}")


MANIFEST_SRC = '{\n  "timeZone": "America/Los_Angeles",\n  "runtimeVersion": "V8"\n}'

LAYOUTS = {
    "flat (legacy)": {
        "access_token": "a", "refresh_token": "R",
        "clientId": "CID", "clientSecret": "CSEC"},
    "clasp 2.4.x": {
        "token": {"access_token": "a", "refresh_token": "R"},
        "oauth2ClientSettings": {"clientId": "CID", "clientSecret": "CSEC"}},
    "clasp 3.x profile": {
        "default": {"client_id": "CID", "client_secret": "CSEC",
                    "type": "authorized_user", "refresh_token": "R"}},
}


def run_deploy(files, *, argv=("deploy",), source=None):
    """Run main() against a stubbed API; return (calls, exit_code)."""
    calls = []

    def fake_request(url, *, method="GET", token=None, data=None, form=None):
        calls.append({"url": url, "method": method, "data": data, "form": form})
        if url == dep.TOKEN_URL:
            return {"access_token": "ACCESS"}
        if method == "GET":
            return {"files": json.loads(json.dumps(files))}   # deep copy
        return {}

    import tempfile
    real_request, real_source, old_argv = dep._request, dep.SOURCE_FILE, sys.argv
    dep._request = fake_request
    tmp = None
    if source is not None:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False)
        tmp.write(source)
        tmp.close()
        dep.SOURCE_FILE = tmp.name          # exercise the real file read
    sys.argv = list(argv)
    try:
        code = dep.main()
    except SystemExit as exc:
        code = exc.code
    finally:
        dep._request, dep.SOURCE_FILE, sys.argv = real_request, real_source, old_argv
        if tmp:
            pathlib.Path(tmp.name).unlink(missing_ok=True)
    return calls, code


def main():
    import os
    os.chdir(ROOT)
    os.environ["APPS_SCRIPT_ID"] = "SCRIPT_ID"

    print("1. the credential is read out of every layout clasp has written")
    for label, blob in LAYOUTS.items():
        got = dep.find_credentials(json.dumps(blob))
        check(f"{label}: all three fields recovered",
              got == {"client_id": "CID", "client_secret": "CSEC", "refresh_token": "R"})

    print("\n2. a credential that cannot work fails loudly")
    for label, blob in {
        "no refresh_token": {"default": {"client_id": "C", "client_secret": "S"}},
        "no client_secret": {"default": {"client_id": "C", "refresh_token": "R"}},
    }.items():
        try:
            dep.find_credentials(json.dumps(blob))
            check(f"{label}: refused", False)
        except SystemExit as exc:
            check(f"{label}: refused, naming the missing field",
                  "refresh_token" in str(exc) or "client_secret" in str(exc))
    try:
        dep.find_credentials('{"default": {"client_id": "trunc')
        check("truncated JSON: refused", False)
    except SystemExit as exc:
        check("truncated JSON: refused, blaming the copy", "truncated" in str(exc))

    print("\n3. what actually gets sent")
    os.environ["CLASPRC_JSON"] = json.dumps(LAYOUTS["clasp 3.x profile"])
    project = [
        {"name": "appsscript", "type": "JSON", "source": MANIFEST_SRC},
        {"name": "Code", "type": "SERVER_JS", "source": "// the old deployed code"},
        {"name": "Helpers", "type": "SERVER_JS", "source": "// someone else's file"},
        {"name": "Page", "type": "HTML", "source": "<p>hi</p>"},
    ]
    calls, code = run_deploy(project, source="// NEW SOURCE")
    put = next((c for c in calls if c["method"] == "PUT"), None)
    check("exit code 0", code == 0)
    check("a PUT was made", put is not None)
    sent = {f["name"]: f for f in (put or {"data": {"files": []}})["data"]["files"]}
    check("Code.gs carries the repo's source", sent.get("Code", {}).get("source") == "// NEW SOURCE")
    check("the manifest is returned byte for byte",
          sent.get("appsscript", {}).get("source") == MANIFEST_SRC)
    check("another author's SERVER_JS file survives untouched",
          sent.get("Helpers", {}).get("source") == "// someone else's file")
    check("the HTML file survives untouched", sent.get("Page", {}).get("source") == "<p>hi</p>")
    check("no file was dropped", len(sent) == 4)

    print("\n4. refusals and no-ops")
    calls, code = run_deploy(
        [{"name": "Code", "type": "SERVER_JS", "source": "x"}], source="// NEW")
    check("a project with no manifest is refused", code != 0
          and not any(c["method"] == "PUT" for c in calls))

    calls, code = run_deploy(project, source="// the old deployed code")
    check("an unchanged script sends no PUT",
          code == 0 and not any(c["method"] == "PUT" for c in calls))

    calls, code = run_deploy(project, argv=("deploy", "--dry-run"), source="// NEW")
    check("--dry-run sends no PUT",
          code == 0 and not any(c["method"] == "PUT" for c in calls))

    calls, code = run_deploy(
        [{"name": "appsscript", "type": "JSON", "source": MANIFEST_SRC}], source="// NEW")
    put = next((c for c in calls if c["method"] == "PUT"), None)
    names = {f["name"] for f in (put or {"data": {"files": []}})["data"]["files"]}
    check("a project with no Code file gets one added", code == 0 and names == {"appsscript", "Code"})

    failed = [label for label, ok in CHECKS if not ok]
    print()
    if failed:
        print(f"FAIL: {len(failed)} of {len(CHECKS)} check(s)")
        for label in failed:
            print(f"  - {label}")
        return 1
    print(f"PASS: {len(CHECKS)} checks — the credential is read from any clasp "
          f"layout, and only Code.gs is ever rewritten.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

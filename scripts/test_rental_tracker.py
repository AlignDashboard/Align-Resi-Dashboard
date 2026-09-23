"""
test_rental_tracker.py
----------------------
Checks for scripts/import_rental_tracker.py, which copies the Rental Rate
Tracker's lease data onto the Rental Rates tab -- decrypted from the tracker's
page, cut down to a whitelist, and re-encrypted with the same password.

Fixture-free: every tracker page is built and encrypted here, in a temp dir,
with a throwaway password, so nothing needs the real tracker, its password or
the network. **Every figure in `data()` is invented** -- this file is public and
the tracker's data is not -- and internally consistent, so the arithmetic checks
have something true to check. Keep it that way: never paste a real row in.

The checks that matter are the invisible failures:

  * a renewal note naming a resident reaching the tab's file. The real tracker
    carries exactly that, and the file is encrypted, so no one would ever see
    it happen -- the whitelist is the only thing in the way, and it is checked
    by decrypting what was written, not by grepping ciphertext.
  * a new upstream field passing through because nobody listed it. Unknown
    fields are dropped and counted, never carried.
  * text in a field that should hold a label -- a name typed into the unit
    column -- which the per-field pattern refuses, without echoing the value.
  * a malformed import replacing the last good file. A refusal writes nothing.
  * the same data re-encrypted on every run: a fresh salt and IV would commit
    a new ciphertext daily with nothing changed.

Run: python scripts/test_rental_tracker.py
"""
import base64
import contextlib
import hashlib
import io
import json
import os
import pathlib
import secrets
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import import_rental_tracker as t  # noqa: E402

PASS, FAIL = [], []
PW = "correct horse battery staple"
NAME = "Jane Placeholder"          # the resident a note names; must never reach the tab


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))


def data():
    return {
        "snapshot": "2026-09-23",
        "leases": [
            {"date": "2026-05-10", "property": "The Landing", "unit": "101", "sqft": 1000,
             "grossRent": 5000.0, "grossPsf": 5.0, "netRent": 5000.0, "netPsf": 5.0,
             "prior": 4000.0, "toPct": 25.0, "toDollars": 1000.0, "term": "12"},
            {"date": "2026-06-05", "property": "Brand New", "unit": "042", "sqft": 600,
             "grossRent": 3000.0, "grossPsf": 5.0, "netRent": 3000.0, "netPsf": 5.0,
             "prior": 2500.0, "toPct": 20.0, "toDollars": 500.0, "term": None},
        ],
        "renewals": [
            {"date": "2026-05-02", "property": "The Landing", "unit": "201", "sqft": 800,
             "oldRate": 4000.0, "newRate": 4400.0, "incPct": 10.0,
             "note": f"corrected per tracker (tenant {NAME}), confirmed by staff"},
            {"date": "2026-06-01", "property": "The Landing", "unit": "202", "sqft": None,
             "oldRate": 4000.0, "newRate": 4200.0, "incPct": 5.0, "note": ""},
        ],
        "weekly": [
            {"week": "5/25–5/31", "ws": "2026-05-25", "we": "2026-05-31",
             "property": "The Landing", "leases": 2, "avgTo": None, "avgRenewal": None,
             "occ": 90.0, "leased": 95.0},
        ],
        "mtm": {"The Landing": {"asOf": "2026-09-21", "units": 10, "occupied": 100, "pct": 10.0,
                                "method": "flag", "graceDays": None,
                                "note": f"oldest holdover {NAME}"}},
    }


def page(d, password=PW, extra_app=True):
    """A tracker page the way the tracker publishes one: the app encrypted in ENC."""
    app = ('<html><h1>Rental Rate Tracker</h1><div class="sub">Both buildings &amp; their '
           'units from <b>the property system</b>.</div><script>const DATA=' + json.dumps(d) + ';'
           + ('const props=["The Landing","Chorus"];const OCC={"Chorus":{occ:80.0,leased:85.0}};'
              if extra_app else '') + '</script></html>')
    salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 1000, 32)
    enc, _ = t._gcm()
    ct = enc(key, iv, app.encode("utf-8"))
    b = lambda x: base64.b64encode(x).decode()
    return ('<html><body><div id="gate"></div><script>const ENC = '
            + json.dumps({"salt": b(salt), "iv": b(iv), "ct": b(ct), "iter": 1000})
            + ';</script></body></html>')


def run(tmp, d, *, password=PW, argv_extra=(), extra_app=True, name="index.html"):
    src = tmp / name
    src.write_text(page(d, extra_app=extra_app), encoding="utf-8")
    out = tmp / "rental_tracker.enc.json"
    old = os.environ.get(t.PASSWORD_ENV)
    os.environ[t.PASSWORD_ENV] = password
    try:
        code = t.main([str(src), "--out", str(out), "--iterations", "1000", *argv_extra])
    finally:
        if old is None:
            os.environ.pop(t.PASSWORD_ENV, None)
        else:
            os.environ[t.PASSWORD_ENV] = old
    return code, out


def opened(out):
    return t.decrypt_envelope(json.loads(out.read_text()), PW)


def main():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="rt-test-"))
    try:
        print("round trip")
        code, out = run(tmp, data())
        check("a valid page imports", code == 0 and out.exists(), f"exit {code}")
        p = opened(out)
        check("both leases arrive", len(p["leases"]) == 2)
        check("the file decrypts to the tracker's own figures",
              p["leases"][0]["netRent"] == 5000.0 and p["leases"][0]["toPct"] == 25.0)
        env = json.loads(out.read_text())
        check("the envelope carries what the page reads",
              all(k in env for k in ("format", "kdf", "iterations", "salt", "iv", "ct",
                                     "snapshot", "counts")) and env["format"] == t.FORMAT)
        check("a 16-byte salt and a 12-byte IV",
              len(base64.b64decode(env["salt"])) == 16 and len(base64.b64decode(env["iv"])) == 12)
        check("counts and snapshot are the only lease facts in the clear",
              # three properties: the tracker lists Chorus, which has no rows yet
              env["counts"] == {"leases": 2, "renewals": 2, "weekly": 1, "properties": 3}
              and env["snapshot"] == "2026-09-23")
        check("the password is nowhere in the file", PW not in out.read_text())

        print("\nwhat never passes")
        blob = json.dumps(p)
        check("a renewal note naming a resident is not in the decrypted file", NAME not in blob)
        check("no note key survives anywhere", '"note"' not in blob)
        check("the month-to-month note is dropped too", "note" not in p["mtm"]["The Landing"])
        rep = t.clean(t.decrypt_page(page(data()), PW))[1]
        check("the drop is reported with counts, not contents",
              rep["dropped"].get("renewals.note") == {"rows": 2, "non_empty": 1}
              and NAME not in json.dumps(rep))
        d = data()
        d["leases"][0]["residentName"] = NAME
        d["weekly"][0]["comment"] = "call back " + NAME
        code, out = run(tmp, d)
        blob = json.dumps(opened(out))
        check("an unknown field is dropped, not carried", code == 0 and NAME not in blob
              and "residentName" not in blob and "comment" not in blob)

        print("\nwhat is refused")
        good = out.read_bytes()
        for label, mutate in [
            ("a name typed into the unit column", lambda d: d["leases"][0].update(unit="Smith, John")),
            ("a malformed date", lambda d: d["leases"][0].update(date="5/10/2026")),
            ("an impossible date", lambda d: d["leases"][0].update(date="2026-02-30")),
            ("a number sent as text", lambda d: d["leases"][0].update(sqft="984")),
            ("a boolean where a number goes", lambda d: d["renewals"][0].update(incPct=True)),
            ("a property name that is prose", lambda d: d["leases"][0].update(
                property="The Landing (tenant disputes the rent)")),
            ("no leases at all", lambda d: d.update(leases=[])),
            ("a week that ends before it starts", lambda d: d["weekly"][0].update(ws="2026-06-05")),
        ]:
            d = data()
            mutate(d)
            code, _ = run(tmp, d)
            check("refused: " + label, code == 1 and out.read_bytes() == good,
                  f"exit {code}; file {'untouched' if out.read_bytes() == good else 'CHANGED'}")
        rep = t.clean(t.decrypt_page(page(dict(data(), leases=[dict(data()["leases"][0],
                                                                    unit="Smith, John")])), PW))[1]
        check("a refused value is never echoed in the report", "Smith" not in json.dumps(rep))
        code, _ = run(tmp, data(), password="wrong password")
        check("a wrong password stops before anything is written",
              code == 2 and out.read_bytes() == good)

        print("\nwrites only when something changed")
        code, out = run(tmp, data())
        before = out.read_bytes()
        code, _ = run(tmp, data())
        check("the same data leaves the file byte for byte", code == 0 and out.read_bytes() == before)
        d = data()
        d["leases"][0]["netRent"] = 5100.0
        code, _ = run(tmp, d)
        after = json.loads(out.read_text())
        check("changed data is re-encrypted under a fresh salt",
              code == 0 and after["salt"] != json.loads(before)["salt"]
              and opened(out)["leases"][0]["netRent"] == 5100.0)
        snap = out.read_bytes()
        code, _ = run(tmp, data(), argv_extra=("--dry-run",))
        check("a dry run writes nothing", code == 0 and out.read_bytes() == snap)

        print("\nwhat else comes across")
        code, out = run(tmp, data())
        p = opened(out)
        check("the tracker's property order, then a building it has not listed",
              p["properties"] == ["The Landing", "Chorus", "Brand New"], str(p["properties"]))
        check("the tracker's stated occupancy is kept",
              p["occ_stated"] == {"Chorus": {"occ": 80.0, "leased": 85.0}})
        check("the sources line arrives as plain text",
              p["about"] == "Both buildings & their units from the property system.", repr(p["about"]))
        check("a unit number keeps its leading zero", p["leases"][1]["unit"] == "042")
        check("a null term stays null", p["leases"][1]["term"] is None)
        d = data()
        code, out = run(tmp, d, extra_app=False, name="lease_detail.html")
        p = opened(out)
        check("lease_detail.html imports too, with no stated occupancy",
              code == 0 and p["occ_stated"] == {} and p["properties"][0] == "The Landing")
        # The scheduled refresh logs to a PUBLIC Actions page, so its quiet mode
        # must say no more than the file's own plaintext: totals and a date.
        loud, quiet = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(loud):
            run(tmp, data(), argv_extra=("--dry-run",))
        with contextlib.redirect_stdout(quiet):
            run(tmp, data(), argv_extra=("--dry-run", "--quiet"))
        check("--quiet names no building and no date span, where the normal log does",
              "Brand New" in loud.getvalue() and "2026-05-10 .." in loud.getvalue()
              and not any(x in quiet.getvalue() for x in ("Brand New", "The Landing", "Chorus", " .. "))
              and "2 leases" in quiet.getvalue(), quiet.getvalue())
        about = t._about('<div class="sub">write to someone@example.com</div>')
        check("a sources line carrying an email address is refused", about is None)
        d = data()
        d["leases"][0]["toPct"] = 99.0
        rep = t.clean(t.decrypt_page(page(d), PW))[1]
        check("a trade-out neither rent reproduces is flagged",
              any("trade-out" in w for w in rep["warnings"]), str(rep["warnings"]))
        rep = t.clean(t.decrypt_page(page(data()), PW))[1]
        check("consistent rows raise no arithmetic warning", not rep["warnings"], str(rep["warnings"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Bring the Rental Rate Tracker's lease data onto the Rental Rates tab -- encrypted.

The tracker (github.com/dbalduc/rental-rates) publishes its pages as ciphertext
that decrypts in the browser once a password is entered: PBKDF2-SHA256 into an
AES-256-GCM key, the WebCrypto layout of ciphertext followed by a 16-byte tag.
Its owner chose to keep the numbers unreadable to anyone without that password,
and this dashboard's own data is readable by anyone with the URL -- so the copy
kept here is encrypted the same way, with the same password, and the tab
decrypts it in the page (owner's call, 2026-09-23).

What this does:

  1. decrypts a tracker page -- index.html or lease_detail.html, which carry the
     same dataset; index.html also carries the tracker's stated occupancy for a
     building with no weekly report, so it is the one to pass;
  2. keeps only the fields the tab draws, each one validated against the shape
     it must have. FREE TEXT NEVER PASSES: the tracker's renewal notes name
     residents, and an unknown field is dropped and reported rather than
     carried, so a note column added upstream tomorrow cannot reach this repo;
  3. re-encrypts the result and writes docs/rental_tracker.enc.json, then reads
     it back and decrypts it to prove the page will be able to.

The password is read from RENTAL_TRACKER_PASSWORD and never written anywhere.
Nothing readable reaches the repo, which is why the output lives in main with
the site shell rather than on the data branch: ciphertext is safe in history.

Usage:
  RENTAL_TRACKER_PASSWORD=... python scripts/import_rental_tracker.py <tracker page | clone dir>
      [--out docs/rental_tracker.enc.json] [--dry-run]

Exit codes: 0 written or unchanged, 1 refused (the data failed validation, and
the live file keeps its last good copy), 2 cannot run (usage, password, crypto).
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import html
import json
import math
import os
import pathlib
import re
import secrets
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "docs" / "rental_tracker.enc.json"
PASSWORD_ENV = "RENTAL_TRACKER_PASSWORD"
FORMAT = "align-rental-tracker/1"
# OWASP's 2023 figure for PBKDF2-HMAC-SHA256. The tracker itself uses 200,000,
# so this copy is never the weaker lock on the same password. The page reads
# the count from the file, so changing it here needs no change there.
ITERATIONS = 600_000

# ---------------------------------------------------------------------------
# AES-256-GCM, from whichever library is installed. Neither is in
# requirements.txt: this runs by hand, and the daily cron never needs it.
# ---------------------------------------------------------------------------

def _gcm():
    try:
        from Crypto.Cipher import AES  # pycryptodome

        def enc(key, iv, pt):
            c = AES.new(key, AES.MODE_GCM, nonce=iv)
            body, tag = c.encrypt_and_digest(pt)
            return body + tag

        def dec(key, iv, data):
            if len(data) < 16:
                raise ValueError("ciphertext shorter than its tag")
            c = AES.new(key, AES.MODE_GCM, nonce=iv)
            return c.decrypt_and_verify(data[:-16], data[-16:])

        return enc, dec
    except ImportError:
        pass
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        return (lambda key, iv, pt: AESGCM(key).encrypt(iv, pt, None),
                lambda key, iv, data: AESGCM(key).decrypt(iv, data, None))
    except BaseException as e:  # a broken wheel can raise a pyo3 panic, not ImportError
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
    sys.exit("error: AES-GCM needs `pip install pycryptodome` (or `cryptography`)")


class WrongPassword(Exception):
    """The ciphertext did not authenticate under this password."""


def _key(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, 32)


def _b64d(s: str) -> bytes:
    return base64.b64decode(re.sub(r"\s+", "", s))


def _b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


# ---------------------------------------------------------------------------
# reading the tracker
# ---------------------------------------------------------------------------

def _literal(text: str, name: str):
    """The JSON literal assigned to `const <name> =`, by brace matching.

    A regex cannot find the end of a nested object; this walks it, skipping
    over string contents so a brace inside a string cannot end it early.
    """
    m = re.search(r"const\s+" + re.escape(name) + r"\s*=\s*", text)
    if not m:
        return None
    i = m.end()
    if i >= len(text) or text[i] not in "{[":
        return None
    depth, quote, esc = 0, None, False
    for j in range(i, len(text)):
        c = text[j]
        if quote:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == quote:
                quote = None
            continue
        if c in "\"'`":
            quote = c
        elif c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
    return None


def decrypt_page(page_html: str, password: str) -> str:
    """The tracker page's own plaintext, authenticated."""
    raw = _literal(page_html, "ENC")
    if raw is None:
        raise ValueError("no `const ENC = {...}` in this file -- is it a tracker page?")
    enc = json.loads(raw)
    missing = {"salt", "iv", "ct", "iter"} - set(enc)
    if missing:
        raise ValueError(f"the tracker's ENC object is missing {sorted(missing)}")
    _, dec = _gcm()
    key = _key(password, _b64d(enc["salt"]), int(enc["iter"]))
    try:
        return dec(key, _b64d(enc["iv"]), _b64d(enc["ct"])).decode("utf-8")
    except (ValueError, KeyError) as e:
        raise WrongPassword(str(e)) from None
    except Exception as e:  # cryptography raises InvalidTag, which is not a ValueError
        if type(e).__name__ == "InvalidTag":
            raise WrongPassword("authentication failed") from None
        raise


# ---------------------------------------------------------------------------
# the whitelist
# ---------------------------------------------------------------------------

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PROPERTY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .'&-]{1,39}$")
UNIT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ./#-]{0,11}$")
TERM = re.compile(r"^\d{1,2}$")
WEEK = re.compile(r"^\d{1,2}/\d{1,2}\s*[–-]\s*\d{1,2}/\d{1,2}$")
METHOD = re.compile(r"^[a-z]{2,12}$")

# field -> kind. A trailing "?" means null is allowed. Anything not named here
# is dropped -- including every note -- and counted in the report.
LEASE = {"date": "date", "property": "property", "unit": "unit?", "sqft": "num?",
         "grossRent": "num?", "grossPsf": "num?", "netRent": "num?", "netPsf": "num?",
         "prior": "num?", "toPct": "num?", "toDollars": "num?", "term": "term?"}
RENEWAL = {"date": "date", "property": "property", "unit": "unit?", "sqft": "num?",
           "oldRate": "num?", "newRate": "num?", "incPct": "num?"}
WEEKLY = {"week": "week", "ws": "date", "we": "date", "property": "property",
          "leases": "num?", "avgTo": "num?", "avgRenewal": "num?", "occ": "num?",
          "leased": "num?"}
MTM = {"asOf": "date", "units": "num?", "occupied": "num?", "pct": "num?",
       "method": "method", "graceDays": "num?"}


def _value(kind: str, v):
    """(ok, cleaned) for one value against its kind."""
    optional = kind.endswith("?")
    kind = kind.rstrip("?")
    if v is None or (isinstance(v, str) and v.strip() == "" and optional):
        return optional, None
    if kind == "num":
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            return False, v
        return True, v
    if kind in ("unit", "term") and isinstance(v, int) and not isinstance(v, bool):
        v = str(v)                       # a unit number is a label, not a quantity
    if not isinstance(v, str):
        return False, v
    v = v.strip()
    if kind == "date":
        if not ISO.match(v):
            return False, v
        try:
            dt.date.fromisoformat(v)
        except ValueError:
            return False, v
        return True, v
    pattern = {"property": PROPERTY, "unit": UNIT, "term": TERM, "week": WEEK,
               "method": METHOD}[kind]
    return (bool(pattern.match(v)), v)


def _rows(rows, spec, where, report):
    out = []
    if not isinstance(rows, list):
        report["problems"].append(f"{where}: expected a list, found {type(rows).__name__}")
        return out
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            report["problems"].append(f"{where}[{i}]: not an object")
            continue
        clean = {}
        for k, v in row.items():
            if k not in spec:
                d = report["dropped"].setdefault(f"{where}.{k}", {"rows": 0, "non_empty": 0})
                d["rows"] += 1
                d["non_empty"] += bool(v not in (None, "") and str(v).strip())
                continue
            ok, cv = _value(spec[k], v)
            if not ok:
                # the value itself is never echoed: a field that fails its
                # pattern is exactly the one that might be carrying text
                report["problems"].append(
                    f"{where}[{i}].{k}: not a valid {spec[k].rstrip('?')}")
                continue
            clean[k] = cv
        for k, kind in spec.items():
            if k not in row and not kind.endswith("?"):
                report["problems"].append(f"{where}[{i}]: missing {k}")
        out.append(clean)
    return out


def _occ_stated(app: str, report):
    """The tracker's hand-typed occupancy for a building with no weekly report.

    `const OCC={"Ansel":{occ:96.3,leased:98.1}}` -- unquoted keys, so not JSON.
    Kept so the two dashboards agree, and labelled on the page as the tracker's
    own figure with no date behind it.
    """
    m = re.search(r"const\s+OCC\s*=\s*\{(.*?)\}\s*;", app, re.S)
    if not m:
        return {}
    out = {}
    for name, occ, leased in re.findall(
            r'"([^"]+)"\s*:\s*\{\s*occ\s*:\s*([\d.]+)\s*,\s*leased\s*:\s*([\d.]+)\s*\}',
            m.group(1)):
        if PROPERTY.match(name) and 0 <= float(occ) <= 100 and 0 <= float(leased) <= 100:
            out[name] = {"occ": float(occ), "leased": float(leased)}
        else:
            report["warnings"].append("an OCC entry did not look like a property's occupancy; skipped")
    return out


def _property_order(app: str, data_props):
    """The tracker's own display order, then anything new it has not listed."""
    raw = _literal(app, "props")
    order = []
    try:
        order = [p for p in json.loads(raw) if isinstance(p, str) and PROPERTY.match(p)] if raw else []
    except json.JSONDecodeError:
        order = []
    return order + [p for p in data_props if p not in order]


def _about(page_html: str):
    """The tracker's subtitle: which system each building's numbers come from.

    The one piece of prose that passes, because it is the tracker author's own
    description of sources rather than anything about a lease or a resident --
    and it keeps the tab's sourcing line current if the tracker changes one.
    Guarded anyway: an email or phone shape refuses it.
    """
    m = re.search(r'<div class="sub">(.*?)</div>', page_html, re.S)
    if not m:
        return None
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", m.group(1)))).strip()
    if not text or len(text) > 800 or re.search(r"@|\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b", text):
        return None
    return text


def _arithmetic(leases, renewals, report):
    """Check each row against its own numbers, the way every parser here does.

    The tracker publishes no totals to tie out against, so the check is the
    arithmetic each row carries: a trade-out must be one of the lease's two
    rents over its prior, a renewal's increase its new rate over its old, and a
    $/sqft its rent over its footage. Warnings, not refusals -- the tracker
    corrects source errors by hand and says so in notes this import drops.
    """
    off = 0
    for r in leases:
        p, to = r.get("prior"), r.get("toPct")
        if p and to is not None:
            cands = [(x / p - 1) * 100 for x in (r.get("netRent"), r.get("grossRent")) if x]
            if cands and min(abs(c - to) for c in cands) > 0.6:
                off += 1
    if off:
        report["warnings"].append(
            f"{off} lease(s) carry a trade-out % that neither rent reproduces over the prior")
    off = sum(1 for r in renewals
              if r.get("oldRate") and r.get("newRate") and r.get("incPct") is not None
              and abs((r["newRate"] / r["oldRate"] - 1) * 100 - r["incPct"]) > 0.6)
    if off:
        report["warnings"].append(
            f"{off} renewal(s) carry an increase % their two rates do not reproduce")
    off = sum(1 for r in leases for rent, psf in (("netRent", "netPsf"), ("grossRent", "grossPsf"))
              if r.get(rent) and r.get("sqft") and r.get(psf) is not None
              and abs(r[rent] / r["sqft"] - r[psf]) > 0.02)
    if off:
        report["warnings"].append(f"{off} $/sqft figure(s) disagree with rent over sqft")


def clean(plaintext: str):
    """(payload, report) from the decrypted page. payload is None when refused."""
    report = {"problems": [], "warnings": [], "dropped": {}}
    raw = _literal(plaintext, "DATA")
    if raw is None:
        report["problems"].append("no `const DATA = {...}` inside the decrypted page")
        return None, report
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        report["problems"].append(f"DATA is not JSON: {e.msg} at {e.pos}")
        return None, report
    if not isinstance(data, dict):
        report["problems"].append("DATA is not an object")
        return None, report

    for k in data:
        if k not in ("snapshot", "leases", "renewals", "weekly", "mtm"):
            report["dropped"][f"DATA.{k}"] = {"rows": 1, "non_empty": 1}
    ok, snapshot = _value("date", data.get("snapshot"))
    if not ok:
        report["problems"].append("DATA.snapshot is not a date")

    leases = _rows(data.get("leases"), LEASE, "leases", report)
    renewals = _rows(data.get("renewals"), RENEWAL, "renewals", report)
    weekly = _rows(data.get("weekly"), WEEKLY, "weekly", report)
    mtm = {}
    raw_mtm = data.get("mtm") or {}
    if not isinstance(raw_mtm, dict):
        report["problems"].append("DATA.mtm is not an object")
        raw_mtm = {}
    for name, row in raw_mtm.items():
        if not PROPERTY.match(str(name)):
            report["problems"].append("mtm: a key is not a property name")
            continue
        got = _rows([row], MTM, f"mtm[{name}]", report)
        if got:
            mtm[name] = got[0]
    # fold the per-property mtm drop counts into one line
    for key in [k for k in report["dropped"] if k.startswith("mtm[")]:
        d = report["dropped"].pop(key)
        agg = report["dropped"].setdefault("mtm." + key.rsplit(".", 1)[1],
                                           {"rows": 0, "non_empty": 0})
        agg["rows"] += d["rows"]
        agg["non_empty"] += d["non_empty"]

    for w in weekly:
        if w.get("ws") and w.get("we") and w["ws"] > w["we"]:
            report["problems"].append(f"weekly: a week starts after it ends ({w['ws']} > {w['we']})")
    if not leases:
        report["problems"].append("no leases -- refusing to replace the tab with an empty one")
    if report["problems"]:
        return None, report

    _arithmetic(leases, renewals, report)
    seen = []
    for r in leases + renewals + weekly:
        if r["property"] not in seen:
            seen.append(r["property"])
    seen += [p for p in mtm if p not in seen]
    payload = {
        "snapshot": snapshot,
        "properties": _property_order(plaintext, seen),
        "leases": leases,
        "renewals": renewals,
        "weekly": weekly,
        "mtm": mtm,
        "occ_stated": _occ_stated(plaintext, report),
        "about": _about(plaintext),
    }
    return payload, report


# ---------------------------------------------------------------------------
# writing the tab's copy
# ---------------------------------------------------------------------------

def encrypt_payload(payload, password, iterations=ITERATIONS, source=None, now=None):
    enc, _ = _gcm()
    salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
    pt = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ct = enc(_key(password, salt, iterations), iv, pt)
    stamp = (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "format": FORMAT,
        "about_this_file": "An encrypted copy of the Rental Rate Tracker's lease data, "
                           "written by scripts/import_rental_tracker.py. The Rental Rates "
                           "tab decrypts it in the browser with the tracker's password; "
                           "nothing in it is readable without that password.",
        "kdf": "PBKDF2-SHA256",
        "iterations": iterations,
        "salt": _b64e(salt),
        "cipher": "AES-256-GCM",
        "iv": _b64e(iv),
        "ct": _b64e(ct),
        # In the clear on purpose: the tab says what it holds and how old it is
        # before it is unlocked, and the data-flow page reports the arrival.
        # Counts and a date, nothing about any lease.
        "snapshot": payload["snapshot"],
        "imported_at": stamp,
        "source": source,
        "counts": {"leases": len(payload["leases"]), "renewals": len(payload["renewals"]),
                   "weekly": len(payload["weekly"]), "properties": len(payload["properties"])},
    }


def decrypt_envelope(env, password):
    if env.get("format") != FORMAT:
        raise ValueError(f"not a {FORMAT} file")
    _, dec = _gcm()
    key = _key(password, _b64d(env["salt"]), int(env["iterations"]))
    try:
        return json.loads(dec(key, _b64d(env["iv"]), _b64d(env["ct"])).decode("utf-8"))
    except (ValueError, KeyError) as e:
        if isinstance(e, json.JSONDecodeError):
            raise
        raise WrongPassword(str(e)) from None
    except Exception as e:
        if type(e).__name__ == "InvalidTag":
            raise WrongPassword("authentication failed") from None
        raise


def _summary(payload, report):
    lines = []
    by = {}
    for kind in ("leases", "renewals", "weekly"):
        for r in payload[kind]:
            e = by.setdefault(r["property"], {"leases": 0, "renewals": 0, "weekly": 0, "dates": []})
            e[kind] += 1
            if kind == "leases":
                e["dates"].append(r["date"])
    lines.append(f"  {'property':16s} {'leases':>6s} {'renewals':>8s} {'weeks':>5s}  new leases")
    for p in payload["properties"]:
        e = by.get(p, {"leases": 0, "renewals": 0, "weekly": 0, "dates": []})
        span = f"{min(e['dates'])} .. {max(e['dates'])}" if e["dates"] else "--"
        lines.append(f"  {p:16s} {e['leases']:6d} {e['renewals']:8d} {e['weekly']:5d}  {span}")
    for k, d in sorted(report["dropped"].items()):
        lines.append(f"  dropped {k}: {d['rows']} row(s), {d['non_empty']} with content"
                     " -- never written")
    if payload.get("occ_stated"):
        lines.append("  kept the tracker's stated occupancy for: "
                     + ", ".join(sorted(payload["occ_stated"])))
    for w in report["warnings"]:
        lines.append("  warning: " + w)
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("source", help="a tracker page (index.html) or a clone of its repo")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--dry-run", action="store_true", help="validate and report; write nothing")
    ap.add_argument("--iterations", type=int, default=ITERATIONS, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)

    password = os.environ.get(PASSWORD_ENV)
    if not password:
        print(f"error: set {PASSWORD_ENV} to the tracker's password", file=sys.stderr)
        return 2
    src = pathlib.Path(a.source)
    if src.is_dir():
        src = src / "index.html"
    if not src.is_file():
        print(f"error: {src} is not a file", file=sys.stderr)
        return 2
    page = src.read_text(encoding="utf-8", errors="replace")
    try:
        plaintext = decrypt_page(page, password)
    except WrongPassword:
        print("error: the tracker page did not decrypt -- wrong password, or the file "
              "is incomplete", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"decrypted {src.name} -- authenticated, {len(plaintext):,} characters")

    payload, report = clean(plaintext)
    if payload is None:
        print("REFUSED -- nothing written; the live file keeps its last good copy:")
        for p in report["problems"][:25]:
            print("  " + p)
        if len(report["problems"]) > 25:
            print(f"  ... and {len(report['problems']) - 25} more")
        return 1
    print(f"snapshot {payload['snapshot']}: {len(payload['leases'])} leases, "
          f"{len(payload['renewals'])} renewals, {len(payload['weekly'])} weekly rows, "
          f"{len(payload['mtm'])} month-to-month counts")
    print(_summary(payload, report))
    if a.dry_run:
        print("dry run -- nothing written")
        return 0

    out = pathlib.Path(a.out)
    # Unchanged data leaves the file alone. A fresh salt and IV make every
    # encryption differ, so rewriting identical data would commit a new
    # ciphertext -- and a new "imported" time -- every time this runs.
    if out.exists():
        try:
            if decrypt_envelope(json.loads(out.read_text(encoding="utf-8")), password) == payload:
                print(f"unchanged -- {out.name} already holds this snapshot")
                return 0
        except (WrongPassword, ValueError, KeyError):
            pass                         # different password or format: replace it
    env = encrypt_payload(payload, password, a.iterations,
                          source="Rental Rate Tracker, github.com/dbalduc/rental-rates ("
                                 + src.name + ")")
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(env, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, out)
    if decrypt_envelope(json.loads(out.read_text(encoding="utf-8")), password) != payload:
        print("error: the written file did not decrypt back to what was written", file=sys.stderr)
        return 2
    print(f"wrote {out} -- {env['iterations']:,} PBKDF2 iterations, "
          f"{out.stat().st_size:,} bytes; read back and verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())

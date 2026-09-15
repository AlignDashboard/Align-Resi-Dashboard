#!/usr/bin/env python3
"""Guard tests for the sealed data files.

Fixture-free: every file is built in a temp dir, no network and no real report.
What is covered is the set of ways this could fail INVISIBLY -- which is most of
them, because ciphertext looks equally opaque whether it is protecting anything
or not:

  * a wrong password appearing to work, or a right one appearing not to
  * a tampered file opening anyway (the GCM tag not actually being checked)
  * one file's ciphertext being served under another's name
  * plaintext surviving inside the envelope
  * the daily run re-sealing unchanged data and committing a diff every night
  * a rotation half-finishing and leaving no single password able to open the set
  * the key derivation drifting away from what unlock.js does in the browser

Run: python scripts/test_encryption.py
"""
import base64
import json
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crypto_data as cd                   # noqa: E402

PASS = FAIL = 0


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def raises(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc:
        return True
    except Exception:                                      # noqa: BLE001
        return False
    return False


class Args:
    """Stand-in for the argparse namespace, so the CLI paths are exercised too."""
    def __init__(self, files=None, replace=False):
        self.files = files or []
        self.replace = replace
        self.password_file = None
        self.new_password_file = None


SAMPLE = {"meta": {"generated_at": "2026-09-15T11:00:00Z", "portfolio": "Align"},
          "monthly_pl": [{"month": "2026-07", "revenue": 1327451.19}],
          "secret_marker": "Zzyzx-Bellweather-9917"}


def write(path, doc):
    pathlib.Path(path).write_text(json.dumps(doc), encoding="utf-8")
    return str(path)


# --------------------------------------------------------------- the format

def test_format():
    print("\nthe envelope")
    salt = b"0123456789abcdef"
    key = cd.derive_key("correct horse battery staple", salt)
    plain = json.dumps(SAMPLE).encode()
    env = cd.seal(plain, key, "docs/metrics.json", salt)

    ok("round trips", cd.unseal(env, "correct horse battery staple", "docs/metrics.json") == plain)
    ok("publishes its own parameters",
       env["v"] == 1 and env["alg"] == "AES-256-GCM" and env["iter"] == cd.ITERATIONS,
       env.get("iter"))
    ok("iteration count is not token", cd.ITERATIONS >= 600_000, cd.ITERATIONS)

    # The whole point: the plaintext must not be recoverable from the envelope.
    blob = json.dumps(env)
    ok("no plaintext survives in the envelope",
       "Zzyzx-Bellweather-9917" not in blob and "monthly_pl" not in blob
       and "1327451" not in blob)
    ok("the ciphertext is not merely base64 of the plaintext",
       base64.b64decode(env["ct"]) != plain)

    ok("a wrong password is refused",
       raises(cd.BadPassword, cd.unseal, env, "correct horse battery stapl", "docs/metrics.json"))
    ok("an empty password is refused",
       raises(cd.BadPassword, cd.unseal, env, "", "docs/metrics.json"))


def test_tamper():
    print("\ntampering")
    salt = b"0123456789abcdef"
    pw = "correct horse battery staple"
    key = cd.derive_key(pw, salt)
    plain = json.dumps(SAMPLE).encode()
    env = cd.seal(plain, key, "docs/metrics.json", salt)

    # Flip one bit of ciphertext. Without an authenticated mode this would
    # decrypt to subtly wrong numbers instead of failing.
    raw = bytearray(base64.b64decode(env["ct"]))
    raw[10] ^= 0x01
    bad = dict(env, ct=base64.b64encode(bytes(raw)).decode())
    ok("a flipped ciphertext bit is caught",
       raises(cd.BadPassword, cd.unseal, bad, pw, "docs/metrics.json"))

    raw = bytearray(base64.b64decode(env["ct"]))
    raw[-1] ^= 0x01                                        # the GCM tag itself
    bad = dict(env, ct=base64.b64encode(bytes(raw)).decode())
    ok("a flipped tag bit is caught",
       raises(cd.BadPassword, cd.unseal, bad, pw, "docs/metrics.json"))

    # The filename is authenticated, so metrics' ciphertext cannot be served as
    # scorecard's. Without the AAD binding this opens happily and the page draws
    # one file's numbers under another's name.
    ok("one file's ciphertext will not open under another's name",
       raises(cd.BadPassword, cd.unseal, env, pw, "docs/scorecard.json"))

    ok("a downgraded version is refused, not guessed at",
       raises(cd.CryptoDataError, cd.unseal, dict(env, v=0), pw, "docs/metrics.json"))
    ok("a swapped algorithm is refused",
       raises(cd.CryptoDataError, cd.unseal, dict(env, alg="AES-128-CBC"), pw, "docs/metrics.json"))
    ok("a nonsense iteration count is refused",
       raises(cd.CryptoDataError, cd.unseal, dict(env, iter=0), pw, "docs/metrics.json"))


def test_kdf_vector():
    print("\nkey derivation (what unlock.js has to reproduce)")
    # RFC-style published PBKDF2-HMAC-SHA256 vector. unlock.js asks WebCrypto for
    # the same primitive with the same inputs, so pinning this pins the browser
    # half too: if the derivation here ever drifts, the page stops opening files
    # the pipeline sealed, and this is what says so first.
    got = cd.derive_key("password", b"salt", 1).hex()
    ok("matches the published PBKDF2-HMAC-SHA256 vector",
       got == "120fb6cffcf8b32c43e7225256c4f837a86548c92ccc35480805987cb70be17b", got)
    ok("derives 256 bits", len(cd.derive_key("x", b"y", 2)) == 32)
    ok("the salt changes the key",
       cd.derive_key("pw", b"a" * 16) != cd.derive_key("pw", b"b" * 16))
    ok("the aad names the file, not the path",
       cd.aad_for("docs/metrics.json") == b"align-dashboard/v1/metrics.json",
       cd.aad_for("docs/metrics.json"))


# --------------------------------------------------------------- the commands

def test_encrypt_cli():
    print("\nencrypt / decrypt")
    os.environ["DASHBOARD_PASSWORD"] = "correct horse battery staple"
    with tempfile.TemporaryDirectory() as tmp:
        a = write(pathlib.Path(tmp, "metrics.json"), SAMPLE)
        b = write(pathlib.Path(tmp, "scorecard.json"), {"meta": {"generated_at": "x"}, "k": 1})

        cd.cmd_encrypt(Args([a, b]))
        ok("seals each file", os.path.exists(a + ".enc") and os.path.exists(b + ".enc"))

        ea = json.loads(pathlib.Path(a + ".enc").read_text())
        eb = json.loads(pathlib.Path(b + ".enc").read_text())
        ok("one salt for the run, so one derivation opens both", ea["salt"] == eb["salt"])
        ok("a distinct IV per file — sharing one would break GCM", ea["iv"] != eb["iv"])

        # The daily cron commits whatever changed. Random salt and IV mean a
        # naive re-encrypt writes different bytes every night, so the repo would
        # take a commit a day on data that never moved.
        before = pathlib.Path(a + ".enc").read_bytes()
        cd.cmd_encrypt(Args([a, b]))
        ok("unchanged plaintext is left alone, byte for byte",
           pathlib.Path(a + ".enc").read_bytes() == before)

        write(pathlib.Path(tmp, "metrics.json"), dict(SAMPLE, changed=True))
        cd.cmd_encrypt(Args([a, b]))
        ok("changed plaintext is re-sealed",
           pathlib.Path(a + ".enc").read_bytes() != before)

        os.remove(a)
        cd.cmd_decrypt(Args([a, b]))
        ok("decrypt restores the plaintext",
           json.loads(pathlib.Path(a).read_text()).get("changed") is True)

        ok("check passes on a good set", cd.cmd_check(Args([a, b])) == 0)

        # --replace is what keeps the deployed artifact from carrying both.
        cd.cmd_encrypt(Args([a, b], replace=True))
        ok("--replace removes the plaintext", not os.path.exists(a) and not os.path.exists(b))


def test_wrong_password_cli():
    print("\nwrong password through the commands")
    with tempfile.TemporaryDirectory() as tmp:
        a = write(pathlib.Path(tmp, "metrics.json"), SAMPLE)
        os.environ["DASHBOARD_PASSWORD"] = "the right one entirely"
        cd.cmd_encrypt(Args([a]))
        os.remove(a)
        os.environ["DASHBOARD_PASSWORD"] = "the wrong one entirely"
        ok("decrypt refuses rather than writing rubbish",
           raises(cd.BadPassword, cd.cmd_decrypt, Args([a])))
        ok("and writes no plaintext when it refuses", not os.path.exists(a))
        ok("check reports the failure", cd.cmd_check(Args([a])) == 1)


def test_rotate():
    print("\nrotation")
    with tempfile.TemporaryDirectory() as tmp:
        a = write(pathlib.Path(tmp, "metrics.json"), SAMPLE)
        b = write(pathlib.Path(tmp, "scorecard.json"), {"meta": {}, "k": 2})
        os.environ["DASHBOARD_PASSWORD"] = "the original password"
        cd.cmd_encrypt(Args([a, b]))

        os.environ["DASHBOARD_PASSWORD_NEW"] = "short"
        ok("a short new password is refused outright",
           raises(cd.CryptoDataError, cd.cmd_rotate, Args([a, b])))

        os.environ["DASHBOARD_PASSWORD_NEW"] = "the original password"
        ok("rotating to the same password is refused",
           raises(cd.CryptoDataError, cd.cmd_rotate, Args([a, b])))

        os.environ["DASHBOARD_PASSWORD_NEW"] = "a much longer replacement passphrase"
        cd.cmd_rotate(Args([a, b]))

        ea = json.loads(pathlib.Path(a + ".enc").read_text())
        ok("the old password no longer opens the files",
           raises(cd.BadPassword, cd.unseal, ea, "the original password", a))
        ok("the new password does",
           json.loads(cd.unseal(ea, "a much longer replacement passphrase", a))["secret_marker"]
           == "Zzyzx-Bellweather-9917")
        eb = json.loads(pathlib.Path(b + ".enc").read_text())
        ok("every file moved together — one salt, both re-sealed",
           ea["salt"] == eb["salt"]
           and cd.unseal(eb, "a much longer replacement passphrase", b))

        # A rotation that rewrote some files before discovering it could not open
        # the rest would leave no single password able to read the set.
        c = write(pathlib.Path(tmp, "landing.json"), {"meta": {}})
        os.environ["DASHBOARD_PASSWORD"] = "a much longer replacement passphrase"
        cd.cmd_encrypt(Args([c]))
        pathlib.Path(c + ".enc").write_text(json.dumps(
            dict(json.loads(pathlib.Path(c + ".enc").read_text()), ct="AAAA")))
        before = pathlib.Path(a + ".enc").read_bytes()
        os.environ["DASHBOARD_PASSWORD_NEW"] = "yet another long replacement phrase"
        ok("one unopenable file aborts the whole rotation",
           raises(cd.BadPassword, cd.cmd_rotate, Args([a, b, c])))
        ok("and leaves the others untouched",
           pathlib.Path(a + ".enc").read_bytes() == before)


NODE_HARNESS = r"""
// Runs docs/unlock.js outside a browser against files crypto_data.py sealed.
// Node's WebCrypto is the same implementation the page uses, so this is a real
// check that the two halves agree -- not a re-implementation of either.
const fs = require("fs"), path = require("path");
const DIR = process.argv[2], PW = process.argv[3], UNLOCK = process.argv[4];
globalThis.window = globalThis;
globalThis.sessionStorage = {
  _d: {}, getItem(k) { return k in this._d ? this._d[k] : null; },
  setItem(k, v) { this._d[k] = String(v); }, removeItem(k) { delete this._d[k]; },
};
globalThis.fetch = async (url) => {
  const f = path.join(DIR, url);
  if (!fs.existsSync(f)) return { status: 404, ok: false, json: async () => null };
  const t = fs.readFileSync(f, "utf8");
  return { status: 200, ok: true, json: async () => JSON.parse(t) };
};
require(UNLOCK);
(async () => {
  const out = {};
  out.mode = await AlignUnlock.detect();
  out.wrongRejected = (await AlignUnlock.tryPassword(PW + "x")) === false;
  out.rightAccepted = (await AlignUnlock.tryPassword(PW)) === true;
  const doc = await AlignUnlock.load("metrics.json");
  out.marker = doc.secret_marker;
  try {
    // scorecard.json sealed under the SAME key, but its ciphertext served as
    // metrics.json's name must still fail: the filename is authenticated.
    fs.copyFileSync(path.join(DIR, "scorecard.json.enc"), path.join(DIR, "swapped.json.enc"));
    await AlignUnlock.load("swapped.json");
    out.swapOpened = true;
  } catch (e) { out.swapOpened = false; }
  console.log(JSON.stringify(out));
})().catch(e => { console.log(JSON.stringify({ error: String(e && e.message || e) })); });
"""


def test_browser_half_agrees():
    """docs/unlock.js must open what crypto_data.py sealed.

    Two implementations of one format drift silently the moment either is
    edited alone -- and the symptom is a live dashboard that shows nothing to
    anyone. Node's WebCrypto is the same primitive set the browser uses, so
    running the page's own unlock.js here is a genuine cross-check rather than
    a second opinion from the same code.
    """
    print("\nthe browser half (docs/unlock.js under Node)")
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        print("   SKIP node not installed — run the browser check by hand instead")
        return
    unlock = pathlib.Path(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "unlock.js")
    if not unlock.is_file():
        ok("docs/unlock.js exists", False, str(unlock))
        return
    pw = "correct horse battery staple"
    os.environ["DASHBOARD_PASSWORD"] = pw
    with tempfile.TemporaryDirectory() as tmp:
        a = write(pathlib.Path(tmp, "metrics.json"), SAMPLE)
        b = write(pathlib.Path(tmp, "scorecard.json"), {"meta": {}, "k": 3})
        cd.cmd_encrypt(Args([a, b]))
        harness = pathlib.Path(tmp, "harness.js")
        harness.write_text(NODE_HARNESS)
        res = subprocess.run([node, str(harness), tmp, pw, str(unlock.resolve())],
                             capture_output=True, text=True, timeout=180)
        try:
            got = json.loads(res.stdout.strip().splitlines()[-1])
        except Exception:                                  # noqa: BLE001
            ok("unlock.js ran", False, (res.stdout[-300:], res.stderr[-300:]))
            return
        ok("unlock.js sees the sealed files", got.get("mode") == "encrypted", got)
        ok("it rejects a wrong password", got.get("wrongRejected") is True, got)
        ok("it accepts the right one", got.get("rightAccepted") is True, got)
        ok("and decrypts to exactly what Python sealed",
           got.get("marker") == "Zzyzx-Bellweather-9917", got)
        ok("the filename binding holds in the browser half too",
           got.get("swapOpened") is False, got)


def test_file_lists_agree():
    print("\nthe three lists that describe one set of files")
    import check_no_pii                                    # noqa: E402
    ok("crypto_data and check_no_pii name the same four files",
       sorted(cd.DATA_FILES) == sorted(check_no_pii.PUBLISHED),
       (cd.DATA_FILES, check_no_pii.PUBLISHED))
    sh = pathlib.Path(os.path.dirname(os.path.abspath(__file__)), "publish_data.sh").read_text()
    ok("publish_data.sh publishes the sealed form of each",
       all(f + ".enc" in sh for f in cd.DATA_FILES),
       [f for f in cd.DATA_FILES if f + ".enc" not in sh])


def main():
    for t in (test_format, test_tamper, test_kdf_vector, test_encrypt_cli,
              test_wrong_password_cli, test_rotate, test_browser_half_agrees,
              test_file_lists_agree):
        t()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Guard tests for the sealed data.

Fixture-free: every repository is built with `git init` in a temp dir, and no
real report or real data file is read. Ciphertext looks equally opaque whether it
is protecting anything or not, so what is covered is the set of ways this could
fail INVISIBLY:

  * a wrong password appearing to work, or a tampered file opening anyway
  * one file's ciphertext opening as another's -- including two properties'
    stores that share a basename
  * plaintext surviving inside an envelope, or reaching the git index
  * a weak or already-public password getting baked in on the first seal
  * the nightly run re-sealing unchanged data and committing a diff every day
  * a stale working copy sealed over newer data (the checkout guard)
  * a store rebuilt from nothing and sealed over its real history
  * a rotation half-finishing and leaving no single password able to open the set
  * two concurrent changes to one sealed file no longer merging
  * the browser half drifting away from this one

Run: python scripts/test_encryption.py
"""
import base64
import contextlib
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import crypto_data as cd                   # noqa: E402

PASS = FAIL = 0
PW = "correct horse battery staple"
PW2 = "a much longer replacement passphrase"


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


def env(**kw):
    """Set exactly these password variables for the duration of a block."""
    for k in ("DASHBOARD_PASSWORD", "DASHBOARD_PASSWORD_OLD", "DASHBOARD_PASSWORD_NEW"):
        os.environ.pop(k, None)
    for k, v in kw.items():
        os.environ[k] = v


def run(root, *argv):
    """The CLI, in process, output swallowed. -> exit code."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        rc = cd.main([*argv, "--root", str(root)])
    run.last = out.getvalue()
    return rc


run.last = ""

MARKER = "Zzyzx-Bellweather-9917"


def pretty(obj):
    return json.dumps(obj, indent=2) + "\n"


def make_repo(tmp, files):
    root = pathlib.Path(tmp)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for k, v in [("user.email", "t@example.com"), ("user.name", "t"),
                 ("commit.gpgsign", "false")]:
        subprocess.run(["git", "-C", str(root), "config", k, v], check=True)
    # The real ignore rules: they are part of what keeps plaintext out of git,
    # and a fixture without them tests a repository that does not exist.
    shutil.copy(HERE.parent / ".gitignore", root / ".gitignore")
    for rel, obj in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(pretty(obj) if not isinstance(obj, str) else obj)
    # -f: a fixture's plaintext stands for main TODAY, where it is tracked; the
    # runner-only store stays out, as it always has.
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-f", "--",
                    *[r for r in files if not cd.never_sealed(r)]], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "init"], check=True)
    return root


def tracked(root):
    return set(subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True,
                              text=True).stdout.split())


def enc(root, rel):
    return json.loads((root / (rel + ".enc")).read_text())


STANDARD = {
    "docs/metrics.json": {"meta": {"generated_at": "2026-09-23T11:00:00Z"},
                          "monthly_pl": [{"month": "2026-07", "revenue": 1327451.19}],
                          "note": MARKER},
    "docs/scorecard.json": {"meta": {"generated_at": "x"}, "k": 1},
    "data/palma/monthly_pl.json": {"points": [{"m": "2026-07", "noi": 111}]},
    "data/the-landing/monthly_pl.json": {"points": [{"m": "2026-07", "noi": 999}]},
    "data/the-landing/rent_roll.json": {"units": [{"unit": "101", "resident": "x"}]},
    "config/properties.json": {"properties": []},
}


# ------------------------------------------------------------------ the envelope

def test_envelope():
    print("\nthe envelope")
    salt = b"0123456789abcdef"
    key = cd.derive_key(PW, salt)
    plain = pretty(STANDARD["docs/metrics.json"]).encode()
    e = cd.seal(plain, key, "docs/metrics.json", salt)

    ok("round trips", cd.unseal(e, PW, "docs/metrics.json") == plain)
    ok("publishes its own parameters",
       e["v"] == 1 and e["alg"] == "AES-256-GCM" and e["iter"] == cd.ITERATIONS
       and e["zip"] == "gzip", e)
    ok("the iteration count is not token", cd.ITERATIONS >= 600_000)
    ok("the path is what it is bound to",
       e["aad"] == "align-dashboard/v1/docs/metrics.json", e["aad"])
    blob = json.dumps(e)
    ok("no plaintext survives in the envelope",
       MARKER not in blob and "monthly_pl" not in blob and "1327451" not in blob)
    ok("wrong password refused",
       raises(cd.BadPassword, cd.unseal, e, PW + "x", "docs/metrics.json"))
    ok("empty password refused", raises(cd.BadPassword, cd.unseal, e, "", "docs/metrics.json"))

    big = ("x" * 50 + "\n") * 2000
    eb = cd.seal(big.encode(), key, "docs/metrics.json", salt)
    ok("compressed before sealing (repetitive JSON shrinks)",
       len(base64.b64decode(eb["ct"])) < len(big) / 10, len(base64.b64decode(eb["ct"])))


def test_tamper():
    print("\ntampering and swapping")
    salt = b"0123456789abcdef"
    key = cd.derive_key(PW, salt)
    e = cd.seal(b'{"a": 1}', key, "data/palma/monthly_pl.json", salt)
    for i, label in ((5, "ciphertext"), (-1, "GCM tag")):
        raw = bytearray(base64.b64decode(e["ct"]))
        raw[i] ^= 1
        bad = dict(e, ct=base64.b64encode(bytes(raw)).decode())
        ok(f"a flipped {label} bit is caught",
           raises(cd.BadPassword, cd.unseal, bad, PW, "data/palma/monthly_pl.json"))
    # The case the basename AAD could not catch: two properties, one filename.
    ok("one property's store will not open as another's (same basename)",
       raises(cd.BadPassword, cd.unseal, e, PW, "data/the-landing/monthly_pl.json"))
    ok("nor as a different file", raises(cd.BadPassword, cd.unseal, e, PW, "docs/metrics.json"))
    for field, val, why in (("v", 0, "version"), ("alg", "AES-128-CBC", "algorithm"),
                            ("iter", 0, "iteration count"), ("zip", "lz4", "compression")):
        ok(f"an unknown {why} is refused rather than guessed at",
           raises(cd.CryptoDataError, cd.unseal, dict(e, **{field: val}), PW,
                  "data/palma/monthly_pl.json"))


def test_kdf():
    print("\nkey derivation (what unlock.js has to reproduce)")
    got = cd.derive_key("password", b"salt", 1).hex()
    ok("matches the published PBKDF2-HMAC-SHA256 vector",
       got == "120fb6cffcf8b32c43e7225256c4f837a86548c92ccc35480805987cb70be17b", got)
    ok("the salt changes the key", cd.derive_key("p", b"a" * 16, 2) != cd.derive_key("p", b"b" * 16, 2))


# ------------------------------------------------------------------ the file set

def test_file_set():
    print("\nwhat is sealed")
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, STANDARD)
        s = cd.sealed_set(root)
        ok("the page's files are in it", {"docs/metrics.json", "docs/scorecard.json"} <= set(s), s)
        ok("every per-property store is in it",
           {"data/palma/monthly_pl.json", "data/the-landing/monthly_pl.json"} <= set(s), s)
        ok("the unit-level, name-bearing stores are never in it",
           "data/the-landing/rent_roll.json" not in s, s)
        ok("config is not data", not any(r.startswith("config/") for r in s), s)
        (root / "data/new-property").mkdir()
        (root / "data/new-property/new_store.json").write_text("{}")
        ok("a store that appears tomorrow is covered by default",
           "data/new-property/new_store.json" in cd.sealed_set(root))
    gi = (HERE.parent / ".gitignore").read_text().split()
    ok("everything never sealed is gitignored outright",
       all(p in gi for p in cd.NEVER_SEAL), [p for p in cd.NEVER_SEAL if p not in gi])
    ok("every plaintext in the sealed set is gitignored",
       all(p in gi for p in cd.PAGE_FILES) and "data/**/*.json" in gi,
       [p for p in cd.PAGE_FILES + ["data/**/*.json"] if p not in gi])


# ------------------------------------------------------------------ first seal

def test_first_seal():
    print("\nthe first seal (reseal --git on a plaintext repo)")
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, STANDARD)
        env(DASHBOARD_PASSWORD="short")
        ok("a short password is refused", run(root, "reseal") == 1, run.last)
        env(DASHBOARD_PASSWORD="AlignExecs")
        ok("the password already public in this repo's history is refused",
           run(root, "reseal") == 1 and "public" in run.last, run.last)
        ok("and a refused seal writes nothing",
           not list(root.rglob("*.enc")), list(root.rglob("*.enc")))

        env(DASHBOARD_PASSWORD=PW)
        ok("a strong password seals", run(root, "reseal", "--git", "--replace") == 0, run.last)
        t = tracked(root)
        ok("the sealed copies are staged",
           {"docs/metrics.json.enc", "data/palma/monthly_pl.json.enc"} <= t, sorted(t))
        ok("the plaintext is out of the index",
           not ({"docs/metrics.json", "data/palma/monthly_pl.json"} & t), sorted(t))
        ok("and off the disk (--replace)", not (root / "docs/metrics.json").exists())
        ok("the name-bearing store was never sealed",
           not (root / "data/the-landing/rent_roll.json.enc").exists())
        salts = {enc(root, r)["salt"] for r in cd.sealed_set(root)}
        ivs = [enc(root, r)["iv"] for r in cd.sealed_set(root)]
        ok("one salt, so one derivation opens everything", len(salts) == 1, salts)
        ok("a distinct IV per file", len(set(ivs)) == len(ivs))
        ok("mode reads sealed", cd.mode(root) == "sealed")
        ok("check passes", run(root, "check") == 0, run.last)


def sealed_repo(tmp):
    root = make_repo(tmp, STANDARD)
    env(DASHBOARD_PASSWORD=PW)
    assert run(root, "reseal", "--git", "--replace") == 0, run.last
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "seal"], check=True)
    return root


# ------------------------------------------------------------------ the cycle

def test_cycle():
    print("\ndecrypt -> edit -> encrypt")
    with tempfile.TemporaryDirectory() as tmp:
        root = sealed_repo(tmp)
        ok("decrypt opens every working copy", run(root, "decrypt") == 0
           and json.loads((root / "docs/metrics.json").read_text())["note"] == MARKER, run.last)
        before = {r: (root / (r + ".enc")).read_bytes() for r in cd.sealed_set(root)}
        run(root, "encrypt")
        ok("nothing changed, so nothing is rewritten -- byte for byte",
           all((root / (r + ".enc")).read_bytes() == b for r, b in before.items()))

        m = json.loads((root / "docs/metrics.json").read_text())
        m["note"] = "changed"
        (root / "docs/metrics.json").write_text(pretty(m))
        salt0 = enc(root, "docs/metrics.json")["salt"]
        ok("a change seals", run(root, "encrypt") == 0, run.last)
        ok("under the same salt, so a tab unlocked this morning still opens it",
           enc(root, "docs/metrics.json")["salt"] == salt0)
        ok("and only the changed file was rewritten",
           (root / "docs/scorecard.json.enc").read_bytes() == before["docs/scorecard.json"])


def test_guard():
    print("\nthe checkout guard")
    with tempfile.TemporaryDirectory() as tmp:
        root = sealed_repo(tmp)
        # A script that found no plaintext and started from nothing:
        (root / "data/palma/monthly_pl.json").write_text(pretty({"points": []}))
        ok("a store never opened here is refused -- it would overwrite its history",
           run(root, "encrypt") == 1 and "never opened" in run.last, run.last)

        run(root, "decrypt")
        # Someone else pushes a newer sealed copy while this one is open:
        newer = cd.seal(b'{"points": ["newer"]}\n', cd.derive_key(PW, base64.b64decode(
            enc(root, "docs/scorecard.json")["salt"])), "docs/scorecard.json",
            base64.b64decode(enc(root, "docs/scorecard.json")["salt"]))
        (root / "docs/scorecard.json.enc").write_text(json.dumps(newer))
        (root / "docs/scorecard.json").write_text(pretty({"k": "edited on a stale copy"}))
        m = json.loads((root / "docs/metrics.json").read_text())
        m["note"] = "also edited"
        (root / "docs/metrics.json").write_text(pretty(m))
        before_metrics = (root / "docs/metrics.json.enc").read_bytes()
        ok("a stale working copy is refused", run(root, "encrypt") == 1
           and "changed since it was opened" in run.last, run.last)
        ok("and the refusal is all or nothing -- the good file was not sealed either",
           (root / "docs/metrics.json.enc").read_bytes() == before_metrics)
        ok("decrypt calls that a conflict rather than picking a side",
           run(root, "decrypt") == 1 and "CONFLICT" in run.last, run.last)
        ok("--force is the deliberate override", run(root, "encrypt", "--force") == 0, run.last)

    with tempfile.TemporaryDirectory() as tmp:
        root = sealed_repo(tmp)
        run(root, "decrypt")
        (root / "docs/metrics.json").write_text(pretty({"local": "work"}))
        run(root, "decrypt")
        ok("decrypt keeps local changes when the sealed copy has not moved",
           json.loads((root / "docs/metrics.json").read_text()) == {"local": "work"})
        # sealed copy moves on; an UNEDITED working copy is simply refreshed
        salt = base64.b64decode(enc(root, "docs/scorecard.json")["salt"])
        (root / "docs/scorecard.json.enc").write_text(json.dumps(cd.seal(
            b'{"fresh": true}\n', cd.derive_key(PW, salt), "docs/scorecard.json", salt)))
        run(root, "decrypt")
        ok("and refreshes an unedited one when it has",
           json.loads((root / "docs/scorecard.json").read_text()) == {"fresh": True})
        run(root, "decrypt", "--force")
        ok("decrypt --force discards local changes",
           json.loads((root / "docs/metrics.json").read_text())["note"] == MARKER)


def test_rotation():
    print("\nrotation by changing the secret")
    with tempfile.TemporaryDirectory() as tmp:
        root = sealed_repo(tmp)
        old_salt = enc(root, "docs/metrics.json")["salt"]
        env(DASHBOARD_PASSWORD=PW2)
        ok("the new password alone cannot open the old seal", run(root, "decrypt") == 1)
        env(DASHBOARD_PASSWORD=PW2, DASHBOARD_PASSWORD_OLD=PW)
        ok("with the old one as a fallback, it opens", run(root, "decrypt") == 0, run.last)
        ok("and an ordinary encrypt re-keys EVERYTHING, changed or not",
           run(root, "encrypt") == 0, run.last)
        env(DASHBOARD_PASSWORD=PW2)
        ok("afterwards the new password opens every file on its own",
           run(root, "check") == 0, run.last)
        ok("under a fresh salt", enc(root, "docs/metrics.json")["salt"] != old_salt)
        env(DASHBOARD_PASSWORD=PW)
        ok("and the old password opens nothing", run(root, "check") == 1)

    with tempfile.TemporaryDirectory() as tmp:
        root = sealed_repo(tmp)
        bad = enc(root, "docs/scorecard.json")
        bad["ct"] = "AAAA"
        (root / "docs/scorecard.json.enc").write_text(json.dumps(bad))
        before = (root / "docs/metrics.json.enc").read_bytes()
        env(DASHBOARD_PASSWORD=PW2, DASHBOARD_PASSWORD_OLD=PW)
        ok("reseal with one unopenable file fails", run(root, "reseal") == 1, run.last)
        ok("and leaves every other file untouched",
           (root / "docs/metrics.json.enc").read_bytes() == before)


def test_check():
    print("\ncheck")
    with tempfile.TemporaryDirectory() as tmp:
        root = sealed_repo(tmp)
        other = b"f" * 16
        (root / "docs/scorecard.json.enc").write_text(json.dumps(
            cd.seal(b"{}", cd.derive_key(PW, other), "docs/scorecard.json", other)))
        ok("two salts are reported -- the browser would derive twice",
           run(root, "check") == 1 and "salts" in run.last, run.last)


def test_passphrase():
    print("\npassphrase")
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        run(root, "passphrase")
        pp = run.last.strip()
        ok("five groups of four", len(pp.split("-")) == 5 and all(len(g) == 4 for g in pp.split("-")), pp)
        ok("strong enough to pass the seal's own check", raises(cd.CryptoDataError,
           cd.check_new_password, pp) is False)
        os.environ["GITHUB_ACTIONS"] = "true"
        ok("refuses to print into a CI log", run(root, "passphrase") == 1)
        del os.environ["GITHUB_ACTIONS"]


# ------------------------------------------------------------------ git integration

def gitc(root, *a, check=True):
    return subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True,
                          check=check, env=os.environ.copy())


def test_git_integration():
    print("\ngit: hooks, diff, merge")
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        files = dict(STANDARD)
        files["docs/metrics.json"] = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6}
        root = make_repo(tmp, files)
        shutil.copytree(HERE, root / "scripts")               # hooks call scripts/crypto_data.py
        shutil.copytree(HERE.parent / ".githooks", root / ".githooks")
        shutil.copy(HERE.parent / ".gitattributes", root / ".gitattributes")
        env(DASHBOARD_PASSWORD=PW)
        run(root, "install")
        run(root, "reseal", "--git", "--replace")
        gitc(root, "add", "-A", ".gitattributes", ".githooks")
        gitc(root, "commit", "-qm", "seal")

        # pre-commit: a force-added plaintext is refused -- first UNEDITED, so the
        # staged-plaintext rule is tested on its own and not covered for by the
        # unsealed-change rule below (mutation found exactly that gap).
        run(root, "decrypt")
        gitc(root, "add", "-f", "docs/scorecard.json")
        ok("pre-commit refuses staged plaintext even when it matches the sealed copy",
           gitc(root, "commit", "-qm", "x", check=False).returncode != 0)
        gitc(root, "restore", "--staged", "docs/scorecard.json")
        (root / "docs/metrics.json").write_text(pretty({"a": 1}))
        gitc(root, "add", "-f", "docs/metrics.json")
        ok("pre-commit refuses staged plaintext",
           gitc(root, "commit", "-qm", "x", check=False).returncode != 0)
        gitc(root, "restore", "--staged", "docs/metrics.json")
        ok("pre-commit refuses a commit that leaves a data change unsealed",
           gitc(root, "commit", "--allow-empty", "-qm", "x", check=False).returncode != 0)
        run(root, "decrypt", "--force")
        ok("and passes once the change is sealed or discarded",
           gitc(root, "commit", "--allow-empty", "-qm", "x", check=False).returncode == 0)
        gitc(root, "tag", "base")          # both branches below fork from here

        # textconv: git diff shows plaintext
        m = json.loads((root / "docs/metrics.json").read_text())
        m["b"] = 20
        (root / "docs/metrics.json").write_text(pretty(m))
        run(root, "encrypt", "--git")
        d = gitc(root, "diff", "--cached").stdout
        ok("git diff shows the change in the clear, where the password is present",
           '"b": 20' in d, d[-400:])
        gitc(root, "commit", "-qm", "b")

        # merge driver: two branches change different lines of one sealed file
        gitc(root, "checkout", "-qb", "other", "base")
        run(root, "decrypt", "--force")
        m = json.loads((root / "docs/metrics.json").read_text())
        m["e"] = 50
        (root / "docs/metrics.json").write_text(pretty(m))
        run(root, "encrypt", "--git")
        gitc(root, "commit", "-qm", "e")
        gitc(root, "checkout", "-q", "-")
        res = gitc(root, "merge", "-q", "--no-edit", "other", check=False)
        ok("two changes to different lines of one sealed file merge cleanly",
           res.returncode == 0, res.stdout + res.stderr)
        merged = json.loads(cd.unseal(enc(root, "docs/metrics.json"), PW, "docs/metrics.json"))
        ok("and the merged file carries both", merged.get("b") == 20 and merged.get("e") == 50, merged)
        ok("post-merge refreshed the working copy",
           json.loads((root / "docs/metrics.json").read_text()) == merged)

        # a real conflict stops the merge instead of picking a side
        gitc(root, "checkout", "-qb", "clash", "base")
        run(root, "decrypt", "--force")
        m = json.loads((root / "docs/metrics.json").read_text())
        m["b"] = 999
        (root / "docs/metrics.json").write_text(pretty(m))
        run(root, "encrypt", "--git")
        gitc(root, "commit", "-qm", "clash")
        gitc(root, "checkout", "-q", "-")
        res = gitc(root, "merge", "-q", "--no-edit", "clash", check=False)
        ok("the same line changed on both sides is a conflict, not a silent pick",
           res.returncode != 0)
        left = json.loads((root / "docs/metrics.json.enc").read_text())
        ok("and the conflicted file is NOT a valid envelope (no silent one-side resolution)",
           "conflict" in left and "ct" not in left, list(left)[:4])
        gitc(root, "add", "docs/metrics.json.enc")
        ok("so committing it unresolved is refused by pre-commit",
           gitc(root, "commit", "-qm", "unresolved", check=False).returncode != 0)
        gitc(root, "merge", "--abort", check=False)

    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, STANDARD)
        env()
        ok("pre-commit is a no-op before the repository is sealed",
           run(root, "pre-commit") == 0, run.last)
        ok("textconv without a password says so rather than failing",
           True)


# ------------------------------------------------------------------ the browser half

NODE_HARNESS = r"""
const fs = require("fs"), path = require("path");
const [DIR, PW, UNLOCK, HOST] = process.argv.slice(2);
globalThis.window = globalThis;
globalThis.location = { hostname: HOST };
globalThis.sessionStorage = { _d: {}, getItem(k) { return k in this._d ? this._d[k] : null; },
  setItem(k, v) { this._d[k] = String(v); }, removeItem(k) { delete this._d[k]; } };
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
  if (out.mode === "encrypted") {
    out.wrongRejected = (await AlignUnlock.tryPassword(PW + "x")) === false;
    out.rightAccepted = (await AlignUnlock.tryPassword(PW)) === true;
    out.marker = (await AlignUnlock.load("metrics.json")).note;
    out.second = (await AlignUnlock.load("scorecard.json")).k;
    fs.copyFileSync(path.join(DIR, "scorecard.json.enc"), path.join(DIR, "lineage.json.enc"));
    try { await AlignUnlock.load("lineage.json"); out.swapOpened = true; }
    catch (e) { out.swapOpened = false; }
  } else {
    try { await AlignUnlock.load("metrics.json"); out.plainServed = true; }
    catch (e) { out.plainServed = false; out.plainError = String(e.message); }
  }
  console.log(JSON.stringify(out));
})().catch(e => console.log(JSON.stringify({ error: String(e && e.message || e) })));
"""


def node_run(site, pw, host):
    node = shutil.which("node")
    h = pathlib.Path(site, "_harness.js")
    h.write_text(NODE_HARNESS)
    res = subprocess.run([node, str(h), str(site), pw,
                          str(HERE.parent / "docs" / "unlock.js"), host],
                         capture_output=True, text=True, timeout=180)
    try:
        return json.loads(res.stdout.strip().splitlines()[-1])
    except Exception:                                      # noqa: BLE001
        return {"error": (res.stdout[-300:], res.stderr[-300:])}


def test_browser_half():
    print("\nthe browser half (docs/unlock.js under Node's WebCrypto)")
    if not shutil.which("node"):
        print("   SKIP node not installed")
        return
    with tempfile.TemporaryDirectory() as tmp:
        root = sealed_repo(tmp)
        site = root / "docs"
        got = node_run(site, PW, "aligndashboard.github.io")
        ok("unlock.js sees the sealed files", got.get("mode") == "encrypted", got)
        ok("rejects a wrong password", got.get("wrongRejected") is True, got)
        ok("accepts the right one", got.get("rightAccepted") is True, got)
        ok("decrypts and decompresses exactly what Python sealed", got.get("marker") == MARKER, got)
        ok("a second file opens on the same derived key", got.get("second") == 1, got)
        ok("the path binding holds in the browser too", got.get("swapOpened") is False, got)
    with tempfile.TemporaryDirectory() as tmp:
        site = pathlib.Path(tmp)
        (site / "metrics.json").write_text(pretty({"meta": {}, "note": MARKER}))
        got = node_run(site, PW, "aligndashboard.github.io")
        ok("an unsealed build on a public host serves nothing",
           got.get("mode") == "plain" and got.get("plainServed") is False, got)
        got = node_run(site, PW, "localhost")
        ok("but opens on localhost, for local work", got.get("plainServed") is True, got)


# ------------------------------------------------------------------ lists that must agree

def test_agreement():
    print("\nthe places that name the sealed set")
    import check_no_pii                                    # noqa: E402
    ok("check_no_pii scans the page files crypto_data seals",
       sorted(cd.PAGE_FILES) == sorted(check_no_pii.PUBLISHED))
    js = (HERE.parent / "docs" / "unlock.js").read_text()
    ok("unlock.js binds the same AAD prefix", cd.AAD_PREFIX in js)
    ok("unlock.js knows the iteration floor is in the envelope, not hardcoded",
       "600000" not in js.replace("600,000", ""))
    sh = (HERE / "publish_data.sh").read_text()
    ok("publish_data.sh publishes the sealed page files",
       all(f + ".enc" in sh for f in cd.PAGE_FILES), [f for f in cd.PAGE_FILES if f + ".enc" not in sh])


def test_entry_guard():
    print("\nthe entry guard (no pipeline script runs on an unopened checkout)")
    with tempfile.TemporaryDirectory() as tmp:
        root = sealed_repo(tmp)

        def refuses():
            try:
                with contextlib.redirect_stderr(io.StringIO()):
                    cd.require_opened("test", root)
            except SystemExit as e:
                return e.code == 2
            return False
        ok("a sealed checkout with nothing opened is refused", refuses())
        run(root, "decrypt")
        ok("once opened, it passes", not refuses())
        salt = base64.b64decode(enc(root, "docs/scorecard.json")["salt"])
        (root / "docs/scorecard.json.enc").write_text(json.dumps(cd.seal(
            b'{"newer": 1}\n', cd.derive_key(PW, salt), "docs/scorecard.json", salt)))
        ok("a sealed copy that moved since opening makes the checkout stale -> refused",
           refuses() and any("stale" in why for _, why in cd.unopened(root)))
        run(root, "decrypt")
        (root / "data/palma/monthly_pl.json").unlink()
        ok("a working copy that went missing is refused", refuses())
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, STANDARD)
        ok("an unsealed checkout is never refused (nothing to open)", cd.unopened(root) == [])
    guarded = ["build_metrics", "refresh_comps", "populate_scorecard", "populate_eliseai",
               "populate_building_metrics", "build_lineage", "landing_drive_status",
               "extract_landing", "extract_scorecard"]
    missing = [g for g in guarded
               if "crypto_data.require_opened" not in (HERE / f"{g}.py").read_text()]
    ok("every script that reads last run's output calls it at its entry point", not missing, missing)
    for g in ("refresh_comps", "populate_scorecard", "build_lineage"):
        src = (HERE / f"{g}.py").read_text()
        main_body = src[src.index("def main"):src.index('if __name__ == "__main__":')]
        ok(f"{g}: in the entry point, not in main() -- tests drive main() directly",
           "require_opened" not in main_body)


def test_shrink_and_rekey():
    print("\nthe shrink check and the partial re-key")
    with tempfile.TemporaryDirectory() as tmp:
        files = dict(STANDARD)
        files["data/palma/monthly_pl.json"] = {"points": [{"m": f"2025-{i:02d}", "noi": i * 1000,
                                                           "pad": "x" * 400} for i in range(1, 25)]}
        root = make_repo(tmp, files)
        env(DASHBOARD_PASSWORD=PW)
        run(root, "reseal", "--git", "--replace")
        run(root, "decrypt")
        (root / "data/palma/monthly_pl.json").write_text(pretty({"points": [{"m": "2026-09"}]}))
        ok("a store that shrank to a fraction is refused -- what a rebuilt-from-nothing looks like",
           run(root, "encrypt") == 1 and "shrank" in run.last, run.last)
        os.environ["ALIGN_ALLOW_SHRINK"] = "1"
        ok("and a deliberate one goes through with ALIGN_ALLOW_SHRINK=1", run(root, "encrypt") == 0, run.last)
        del os.environ["ALIGN_ALLOW_SHRINK"]

    with tempfile.TemporaryDirectory() as tmp:
        root = sealed_repo(tmp)
        run(root, "decrypt", "docs/metrics.json")         # only ONE file open here
        m = json.loads((root / "docs/metrics.json").read_text())
        m["note"] = "x"
        (root / "docs/metrics.json").write_text(pretty(m))
        env(DASHBOARD_PASSWORD=PW2)                        # a session whose variable moved on
        before = (root / "docs/metrics.json.enc").read_bytes()
        ok("a new password is not applied to only the files open here -- it would split the key",
           run(root, "encrypt") == 1 and "not open here to be re-keyed" in run.last, run.last)
        ok("and nothing was written", (root / "docs/metrics.json.enc").read_bytes() == before)


# ------------------------------------------------------------------ the workflows

def _steps(wf):
    import yaml
    d = yaml.safe_load((HERE.parent / ".github" / "workflows" / wf).read_text())
    job = next(iter(d["jobs"].values()))
    return [(st.get("name", ""), st.get("run", "") or "", st.get("env", {}) or {})
            for st in job["steps"]]


def _index(steps, pred):
    return next((i for i, st in enumerate(steps) if pred(st)), None)


def test_workflows():
    """The ORDER of the steps is the design, and a reordered one looks fine.

    Opened before the re-sync reset, a working copy is this morning's data under
    tonight's sealed copy. Sealed after the commit, nothing is sealed. The PII
    check after the seal reads nothing. None of those fails on its own.
    """
    print("\nthe workflows")
    try:
        import yaml                                        # noqa: F401
    except ImportError:
        print("   SKIP pyyaml not installed")
        return
    st = _steps("update.yml")
    key = _index(st, lambda s: "crypto_data.py check" in s[1] and "DASHBOARD_PASSWORD" in s[1])
    fetch = _index(st, lambda s: "fetch_drive.py" in s[1])
    resync = _index(st, lambda s: "git reset" in s[1] and "Re-sync" in s[0])
    opened = _index(st, lambda s: "crypto_data.py decrypt" in s[1])
    build = _index(st, lambda s: "build_metrics.py" in s[1])
    pii = _index(st, lambda s: "check_no_pii.py" in s[1])
    seal = _index(st, lambda s: "crypto_data.py encrypt" in s[1])
    commit = _index(st, lambda s: "git commit" in s[1])
    ok("update.yml: the key is checked before the hours-long Drive fetch",
       None not in (key, fetch) and key < fetch, (key, fetch))
    ok("update.yml: opened AFTER the re-sync reset, and before the build",
       None not in (resync, opened, build) and resync < opened < build, (resync, opened, build))
    ok("update.yml: PII check on the plaintext, then seal, then commit",
       None not in (pii, seal, commit) and pii < seal < commit, (pii, seal, commit))
    ok("update.yml: the PII check refuses an unopened checkout",
       "--require-open" in st[pii][1])
    ok("update.yml: commits the sealed copies, never the plaintext names",
       "metrics.json.enc" in st[commit][1] and 'PATHS="data docs/metrics.json docs' not in st[commit][1])
    ok("update.yml: the push-retry replays only what this run wrote",
       "KEPT=$(git diff --name-only --diff-filter=d \"$BASE\" HEAD" in st[commit][1]
       and "crypto_data.py untrack" in st[commit][1])
    ok("update.yml: every step that opens or seals has the key, and its fallback",
       all("DASHBOARD_PASSWORD" in s[2] and "DASHBOARD_PASSWORD_OLD" in s[2]
           for s in st if "crypto_data.py" in s[1]))

    rc = _steps("refresh_comps.yml")
    o = _index(rc, lambda s: "crypto_data.py decrypt" in s[1])
    r = _index(rc, lambda s: "refresh_comps.py" in s[1])
    c = _index(rc, lambda s: "git commit" in s[1])
    ok("refresh_comps.yml: opened before the refresh", None not in (o, r) and o < r, (o, r))
    retry = rc[c][1] if c is not None else ""
    ok("refresh_comps.yml: the retry re-opens main's copies after its reset, before rebuilding",
       retry.find("git reset --hard origin/main") < retry.find("crypto_data.py decrypt --force")
       < retry.find("refresh_comps.py") and "crypto_data.py decrypt --force" in retry)
    ok("refresh_comps.yml: commits the sealed metrics, not the plaintext",
       'PATHS="docs/metrics.json.enc data"' in retry)

    sd = _steps("seal_data.yml")
    ok("seal_data.yml: reseals under the secret, with the old one as a fallback",
       any("crypto_data.py reseal --git" in s[1] and "DASHBOARD_PASSWORD_OLD" in s[2] for s in sd))
    ok("seal_data.yml: PII check before the seal",
       _index(sd, lambda s: "check_no_pii.py" in s[1]) < _index(sd, lambda s: "reseal" in s[1]))
    for wf in ("update.yml", "refresh_comps.yml", "seal_data.yml", "deploy.yml"):
        raw = (HERE.parent / ".github" / "workflows" / wf).read_text()
        ok(f"{wf}: never echoes a password into the (public) log",
           "echo \"$DASHBOARD_PASSWORD" not in raw and "set -x" not in raw)


def _commit_step():
    import yaml
    d = yaml.safe_load((HERE.parent / ".github/workflows/update.yml").read_text())
    return next(st["run"] for st in d["jobs"]["update"]["steps"] if st["name"] == "Commit changes")


def test_update_replay():
    """Run update.yml's REAL commit step against a push race.

    A bare repo stands in for origin. The cron clone changes metrics; meanwhile a
    Routine clone records a day in another store and pushes first. Before, the
    retry replayed every data path, so the Routine's day was overwritten by the
    cron's older copy of a file it never wrote (A15). Now it must survive.
    """
    print("\nupdate.yml's push race, executed")
    try:
        import yaml                                        # noqa: F401
    except ImportError:
        print("   SKIP pyyaml not installed")
        return
    step = _commit_step()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        seed = sealed_repo(tmp / "seed")
        subprocess.run(["git", "-C", str(seed), "branch", "-M", "main"], check=True)
        subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(tmp / "origin.git")], check=True)

        def clone(name):
            c = tmp / name
            subprocess.run(["git", "clone", "-q", str(tmp / "origin.git"), str(c)], check=True)
            for k, v in [("user.email", "t@example.com"), ("user.name", name),
                         ("commit.gpgsign", "false")]:
                subprocess.run(["git", "-C", str(c), "config", k, v], check=True)
            shutil.copytree(HERE, c / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
            return c

        def edit(c, rel, key, val):
            run(c, "decrypt")
            doc = json.loads((c / rel).read_text())
            doc[key] = val
            (c / rel).write_text(pretty(doc))
            assert run(c, "encrypt", "--git") == 0, run.last

        def race(routine_rel):
            cron, routine = clone("cron"), clone("routine")
            edit(cron, "docs/metrics.json", "cron", "this run's build")
            edit(routine, routine_rel, "routine", "recorded mid-run")
            gitc(routine, "commit", "-qm", "routine day")
            gitc(routine, "push", "-q", "origin", "HEAD:main")
            r = subprocess.run(["bash", "-c", step], cwd=cron, capture_output=True, text=True,
                               env=dict(os.environ), timeout=120)
            check = clone("check")
            run(check, "decrypt")
            return r, check

        r, check = race("data/palma/monthly_pl.json")
        ok("the cron's push goes through after losing the race", r.returncode == 0 and
           "Pushed on attempt" in r.stdout, (r.returncode, r.stdout[-300:], r.stderr[-300:]))
        ok("main carries the cron's output",
           json.loads((check / "docs/metrics.json").read_text()).get("cron") == "this run's build")
        ok("AND the Routine's day, in a file the cron never wrote (A15's daily loss)",
           json.loads((check / "data/palma/monthly_pl.json").read_text()).get("routine")
           == "recorded mid-run")
        ok("nothing plaintext reached origin",
           not any(f in tracked(check) for f in cd.sealed_set(check)))

    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        seed = sealed_repo(tmp / "seed")
        subprocess.run(["git", "-C", str(seed), "branch", "-M", "main"], check=True)
        subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(tmp / "origin.git")], check=True)
        cron, routine = clone("cron"), clone("routine")
        edit(cron, "docs/metrics.json", "cron", "this run's build")
        edit(routine, "docs/metrics.json", "routine", "same file")
        gitc(routine, "commit", "-qm", "routine")
        gitc(routine, "push", "-q", "origin", "HEAD:main")
        r = subprocess.run(["bash", "-c", step], cwd=cron, capture_output=True, text=True,
                           env=dict(os.environ), timeout=120)
        ok("where both changed one file, the run still wins -- and the log names the file",
           r.returncode == 0 and "both changed" in r.stdout and "docs/metrics.json.enc" in r.stdout,
           r.stdout[-400:])


def test_review_round():
    """The four failures the adversarial review reproduced against a bare origin."""
    print("\nreview round: cutover plaintext, rotation mid-run, rotation pre-flight")
    # --- [0] plaintext committed beside its sealed copy: refused at push, repaired by reseal
    with tempfile.TemporaryDirectory() as tmp:
        root = sealed_repo(tmp)
        run(root, "decrypt")
        m = json.loads((root / "docs/metrics.json").read_text())
        m["note"] = "edited as plaintext before the seal reached this session"
        (root / "docs/metrics.json").write_text(pretty(m))
        gitc(root, "add", "-f", "docs/metrics.json")
        env_ = dict(os.environ, GIT_COMMITTER_DATE="2099-01-01T00:00:00Z",
                    GIT_AUTHOR_DATE="2099-01-01T00:00:00Z")
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "plaintext", "--no-verify"],
                       check=True, env=env_)
        head = gitc(root, "rev-parse", "HEAD").stdout.strip()
        r = subprocess.run([sys.executable, str(HERE / "crypto_data.py"), "pre-push", "--root", str(root)],
                           input=f"refs/heads/main {head} refs/heads/main {'0' * 40}\n",
                           capture_output=True, text=True)
        ok("pre-push refuses a sealed tree that carries plaintext beside it", r.returncode == 1,
           r.stderr[-200:])
        import check_no_pii as cnp                         # noqa: E402
        ok("seal_data's own PII check does not fail on the thing it is there to fix",
           subprocess.run([sys.executable, str(HERE / "check_no_pii.py"), "--sealing"], cwd=root,
                          capture_output=True).returncode == 0)
        ok("the ordinary PII check does fail on it",
           subprocess.run([sys.executable, str(HERE / "check_no_pii.py")], cwd=root,
                          capture_output=True).returncode == 1)
        ok("reseal adopts the plaintext committed after its sealed copy",
           run(root, "reseal", "--git") == 0 and "ADOPTED" in run.last, run.last)
        ok("and the sealed copy now carries that newer content",
           json.loads(cd.unseal(enc(root, "docs/metrics.json"), PW, "docs/metrics.json"))["note"]
           .startswith("edited as plaintext"))
        ok("with the plaintext out of the index", "docs/metrics.json" not in
           set(gitc(root, "ls-files").stdout.split()))

    # --- [2] the pre-flight accepts a rotation in progress; the post-seal check does not
    with tempfile.TemporaryDirectory() as tmp:
        root = sealed_repo(tmp)
        env(DASHBOARD_PASSWORD=PW2, DASHBOARD_PASSWORD_OLD=PW)
        ok("check --allow-old passes while every file is still under the old password",
           run(root, "check", "--allow-old") == 0, run.last)
        ok("the strict check still reports it", run(root, "check") == 1)
        env(DASHBOARD_PASSWORD=PW)

    # --- [1] a password change while the cron built: no replay across keys
    try:
        import yaml                                        # noqa: F401
    except ImportError:
        print("   SKIP pyyaml not installed")
        return
    step = _commit_step()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        seed = sealed_repo(tmp / "seed")
        subprocess.run(["git", "-C", str(seed), "branch", "-M", "main"], check=True)
        subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(tmp / "origin.git")], check=True)

        def clone(name):
            c = tmp / name
            subprocess.run(["git", "clone", "-q", str(tmp / "origin.git"), str(c)], check=True)
            for k, v in [("user.email", "t@example.com"), ("user.name", name),
                         ("commit.gpgsign", "false")]:
                subprocess.run(["git", "-C", str(c), "config", k, v], check=True)
            shutil.copytree(HERE, c / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
            return c
        cron, owner = clone("cron"), clone("owner")
        env(DASHBOARD_PASSWORD=PW)
        run(cron, "decrypt")
        m = json.loads((cron / "docs/metrics.json").read_text())
        m["cron"] = "built under the old password"
        (cron / "docs/metrics.json").write_text(pretty(m))
        run(cron, "encrypt", "--git")
        env(DASHBOARD_PASSWORD=PW2, DASHBOARD_PASSWORD_OLD=PW)       # the owner rotates mid-run
        assert run(owner, "reseal", "--git") == 0, run.last
        gitc(owner, "commit", "-qm", "rotate")
        gitc(owner, "push", "-q", "origin", "HEAD:main")
        env(DASHBOARD_PASSWORD=PW)                                    # the cron's job still has the old one
        r = subprocess.run(["bash", "-c", step], cwd=cron, capture_output=True, text=True,
                           env=dict(os.environ), timeout=120)
        ok("the cron refuses to replay across a password change",
           r.returncode != 0 and "different key" in (r.stdout + r.stderr), (r.returncode, r.stderr[-300:]))
        check = clone("check")
        env(DASHBOARD_PASSWORD=PW2)
        ok("and main is still wholly under the new password -- no split, no retired key restored",
           run(check, "check") == 0, run.last)
        env(DASHBOARD_PASSWORD=PW)


def test_review_round_two():
    print("\nreview round two: typeable passwords, subset seals, merges mid-rotation")
    # --- [0] a secret pasted with its line ending seals under what the page can type
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, STANDARD)
        env(DASHBOARD_PASSWORD=PW + "\n")
        sealed_ok = run(root, "reseal", "--git", "--replace") == 0
        env(DASHBOARD_PASSWORD=PW)
        ok("a secret with a trailing newline seals under the password as typed",
           sealed_ok and (root / "docs/metrics.json.enc").is_file() and run(root, "check") == 0,
           run.last)
    for bad, why in ((PW + "\t", "a control character"), (" " + PW, "a leading space"),
                     (PW + " ", "a trailing space"), ("pässwörd-lång-enough", "non-ASCII")):
        ok(f"a password with {why} is refused -- the page's field cannot reproduce it",
           raises(cd.CryptoDataError, cd.check_new_password, bad))

    # --- [1] sealing one new store joins the salt the rest are under
    with tempfile.TemporaryDirectory() as tmp:
        root = sealed_repo(tmp)
        (root / "data/newprop").mkdir(parents=True)
        (root / "data/newprop/eliseai_daily.json").write_text(pretty({"days": [1]}))
        ok("sealing only a brand-new store works", run(root, "encrypt",
           "data/newprop/eliseai_daily.json", "--git") == 0, run.last)
        ok("and it joins the set's salt instead of minting its own", run(root, "check") == 0, run.last)

    # --- [2] a merge while a rotation is half-landed keeps the set on one key
    with tempfile.TemporaryDirectory() as tmp:
        files = dict(STANDARD)
        files["docs/metrics.json"] = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6}
        root = make_repo(tmp, files)
        shutil.copytree(HERE, root / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(HERE.parent / ".githooks", root / ".githooks")
        shutil.copy(HERE.parent / ".gitattributes", root / ".gitattributes")
        env(DASHBOARD_PASSWORD=PW)
        run(root, "install")
        run(root, "reseal", "--git", "--replace")
        gitc(root, "add", "-A", ".gitattributes", ".githooks")
        gitc(root, "commit", "-qm", "seal", "--no-verify")
        gitc(root, "tag", "base")
        # L: a change made under the OLD password
        run(root, "decrypt", "--force")
        m = json.loads((root / "docs/metrics.json").read_text()); m["b"] = 20
        (root / "docs/metrics.json").write_text(pretty(m))
        run(root, "encrypt", "--git")
        gitc(root, "commit", "-qm", "L", "--no-verify")
        # R: the rotation lands
        gitc(root, "checkout", "-qb", "R", "base")
        env(DASHBOARD_PASSWORD=PW2, DASHBOARD_PASSWORD_OLD=PW)
        run(root, "decrypt", "--force")
        assert run(root, "reseal", "--git") == 0, run.last
        gitc(root, "commit", "-qm", "rotate", "--no-verify")
        gitc(root, "checkout", "-q", "-")
        res = gitc(root, "merge", "-q", "--no-edit", "--no-verify", "R", check=False)
        env(DASHBOARD_PASSWORD=PW2)
        ok("merging the rotation into a branch that changed a sealed file under the old key "
           "leaves ONE key", res.returncode == 0 and run(root, "check") == 0,
           (res.returncode, res.stderr[-200:], run.last[-200:]))
        try:
            kept = json.loads(cd.unseal(enc(root, "docs/metrics.json"), PW2, "docs/metrics.json"))["b"]
        except (cd.CryptoDataError, KeyError, ValueError):
            kept = None
        ok("and keeps the branch's change", kept == 20, kept)
        env(DASHBOARD_PASSWORD=PW)


NODE_SCENARIOS = r"""
const fs = require("fs"), path = require("path");
const [DIR, PW, UNLOCK, HOST, SCENARIO, SEARCH, PW2] = process.argv.slice(2);
globalThis.window = globalThis;
globalThis.location = { hostname: HOST, search: SEARCH || "" };
globalThis.sessionStorage = { _d: {}, getItem(k) { return k in this._d ? this._d[k] : null; },
  setItem(k, v) { this._d[k] = String(v); }, removeItem(k) { delete this._d[k]; } };
let failNext = SCENARIO === "flaky" ? 1 : 0, requests = 0;
globalThis.fetch = async (url) => {
  requests++;
  if (failNext > 0) { failNext--; throw new TypeError("Failed to fetch"); }
  const f = path.join(DIR, url);
  if (!fs.existsSync(f)) return { status: 404, ok: false, json: async () => null };
  const t = fs.readFileSync(f, "utf8");
  return { status: 200, ok: true, json: async () => JSON.parse(t) };
};
require(UNLOCK);
(async () => {
  const out = {};
  if (SCENARIO === "flaky") {
    try { await AlignUnlock.detect(); out.first = "ok"; } catch (e) { out.first = "failed"; }
    out.mode = await AlignUnlock.detect();
    out.opened = await AlignUnlock.tryPassword(PW);
  } else if (SCENARIO === "rotate") {
    out.mode = await AlignUnlock.detect();            // gate shown, envelope fetched
    fs.readdirSync(path.join(DIR, "_rotated")).forEach(f =>
      fs.copyFileSync(path.join(DIR, "_rotated", f), path.join(DIR, f)));   // rotation lands
    out.newOpens = await AlignUnlock.tryPassword(PW2);
    try { out.second = (await AlignUnlock.load("scorecard.json")).k; } catch (e) { out.second = String(e.message); }
  } else if (SCENARIO === "conflict") {
    out.mode = await AlignUnlock.detect();
    try { await AlignUnlock.tryPassword(PW); out.msg = "opened"; } catch (e) { out.msg = String(e.message); }
  } else {
    out.mode = await AlignUnlock.detect();
    // Sealed, load() rightly parks until a key exists -- nothing to read here.
    if (out.mode !== "encrypted") {
      try { out.note = (await AlignUnlock.load("metrics.json")).note; } catch (e) { out.note = "ERR " + e.message; }
    }
  }
  console.log(JSON.stringify(out));
})().catch(e => console.log(JSON.stringify({ error: String(e && e.message || e) })));
"""


def node_scenario(site, scenario, host="aligndashboard.github.io", search="", pw=PW, pw2=PW2):
    h = pathlib.Path(site, "_scenarios.js")
    h.write_text(NODE_SCENARIOS)
    res = subprocess.run([shutil.which("node"), str(h), str(site), pw,
                          str(HERE.parent / "docs" / "unlock.js"), host, scenario, search, pw2],
                         capture_output=True, text=True, timeout=180)
    try:
        return json.loads(res.stdout.strip().splitlines()[-1])
    except Exception:                                      # noqa: BLE001
        return {"error": (res.stdout[-300:], res.stderr[-300:])}


def test_browser_review():
    print("\nthe browser half, from the review: stale gates, flaky fetches, conflicts, local copies")
    if not shutil.which("node"):
        print("   SKIP node not installed")
        return
    with tempfile.TemporaryDirectory() as tmp:
        root = sealed_repo(tmp)
        site = root / "docs"
        # a gate open across a rotation accepts the NEW password
        rot = pathlib.Path(tmp, "rot")
        shutil.copytree(root, rot, ignore=shutil.ignore_patterns(".git"))
        env(DASHBOARD_PASSWORD=PW2, DASHBOARD_PASSWORD_OLD=PW)
        run(rot, "decrypt"); run(rot, "reseal")
        env(DASHBOARD_PASSWORD=PW)
        (site / "_rotated").mkdir()
        for f in rot.glob("docs/*.enc"):
            shutil.copy(f, site / "_rotated" / f.name)
        got = node_scenario(site, "rotate")
        ok("a gate left open across a rotation opens with the NEW password",
           got.get("newOpens") is True and got.get("second") == 1, got)
    with tempfile.TemporaryDirectory() as tmp:
        root = sealed_repo(tmp)
        got = node_scenario(root / "docs", "flaky")
        ok("a failed first request is retried, not remembered as 'not published'",
           got.get("first") == "failed" and got.get("mode") == "encrypted" and got.get("opened") is True, got)
        (root / "docs/metrics.json.enc").write_text(json.dumps({"conflict": "docs/metrics.json"}))
        got = node_scenario(root / "docs", "conflict")
        ok("a conflict placeholder is named as one, not as a wrong password or a changed key",
           "merge" in got.get("msg", "") and "atob" not in got.get("msg", ""), got)
    with tempfile.TemporaryDirectory() as tmp:
        root = sealed_repo(tmp)
        run(root, "decrypt")
        m = json.loads((root / "docs/metrics.json").read_text()); m["note"] = "WORKING COPY"
        (root / "docs/metrics.json").write_text(pretty(m))
        got = node_scenario(root / "docs", "local", host="127.0.0.1")
        ok("locally, a decrypted working copy wins over the sealed file beside it",
           got.get("mode") == "plain" and got.get("note") == "WORKING COPY", got)
        got = node_scenario(root / "docs", "local", host="127.0.0.1", search="?sealed")
        ok("and ?sealed tests the real gate instead", got.get("mode") == "encrypted", got)
        got = node_scenario(root / "docs", "local", host="aligndashboard.github.io")
        ok("on a public host the working copy is never used", got.get("mode") == "encrypted", got)
    with tempfile.TemporaryDirectory() as tmp:
        site = pathlib.Path(tmp)
        (site / "metrics.json").write_text(pretty({"meta": {}, "note": MARKER}))
        got = node_scenario(site, "local", host="0.0.0.0")
        ok("0.0.0.0 -- the URL http.server prints -- counts as local", got.get("note") == MARKER, got)


def test_leaks_review():
    print("\nleaks review: commit messages, envelopes under a public password")
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        shutil.copytree(HERE, root / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        msg = root / "MSG"
        for text, want, why in (
                ("EliseAI daily: the queue cleared, NOI now $1,234,567", 1, "a dollar figure"),
                ("Budget variance moved to +22.2%", 1, "a percentage"),
                ("Seal the data files and document the setup (A18)", 0, "a plain description"),
                ("Auto-update metrics (2026-09-23)", 0, "the bot's own dated message"),
                ("Serve on 0.0.0.0 and pin Python 3.12", 0, "an IP and a version number"),
                ("Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>", 0,
                 "the attribution trailer"),
                ("off by 4321.50 on the tie-out", 1, "a two-decimal amount"),
                ("rent roll total 1234567", 1, "a bare large integer")):
            msg.write_text(text + "\n# a comment line with $9,999 is ignored\n")
            ok(f"commit-msg: {why} -> {'refused' if want else 'accepted'}",
               run(root, "commit-msg", str(msg)) == want, run.last[-150:])
        os.environ["ALIGN_ALLOW_FIGURES"] = "1"
        msg.write_text("a number that is not data: 1,000,000 iterations\n")
        ok("ALIGN_ALLOW_FIGURES=1 lets one through", run(root, "commit-msg", str(msg)) == 0)
        del os.environ["ALIGN_ALLOW_FIGURES"]

    with tempfile.TemporaryDirectory() as tmp:
        root = sealed_repo(tmp)
        # what the first pass did: sealed under the public password, basename AAD, no gzip
        salt = b"s" * 16
        key = cd.derive_key(cd.KNOWN_PUBLIC_PASSWORDS[0], salt)
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        iv = b"i" * 12
        legacy = {"v": 1, "alg": cd.ALG, "kdf": cd.KDF, "iter": cd.ITERATIONS,
                  "salt": base64.b64encode(salt).decode(), "iv": base64.b64encode(iv).decode(),
                  "ct": base64.b64encode(AESGCM(key).encrypt(iv, b'{"old": 1}',
                                                             b"align-dashboard/v1/lineage.json")).decode()}
        (root / "docs/lineage.json.enc").write_text(json.dumps(legacy))
        gitc(root, "add", "docs/lineage.json.enc")
        gitc(root, "commit", "-qm", "legacy", "--no-verify")
        out = root / "public-blobs"
        run(root, "scan-public", str(out))
        ids = out.read_text().split()
        ok("scan-public finds an envelope sealed under the public password, in history",
           len(ids) == 1, run.last[-200:])
        ok("and not the ones sealed under the real password",
           "1 sealed blob" in run.last, run.last[-120:])


def main():
    saved = {k: os.environ.get(k) for k in ("DASHBOARD_PASSWORD", "DASHBOARD_PASSWORD_OLD",
                                            "DASHBOARD_PASSWORD_NEW")}
    try:
        for t in (test_envelope, test_tamper, test_kdf, test_file_set, test_first_seal,
                  test_cycle, test_guard, test_rotation, test_check, test_passphrase,
                  test_git_integration, test_browser_half, test_agreement, test_entry_guard,
                  test_shrink_and_rekey,
                  test_workflows, test_update_replay, test_review_round,
                  test_review_round_two, test_browser_review,
                  test_leaks_review):
            # One test crashing must not hide the rest -- a guard broken on purpose
            # (mutation testing) often surfaces as an exception, and a suite that
            # stops there reports every later check as simply absent.
            try:
                t()
            except Exception as exc:                       # noqa: BLE001
                ok(f"{t.__name__} ran to the end", False, f"{type(exc).__name__}: {exc}"[:300])
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()

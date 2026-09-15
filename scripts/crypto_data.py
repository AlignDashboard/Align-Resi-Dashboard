#!/usr/bin/env python3
"""Encrypt the dashboard's data files so the published site ships no plaintext.

The site is static and the repository is public, so every number the page draws
used to be one `curl` away: the password gate in index.html was a constant in
readable source, and docs/*.json sat beside it in the open. This is the other
half — the data is sealed with a key derived from that password, so the gate is
what actually stands between a stranger and the financials rather than a
formality in front of a file they could fetch directly.

    docs/metrics.json  ->  docs/metrics.json.enc

The envelope is JSON so it survives being served by GitHub Pages as a plain
static file, and every parameter the reader needs is inside it:

    {"v":1, "alg":"AES-256-GCM", "kdf":"PBKDF2-HMAC-SHA256", "iter":600000,
     "salt":"<b64>", "iv":"<b64>", "ct":"<b64>", "aad":"align-dashboard/v1/metrics.json"}

Chosen so the browser half needs no library at all -- WebCrypto does PBKDF2 and
AES-GCM natively, and Python's AESGCM returns ciphertext||tag, which is exactly
what SubtleCrypto.decrypt expects. docs/unlock.js is the other side of this
file; the two must be changed together.

Four things worth knowing about the format:

  * One salt per run, a fresh IV per file. One password derivation therefore
    unlocks all four files, which matters because the derivation is deliberately
    expensive. Reusing an IV under one key would break GCM outright, so those
    are never shared.
  * The filename is bound in as additional authenticated data. Without it a
    stranger could serve scorecard.json.enc in place of metrics.json.enc and the
    page would decrypt it happily; with it, a swapped file fails to open.
  * Unchanged data is not re-sealed. The salt and IV are random, so a plain
    re-encrypt would produce different bytes every night and the daily cron
    would commit a diff even on a day nothing moved. Encrypt opens the existing
    envelope first and leaves it alone when the plaintext matches.
  * Iterations live in the envelope rather than in the reader, so the cost can
    be raised later by re-encrypting and nothing on the page needs editing.

WHAT THIS DOES NOT DO. The ciphertext is public and the password is the only
secret, so an attacker can take the files away and guess offline at whatever
rate their hardware allows. 600,000 PBKDF2 iterations makes each guess cost
real time, but against a short or guessable password that is a speed bump, not
a wall. The protection is exactly as good as the passphrase -- see the rotation
note in CLAUDE.md.

Usage:
  python scripts/crypto_data.py encrypt              # docs/*.json -> docs/*.json.enc
  python scripts/crypto_data.py decrypt              # docs/*.json.enc -> docs/*.json
  python scripts/crypto_data.py check                # open each envelope, report
  python scripts/crypto_data.py rotate               # re-seal under a new password

The password comes from --password-file, then $DASHBOARD_PASSWORD, then an
interactive prompt. There is deliberately no --password flag: it would land in
shell history and in CI logs.
"""
import argparse
import base64
import getpass
import hashlib
import json
import os
import pathlib
import secrets
import subprocess
import sys

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:                                        # noqa: BLE001
    AESGCM = None

VERSION = 1
ALG = "AES-256-GCM"
KDF = "PBKDF2-HMAC-SHA256"
ITERATIONS = 600_000
SALT_BYTES = 16
IV_BYTES = 12                       # 96 bits, the GCM nonce size WebCrypto wants
KEY_BYTES = 32
SUFFIX = ".enc"

# The four files the page fetches. Kept in the same order as check_no_pii.PUBLISHED
# and publish_data.sh's FILES; all three lists describe the same set.
DATA_FILES = ["docs/metrics.json", "docs/landing.json",
              "docs/scorecard.json", "docs/lineage.json"]


class CryptoDataError(Exception):
    """Anything the caller should see as a clean failure rather than a traceback."""


class BadPassword(CryptoDataError):
    """The key did not open the envelope -- wrong password, or tampered bytes."""


def _b64e(b):
    return base64.b64encode(b).decode("ascii")


def _b64d(s):
    return base64.b64decode(s.encode("ascii"))


def aad_for(name):
    """What the ciphertext is bound to, so one file cannot be served as another."""
    return f"align-dashboard/v{VERSION}/{os.path.basename(name)}".encode("utf-8")


def derive_key(password, salt, iterations=ITERATIONS):
    """PBKDF2-HMAC-SHA256. Must stay identical to unlock.js's deriveBits call."""
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                               iterations, dklen=KEY_BYTES)


def seal(plaintext, key, name, salt, iterations=ITERATIONS):
    """Wrap bytes into an envelope dict. A fresh IV every time, never reused."""
    if AESGCM is None:
        raise CryptoDataError(
            "the 'cryptography' package is required: pip install -r requirements.txt")
    iv = secrets.token_bytes(IV_BYTES)
    ct = AESGCM(key).encrypt(iv, plaintext, aad_for(name))
    return {"v": VERSION, "alg": ALG, "kdf": KDF, "iter": iterations,
            "salt": _b64e(salt), "iv": _b64e(iv), "ct": _b64e(ct),
            "aad": aad_for(name).decode("utf-8")}


def unseal(env, password, name):
    """Open an envelope. Raises BadPassword on a wrong key or altered bytes.

    The version/algorithm checks are not ceremony: a future format read by this
    code would fail somewhere less obvious, and "decrypted to nonsense" is a
    worse failure than "refused to try".
    """
    if AESGCM is None:
        raise CryptoDataError(
            "the 'cryptography' package is required: pip install -r requirements.txt")
    if env.get("v") != VERSION:
        raise CryptoDataError(f"{name}: envelope version {env.get('v')!r}, expected {VERSION}")
    if env.get("alg") != ALG or env.get("kdf") != KDF:
        raise CryptoDataError(f"{name}: unexpected alg/kdf {env.get('alg')!r}/{env.get('kdf')!r}")
    iterations = env.get("iter")
    if not isinstance(iterations, int) or iterations < 1:
        raise CryptoDataError(f"{name}: bad iteration count {iterations!r}")
    key = derive_key(password, _b64d(env["salt"]), iterations)
    try:
        return AESGCM(key).decrypt(_b64d(env["iv"]), _b64d(env["ct"]), aad_for(name))
    except Exception as exc:                               # noqa: BLE001
        raise BadPassword(
            f"{name}: could not be decrypted -- wrong password, or the file has "
            f"been altered since it was sealed") from exc


# ----------------------------------------------------------------- password

def read_password(args, confirm=False, prompt="Dashboard password: ",
                  env_var="DASHBOARD_PASSWORD", file_attr="password_file"):
    """--password-file, then the environment, then a prompt. Never an argv flag."""
    path = getattr(args, file_attr, None)
    if path:
        pw = pathlib.Path(path).read_text(encoding="utf-8").strip("\r\n")
        if not pw:
            raise CryptoDataError(f"{path} is empty")
        return pw
    pw = os.environ.get(env_var)
    if pw:
        return pw
    if not sys.stdin.isatty():
        raise CryptoDataError(
            f"no password: set ${env_var}, pass --password-file, or run interactively")
    pw = getpass.getpass(prompt)
    if not pw:
        raise CryptoDataError("empty password")
    if confirm and getpass.getpass("Confirm: ") != pw:
        raise CryptoDataError("passwords did not match")
    return pw


# ----------------------------------------------------------------- commands

def _targets(args, suffix=""):
    names = args.files or DATA_FILES
    return [n + suffix for n in names]


def cmd_encrypt(args):
    password = read_password(args, confirm=True)
    salt = secrets.token_bytes(SALT_BYTES)
    wrote = skipped = 0
    for src in _targets(args):
        p = pathlib.Path(src)
        if not p.is_file():
            print(f"   SKIP {src} (not present)")
            continue
        plaintext = p.read_bytes()
        out = pathlib.Path(src + SUFFIX)

        # Re-sealing unchanged data would churn the file on every run, because
        # the salt and IV are random. Open what is already there and leave it be
        # when nothing moved, so the cron's "no changes to commit" still works.
        current = False
        if out.is_file():
            try:
                current = unseal(json.loads(out.read_text()), password, src) == plaintext
            except (CryptoDataError, ValueError, KeyError):
                current = False

        if current:
            print(f"   SAME {out} (plaintext unchanged, left alone)")
            skipped += 1
        else:
            key = derive_key(password, salt)
            out.write_text(json.dumps(seal(plaintext, key, src, salt)) + "\n", encoding="utf-8")
            print(f"   WROTE {out} ({len(plaintext):,} bytes -> {out.stat().st_size:,})")
            wrote += 1

        # Outside the branch on purpose. --replace is what keeps a deployed
        # artifact from carrying the plaintext beside the sealed copy, and an
        # already-current envelope is exactly when it would be easiest to forget
        # -- the file is left alone, so the plaintext would survive the one run
        # that looked like it had nothing to do.
        if args.replace:
            p.unlink()
            print(f"         removed plaintext {src}")
    print(f"\n{wrote} sealed, {skipped} already current")
    return 0


def cmd_decrypt(args):
    password = read_password(args)
    n = 0
    for src in _targets(args, SUFFIX):
        p = pathlib.Path(src)
        if not p.is_file():
            print(f"   SKIP {src} (not present)")
            continue
        out = pathlib.Path(src[:-len(SUFFIX)])
        plaintext = unseal(json.loads(p.read_text()), password, str(out))
        json.loads(plaintext)                              # refuse to write non-JSON
        out.write_bytes(plaintext)
        print(f"   WROTE {out} ({len(plaintext):,} bytes)")
        n += 1
    print(f"\n{n} opened")
    return 0


def cmd_check(args):
    """Open every envelope and confirm it still holds parseable JSON."""
    password = read_password(args)
    problems, seen = [], []
    for src in _targets(args, SUFFIX):
        p = pathlib.Path(src)
        if not p.is_file():
            print(f"   SKIP {src} (not present)")
            continue
        name = src[:-len(SUFFIX)]
        try:
            env = json.loads(p.read_text())
            plaintext = unseal(env, password, name)
            doc = json.loads(plaintext)
        except (CryptoDataError, ValueError) as exc:
            print(f"   FAIL {src}: {exc}")
            problems.append(str(exc))
            continue
        seen.append(env["salt"])
        gen = (doc.get("meta") or {}).get("generated_at", "—") if isinstance(doc, dict) else "—"
        print(f"   PASS {src}  iter={env['iter']:,}  {len(plaintext):,} bytes  generated {gen}")
    if len(set(seen)) > 1:
        # Not wrong, just slower: the page derives a key per distinct salt.
        print(f"\n   NOTE {len(set(seen))} different salts — the page will derive a key "
              f"for each. Re-run encrypt on all files together to share one.")
    if problems:
        print("\nFAIL: not every envelope opened", file=sys.stderr)
        return 1
    print("\nPASS: every envelope opens and holds JSON")
    return 0


def cmd_rotate(args):
    """Re-seal under a new password, so changing it does not mean a pipeline run."""
    old = read_password(args, prompt="Current password: ")
    new = read_password(args, confirm=True, prompt="New password: ",
                        env_var="DASHBOARD_PASSWORD_NEW",
                        file_attr="new_password_file")
    if old == new:
        raise CryptoDataError("the new password is the same as the current one")
    if len(new) < 12:
        # The ciphertext is public and guessable offline; a short password is the
        # whole attack. Refusing is kinder than a warning nobody reads.
        raise CryptoDataError(
            "new password is under 12 characters. The sealed files are public and "
            "can be attacked offline, so a short one is not worth the ceremony — "
            "use a passphrase.")
    salt = secrets.token_bytes(SALT_BYTES)
    opened = []
    for src in _targets(args, SUFFIX):
        p = pathlib.Path(src)
        if not p.is_file():
            print(f"   SKIP {src} (not present)")
            continue
        name = src[:-len(SUFFIX)]
        opened.append((p, name, unseal(json.loads(p.read_text()), old, name)))
    if not opened:
        raise CryptoDataError("nothing to rotate")
    # Every file opens before any is rewritten: a half-rotated set would leave
    # the page unable to show anything and no single password able to fix it.
    key = derive_key(new, salt)
    for p, name, plaintext in opened:
        p.write_text(json.dumps(seal(plaintext, key, name, salt)) + "\n", encoding="utf-8")
        print(f"   RESEALED {p}")
    print(f"\n{len(opened)} file(s) re-sealed under the new password.")
    print("Now update the DASHBOARD_PASSWORD repository secret to match, or the "
          "next pipeline run will not be able to open them.")
    return 0


COMMANDS = {"encrypt": cmd_encrypt, "decrypt": cmd_decrypt,
            "check": cmd_check, "rotate": cmd_rotate}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=sorted(COMMANDS))
    ap.add_argument("files", nargs="*",
                    help="plaintext paths (default: the four docs/*.json)")
    ap.add_argument("--password-file", help="read the password from this file")
    ap.add_argument("--new-password-file", help="rotate: read the new password from this file")
    ap.add_argument("--replace", action="store_true",
                    help="encrypt: delete the plaintext once it is sealed")
    args = ap.parse_args(argv)

    root = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True).stdout.strip()
    if root:
        os.chdir(root)
    try:
        return COMMANDS[args.command](args)
    except CryptoDataError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

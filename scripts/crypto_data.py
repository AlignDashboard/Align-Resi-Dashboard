#!/usr/bin/env python3
"""Seal the dashboard's data so the public repository and site carry ciphertext only.

The repository is public and the site is static, so every figure the pipeline
produces used to be readable by anyone: docs/*.json one `curl` from the live
page, data/<slug>/*.json one click from GitHub. Sealed, each becomes a sibling
`<name>.enc` holding AES-256-GCM ciphertext under a key derived from the
dashboard password, and the plaintext is gitignored -- a working copy that exists
only on a machine that has the password.

    docs/metrics.json            ->  docs/metrics.json.enc      (the page opens it)
    data/palma/monthly_pl.json   ->  data/palma/monthly_pl.json.enc  (the pipeline does)

docs/unlock.js is the browser half of this file. The two must change together.

THE ENVELOPE -- JSON, so GitHub Pages serves it as a static file, and complete,
so the reader needs nothing but the file:

    {"v":1, "alg":"AES-256-GCM", "kdf":"PBKDF2-HMAC-SHA256", "iter":600000,
     "salt":"<b64>", "iv":"<b64>", "zip":"gzip",
     "aad":"align-dashboard/v1/docs/metrics.json", "ct":"<b64>"}

Chosen so the browser needs no library: WebCrypto does PBKDF2 and AES-GCM, and
DecompressionStream does gzip. Things that are load-bearing:

  * The REPO-RELATIVE PATH is bound in as additional authenticated data. Not the
    basename: data/palma/monthly_pl.json and data/the-landing/monthly_pl.json
    share one, and a basename binding would let one property's figures open as
    the other's. With the path bound, a file served or committed under any other
    name fails to open.
  * One salt per PASSWORD, not per run. A run reuses the salt of whatever already
    opens under the password, so one derivation opens every file, and the key a
    browser tab derived this morning still opens tonight's re-seal. A fresh salt
    only comes with a new password. The IV is fresh for every envelope, always.
  * gzip before sealing. Ciphertext does not delta-compress in git, so every
    commit stores each changed file whole; compressing first makes that ~6-10x
    smaller, and the transfer to the browser with it.
  * Unchanged data is not re-sealed. The IV is random, so re-encrypting identical
    plaintext would still write different bytes and every cron run would commit
    a diff on data that never moved.

THE CHECKOUT GUARD. Ciphertext cannot be merged by eye, and a plaintext working
copy can go stale without anything looking wrong -- open the files, pull, and the
copy on disk now predates what main carries. Sealing that would silently
overwrite whatever arrived in between. So `decrypt` records, per file, the
envelope it opened and the plaintext it wrote (in the gitignored .sealed-state.json)
and `encrypt` refuses to seal a file whose sealed copy has moved since, or that
was never opened in this checkout at all -- the second being the other way to
lose data: a script that finds no plaintext, starts an empty history, and has the
truncated result sealed over the real one. `--force` overrides both, for the one
caller that means it (update.yml's push race, which replays its output over main
by design -- open item A15).

THE PASSWORD. From --password-file, then $DASHBOARD_PASSWORD, then a prompt. There
is no --password flag: it would land in shell history and in CI logs, which on a
public repository are public. $DASHBOARD_PASSWORD_OLD, when set, is tried as a
fallback for OPENING, never for sealing -- which is what makes rotation a matter
of changing the secret: every run opens under whichever works and seals under the
new one. The protection is exactly as strong as the passphrase: the ciphertext is
public and can be guessed at offline for ever.

Usage:
  crypto_data.py status               what is sealed, opened, changed
  crypto_data.py decrypt [--force]    open every sealed file into its working copy
  crypto_data.py encrypt [--git]      seal changed working copies (guarded)
  crypto_data.py reseal [--git]       open everything, seal all of it under $DASHBOARD_PASSWORD
                                      -- the first seal and every rotation (seal_data.yml)
  crypto_data.py rotate               reseal, prompting for the current and new passwords
  crypto_data.py check                open every envelope and confirm one key opens them all
  crypto_data.py passphrase           print a strong, typeable passphrase
  crypto_data.py install              git diff/merge drivers + hooks for this checkout
  crypto_data.py session-start        install, then decrypt if a password is available
  (textconv, merge-driver, pre-commit, post-sync are git's entry points)
"""
import argparse
import base64
import fnmatch
import getpass
import gzip
import hashlib
import json
import os
import pathlib
import secrets
import subprocess
import sys

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except Exception:                                          # noqa: BLE001
    # Not only ImportError: a system `cryptography` with a missing CFFI backend
    # raises a PanicException from Rust instead.
    AESGCM = None

VERSION = 1
ALG = "AES-256-GCM"
KDF = "PBKDF2-HMAC-SHA256"
ITERATIONS = 600_000
SALT_BYTES = 16
IV_BYTES = 12                        # 96 bits, the GCM nonce size WebCrypto wants
KEY_BYTES = 32
SUFFIX = ".enc"
AAD_PREFIX = f"align-dashboard/v{VERSION}/"
STATE_FILE = ".sealed-state.json"
MIN_PASSWORD = 12
# A working copy that shrinks by more than half (and by more than this many
# bytes) is refused at the seal. Ciphertext diffs show nothing, so this is what
# stands in for reading the diff: a history rebuilt from nothing, a block
# dropped by a bug. ALIGN_ALLOW_SHRINK=1 lets a deliberate one through.
SHRINK_FLOOR = 4096

# The four files the page fetches. docs/unlock.js asks for these by name.
PAGE_FILES = ["docs/metrics.json", "docs/landing.json",
              "docs/scorecard.json", "docs/lineage.json"]

# Everything sealed: the page's four, and every per-property store the pipeline
# accumulates. A new store under data/ is covered the day it appears, rather than
# the day someone remembers to list it -- the same reason build_metrics scrubs
# names centrally instead of per parser.
SEALED_GLOBS = PAGE_FILES + ["data/**/*.json"]

# Never sealed and never committed in ANY form. These are unit level and arrive
# with resident names; they are gitignored outright and exist only on the CI
# runner for the length of a run. Sealing them would put names in the repository
# encrypted -- still names, readable by every viewer the password is shared with,
# and by anyone at all the day the password leaks.
NEVER_SEAL = ["data/*/rent_roll.json", "data/*/delinquency.json"]

# Passwords that are public already, in this repository's history.
KNOWN_PUBLIC = {"alignexecs"}


class CryptoDataError(Exception):
    """A clean failure: printed as one line, never as a traceback."""


class BadPassword(CryptoDataError):
    """No available password opens the envelope, or its bytes were altered."""


# ------------------------------------------------------------------ primitives

def _b64e(b):
    return base64.b64encode(b).decode("ascii")


def _b64d(s):
    return base64.b64decode(s.encode("ascii"))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def aad_for(rel):
    """What a file's ciphertext is bound to: its repo-relative path."""
    rel = pathlib.PurePosixPath(str(rel).replace(os.sep, "/")).as_posix()
    return (AAD_PREFIX + rel).encode("utf-8")


def derive_key(password, salt, iterations=ITERATIONS):
    """PBKDF2-HMAC-SHA256. Must stay identical to unlock.js's deriveBits call."""
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                               iterations, dklen=KEY_BYTES)


def _need_aes():
    if AESGCM is None:
        raise CryptoDataError(
            "the 'cryptography' package is required: pip install -r requirements.txt")


def seal(plaintext, key, rel, salt, iterations=ITERATIONS):
    """Plaintext bytes -> envelope dict. A fresh IV every call, never reused."""
    _need_aes()
    iv = secrets.token_bytes(IV_BYTES)
    body = gzip.compress(plaintext, mtime=0)
    ct = AESGCM(key).encrypt(iv, body, aad_for(rel))
    return {"v": VERSION, "alg": ALG, "kdf": KDF, "iter": iterations,
            "salt": _b64e(salt), "iv": _b64e(iv), "zip": "gzip",
            "aad": aad_for(rel).decode("utf-8"), "ct": _b64e(ct)}


def check_envelope(env, rel):
    """Refuse a format this code does not read, rather than guess at it."""
    if not isinstance(env, dict):
        raise CryptoDataError(f"{rel}: not an envelope")
    if env.get("v") != VERSION:
        raise CryptoDataError(f"{rel}: envelope version {env.get('v')!r}, expected {VERSION}")
    if env.get("alg") != ALG or env.get("kdf") != KDF:
        raise CryptoDataError(f"{rel}: unexpected alg/kdf {env.get('alg')!r}/{env.get('kdf')!r}")
    it = env.get("iter")
    if not isinstance(it, int) or it < 1:
        raise CryptoDataError(f"{rel}: bad iteration count {it!r}")
    if env.get("zip") not in (None, "gzip"):
        raise CryptoDataError(f"{rel}: unknown compression {env.get('zip')!r}")


def unseal_with_key(env, key, rel):
    _need_aes()
    check_envelope(env, rel)
    try:
        body = AESGCM(key).decrypt(_b64d(env["iv"]), _b64d(env["ct"]), aad_for(rel))
    except Exception as exc:                               # noqa: BLE001
        raise BadPassword(f"{rel}: could not be opened -- wrong password, a file "
                          f"sealed under another name, or altered bytes") from exc
    return gzip.decompress(body) if env.get("zip") == "gzip" else body


class Keyring:
    """Passwords to try, and the keys derived from them, memoised.

    The derivation is deliberately slow, so a run that opens thirty files under
    one salt derives once rather than thirty times.
    """

    def __init__(self, passwords):
        self.passwords = [p for p in passwords if p]
        self._keys = {}

    def key(self, password, salt, iterations):
        k = (password, salt, iterations)
        if k not in self._keys:
            self._keys[k] = derive_key(password, salt, iterations)
        return self._keys[k]

    def open(self, env, rel):
        """-> (plaintext, password that opened it)."""
        check_envelope(env, rel)
        salt = _b64d(env["salt"])
        for pw in self.passwords:
            try:
                return unseal_with_key(env, self.key(pw, salt, env["iter"]), rel), pw
            except BadPassword:
                continue
        raise BadPassword(f"{rel}: no available password opens it -- wrong password, "
                          f"a file sealed under another name, or altered bytes")

    def opens_under(self, env, rel, password):
        try:
            unseal_with_key(env, self.key(password, _b64d(env["salt"]), env["iter"]), rel)
            return True
        except CryptoDataError:
            return False


def unseal(env, password, rel):
    """One-password convenience wrapper."""
    return Keyring([password]).open(env, rel)[0]


# ------------------------------------------------------------------ the file set

def _rel(path, root):
    return pathlib.Path(path).resolve().relative_to(root.resolve()).as_posix()


def never_sealed(rel):
    return any(fnmatch.fnmatch(rel, pat) for pat in NEVER_SEAL)


def sealed_set(root):
    """Every plaintext path that is, or should be, sealed -- repo-relative, sorted.

    The union of what exists in plaintext and what exists sealed, so a file shows
    up whether this checkout has opened it or not.
    """
    out = set()
    for pat in SEALED_GLOBS:
        for p in root.glob(pat):
            if p.is_file():
                out.add(_rel(p, root))
        for p in root.glob(pat + SUFFIX):
            if p.is_file():
                out.add(_rel(p, root)[:-len(SUFFIX)])
    return sorted(r for r in out if not never_sealed(r))


def select(root, only):
    everything = sealed_set(root)
    if not only:
        return everything
    want = {_rel(root / o if not os.path.isabs(o) else o, root).removesuffix(SUFFIX)
            for o in only}
    unknown = sorted(want - set(everything))
    if unknown:
        raise CryptoDataError(f"not in the sealed set: {', '.join(unknown)}")
    return [r for r in everything if r in want]


def read_env(root, rel):
    raw = (root / (rel + SUFFIX)).read_bytes()
    try:
        return json.loads(raw), raw
    except ValueError as exc:
        raise CryptoDataError(f"{rel}{SUFFIX}: not JSON -- truncated or not an envelope") from exc


def write_env(root, rel, env):
    raw = (json.dumps(env) + "\n").encode("utf-8")
    (root / (rel + SUFFIX)).write_bytes(raw)
    return raw


def mode(root):
    """'sealed' once anything is sealed, 'unsealed' before, for the whole repo."""
    return "sealed" if any((root / (r + SUFFIX)).is_file() for r in sealed_set(root)) \
        else "unsealed"


# ------------------------------------------------------------------ checkout state

def load_state(root):
    p = root / STATE_FILE
    try:
        return json.loads(p.read_text()) if p.is_file() else {}
    except ValueError:
        return {}


def save_state(root, state):
    (root / STATE_FILE).write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")


# ------------------------------------------------------------------ the entry guard

def _toplevel():
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                         text=True).stdout.strip()
    return pathlib.Path(top or ".").resolve()


def unopened(root):
    """-> sealed files whose working copy is missing, stale, or of unknown origin."""
    if mode(root) != "sealed":
        return []
    state, out = load_state(root), []
    for rel in sealed_set(root):
        enc = root / (rel + SUFFIX)
        if not enc.is_file():
            continue                          # a new store, not sealed yet: nothing to open
        st = state.get(rel)
        if not (root / rel).is_file() or not st or st.get("plain") is None:
            out.append((rel, "not opened"))
        elif st.get("env") != sha(enc.read_bytes()):
            out.append((rel, "stale -- the sealed copy moved since it was opened"))
    return out


def require_opened(who, root=None):
    """Refuse to run a pipeline script against a sealed checkout that is not open.

    Every script that reads last run's output does so as `json.load(open(fp)) if
    fp.exists() else <empty>`, so on a checkout where only the sealed copies exist
    it would not fail -- it would start the history over, and the truncated result
    would be sealed over the real one with every step green. Called from each
    script's command-line entry point (not from main(), which tests drive
    directly against temp dirs), so the refusal comes before any work, not four
    hours in at the seal.
    """
    root = pathlib.Path(root).resolve() if root else _toplevel()
    bad = unopened(root)
    if not bad:
        return
    shown = "\n".join(f"    {r}: {why}" for r, why in bad[:8])
    more = f"\n    ... and {len(bad) - 8} more" if len(bad) > 8 else ""
    sys.stderr.write(
        f"{who}: {len(bad)} sealed data file(s) are not open in this checkout:\n"
        f"{shown}{more}\n"
        f"Run `python3 scripts/crypto_data.py decrypt` first (needs DASHBOARD_PASSWORD). "
        f"Without it this would build from missing history, and the result would be "
        f"sealed over the real data.\n")
    sys.exit(2)


# ------------------------------------------------------------------ passwords

def check_new_password(pw):
    if pw.strip().lower() in KNOWN_PUBLIC:
        raise CryptoDataError(
            "that password is public -- it sat in index.html in this repository's "
            "history. Choose a new one: crypto_data.py passphrase prints a strong one.")
    if len(pw) < MIN_PASSWORD:
        raise CryptoDataError(
            f"the password is under {MIN_PASSWORD} characters. The sealed files are "
            f"public and can be attacked offline, so a short one protects nothing -- "
            f"use a passphrase (crypto_data.py passphrase prints one).")


def read_password(args, confirm=False, prompt="Dashboard password: ",
                  env_var="DASHBOARD_PASSWORD", file_attr="password_file"):
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
        raise CryptoDataError(f"no password: set ${env_var}, pass --password-file, "
                              f"or run interactively")
    pw = getpass.getpass(prompt)
    if not pw:
        raise CryptoDataError("empty password")
    if confirm and getpass.getpass("Confirm: ") != pw:
        raise CryptoDataError("passwords did not match")
    return pw


def keyring_for(args, confirm=False):
    """-> (the password to seal under, a Keyring that also tries the old one)."""
    primary = read_password(args, confirm=confirm)
    old = os.environ.get("DASHBOARD_PASSWORD_OLD") or ""
    return primary, Keyring([primary] + ([old] if old and old != primary else []))


def canonical_salt(root, rels, ring, password):
    """-> (salt, fresh). The salt already in use under this password, or a new one.

    Reusing it is what keeps one derivation opening every file, and a browser tab
    unlocked this morning still opening tonight's re-seal. `fresh` means nothing
    opens under this password yet -- a first seal or a rotation -- which is the
    one moment a weak or public password could get baked in, so callers check it.
    """
    for rel in rels:
        if (root / (rel + SUFFIX)).is_file():
            env, _ = read_env(root, rel)
            if env.get("iter") == ITERATIONS and ring.opens_under(env, rel, password):
                return _b64d(env["salt"]), False
    return secrets.token_bytes(SALT_BYTES), True


# ------------------------------------------------------------------ git helpers

def git(root, *args, check=True):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          text=True, check=check)


def git_stage(root, rel):
    """Stage the sealed copy and take the plaintext out of the index."""
    git(root, "rm", "--cached", "--quiet", "--ignore-unmatch", "--", rel)
    git(root, "add", "--", rel + SUFFIX)


# ------------------------------------------------------------------ commands

def cmd_status(args, root):
    state = load_state(root)
    rels = sealed_set(root)
    print(f"mode: {mode(root)}  ({len(rels)} files in the sealed set)")
    rows = {"sealed": 0, "opened": 0, "changed": 0, "unsealed": 0, "stale": 0}
    for rel in rels:
        enc, plain = root / (rel + SUFFIX), root / rel
        st = state.get(rel)
        if not enc.is_file():
            rows["unsealed"] += 1
            print(f"   UNSEALED {rel}")
            continue
        rows["sealed"] += 1
        if not plain.is_file():
            continue
        rows["opened"] += 1
        env_moved = st is None or st.get("env") != sha(enc.read_bytes())
        changed = st is None or st.get("plain") != sha(plain.read_bytes())
        if env_moved:
            rows["stale"] += 1
            print(f"   STALE    {rel}  (the sealed copy moved since it was opened)")
        elif changed:
            rows["changed"] += 1
            print(f"   CHANGED  {rel}")
    print("   " + ", ".join(f"{v} {k}" for k, v in rows.items()))
    return 0


def cmd_decrypt(args, root):
    """Open sealed files into working copies, without clobbering local changes."""
    rels = [r for r in select(root, args.files) if (root / (r + SUFFIX)).is_file()]
    if not rels:
        if not args.quiet:
            print("nothing sealed to open")
        return 0
    _, ring = keyring_for(args)
    state = load_state(root)
    opened = kept = same = 0
    conflicts = []
    for rel in rels:
        env, raw = read_env(root, rel)
        env_sha = sha(raw)
        plain_p = root / rel
        st = state.get(rel)
        if plain_p.is_file() and not args.force:
            cur = sha(plain_p.read_bytes())
            if st and st.get("env") == env_sha:
                if st.get("plain") == cur:
                    same += 1
                else:
                    kept += 1
                    if not args.quiet:
                        print(f"   KEPT     {rel} (local changes, sealed copy unchanged)")
                continue
            if not st or st.get("plain") != cur:
                # Changed locally AND the sealed copy moved on (or the working
                # copy is of unknown origin). Either one could be the real data.
                plaintext, _ = ring.open(env, rel)
                if sha(plaintext) == cur:
                    state[rel] = {"env": env_sha, "plain": cur}
                    same += 1
                    continue
                conflicts.append(rel)
                print(f"   CONFLICT {rel} -- changed here, and the sealed copy moved on "
                      f"since it was opened. Keep yours: encrypt --force. Take the "
                      f"sealed one: decrypt --force.")
                continue
        plaintext, _ = ring.open(env, rel)
        try:
            json.loads(plaintext)
        except ValueError as exc:
            raise CryptoDataError(f"{rel}: opened, but is not JSON") from exc
        plain_p.parent.mkdir(parents=True, exist_ok=True)
        plain_p.write_bytes(plaintext)
        state[rel] = {"env": env_sha, "plain": sha(plaintext)}
        opened += 1
        if not args.quiet:
            print(f"   OPENED   {rel}")
    save_state(root, state)
    if not args.quiet or conflicts:
        print(f"{opened} opened, {same} already current, {kept} kept with local changes, "
              f"{len(conflicts)} conflicts")
    return 1 if conflicts else 0


def _seal_all(root, rels, ring, password, state, plaintexts, *, reason_same=True,
              replace=False, stage=False, quiet=False):
    """Write envelopes for {rel: plaintext}, skipping ones already current."""
    salt, fresh = canonical_salt(root, rels, ring, password)
    if fresh:
        check_new_password(password)       # raises before anything is written
    key = ring.key(password, salt, ITERATIONS)
    wrote = same = 0
    for rel in rels:
        if rel not in plaintexts:
            continue
        plaintext = plaintexts[rel]
        enc = root / (rel + SUFFIX)
        if enc.is_file() and reason_same:
            env, _ = read_env(root, rel)
            if (env.get("salt") == _b64e(salt) and env.get("iter") == ITERATIONS
                    and ring.opens_under(env, rel, password)
                    and unseal_with_key(env, key, rel) == plaintext):
                same += 1
                state[rel] = {"env": sha(enc.read_bytes()), "plain": sha(plaintext)}
                if replace:
                    _drop_working_copy(root, rel, state)
                if stage:
                    git_stage(root, rel)
                continue
        raw = write_env(root, rel, seal(plaintext, key, rel, salt))
        state[rel] = {"env": sha(raw), "plain": sha(plaintext)}
        wrote += 1
        if not quiet:
            print(f"   SEALED   {rel}  ({len(plaintext):,} -> {len(raw):,} bytes)")
        if replace:
            _drop_working_copy(root, rel, state)
        if stage:
            git_stage(root, rel)
    return wrote, same


def _drop_working_copy(root, rel, state):
    """Delete a working copy AND forget it was ever opened.

    Leaving the record behind is what would let a script that later recreates
    the file from nothing pass for an ordinary edit of an opened one -- exactly
    the truncated-history seal the guard exists to stop.
    """
    if (root / rel).is_file():
        (root / rel).unlink()
    if rel in state:
        state[rel] = {"env": state[rel].get("env")}


def cmd_encrypt(args, root):
    """Seal changed working copies -- only ones opened from the current sealed copy."""
    password, ring = keyring_for(args, confirm=True)
    rels = select(root, args.files)
    state = load_state(root)
    todo, refused = {}, []
    for rel in rels:
        plain_p, enc = root / rel, root / (rel + SUFFIX)
        if not plain_p.is_file():
            continue
        plaintext = plain_p.read_bytes()
        try:
            json.loads(plaintext)
        except ValueError:
            refused.append(f"{rel}: the working copy is not valid JSON")
            continue
        if enc.is_file() and not args.force:
            st = state.get(rel)
            now = sha(enc.read_bytes())
            if st is None or st.get("plain") is None:
                refused.append(f"{rel}: never opened in this checkout -- sealing it could "
                               f"overwrite history it was built without. Run decrypt first.")
                continue
            if st.get("env") != now:
                refused.append(f"{rel}: the sealed copy changed since it was opened "
                               f"(a pull brought a newer one). Run decrypt, redo the change.")
                continue
        todo[rel] = plaintext
    # Shrinkage. A sealed file cannot be diffed by eye, so a history rebuilt
    # from nothing looks exactly like a normal day -- refuse the obvious case.
    if os.environ.get("ALIGN_ALLOW_SHRINK") != "1":
        for rel, plaintext in list(todo.items()):
            enc = root / (rel + SUFFIX)
            if not enc.is_file():
                continue
            try:
                before, _ = ring.open(read_env(root, rel)[0], rel)
            except CryptoDataError:
                continue
            if len(plaintext) * 2 < len(before) and len(before) - len(plaintext) > SHRINK_FLOOR:
                refused.append(f"{rel}: shrank from {len(before):,} to {len(plaintext):,} bytes "
                               f"-- a history rebuilt from nothing looks like this. If it is "
                               f"deliberate, set ALIGN_ALLOW_SHRINK=1.")
    # A new key for only some of the files. Sealing changed files under a password
    # the rest are not under would leave the set split across two keys, which
    # the page cannot open. Minting a new key is only right when every sealed
    # file is being re-sealed with it -- a rotation, done by reseal or by a run
    # that opened everything under DASHBOARD_PASSWORD_OLD.
    if todo and mode(root) == "sealed" and canonical_salt(root, rels, ring, password)[1]:
        sealed_now = {r for r in rels if (root / (r + SUFFIX)).is_file()}
        left = sorted(sealed_now - set(todo))
        if left:
            refused.append(f"DASHBOARD_PASSWORD opens none of the sealed files, and {len(left)} "
                           f"of them (e.g. {left[0]}) are not open here to be re-keyed. To change "
                           f"the password, set DASHBOARD_PASSWORD_OLD and run reseal.")
    if refused:
        # All or nothing: a partial seal leaves a commit half from this run and
        # half from before, which is worse than either.
        for r in refused:
            print(f"   REFUSED  {r}", file=sys.stderr)
        raise CryptoDataError(f"{len(refused)} problem(s); nothing was sealed")
    if not todo:
        if not args.quiet:
            print("no working copies to seal")
        return 0
    wrote, same = _seal_all(root, rels, ring, password, state, todo,
                            replace=args.replace, stage=args.git, quiet=args.quiet)
    save_state(root, state)
    if not args.quiet:
        print(f"{wrote} sealed, {same} already current")
    return 0


def cmd_reseal(args, root, password=None, ring=None):
    """Open everything and seal all of it under one password. First seal, and rotation.

    Every file is opened before any is rewritten. A rotation that failed halfway
    would leave some files under the old password and some under the new, and no
    single password able to show the dashboard.
    """
    if password is None:
        password, ring = keyring_for(args, confirm=True)
    rels = select(root, args.files)
    plaintexts = {}
    tracked = set(git(root, "ls-files", check=False).stdout.split())
    for rel in rels:
        enc, plain_p = root / (rel + SUFFIX), root / rel
        if enc.is_file():
            env, _ = read_env(root, rel)
            plaintexts[rel], _ = ring.open(env, rel)
            if rel in tracked and plain_p.is_file() and plain_p.read_bytes() != plaintexts[rel]:
                # Plaintext committed beside its sealed copy -- a cutover race, a
                # force-add, a rebase that re-added it. This is the case
                # seal_data.yml exists to repair, so settle it rather than refuse:
                # the one committed more recently is the current data.
                if _commit_time(root, rel) > _commit_time(root, rel + SUFFIX):
                    plaintexts[rel] = plain_p.read_bytes()
                    print(f"   ADOPTED  {rel} (committed after its sealed copy)")
            elif plain_p.is_file() and plain_p.read_bytes() != plaintexts[rel] and not args.force:
                raise CryptoDataError(
                    f"{rel}: the working copy differs from the sealed copy. Seal or "
                    f"discard it first (encrypt, or decrypt --force), then reseal.")
        elif plain_p.is_file():
            plaintexts[rel] = plain_p.read_bytes()          # never sealed yet
    if not plaintexts:
        print("nothing to seal")
        return 0
    state = load_state(root)
    wrote, same = _seal_all(root, rels, ring, password, state, plaintexts,
                            replace=args.replace, stage=args.git)
    save_state(root, state)
    print(f"{wrote} sealed, {same} already current under this password")
    return 0


def _commit_time(root, path):
    out = git(root, "log", "-1", "--format=%ct", "--", path, check=False).stdout.strip()
    return int(out) if out.isdigit() else 0


def cmd_rotate(args, root):
    old = read_password(args, prompt="Current password: ")
    new = read_password(args, confirm=True, prompt="New password: ",
                        env_var="DASHBOARD_PASSWORD_NEW", file_attr="new_password_file")
    if old == new:
        raise CryptoDataError("the new password is the same as the current one")
    check_new_password(new)
    rc = cmd_reseal(args, root, password=new, ring=Keyring([new, old]))
    print("Now set the DASHBOARD_PASSWORD repository secret (and the Claude "
          "environment's variable) to the new password, or the next run cannot "
          "open its own data.")
    return rc


def cmd_untrack(args, root):
    """Take plaintext out of the index wherever its sealed copy exists. No password.

    For the cron's push-retry, which resets to main and restores this run's
    sealed files: if main still tracked plaintext (the race with the first seal),
    the plaintext comes back into the index with the reset and has to go again.
    """
    tracked = set(git(root, "ls-files").stdout.split())
    n = 0
    for rel in sealed_set(root):
        if rel in tracked and (root / (rel + SUFFIX)).is_file():
            git(root, "rm", "--cached", "--quiet", "--", rel)
            n += 1
    if n and not args.quiet:
        print(f"{n} plaintext file(s) taken out of the index")
    return 0


def cmd_check(args, root):
    rels = [r for r in select(root, args.files) if (root / (r + SUFFIX)).is_file()]
    if not rels:
        print("nothing sealed")
        return 0
    password, ring = keyring_for(args)
    salts, problems = set(), []
    for rel in rels:
        try:
            env, _ = read_env(root, rel)
            plaintext, used = ring.open(env, rel)
            json.loads(plaintext)
            salts.add(env["salt"])
            if used != password and not getattr(args, "allow_old", False):
                # Strict by default (the check after a seal). The pre-flight passes
                # --allow-old: files under the old password are a rotation in
                # progress that this very run will complete, not a failure.
                problems.append(f"{rel}: opens only under DASHBOARD_PASSWORD_OLD")
        except (CryptoDataError, ValueError) as exc:
            problems.append(str(exc))
    if len(salts) > 1:
        problems.append(f"{len(salts)} different salts -- the browser would derive a key "
                        f"for each. Run reseal to put everything under one.")
    for p in problems:
        print(f"   FAIL {p}")
    print(f"{len(rels) - len(problems)}/{len(rels)} open cleanly under one key"
          if not problems else f"FAIL: {len(problems)} problem(s)")
    return 1 if problems else 0


def cmd_passphrase(args, root):
    """Twenty characters from an unambiguous alphabet, in fives -- ~99 bits.

    Strong enough that offline guessing against the public ciphertext is not a
    plan, and typeable by the people who have to type it. Printed to this
    terminal only: never run it in CI, where the log is public.
    """
    if os.environ.get("GITHUB_ACTIONS") == "true":
        raise CryptoDataError("refusing to print a password into a GitHub Actions log")
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"         # no l/1, o/0, i
    groups = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(5)]
    print("-".join(groups))
    return 0


# ------------------------------------------------------------------ git integration

HOOKS_DIR = ".githooks"


def cmd_install(args, root):
    """Teach this checkout's git to diff, merge and guard sealed files."""
    py = "python3 scripts/crypto_data.py"
    for k, v in [("diff.alignenc.textconv", f"{py} textconv"),
                 ("diff.alignenc.cachetextconv", "false"),
                 ("merge.alignenc.name", "open, 3-way merge and re-seal sealed data"),
                 ("merge.alignenc.driver", f"{py} merge-driver %O %A %B %P"),
                 ("core.hooksPath", HOOKS_DIR)]:
        git(root, "config", k, v)
    if not args.quiet:
        print(f"git: sealed files now diff as plaintext, merge through a re-seal, and "
              f"{HOOKS_DIR}/ guards commits")
    return 0


def cmd_session_start(args, root):
    """Claude Code SessionStart hook. Prints what the session needs to know."""
    try:
        cmd_install(argparse.Namespace(quiet=True), root)
    except subprocess.CalledProcessError:
        pass
    m = mode(root)
    if m != "sealed":
        print("[sealed data] this checkout is not sealed yet; nothing to open.")
        return 0
    if not os.environ.get("DASHBOARD_PASSWORD"):
        print("[sealed data] The data files are sealed and DASHBOARD_PASSWORD is not set "
              "in this environment, so docs/*.json and data/**/*.json are NOT on disk. "
              "Do not run the pipeline or any populate_* script: with no history they "
              "would build from nothing. Ask the owner to add DASHBOARD_PASSWORD to the "
              "environment's variables.")
        return 0
    rc = cmd_decrypt(argparse.Namespace(files=[], force=False, quiet=True,
                                        password_file=None), root)
    print("[sealed data] opened the sealed data files into their working copies. Edit "
          "the plaintext as usual; before committing a data change run "
          "`python3 scripts/crypto_data.py encrypt --git`. After a pull, run "
          "`python3 scripts/crypto_data.py decrypt` (git hooks do both where installed). "
          "Never commit plaintext docs/*.json or data/**/*.json.")
    return rc


def cmd_textconv(args, root):
    """git diff shows a sealed file as its plaintext when the password is here."""
    p = pathlib.Path(args.files[0])
    raw = p.read_bytes()
    try:
        env = json.loads(raw)
        rel = env["aad"][len(AAD_PREFIX):] if str(env.get("aad", "")).startswith(AAD_PREFIX) \
            else None
        pw = os.environ.get("DASHBOARD_PASSWORD")
        if rel and pw:
            old = os.environ.get("DASHBOARD_PASSWORD_OLD")
            sys.stdout.write(Keyring([pw, old]).open(env, rel)[0].decode("utf-8"))
            return 0
    except Exception:                                      # noqa: BLE001
        pass
    sys.stdout.write("<sealed: set DASHBOARD_PASSWORD to diff the contents>\n")
    return 0


def cmd_merge_driver(args, root):
    """git merge driver: open base/ours/theirs, 3-way merge the JSON text, re-seal.

    Without it every concurrent change to one sealed file is a conflict, since
    ciphertext is one line; with it they merge exactly as the plaintext did. On
    a real conflict it leaves ours in place and reports failure, so git stops.
    """
    base_p, ours_p, theirs_p, rel = args.files[:4]
    rel = rel.removesuffix(SUFFIX)
    pw = os.environ.get("DASHBOARD_PASSWORD")
    if not pw:
        print(f"[alignenc] {rel}: DASHBOARD_PASSWORD not set; cannot merge sealed files",
              file=sys.stderr)
        return 1
    old = os.environ.get("DASHBOARD_PASSWORD_OLD")
    ring = Keyring([pw, old])

    def opened(p):
        raw = pathlib.Path(p).read_bytes()
        if not raw.strip():
            return b""
        return ring.open(json.loads(raw), rel)[0]

    import tempfile
    try:
        parts = [opened(base_p), opened(ours_p), opened(theirs_p)]
    except CryptoDataError as exc:
        print(f"[alignenc] {exc}", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for name, data in zip(("ours", "base", "theirs"), (parts[1], parts[0], parts[2])):
            q = pathlib.Path(tmp, name)
            q.write_bytes(data)
            paths.append(str(q))
        res = subprocess.run(["git", "merge-file", "-p", *paths], capture_output=True)
    if res.returncode != 0:
        # Leaving ours in place would leave a perfectly valid envelope with no
        # conflict markers, and the natural `git add` + continue would then keep
        # one side without a trace. So the file becomes something nothing will
        # accept -- decrypt, check, pre-commit and the page all refuse it -- and
        # an unresolved conflict fails loudly wherever it goes next.
        pathlib.Path(ours_p).write_text(json.dumps({
            "conflict": rel,
            "resolve": "both sides changed the same lines. Take one side's .enc "
                       "(git checkout --ours/--theirs), decrypt, redo the other "
                       "side's change, encrypt --git."}) + "\n")
        print(f"[alignenc] {rel}: the two sides changed the same lines -- resolve by "
              f"hand (take one side, decrypt, redo the other's change, encrypt --git)",
              file=sys.stderr)
        return 1
    try:
        json.loads(res.stdout)
    except ValueError:
        print(f"[alignenc] {rel}: the merged text is not valid JSON", file=sys.stderr)
        return 1
    # Re-seal under the salt the rest of the checkout uses, so a merge does not
    # leave one file on its own key (the browser would have to derive twice).
    salt, fresh = canonical_salt(root, sealed_set(root), ring, pw)
    if fresh:
        check_new_password(pw)
    merged = seal(res.stdout, ring.key(pw, salt, ITERATIONS), rel, salt)
    pathlib.Path(ours_p).write_text(json.dumps(merged) + "\n")
    return 0


def cmd_pre_commit(args, root):
    """git pre-commit hook: no plaintext data in a commit, and no unsealed change left behind."""
    if mode(root) != "sealed":
        return 0
    rels = set(sealed_set(root))
    staged = git(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR").stdout.split()
    clear = [f for f in staged if f in rels]
    state = load_state(root)
    unsealed = [r for r in rels if (root / r).is_file() and (
        # a new store: plaintext with no sealed copy, in a repo that seals
        not (root / (r + SUFFIX)).is_file()
        # or an opened one that changed and was not re-sealed
        or (state.get(r) and state[r].get("plain") != sha((root / r).read_bytes())))]
    bad_env = []
    for f in staged:
        if f.endswith(SUFFIX) and f[:-len(SUFFIX)] in rels:
            try:
                check_envelope(json.loads(git(root, "show", f":{f}").stdout), f)
            except (CryptoDataError, ValueError):
                bad_env.append(f)
    if bad_env:
        print("pre-commit: these staged sealed files are not envelopes -- an unresolved "
              "merge conflict, or a broken file:\n  " + "\n  ".join(bad_env), file=sys.stderr)
        return 1
    if not clear and not unsealed:
        return 0
    if clear:
        print("pre-commit: plaintext data is staged -- the repository is public:\n  "
              + "\n  ".join(clear) + "\nUnstage it (git restore --staged <file>) and run "
              "`python3 scripts/crypto_data.py encrypt --git` to commit the sealed copy.",
              file=sys.stderr)
    if unsealed:
        print("pre-commit: these working copies changed and are not sealed, so this commit "
              "would leave the change behind:\n  " + "\n  ".join(sorted(unsealed)) +
              "\nSeal and stage them: `python3 scripts/crypto_data.py encrypt --git`. "
              "Or discard them: `python3 scripts/crypto_data.py decrypt --force`.",
              file=sys.stderr)
    return 1


def _tree_plaintext(root, sha):
    """Sealed-set plaintext paths in a commit's tree, if that tree seals anything."""
    names = git(root, "ls-tree", "-r", "--name-only", sha, check=False).stdout.split()
    if not any(n.endswith(SUFFIX) for n in names):
        return []                                   # an unsealed tree: nothing to protect
    def sealable(n):
        return any(fnmatch.fnmatch(n, g) for g in SEALED_GLOBS) and not never_sealed(n)
    return sorted(n for n in names if sealable(n))


def cmd_pre_push(args, root):
    """git pre-push hook: refuse to push a sealed tree that also carries plaintext.

    pre-commit does not run on `rebase --continue` or `commit --no-verify`, and a
    conflict at the cutover resolves naturally into exactly this: the plaintext
    re-added beside its sealed copy. Checked on what is actually being pushed.
    """
    bad = []
    for line in sys.stdin.read().splitlines():
        parts = line.split()
        if len(parts) != 4 or set(parts[1]) == {"0"}:
            continue                                # a deletion
        bad += _tree_plaintext(root, parts[1])
    if bad:
        print("pre-push: refusing -- the commit being pushed carries plaintext data beside "
              "the sealed copies, and this repository is public:\n  "
              + "\n  ".join(sorted(set(bad))[:10]) +
              "\nTake it out of the index (python3 scripts/crypto_data.py untrack), "
              "commit, and push again.", file=sys.stderr)
        return 1
    return 0


def cmd_same_key(args, root):
    """Is <ref> sealed under the same key as this checkout? No password needed.

    update.yml's push retry replays sealed files over main. If the password was
    changed while the run was building, main is under a new key and the replay
    would put some files back under the old one -- a split no single password
    opens, or a retired password quietly restored.
    """
    ref = args.files[0] if args.files else "origin/main"
    here = root / ("docs/metrics.json" + SUFFIX)
    there = git(root, "show", f"{ref}:docs/metrics.json{SUFFIX}", check=False)
    if there.returncode != 0 or not here.is_file():
        return 0                                    # one side is not sealed yet
    try:
        a = json.loads(here.read_text())
        b = json.loads(there.stdout)
    except ValueError:
        return 0
    if (a.get("salt"), a.get("iter")) != (b.get("salt"), b.get("iter")):
        print(f"::error::{ref} is sealed under a different key than this run: the password "
              f"was changed while it ran. Not replaying -- rerun the workflow.", file=sys.stderr)
        return 1
    return 0


def cmd_post_sync(args, root):
    """post-merge / post-checkout / post-rewrite: refresh working copies after a pull."""
    if mode(root) != "sealed" or not os.environ.get("DASHBOARD_PASSWORD"):
        return 0
    try:
        return cmd_decrypt(argparse.Namespace(files=[], force=False, quiet=True,
                                              password_file=None), root)
    except CryptoDataError as exc:
        print(f"[sealed data] could not refresh working copies: {exc}", file=sys.stderr)
        return 0                                           # never block a checkout


COMMANDS = {"status": cmd_status, "decrypt": cmd_decrypt, "encrypt": cmd_encrypt,
            "reseal": cmd_reseal, "rotate": cmd_rotate, "check": cmd_check,
            "untrack": cmd_untrack, "pre-push": cmd_pre_push, "same-key": cmd_same_key,
            "passphrase": cmd_passphrase, "install": cmd_install,
            "session-start": cmd_session_start, "textconv": cmd_textconv,
            "merge-driver": cmd_merge_driver, "pre-commit": cmd_pre_commit,
            "post-sync": cmd_post_sync}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=sorted(COMMANDS))
    ap.add_argument("files", nargs="*", help="limit to these paths (default: the whole sealed set)")
    ap.add_argument("--root", help="repository root (default: git's top level)")
    ap.add_argument("--password-file")
    ap.add_argument("--new-password-file", help="rotate: the new password")
    ap.add_argument("--force", action="store_true",
                    help="decrypt: overwrite working copies; encrypt: skip the checkout guard")
    ap.add_argument("--replace", action="store_true", help="delete working copies once sealed")
    ap.add_argument("--git", action="store_true",
                    help="stage the sealed copies and take the plaintext out of the index")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--allow-old", action="store_true",
                    help="check: files that open only under DASHBOARD_PASSWORD_OLD are a "
                         "rotation in progress, not a failure (the pre-flight)")
    args = ap.parse_args(argv)

    if args.root:
        root = pathlib.Path(args.root)
    else:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True).stdout.strip()
        root = pathlib.Path(top or ".")
    try:
        return COMMANDS[args.command](args, root.resolve())
    except CryptoDataError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

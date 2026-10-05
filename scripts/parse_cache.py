#!/usr/bin/env python3
"""Keep a report's parse between runs, so the daily build stops re-reading
every report Drive has ever held.

fetch_drive pulls every file in every registered folder on every run --
nothing in Drive is ever marked done -- and process_manifest used to parse
each one afresh. So the build grew with the drop tree, and almost all of it
was work already done the day before: run #107 (2026-10-05) spent 362 of its
430 seconds on the daily leasing reports, about 11 s for each Madelon copy,
and another 50 on ninety comp extracts, every one of which it had read on
every run since it landed.

A parse is a function of four things, and the key is all four:

  * the file -- its bytes (sha256) and the path it was read from, because
    parsers read the filename: the daily leasing week label, a property
    named only in the name;
  * the parser's code -- its own module and every repo module it imports,
    found by walking the imports with `ast`. A grep would also find the
    `from parse_comps import parse` a docstring quotes;
  * the config that code names -- `properties.json` and `coa_map.json`,
    found the same way. `report_map.json` is read by the router after the
    parse, not by any parser, and it is the config file that changes most;
  * the Python and openpyxl versions, and FORMAT below.

Change any of them and the file is parsed again, exactly as before.

What is kept, and what never is:

  * A parse is kept only for a report type in CACHED_TYPES, each of which
    carries nothing the repo does not already commit. NOT_KEPT names the
    types read afresh on every run and why: resident names, a tenant code,
    unit-level rows the repo keeps out of git on purpose. A new report type
    is in neither list, so it is never kept until someone has checked it --
    the slow default rather than the leaky one.
  * Whatever its type, a parse carrying a key from build_metrics.PII_FIELDS
    is never kept, and the run says so. That is the backstop for the list.
  * A failure is kept for every type, as its message alone. That message is
    printed to the public Actions log on every run that meets the file, so
    keeping it reveals nothing -- and 183 of the lines each build printed
    were the same rejections, re-derived from scratch every day: a prospect
    report handed to the renewal-tracker parser, a tracker handed to the
    daily-report one. OSError and MemoryError are not kept; they describe
    the machine rather than the file.

It checks itself. The key can only cover the dependencies it can see, so
every run re-parses ONE kept file per parser -- the one checked least
recently -- and compares the two. A difference means the parse depends on
something the key does not cover: the run warns, sets aside every kept parse
of that parser and reads them all again. A missed dependency that changed
every file shows on the next run; one that changed a few shows within a
sweep of that parser's files, one file per run.

`_cache/parse/` (gitignored) holds one pickle per parse and an index of when
each was last used and last checked. update.yml restores it from the Actions
cache before the build and saves it after, so a run starts with every parse
the previous one made. Nothing in it is published. An entry unused for
PRUNE_DAYS is deleted, so the cache follows the drop tree rather than its
history.

PARSE_CACHE=off parses everything afresh, as before; any other value is the
directory to keep the parses in.
"""
import ast
import datetime as dt
import hashlib
import json
import math
import os
import pathlib
import pickle
import sys
import time
import warnings

# Bump when the entry or index shape changes: every kept parse is then refused
# on read, and the next run parses everything once.
FORMAT = 1
DEFAULT_DIR = "_cache/parse"
PRUNE_DAYS = 14

HERE = pathlib.Path(__file__).resolve().parent
CONFIG = HERE.parent / "config"

# The report types whose parse may be kept between runs. Add one only after
# checking that everything its parse carries is already committed somewhere.
CACHED_TYPES = {
    "daily_leasing_report": "per-lease rents and dates; the sheet has no name "
                            "column, and the leasing associate is dropped at parse",
    "market_comps": "medians, counts and shares; the licensed listing rows never "
                    "leave the parser",
    "lease_tradeout": "per-lease rents with no resident column, stored whole in "
                      "data/<slug>/lease_tradeout.json",
    "t12_statement": "monthly series and account-group sums, all published",
    "budget": "the T12 parser's output, run on a plan",
    "leasing_funnel": "aggregate counts and rates; the export has no person-level data",
    "unit_directory": "floorplans and unit counts, stored whole",
}

# Read afresh on every run. Not consulted by the code -- a type in neither list
# is not kept either -- but it is the record of why, and test_parse_cache.py
# holds the two lists apart.
NOT_KEPT = {
    "rent_roll": "a resident name on every unit; its store is gitignored",
    "ar_analytics": "a resident name on every balance; its store is gitignored",
    "renewal_tracker": "the MTM roster's tenant code, emitted on purpose so "
                       "scrub() drops it at storage",
    "concession_burnoff": "per-unit rows the store deliberately does not persist",
}

NOT_KEPT_FAILURES = (OSError, MemoryError)


class ReusedFailure(Exception):
    """A parse that failed on an earlier run, raised again with its message.

    process_manifest prints `{e}`, so the log line is the one the parser's own
    exception produced.
    """


def call_parser(mod, item):
    """The call process_manifest has always made: every parser exposes
    parse(path), and parse_t12 is kept as an alias."""
    return (mod.parse if hasattr(mod, "parse") else mod.parse_t12)(item["path"])


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _tree(path):
    """A module's syntax tree, read quietly. ast.parse compiles the source, so a
    SyntaxWarning in a parser would otherwise be printed again on every run --
    reporting it is the import's business, not the cache's."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ast.parse(pathlib.Path(path).read_text(encoding="utf-8"),
                         filename=str(path))


def module_closure(path):
    """The module at `path` and every module beside it that it imports,
    transitively, as sorted paths.

    Imports are read from the syntax tree, so the `from parse_comps import
    parse` a usage docstring quotes is not one, and an import inside a
    function is.
    """
    path = pathlib.Path(path).resolve()
    here = path.parent
    seen, todo = set(), [path]
    while todo:
        p = todo.pop()
        if p in seen:
            continue
        seen.add(p)
        for node in ast.walk(_tree(p)):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                cand = here / (name.split(".")[0] + ".py")
                if cand.is_file():
                    todo.append(cand.resolve())
    return sorted(seen)


def configs_named(sources, config_dir):
    """The config files `sources` name in a string literal -- the ones a parse
    can read. `"properties.json"` in an os.path.join counts; prose that
    merely mentions a file inside a longer docstring does not."""
    config_dir = pathlib.Path(config_dir)
    present = ({p.name: p for p in config_dir.glob("*.json")}
               if config_dir.is_dir() else {})
    named = set()
    for p in sources:
        for node in ast.walk(_tree(p)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                base = os.path.basename(node.value.strip())
                if base in present:
                    named.add(base)
    return [present[n] for n in sorted(named)]


def person_key(obj, fields):
    """The first key from `fields` anywhere inside `obj`, or None."""
    stack = [obj]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            for k, v in x.items():
                if k in fields:
                    return k
                stack.append(v)
        elif isinstance(x, (list, tuple, set, frozenset)):
            stack.extend(x)
    return None


def canonical(obj):
    """A rendering two parses share exactly when their content is the same:
    key order ignored, NaN equal to itself, a date as its repr."""
    def plain(x):
        if isinstance(x, dict):
            return {k if isinstance(k, str) else repr(k): plain(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [plain(v) for v in x]
        if isinstance(x, (set, frozenset)):
            return sorted((plain(v) for v in x), key=repr)
        if isinstance(x, float) and math.isnan(x):
            return "NaN"
        if x is None or isinstance(x, (str, int, float, bool)):
            return x
        return repr(x)
    return json.dumps(plain(obj), sort_keys=True, ensure_ascii=False)


def _openpyxl_version():
    try:
        import openpyxl
        return openpyxl.__version__
    except Exception:                                 # noqa: BLE001
        return "absent"


class NoCache:
    """PARSE_CACHE=off: every file parsed afresh, nothing kept."""

    def prepare(self, items, load):
        pass

    def parse(self, item, mod):
        return call_parser(mod, item)

    def finish(self):
        pass


class ParseCache:
    def __init__(self, root=DEFAULT_DIR, *, person_fields=(), cached_types=None,
                 config_dir=CONFIG, now=None, log=print):
        self.root = pathlib.Path(root)
        self.entries = self.root / "entries"
        self.person_fields = frozenset(person_fields)
        self.cached_types = CACHED_TYPES if cached_types is None else cached_types
        self.config_dir = pathlib.Path(config_dir)
        self.now = _aware(now or dt.datetime.now(dt.timezone.utc))
        self.log = log
        self.index = self._load_index()
        self._fps = {}            # parser module -> fingerprint of its code and config
        self._keys = {}           # (parser module, path) -> key
        self.used = set()         # keys looked up this run
        self.written = set()      # keys written this run, trusted whatever else happens
        self.distrusted = set()   # parsers whose earlier parses are set aside this run
        self.counts = {"reused": 0, "reused_failures": 0, "parsed": 0, "kept": 0}
        self.parse_seconds = 0.0
        self.checks = []          # (parser, file, matched, seconds)
        self.pruned = 0

    # ---- the key -----------------------------------------------------------

    def fingerprint(self, mod):
        name = mod.__name__
        if name not in self._fps:
            sources = module_closure(mod.__file__)
            h = hashlib.sha256(f"parse-cache format {FORMAT}\n".encode())
            h.update(f"python {sys.version_info[0]}.{sys.version_info[1]}\n".encode())
            h.update(f"openpyxl {_openpyxl_version()}\n".encode())
            for label, paths in (("src", sources),
                                 ("cfg", configs_named(sources, self.config_dir))):
                for p in paths:
                    h.update(f"{label} {pathlib.Path(p).name}\n".encode())
                    h.update(pathlib.Path(p).read_bytes())
                    h.update(b"\0")
            self._fps[name] = h.hexdigest()
        return self._fps[name]

    def key(self, item, mod):
        k = (mod.__name__, item["path"])
        if k not in self._keys:
            h = hashlib.sha256()
            for part in (self.fingerprint(mod), str(item["path"]),
                         sha256_file(item["path"])):
                h.update(part.encode())
                h.update(b"\0")
            self._keys[k] = h.hexdigest()
        return self._keys[k]

    # ---- one file -----------------------------------------------------------

    def parse(self, item, mod):
        """The parse of `item`: kept from an earlier run when its key matches,
        otherwise read afresh and kept if it may be. Raises as the parser
        would, with the same message, when the file fails."""
        try:
            key = self.key(item, mod)
        except Exception as e:                        # noqa: BLE001
            self.log(f"[cache] {item.get('name')}: cannot be keyed ({e}) -- "
                     f"parsed afresh and not kept")
            return call_parser(mod, item)
        self.used.add(key)
        trusted = key in self.written or mod.__name__ not in self.distrusted
        kept = self._read(key) if trusted else None
        if kept is not None:
            if kept["ok"]:
                self.counts["reused"] += 1
                return kept["result"]
            self.counts["reused_failures"] += 1
            raise ReusedFailure(kept["error"])
        t0 = time.monotonic()
        try:
            result = call_parser(mod, item)
        except Exception as e:
            self._tally(t0)
            self._keep(key, item, mod, ok=False, error=e)
            raise
        self._tally(t0)
        # Kept BEFORE it is returned: process_manifest writes landed_at and
        # source_file into the parse, and what is kept must be what the parser
        # made, so a later run gets the same object this one started from.
        self._keep(key, item, mod, ok=True, result=result)
        return result

    def _tally(self, t0):
        self.counts["parsed"] += 1
        self.parse_seconds += time.monotonic() - t0

    def _keep(self, key, item, mod, ok, result=None, error=None):
        # Whatever was kept under this key is wrong by now -- this is only
        # reached on a miss or after a failed check -- and it must go even when
        # the new parse may not be kept: a failure kept for a renewal tracker
        # that now parses would otherwise outlive the run that disproved it.
        self._drop(key)
        rtype = item.get("report_type")
        if ok:
            if rtype not in self.cached_types:
                return
            found = person_key(result, self.person_fields)
            if found:
                self.log(f"::warning::[cache] {item.get('name')}: this {rtype} parse "
                         f"carries a person field ({found!r}), so it is not kept "
                         f"between runs. CACHED_TYPES says a {rtype} parse never "
                         f"does -- check {mod.__name__}.")
                return
            payload = {"ok": True, "result": result}
        else:
            if isinstance(error, NOT_KEPT_FAILURES):
                return
            payload = {"ok": False, "error": str(error)}
        payload.update(format=FORMAT, key=key)
        try:
            blob = pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)
            self.entries.mkdir(parents=True, exist_ok=True)
            tmp = self.entries / f".{key}.tmp"
            tmp.write_bytes(blob)
            os.replace(tmp, self.entries / f"{key}.pickle")
        except Exception as e:                        # noqa: BLE001
            self.log(f"[cache] {item.get('name')}: its parse could not be kept ({e})")
            return
        stamp = self._stamp()
        self.index[key] = {"parser": mod.__name__, "report_type": rtype,
                           "file": item.get("name"), "ok": ok, "created": stamp,
                           "checked": stamp, "last_used": stamp}
        self.written.add(key)
        self.counts["kept"] += 1

    def _read(self, key):
        path = self.entries / f"{key}.pickle"
        if not path.is_file():
            return None
        try:
            with open(path, "rb") as fh:
                payload = pickle.load(fh)
            if not isinstance(payload, dict) or payload.get("format") != FORMAT \
                    or payload.get("key") != key:
                raise ValueError("written by another version")
        except Exception as e:                        # noqa: BLE001
            self.log(f"[cache] a kept parse could not be read ({e}) -- parsed afresh")
            self._drop(key)
            return None
        return payload

    # ---- the run as a whole ---------------------------------------------------

    def prepare(self, items, load):
        """Key every file this run will parse, then check one kept parse per
        parser against a fresh one -- the one checked least recently.

        A fault in here must cost the run its check, never the run: the
        parses themselves are still read and kept by parse() as normal."""
        try:
            self._prepare(items, load)
        except Exception as e:                        # noqa: BLE001
            self.log(f"::warning::[cache] the check could not run ({e!r}); "
                     f"kept parses are used unchecked this run")

    def _prepare(self, items, load):
        pick = {}                 # parser -> (checked, file, item, mod, key)
        for item in items:
            try:
                mod = load(item)
                key = self.key(item, mod)
            except Exception:                         # noqa: BLE001
                continue          # the main loop meets the same error and says so
            if not (self.entries / f"{key}.pickle").is_file():
                continue
            cand = (self._record(key).get("checked") or "", item.get("name") or "",
                    item, mod, key)
            cur = pick.get(mod.__name__)
            if cur is None or cand[:2] < cur[:2]:
                pick[mod.__name__] = cand
        for name in sorted(pick):
            _, _, item, mod, key = pick[name]
            self._check(item, mod, key)

    def _check(self, item, mod, key):
        kept = self._read(key)
        if kept is None:
            return
        t0 = time.monotonic()
        try:
            fresh, err = call_parser(mod, item), None
        except Exception as e:                        # noqa: BLE001
            fresh, err = None, e
        secs = time.monotonic() - t0
        if kept["ok"]:
            same = err is None and canonical(kept["result"]) == canonical(fresh)
        else:
            same = err is not None and kept["error"] == str(err)
        name = item.get("name")
        self.checks.append((mod.__name__, name, same, secs))
        if same:
            self._record(key)["checked"] = self._stamp()
            self.log(f"[cache] checked {mod.__name__}: a fresh parse of {name} "
                     f"matches the one kept ({secs:.1f}s)")
            return
        when = self._record(key).get("created") or "an earlier run"
        self.log(f"::warning::[cache] a fresh parse of {name} by {mod.__name__} "
                 f"differs from the one kept on {when}, so that parse depends on "
                 f"something its key does not cover. Every kept {mod.__name__} "
                 f"parse is set aside for this run and read again.")
        self.distrusted.add(mod.__name__)
        # Replace this one now, so the main loop does not parse it a second time.
        self._keep(key, item, mod, ok=err is None, result=fresh, error=err)

    def finish(self):
        """Record what this run used, prune what no run has used for
        PRUNE_DAYS, save the index and say what the cache did. A fault in
        here costs the bookkeeping, never the run."""
        try:
            self._finish()
        except Exception as e:                        # noqa: BLE001
            self.log(f"::warning::[cache] its bookkeeping failed ({e!r}); the "
                     f"parses this run kept are still on disk")

    def _finish(self):
        stamp = self._stamp()
        for key in self.used:
            if (self.entries / f"{key}.pickle").is_file():
                self._record(key)["last_used"] = stamp
        if self.entries.is_dir():                     # files the index lost track of
            for p in self.entries.glob("*.pickle"):
                self._record(p.stem)
        cutoff = self.now - dt.timedelta(days=PRUNE_DAYS)
        for key, rec in list(self.index.items()):
            if not (self.entries / f"{key}.pickle").is_file() \
                    or _when(rec.get("last_used"), self.now) < cutoff:
                self._drop(key)
                self.pruned += 1
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = self.root / ".index.json.tmp"
            tmp.write_text(json.dumps({"format": FORMAT, "entries": self.index},
                                      indent=1, sort_keys=True))
            os.replace(tmp, self.root / "index.json")
        except OSError as e:
            self.log(f"[cache] the index could not be saved ({e}); the parses "
                     f"themselves still are")
        line = self.summary()
        self.log(f"[cache] {line}")
        summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_file:
            try:
                with open(summary_file, "a") as fh:
                    fh.write(f"**Parse cache:** {line}\n\n")
            except OSError:
                pass

    def summary(self):
        c = self.counts
        bits = [f"reused {c['reused']} parse(s) and {c['reused_failures']} known "
                f"failure(s); parsed {c['parsed']} file(s) afresh in "
                f"{self.parse_seconds:.1f}s and kept {c['kept']}"]
        if self.checks:
            bad = [p for p, _, same, _ in self.checks if not same]
            bits.append(f"checked {len(self.checks)} parser(s) against a fresh "
                        f"parse" + (f", {len(bad)} set aside: {', '.join(bad)}"
                                    if bad else ", all matched"))
        if self.pruned:
            bits.append(f"pruned {self.pruned} unused entr{'y' if self.pruned == 1 else 'ies'}")
        return "; ".join(bits)

    # ---- bookkeeping ------------------------------------------------------------

    def _stamp(self):
        return self.now.isoformat(timespec="seconds")

    def _record(self, key):
        """The index record for a kept parse, made if the index lost it. A
        record with no "checked" date sorts first, so it is checked next."""
        return self.index.setdefault(key, {"checked": None,
                                           "last_used": self._stamp()})

    def _drop(self, key):
        self.index.pop(key, None)
        try:
            (self.entries / f"{key}.pickle").unlink()
        except OSError:
            pass

    def _load_index(self):
        try:
            data = json.loads((self.root / "index.json").read_text())
            if data.get("format") == FORMAT and isinstance(data.get("entries"), dict):
                return {k: v for k, v in data["entries"].items() if isinstance(v, dict)}
        except (OSError, ValueError, AttributeError):
            pass
        return {}


def _aware(when):
    return when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)


def _when(stamp, default):
    try:
        return _aware(dt.datetime.fromisoformat(stamp))
    except (TypeError, ValueError):
        return default


def from_env(**kwargs):
    """The cache process_manifest uses: PARSE_CACHE=off for none, any other
    value for a directory, unset for _cache/parse."""
    value = os.environ.get("PARSE_CACHE", "").strip()
    if value.lower() in ("off", "0", "false", "no"):
        return NoCache()
    return ParseCache(value or DEFAULT_DIR, **kwargs)

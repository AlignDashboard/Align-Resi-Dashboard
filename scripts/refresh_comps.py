#!/usr/bin/env python3
"""Refresh ONLY the `comps` block of docs/metrics.json, from comp exports on disk.

    python scripts/refresh_comps.py <file-or-dir> [...] [--landed-at ISO] [--dry-run]

Why this exists rather than just running the pipeline. The HelloData export
arrives several times a day, for every market Align asks for; the daily cron
that would otherwise pick it up runs once and takes about five hours, and its
push-retry loop replays whatever it built over anything newer (open item A15).
So "the comps tab is refreshed daily" cannot rest on that run alone.

This does the same thing for one feed and touches nothing else. It parses the
files it is given, stores each section under the property it names, and rewrites
`metrics["comps"]` through `build_metrics.comps_block` -- the same function the
pipeline calls, so the published block cannot depend on which of the two wrote
it. Every other block in the file is left exactly as it was found.

Three things worth knowing:

  * It is safe to run on the same files twice, and safe to run on an OLD file.
    `store_comps` keeps the newest `as_of` and refuses to go backwards, which
    matters here more than anywhere: arrival order does not track vintage in
    this feed -- a copy that landed 2026-09-21 is as of 2026-08-05, six weeks
    behind one that landed three days earlier.
  * A file it cannot read is reported and skipped, not fatal. The export is a
    PAIR of near-identical names and the formatted twin has no parseable table
    in it, so a batch that refuses everything on the first unreadable file
    would refuse every batch.
  * `--dry-run` parses and compares and writes nothing, which is how a
    scheduled check asks "is there a newer vintage?" without touching the repo.

Exit code is 0 whenever the run completed, whether or not anything moved; the
last line says which. A non-zero exit means the block could not be rebuilt.
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import build_metrics as bm      # noqa: E402
import parse_comps as pc        # noqa: E402

METRICS = pathlib.Path("docs/metrics.json")
SUFFIXES = (".xlsx", ".xls", ".xlsm")


def files_from(args_paths):
    """Every export named, with directories expanded, in a stable order."""
    out = []
    for raw in args_paths:
        p = pathlib.Path(raw)
        if p.is_dir():
            out += sorted(f for f in p.iterdir()
                          if f.is_file() and f.suffix.lower() in SUFFIXES)
        elif p.is_file():
            out.append(p)
        else:
            print(f"[warn] {p} does not exist -- skipping")
    return out


def groups_for(parsed, code_to_prop, label):
    """slug -> (property, [section]).

    Mirrors the grouping in `build_metrics.process_manifest`, deliberately not
    shared with it: that one also carries resident rows, a `summarise` hook and
    the unattributed-property fallback, none of which a comp export has. A
    section that names a building the master does not know is REPORTED, because
    it is the whole of a market dropping out -- which is exactly how the Oakland
    set went missing until the master learned to route on a property's own name.
    """
    groups = {}
    for sec in parsed.get("sections") or []:
        code = (sec.get("property_code") or "").lower()
        prop = code_to_prop.get(code)
        if not prop:
            print(f"[warn] {label}: no property matches '{sec.get('property_code')}' "
                  f"-- add it to config/properties.json as a name, alias or code; "
                  f"that market is not published")
            continue
        groups.setdefault(prop["slug"], (prop, []))[1].append(sec)
    return groups


def published(metrics):
    """{slug: as_of} as the file currently stands, for the before/after."""
    return {p["slug"]: p.get("as_of")
            for p in ((metrics.get("comps") or {}).get("properties") or [])}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", help="comp export files, or directories of them")
    ap.add_argument("--landed-at", help="Drive arrival time (ISO-8601) for these files")
    ap.add_argument("--dry-run", action="store_true",
                    help="parse and compare; write nothing")
    a = ap.parse_args()

    if not METRICS.exists():
        sys.exit(f"[error] {METRICS} does not exist -- run the pipeline first")
    metrics = json.load(open(METRICS))
    before = published(metrics)

    all_props, code_to_prop = bm.load_properties()
    paths = files_from(a.paths)
    if not paths:
        sys.exit("[error] no comp exports found in the paths given")

    read = 0
    for path in paths:
        try:
            parsed = pc.parse(str(path))
        except Exception as e:                               # noqa: BLE001
            print(f"[error] {path.name}: {e} -- skipping this file")
            continue
        if parsed.get("skip"):
            print(f"[skip] {path.name}: {parsed['skip']}")
            continue
        parsed.setdefault("source_file", path.name)
        if a.landed_at:
            parsed["landed_at"] = a.landed_at
        read += 1

        for slug, (prop, secs) in groups_for(parsed, code_to_prop, path.name).items():
            if bm.quarantined(prop, "market_comps"):
                print(f"[quarantined] {path.name} -> {prop['name']}: "
                      f"{prop['quarantine']['reason']}")
                continue
            one = dict(parsed)
            one["property"] = prop["name"]
            one["property_code"] = secs[0].get("property_code")
            one["sections"] = secs
            if a.dry_run:
                was = before.get(slug)
                mine = str(secs[0].get("as_of") or "")[:10]
                verdict = ("newer than the published " + str(was) if was and mine > was
                           else "not newer than the published " + str(was) if was
                           else "a market not on the tab yet")
                print(f"[dry-run] {path.name} -> {prop['name']}: as of {mine}, {verdict}")
                continue
            bm.store_comps(prop, one)

    if not read:
        print("\nno readable comp export among the files given; nothing to do.")
        print("changed: no")
        return

    if a.dry_run:
        print(f"\n{read} export(s) read. Nothing written (--dry-run).")
        print("changed: no")
        return

    metrics["comps"] = bm.comps_block(all_props, metrics)
    after = published(metrics)

    moved = {s: (before.get(s), after[s]) for s in after
             if before.get(s) != after[s]}
    json.dump(metrics, open(METRICS, "w"), indent=2)

    print(f"\n{read} export(s) read; {len(after)} market(s) published.")
    for slug, (was, now) in sorted(moved.items()):
        print(f"  {slug}: {was or 'not published'} -> {now}")
    for slug in sorted(set(after) - set(moved)):
        print(f"  {slug}: unchanged at {after[slug]}")
    print(f"changed: {'yes' if moved else 'no'}")


if __name__ == "__main__":
    main()

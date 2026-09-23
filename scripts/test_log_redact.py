#!/usr/bin/env python3
"""Checks for scripts/ci_logs/sitecustomize.py -- the CI log redaction.

Run: python scripts/test_log_redact.py
"""
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
# Loaded by path, under another name: the interpreter has usually imported a
# system sitecustomize already, and `import sitecustomize` would return that one.
# (In the workflows PYTHONPATH puts ours first, which the subprocess checks cover.)
import importlib.util                      # noqa: E402
_spec = importlib.util.spec_from_file_location("align_ci_sitecustomize",
                                               HERE / "ci_logs" / "sitecustomize.py")
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)

PASS = FAIL = 0


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def main():
    print("what is masked")
    for raw in ["Budget Variance % +$123,955/+11.1%", "($199,363/mo)", "$-135,565/mo",
                "revenue 1327451.19/mo", "loss to lease 37%", "$6,757", "$4.01/sqft",
                "total 14194490", "−4.3%", "$2.4M of T12"]:
        out = sc.redact(raw)
        digits = [c for c in out if c.isdigit()]
        ok(f"{raw!r} -> {out!r}", not any(ch.isdigit() for ch in out.replace("T12", "")), digits)
    print("\nwhat is kept")
    for raw in ["[ok] stored rent roll for The Landing (as of 2026-09-11)",
                "metricsbuilding20260823.csv", "247 lease(s) 2024-08-01..2026-09-16",
                "::error::DASHBOARD_PASSWORD is not set", "Pushed on attempt 3.",
                "31 units", "step 14:50:56"]:
        ok(f"{raw!r} unchanged", sc.redact(raw) == raw, sc.redact(raw))

    print("\nin a real interpreter")
    env = dict(os.environ, PYTHONPATH=str(HERE / "ci_logs"), GITHUB_ACTIONS="true")
    code = ("import sys; print('KPI', '$123,955', 'NOI', '72.6%'); "
            "print('split write $12,', end=''); print('345 done'); "
            "sys.stderr.write('tie-out off by $3,141\\n'); raise SystemExit(3)")
    r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    ok("stdout is redacted", "123,955" not in r.stdout and "72.6" not in r.stdout, r.stdout)
    ok("a figure split across two writes is still caught", "12,345" not in r.stdout, r.stdout)
    ok("stderr is redacted", "3,141" not in r.stderr, r.stderr)
    ok("the exit code is untouched", r.returncode == 3, r.returncode)
    r = subprocess.run([sys.executable, "-c", "raise ValueError('owed $9,678.15')"],
                       env=env, capture_output=True, text=True)
    ok("a traceback is redacted", "9,678" not in r.stderr and "ValueError" in r.stderr, r.stderr[-200:])
    r = subprocess.run([sys.executable, "-c", "print('$123,955')"],
                       env=dict(env, GITHUB_ACTIONS="false"), capture_output=True, text=True)
    ok("outside Actions nothing changes", "$123,955" in r.stdout, r.stdout)
    r = subprocess.run([sys.executable, "-c", "print('$123,955')"],
                       env=dict(env, ALIGN_LOG_REDACT="0"), capture_output=True, text=True)
    ok("ALIGN_LOG_REDACT=0 switches it off", "$123,955" in r.stdout, r.stdout)

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()

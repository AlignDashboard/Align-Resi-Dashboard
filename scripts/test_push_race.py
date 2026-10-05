#!/usr/bin/env python3
"""Guard tests for scripts/commit_and_push.sh -- the daily run's commit step.

What it must never do again is the replay: on a rejected push it used to reset
to the new main and copy this run's files back over it, which is how run #88
blanked the Market Comps tab on 2026-09-18 (open item A15). It rebuilds on the
new main now, and these checks pin the rules that make that safe:

  1. a race is rebuilt on, and the commit that won it survives -- its own edits
     to the very files this run writes, and its new inputs feeding the rebuild;
  2. a rejection with main unmoved is pushed again, not rebuilt;
  3. main moving again and again ends in a failed run after MAX_REBUILDS, with
     nothing overwritten;
  4. nothing is committed past a failing personal-data check, rebuilt or not;
  5. a push that landed but reported failure is recognised, not rebuilt;
  6. a rebuild starts from the new main alone -- a file only the first build
     wrote does not ride into the rebuilt commit;
  7. a rebuild that fails, or that finds main already carrying the output,
     commits nothing -- and a commit that fails is a failed run, never
     "nothing to commit".

Real git against a bare repository in a temp dir, with the user's git config
shut out (no signing, no hooks), and a fake build that derives its output from
the repo's own inputs -- so "rebuilt on the new main" is something a check can
see. No network, no GitHub.

Run: python scripts/test_push_race.py
"""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = pathlib.Path(os.environ.get("COMMIT_SCRIPT", ROOT / "scripts" / "commit_and_push.sh"))
REAL_GIT = shutil.which("git")

PASS = FAIL = 0


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"   PASS {name}")
    else:
        FAIL += 1
        print(f"   FAIL {name}\n        got  {got!r}\n        want {want!r}")


ENV = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
           GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
           GIT_COMMITTER_EMAIL="t@t")
ENV.pop("GITHUB_STEP_SUMMARY", None)
ENV.pop("GITHUB_ACTIONS", None)


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, env=ENV, check=True,
                          capture_output=True, text=True).stdout.strip()


# The fake build: everything it writes is a function of the repo it runs in
# (inputs/feed.txt) plus this run's own "reports" (RUN_MARK), and it updates
# the scorecard IN PLACE, as populate_scorecard does -- so a rebuild keeps a
# key someone else added and a replay would not.
BUILD = r'''
import json, os, pathlib
feed = pathlib.Path("inputs/feed.txt").read_text().strip()
run = os.environ.get("RUN_MARK", "run")
pathlib.Path("docs").mkdir(exist_ok=True)
pathlib.Path("data").mkdir(exist_ok=True)
json.dump({"feed": feed, "run": run}, open("docs/metrics.json", "w"))
sc = json.load(open("docs/scorecard.json"))
sc.update(feed=feed, run=run)
json.dump(sc, open("docs/scorecard.json", "w"), sort_keys=True)
pathlib.Path(f"data/{feed}.json").write_text(json.dumps({"feed": feed}))
count = os.environ.get("BUILD_COUNT")
if count:
    p = pathlib.Path(count)
    p.write_text(str(int(p.read_text()) + 1 if p.exists() else 1))
'''

# Personal data, as far as the fake check is concerned, is the word LEAK in
# anything the run would commit.
CHECK = r'''
import pathlib, sys
for p in list(pathlib.Path("docs").glob("*.json")) + list(pathlib.Path("data").rglob("*.json")):
    if "LEAK" in p.read_text():
        print("personal data in", p); sys.exit(1)
'''

# Someone else's commit landing on main: a fresh clone, an edit, a push.
HAND = r'''
import json, pathlib, subprocess, sys
repo, n = sys.argv[1], sys.argv[2]
run = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
run("fetch", "-q", "origin", "main"); run("reset", "-q", "--hard", "origin/main")
sc = pathlib.Path(repo, "docs/scorecard.json")
d = json.loads(sc.read_text())
d[f"hand_{n}" if f"hand_{n}" not in d else f"hand_{n}_{len(d)}"] = True
sc.write_text(json.dumps(d, sort_keys=True))
run("commit", "-qam", f"hand commit {n}"); run("push", "-q", "origin", "HEAD:main")
'''


class World:
    """A bare remote, the runner's clone and someone else's clone."""

    def __init__(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.remote = self.tmp / "remote.git"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.remote))
        seed = self.tmp / "seed"
        git(self.tmp, "clone", "-q", str(self.remote), str(seed))
        (seed / "inputs").mkdir()
        (seed / "inputs/feed.txt").write_text("v1\n")
        (seed / "docs").mkdir()
        (seed / "docs/scorecard.json").write_text(json.dumps({"seed": True}))
        (seed / "docs/metrics.json").write_text("{}")
        (seed / ".gitignore").write_text("_downloads/\n")
        git(seed, "add", "-A")
        git(seed, "commit", "-qm", "seed")
        git(seed, "push", "-q", "origin", "HEAD:main")
        self.runner = self.tmp / "runner"
        self.other = self.tmp / "other"
        # Shallow, as actions/checkout makes it: HEAD^, merge-base and the
        # base..tip listing all have to work across a depth-1 history.
        git(self.tmp, "clone", "-q", "--depth", "1", f"file://{self.remote}", str(self.runner))
        git(self.runner, "remote", "set-url", "origin", str(self.remote))
        git(self.tmp, "clone", "-q", str(self.remote), str(self.other))
        for name, body in (("build.py", BUILD), ("check.py", CHECK), ("hand.py", HAND)):
            (self.tmp / name).write_text(body)
        self.count = self.tmp / "rebuilds"
        self.hands = 0

    def build(self, mark="run"):
        """The run's own first build, before the commit step."""
        subprocess.run([sys.executable, str(self.tmp / "build.py")], cwd=self.runner,
                       env=dict(ENV, RUN_MARK=mark), check=True)

    def hand(self, feed=None):
        """Someone else's commit lands on main, optionally changing the input."""
        self.hands += 1
        if feed is not None:
            git(self.other, "fetch", "-q", "origin", "main")
            git(self.other, "reset", "-q", "--hard", "origin/main")
            (self.other / "inputs/feed.txt").write_text(feed + "\n")
            git(self.other, "commit", "-qam", f"new input {feed}")
            git(self.other, "push", "-q", "origin", "HEAD:main")
        subprocess.run([sys.executable, str(self.tmp / "hand.py"), str(self.other),
                        str(self.hands)], env=ENV, check=True)

    def commit_step(self, rebuild=None, extra_env=None, path_prefix=None):
        env = dict(ENV, RETRY_DELAY="0", MSG="Auto-update metrics (test)",
                   PATHS="data docs/metrics.json docs/scorecard.json",
                   CHECK=f"{sys.executable} {self.tmp / 'check.py'}",
                   REBUILD=rebuild or (f"BUILD_COUNT={self.count} RUN_MARK=run "
                                       f"{sys.executable} {self.tmp / 'build.py'}"))
        env.update(extra_env or {})
        if path_prefix:
            env["PATH"] = f"{path_prefix}{os.pathsep}{env['PATH']}"
        r = subprocess.run(["bash", str(SCRIPT)], cwd=self.runner, env=env,
                           capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    def rebuilds(self):
        return int(self.count.read_text()) if self.count.exists() else 0

    def main_file(self, path):
        try:
            return git(self.remote, "show", f"main:{path}")
        except subprocess.CalledProcessError:
            return None

    def main_json(self, path):
        text = self.main_file(path)
        return json.loads(text) if text is not None else None

    def main_log(self):
        return git(self.remote, "log", "--format=%s", "main").splitlines()

    def done(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


print("a run with nothing new commits nothing")
w = World()
code, out = w.commit_step()
check("exits 0", code, 0)
check("says so", "No changes to commit." in out, True)
check("main is untouched", w.main_log(), ["seed"])
w.done()

print("\nno race: one push, no rebuild")
w = World()
check("the runner's clone is shallow, as actions/checkout makes it",
      git(w.runner, "rev-parse", "--is-shallow-repository"), "true")
w.build()
code, out = w.commit_step()
check("exits 0", code, 0)
check("pushed on the first attempt", "on attempt 1." in out, True)
check("nothing was rebuilt", w.rebuilds(), 0)
check("main carries the run's output", w.main_json("docs/metrics.json"),
      {"feed": "v1", "run": "run"})
w.done()

print("\nrule 1 -- a race is rebuilt on, and the commit that won it survives")
w = World()
w.build()
w.hand(feed="v2")           # a new input AND an edit to a file this run writes
code, out = w.commit_step()
check("exits 0", code, 0)
check("rebuilt once", w.rebuilds(), 1)
check("the other commit's scorecard edit survives",
      (w.main_json("docs/scorecard.json") or {}).get("hand_1"), True)
check("the rebuild read the other commit's input",
      w.main_json("docs/metrics.json"), {"feed": "v2", "run": "run"})
check("the other commit keeps its place in history",
      w.main_log()[1:3], ["hand commit 1", "new input v2"])
check("the run's commit sits on top of it", w.main_log()[0], "Auto-update metrics (test)")
check("the log names the paths it kept", "docs/scorecard.json" in out, True)
check("rule 6 -- a file only the first build wrote is not committed",
      w.main_file("data/v1.json"), None)
w.done()

print("\nrule 2 -- a rejection with main unmoved is pushed again, not rebuilt")
w = World()
w.build()
flag = w.tmp / "reject-once"
flag.write_text("1")
hook = w.remote / "hooks" / "pre-receive"
hook.write_text(f'#!/bin/sh\nif [ -f "{flag}" ]; then rm -f "{flag}"; '
                f'echo "simulated 500" >&2; exit 1; fi\nexit 0\n')
hook.chmod(0o755)
code, out = w.commit_step()
check("exits 0", code, 0)
check("says it was not a race", "not a race" in out, True)
check("pushed on the second attempt", "on attempt 2." in out, True)
check("nothing was rebuilt", w.rebuilds(), 0)
check("main carries the first build", w.main_json("docs/metrics.json"),
      {"feed": "v1", "run": "run"})
w.done()

print("\nrule 3 -- main moving again and again ends the run, overwriting nothing")
w = World()
w.build()
w.hand()
racing = (f"BUILD_COUNT={w.count} {sys.executable} {w.tmp / 'build.py'} && "
          f"{sys.executable} {w.tmp / 'hand.py'} {w.other} again")
code, out = w.commit_step(rebuild=racing)
check("fails the run", code, 1)
check("says it gave up", "giving up rather than overwriting" in out, True)
check("rebuilt exactly MAX_REBUILDS times", w.rebuilds(), 3)
check("none of the run's commits reached main",
      "Auto-update metrics (test)" in w.main_log(), False)
check("the last hand commit is main's tip", w.main_log()[0], "hand commit again")
w.done()

print("\nrule 4 -- a failing personal-data check commits nothing, first try or rebuilt")
w = World()
w.build()
(w.runner / "data/leak.json").write_text('"LEAK"')
code, out = w.commit_step()
check("first try: fails the run", code, 1)
check("first try: says why", "personal-data check failed" in out, True)
check("first try: main is untouched", w.main_log(), ["seed"])
w.done()
w = World()
w.build()
w.hand(feed="LEAK")         # the newer main makes the REBUILT output fail the check
code, out = w.commit_step()
check("rebuilt: fails the run", code, 1)
check("rebuilt: says why", "personal-data check failed" in out, True)
check("rebuilt: none of the run's commits reached main",
      "Auto-update metrics (test)" in w.main_log(), False)
w.done()

print("\nrule 5 -- a push that landed but reported failure is not rebuilt")
w = World()
w.build()
shim = w.tmp / "shim"
shim.mkdir()
flag = w.tmp / "landed-but-failed"
flag.write_text("1")
(shim / "git").write_text(f'#!/bin/sh\nif [ "$1" = "push" ] && [ -f "{flag}" ]; then '
                          f'rm -f "{flag}"; "{REAL_GIT}" "$@"; exit 1; fi\n'
                          f'exec "{REAL_GIT}" "$@"\n')
(shim / "git").chmod(0o755)
code, out = w.commit_step(path_prefix=str(shim))
check("exits 0", code, 0)
check("recognises the push landed", "the earlier push landed" in out, True)
check("nothing was rebuilt", w.rebuilds(), 0)
check("main carries the run's commit once",
      w.main_log().count("Auto-update metrics (test)"), 1)
w.done()

print("\nrule 7 -- a failed rebuild, or main already carrying the output, commits nothing")
w = World()
w.build()
w.hand()
code, out = w.commit_step(rebuild="false")
check("failed rebuild: fails the run", code, 1)
check("failed rebuild: says so", "rebuild on the new main failed" in out, True)
check("failed rebuild: main is the other commit", w.main_log()[0], "hand commit 1")
w.done()
w = World()
w.build()
# another run already published exactly this output
git(w.other, "fetch", "-q", "origin", "main")
subprocess.run([sys.executable, str(w.tmp / "build.py")], cwd=w.other,
               env=dict(ENV, RUN_MARK="run"), check=True)
git(w.other, "add", "-A")
git(w.other, "commit", "-qm", "same output, other runner")
git(w.other, "push", "-q", "origin", "HEAD:main")
code, out = w.commit_step()
check("already carried: exits 0", code, 0)
check("already carried: says so", "already carries this run's output" in out, True)
check("already carried: no second commit", w.main_log()[0], "same output, other runner")
w.done()

print("\na commit that fails is a failed run, not \"nothing to commit\"")
w = World()
w.build()
hook = w.runner / ".git" / "hooks" / "pre-commit"
hook.write_text("#!/bin/sh\necho 'commit refused' >&2\nexit 1\n")
hook.chmod(0o755)
code, out = w.commit_step()
check("fails the run", code, 1)
check("says the commit failed", "git commit failed" in out, True)
check("does not claim there was nothing to commit", "No changes to commit" in out, False)
check("main is untouched", w.main_log(), ["seed"])
w.done()

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)

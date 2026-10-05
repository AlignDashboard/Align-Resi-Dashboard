#!/usr/bin/env bash
# Commit the daily run's output and push it to main. When the push loses a
# race, REBUILD ON THE NEW MAIN -- never replay this run's files over it.
#
# Why rebuild. Every path this commits is generated, and a run's output is a
# function of two things: the reports it fetched, and the repo it built on.
# When main moves mid-run, the second half is stale, and there were two ways to
# get past that before. Both broke the dashboard:
#
#   - `git pull --rebase` between tries conflicts on the very files the run
#     just wrote, stops mid-rebase, and the loop spun in a detached HEAD it could
#     not push from. Nothing published 2026-09-13 to 2026-09-15.
#   - Its replacement reset to the new main and copied this run's files back
#     over it. A merge of regenerated JSON makes a file no run ever wrote, so a
#     copy looked like the safe choice -- but it is a clobber. Run #88
#     (2026-09-18) built for five hours, the Market Comps merge landed three
#     hours in, and the copy put back a metrics.json with no comps block: the
#     tab went blank, every step was green, and the only trace was a warning in
#     a log nobody reads (open item A15).
#
# A rebuild is the third way, and it was only affordable once the build took
# minutes (9m29s on run #98) rather than hours. The reports are still on disk
# (_downloads/ is gitignored, so a reset leaves them alone), so resetting to the
# new main and running the same build again produces what a run starting now
# would have: the newer commits' code AND their data -- a hand-added EliseAI
# day, a newer comps vintage, a fixed parser -- with this run's reports on top.
#
# Four rules:
#   1. A rejection with main UNMOVED is not a race (GitHub returns the odd
#      500). The same commit is pushed again; nothing is rebuilt.
#   2. Main moved: reset to it, rebuild, check, commit, push.
#   3. Main keeps moving: after MAX_REBUILDS it gives up and fails the run.
#      A red run is a signal somebody receives; an overwrite is not.
#   4. Nothing is committed without CHECK passing first -- the personal-data
#      check, on the first commit and on every rebuilt one.
#
# Environment, all optional; the defaults are update.yml's:
#   PATHS          what the run commits
#   MSG            the commit message
#   REBUILD        the command that regenerates PATHS from the reports on disk
#   CHECK          the gate every commit must pass first
#   REMOTE, BRANCH where to push
#   MAX_ATTEMPTS   pushes in all (5)
#   MAX_REBUILDS   how many of those may follow a rebuild (3)
#   RETRY_DELAY    seconds before the first retry, doubled each time (2)
#
# scripts/test_push_race.py holds it down against a real bare repository.
set -u

PATHS=${PATHS:-"data docs/metrics.json docs/scorecard.json docs/lineage.json"}
MSG=${MSG:-"Auto-update metrics ($(date -u +%Y-%m-%d))"}
REBUILD=${REBUILD:-"bash scripts/build_pipeline.sh"}
CHECK=${CHECK:-"python scripts/check_no_pii.py"}
REMOTE=${REMOTE:-origin}
BRANCH=${BRANCH:-main}
MAX_ATTEMPTS=${MAX_ATTEMPTS:-5}
MAX_REBUILDS=${MAX_REBUILDS:-3}
RETRY_DELAY=${RETRY_DELAY:-2}

summary() {
  [ -n "${GITHUB_STEP_SUMMARY:-}" ] && echo "$*" >> "$GITHUB_STEP_SUMMARY"
  return 0
}

# Stage only what exists or is tracked: `git add` fails the whole call on a
# pathspec that matches nothing, and a run with no data/ should still commit
# its JSON. A tracked file the build deleted still matches, so it is staged as
# a deletion.
stage_paths() {
  local p present=()
  for p in $PATHS; do
    if [ -e "$p" ] || [ -n "$(git ls-files -- "$p")" ]; then
      present+=("$p")
    fi
  done
  [ ${#present[@]} -eq 0 ] || git add -A -- "${present[@]}"
}

# 0 = committed, 1 = nothing to commit. Exits the script if CHECK fails.
commit_output() {
  if ! eval "$CHECK"; then
    echo "::error::the personal-data check failed -- nothing committed"
    summary "**Refused**: the personal-data check failed, so nothing was committed."
    exit 1
  fi
  stage_paths
  if git diff --staged --quiet; then
    return 1
  fi
  if ! git commit -qm "$MSG"; then
    echo "::error::git commit failed -- nothing pushed"
    summary "**Not pushed**: \`git commit\` failed."
    exit 1
  fi
}

if ! commit_output; then
  echo "No changes to commit."
  summary "No changes to commit."
  exit 0
fi

rebuilds=0
for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
  if git push -q "$REMOTE" "HEAD:$BRANCH"; then
    sha=$(git rev-parse --short HEAD)
    if [ "$rebuilds" -gt 0 ]; then
      echo "Pushed $sha on attempt $attempt, after $rebuilds rebuild(s) on a newer $BRANCH."
      summary "Pushed \`$sha\` on attempt $attempt, rebuilt $rebuilds time(s) on a newer \`$BRANCH\` rather than overwriting it."
    else
      echo "Pushed $sha on attempt $attempt."
      summary "Pushed \`$sha\` on attempt $attempt."
    fi
    exit 0
  fi
  [ "$attempt" -eq "$MAX_ATTEMPTS" ] && break

  delay=$((RETRY_DELAY * (1 << (attempt - 1))))
  echo "Push failed; retrying in ${delay}s."
  sleep "$delay"
  if ! git fetch -q "$REMOTE" "$BRANCH"; then
    echo "::warning::could not fetch $BRANCH; pushing the same commit again"
    continue
  fi
  base=$(git rev-parse HEAD^)
  tip=$(git rev-parse FETCH_HEAD)

  # A push can land and still report a failure (a dropped connection after
  # the server accepted it). Then the commit is already in main and the only
  # wrong move left would be to rebuild it.
  if git merge-base --is-ancestor HEAD "$tip"; then
    echo "$BRANCH already contains $(git rev-parse --short HEAD); the earlier push landed."
    summary "Pushed \`$(git rev-parse --short HEAD)\`; the push reported a failure but had landed."
    exit 0
  fi

  # Rule 1: not a race.
  if [ "$tip" = "$base" ]; then
    echo "$BRANCH has not moved, so that was not a race; pushing the same commit again."
    continue
  fi

  # Rule 3: it keeps moving.
  if [ "$rebuilds" -ge "$MAX_REBUILDS" ]; then
    echo "::error::$BRANCH moved under this run again after $rebuilds rebuild(s); giving up rather than overwriting it"
    git log --oneline "$base..$tip" | sed 's/^/  /'
    summary "**Not pushed**: \`$BRANCH\` moved under this run again after $rebuilds rebuild(s). Nothing was overwritten; the next run carries the day's reports."
    exit 1
  fi

  # Rule 2: rebuild on it.
  rebuilds=$((rebuilds + 1))
  echo "::warning::$BRANCH moved under this run; rebuilding on $(git rev-parse --short "$tip") rather than overwriting it"
  git log --oneline "$base..$tip" | sed 's/^/  /'
  touched=$(git diff --name-only "$base" "$tip" -- $PATHS)
  if [ -n "$touched" ]; then
    echo "  of which these are paths this run writes -- kept, and rebuilt on top of:"
    echo "$touched" | sed 's/^/    /'
  fi
  # Everything the first build wrote under PATHS is in this run's own commit,
  # so the reset takes it away too: the rebuild starts from the new main alone.
  # Ignored files -- _downloads/, the per-unit stores -- are left in place,
  # which is what makes the rebuild possible at all. The reset may replace this
  # very script; that is safe, because git writes a new file rather than
  # rewriting the old one in place, so the running bash keeps reading the
  # version it started with (checked with a descriptor held open across a
  # reset, git 2.43).
  git reset -q --hard "$tip"
  if ! eval "$REBUILD"; then
    echo "::error::the rebuild on the new $BRANCH failed -- nothing committed, and $BRANCH is left as it is"
    summary "**Not pushed**: the rebuild on the new \`$BRANCH\` failed. Nothing was overwritten."
    exit 1
  fi
  if ! commit_output; then
    echo "$BRANCH already carries this run's output; nothing left to push."
    summary "\`$BRANCH\` moved during the run and already carries its output; nothing left to push."
    exit 0
  fi
done

echo "::error::push failed after $MAX_ATTEMPTS attempts"
summary "**Not pushed**: the push failed after $MAX_ATTEMPTS attempts."
exit 1

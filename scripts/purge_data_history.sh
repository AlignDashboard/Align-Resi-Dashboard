#!/usr/bin/env bash
# Remove the data files from EVERY commit in this repository's history, then
# force-push the rewritten history.
#
# This is the cleanup for data already committed. It is deliberately awkward to
# run, because it rewrites history: every commit SHA changes, and anyone with a
# clone has to re-clone. Read all of this before using it.
#
# WHAT IT CANNOT DO
#   * Un-publish. Anything that was public has been cloned, cached and ingested
#     by third parties (GH Archive, search engines, forks). Treat every value
#     ever committed to a public repo as disclosed. This limits future exposure;
#     it does not undo past exposure.
#   * Clean up forks. Forks of a public repo keep their own copy of the history.
#   * Purge GitHub's own storage immediately. Unreachable objects linger until
#     GitHub garbage-collects; open a support ticket if that matters to you.
#
# BEFORE RUNNING
#   1. Push everything you care about, and take a copy of the repo directory.
#   2. Tell anyone else with a clone that they will need to re-clone.
#   3. Confirm the live site does not depend on the paths being purged — after
#      the switch to Actions-based Pages deployment it does not, because the data
#      comes from the `data` branch instead.
#
# Usage:
#   scripts/purge_data_history.sh --dry-run     # show what would be rewritten
#   scripts/purge_data_history.sh --yes-rewrite-history
set -euo pipefail

PATHS=(
  docs/metrics.json
  docs/landing.json
  docs/scorecard.json
  data
)

cd "$(git rev-parse --show-toplevel)"
MODE="${1:---dry-run}"

echo "paths to purge from all history:"
printf '    %s\n' "${PATHS[@]}"
echo
echo "commits currently touching them:"
for p in "${PATHS[@]}"; do
  printf '    %-24s %s commits\n' "$p" "$(git rev-list --count HEAD -- "$p")"
done
echo "repo size now: $(git count-objects -vH | awk '/size-pack/{print $2, $3}')"
echo

if [ "$MODE" = "--dry-run" ]; then
  cat <<'MSG'
--dry-run: nothing changed.

To actually rewrite history you need git-filter-repo (a single Python file,
free: https://github.com/newren/git-filter-repo):

    pip install git-filter-repo

then re-run with --yes-rewrite-history.
MSG
  exit 0
fi

if [ "$MODE" != "--yes-rewrite-history" ]; then
  echo "refusing: pass --yes-rewrite-history once you have read the header and taken a backup" >&2
  exit 1
fi

command -v git-filter-repo >/dev/null 2>&1 || {
  echo "error: git-filter-repo not found. pip install git-filter-repo" >&2; exit 1; }

args=()
for p in "${PATHS[@]}"; do args+=(--path "$p"); done

echo "rewriting history (this creates a fresh commit graph)…"
git filter-repo --invert-paths "${args[@]}" --force

echo
echo "history rewritten. repo size now: $(git count-objects -vH | awk '/size-pack/{print $2, $3}')"
cat <<'MSG'

Remaining steps, done deliberately by you:

  1. Check the result:   git log --oneline | head
                         git log --all --oneline -- docs/landing.json   # expect nothing
  2. filter-repo removes the remote to stop an accidental push. Re-add it:
                         git remote add origin <your remote url>
  3. Force-push every branch and tag:
                         git push --force --all origin
                         git push --force --tags origin
  4. Tell collaborators to re-clone. Old clones will not merge cleanly.
MSG

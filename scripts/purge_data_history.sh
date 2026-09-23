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
#   3. Confirm the live site does not depend on the paths being purged. Once the
#      data is sealed it does not: only the PLAINTEXT is removed, and the sealed
#      *.json.enc at the tip are kept (a pattern ending in .json does not match
#      .json.enc). Before sealing, it would take the site's data with it.
#   4. Run it in a fresh FULL clone (`git clone --mirror`), never a shallow one:
#      rewriting a shallow graph and force-pushing silently misses history.
#   5. Delete stale remote branches first (`git branch -r`). Each one carries the
#      plaintext history up to its fork point, and `push --force --all` only
#      rewrites the branches this clone has locally.
#
# Usage:
#   scripts/purge_data_history.sh --dry-run     # show what would be rewritten
#   scripts/purge_data_history.sh --yes-rewrite-history
set -euo pipefail

# The PLAINTEXT, and only the plaintext. Sealing the data (crypto_data.py)
# protects every version committed from then on; every version committed before
# it is still readable by anyone who clones, and that is what this removes. The
# sealed *.json.enc are kept, so the tip keeps its data and the pipeline its
# history. metrics_v3.json is an early root-level copy the list used to miss.
PATHS=(
  docs/metrics.json
  docs/landing.json
  docs/scorecard.json
  docs/lineage.json
  metrics_v3.json
)
GLOBS=(
  'data/*/*.json'
)

cd "$(git rev-parse --show-toplevel)"
MODE="${1:---dry-run}"

echo "plaintext to purge from all history:"
printf '    %s\n' "${PATHS[@]}" "${GLOBS[@]}"
echo
echo "commits touching them, across every ref:"
for p in "${PATHS[@]}"; do
  printf '    %-24s %s commits\n' "$p" "$(git rev-list --count --all -- "$p")"
done
for g in "${GLOBS[@]}"; do
  printf '    %-24s %s commits\n' "$g" "$(git rev-list --count --all -- ":(glob)$g")"
done
if [ -f "$(git rev-parse --git-dir)/shallow" ]; then
  echo "::warning:: this clone is SHALLOW -- counts are lower bounds, and rewriting it would miss history"
fi
# Sealed blobs anywhere in history that open under a password already public:
# effectively plaintext, and kept by the *.json.enc rule above unless stripped.
PUBLIC_BLOBS="$(mktemp)"
python3 scripts/crypto_data.py scan-public "$PUBLIC_BLOBS" | tail -1
echo
echo "pull-request refs GitHub keeps (a force-push cannot rewrite these):"
git ls-remote origin 'refs/pull/*' 2>/dev/null | awk '{print "    " $2}' || true
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

if [ -f "$(git rev-parse --git-dir)/shallow" ]; then
  echo "refusing: this clone is shallow. Use a fresh full clone (git clone --mirror)." >&2
  exit 1
fi

args=()
for p in "${PATHS[@]}"; do args+=(--path "$p"); done
for g in "${GLOBS[@]}"; do args+=(--path-glob "$g"); done
# and the envelopes sealed under a public password, found above
[ -s "$PUBLIC_BLOBS" ] && args+=(--strip-blobs-with-ids "$PUBLIC_BLOBS")

echo "rewriting history (this creates a fresh commit graph)…"
git filter-repo --invert-paths "${args[@]}" --force

echo
echo "history rewritten. repo size now: $(git count-objects -vH | awk '/size-pack/{print $2, $3}')"
cat <<'MSG'

Remaining steps, done deliberately by you:

  1. Check the result:   git log --oneline | head
                         git log --all --oneline -- docs/landing.json   # expect nothing
                         git ls-files '*.enc' | wc -l                   # sealed data still there
  2. filter-repo removes the remote to stop an accidental push. Re-add it:
                         git remote add origin <your remote url>
  3. Force-push every branch and tag:
                         git push --force --all origin
                         git push --force --tags origin
  4. Tell collaborators to re-clone. Old clones will not merge cleanly.
  5. refs/pull/*/head (listed above) are GitHub's own and survive any force-push:
     old pull requests keep their plaintext history, fetchable by anyone. Only
     GitHub Support can remove them -- or making the repository private hides them.
MSG

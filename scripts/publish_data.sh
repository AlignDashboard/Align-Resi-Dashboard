#!/usr/bin/env bash
# Publish the dashboard's data files to the `data` branch as a SINGLE commit,
# replacing whatever was there. The branch is rewritten each time, so only the
# current data exists in git — nothing accumulates, and there is no back
# catalogue of last month's financials sitting in history.
#
# Uses git plumbing rather than checking out a branch, so your working tree and
# current branch are untouched.
#
# Usage:
#   scripts/publish_data.sh                 # publish to origin
#   scripts/publish_data.sh --dry-run       # build the commit, do not push
#   REMOTE=upstream scripts/publish_data.sh # different remote
set -euo pipefail

BRANCH="${BRANCH:-data}"
REMOTE="${REMOTE:-origin}"
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

FILES=(docs/metrics.json docs/landing.json docs/scorecard.json docs/lineage.json)

cd "$(git rev-parse --show-toplevel)"

present=()
for f in "${FILES[@]}"; do
  if [ -s "$f" ]; then
    present+=("$f")
  else
    echo "warning: $f missing or empty — not publishing it" >&2
  fi
done
[ ${#present[@]} -gt 0 ] || { echo "error: no data files to publish" >&2; exit 1; }

# Build a tree containing just the data files, flattened to the branch root.
tree=$(
  for f in "${present[@]}"; do
    blob=$(git hash-object -w "$f")
    printf '100644 blob %s\t%s\n' "$blob" "$(basename "$f")"
  done | git mktree
)

# No parent: the commit has no history behind it, which is the point.
msg="Data snapshot $(date -u +%Y-%m-%dT%H:%M:%SZ)

Single-commit branch, rewritten on every publish so no previous version of the
data remains in git. Files: $(printf '%s ' "${present[@]##*/}")"
commit=$(printf '%s' "$msg" | git commit-tree "$tree")

echo "built commit $commit for branch '$BRANCH':"
git ls-tree --long "$tree" | sed 's/^/    /'

if [ "$DRY" = 1 ]; then
  echo "--dry-run: not pushing. To publish:  git push --force $REMOTE $commit:refs/heads/$BRANCH"
  exit 0
fi

# --force is intentional and safe here: the branch is a snapshot, not a history.
git push --force "$REMOTE" "$commit:refs/heads/$BRANCH"
echo "published to $REMOTE/$BRANCH (previous snapshot replaced)"

#!/usr/bin/env bash
# Everything the daily run DERIVES from the reports it fetched, in order:
# metrics, the three scorecard fills, the lineage.
#
# One definition, run twice when it has to be. update.yml's build step runs it
# once; scripts/commit_and_push.sh runs it again on top of the new main when
# the run's push loses a race (open item A15). The rebuild therefore cannot be
# a different sequence from the build it replaces -- a step added here is in
# both, and a step added anywhere else is in neither.
#
# It reads the reports already on disk (_downloads/, gitignored, so a reset to
# a newer main leaves them in place) and fetches nothing. Stages run in order
# and the first failure stops it: a half-filled scorecard is not committable.
#
# Usage: bash scripts/build_pipeline.sh
set -euo pipefail
cd "$(dirname "$0")/.."

TIMINGS=()

stage() {
  local name=$1 start=$SECONDS
  shift
  [ -n "${GITHUB_ACTIONS:-}" ] && echo "::group::$name"
  echo "== $name"
  "$@"
  local took=$((SECONDS - start))
  [ -n "${GITHUB_ACTIONS:-}" ] && echo "::endgroup::"
  echo "   $name took $((took / 60))m$((took % 60))s"
  TIMINGS+=("| $name | $((took / 60))m$((took % 60))s |")
}

# The measured KPI values have to be filled on the runner, not locally: the
# reports only exist there. build_metrics has just written the scrubbed
# data/<slug>/delinquency.json that this reads. This is also what takes the
# delinquency cells back from the --from-landing fill before it, per G3.
fill_measured() {
  local f slug
  for f in data/*/delinquency.json; do
    [ -e "$f" ] || continue
    slug=$(basename "$(dirname "$f")")
    python scripts/populate_scorecard.py --from-pipeline "$slug"
  done
}

# The building-metrics CSV lands in the Drive EliseAI Reports folder and needs
# no parse/accumulate step: populate_building_metrics fills the scorecard from
# it directly. Drive's landed_at rides along as the arrival time, so "data last
# updated" reflects when the export actually arrived rather than when someone
# handed it over. Runs after the delinquency fill so the never-take-an-owned-
# cell rule sees the other feeds' claims.
fill_building_metrics() {
  python - <<'EOF'
import json, pathlib, subprocess, sys
folder = pathlib.Path("_downloads/bldg_metrics_csv")
csvs = sorted(folder.glob("*.csv")) if folder.exists() else []
if not csvs:
    print("no building-metrics CSV this run"); sys.exit(0)
newest = csvs[-1]
landed = next((e.get("landed_at")
               for e in json.load(open("_downloads/manifest.json"))
               if e.get("name") == newest.name), None)
cmd = [sys.executable, "scripts/populate_building_metrics.py", str(newest)]
if landed:
    cmd += ["--received-at", landed]
print("running:", " ".join(cmd))
sys.exit(subprocess.call(cmd))
EOF
}

stage "Build metrics" python scripts/build_metrics.py

# The statement-derived cells --from-landing owns alone -- NOI Margin %,
# Concession Load %, Controllable OpEx/Unit, Budget Variance %, Month to Month
# Leases -- used to move only when someone ran this by hand, so they published
# July figures for a month after the August statement landed (open item H1).
#
# It runs BEFORE the --from-pipeline fill, not after, and the order is the
# whole point. Both paths fill the same two delinquency cells and the last run
# wins; a --from-landing run going last is what put a six-week-old workbook tab
# in front of a same-week Drive AR report on 2026-09-03, moving the published
# rate from 6.7% to 4.6% with nothing failing and nothing saying so (open item
# G3). Going first, its figures stand where no Drive feed owns the cell and are
# overwritten where one does.
stage "Fill workbook-derived KPI values into the scorecard" \
  python scripts/populate_scorecard.py --from-landing

stage "Fill measured KPI values into the scorecard" fill_measured

stage "Fill the scorecard from the building-metrics export" fill_building_metrics

# After the fills, so the chain reports what this run actually produced --
# which reports arrived, when they landed, which scorecard cells each feed
# ended up owning. It refuses to write if a card anchor or a data-table id it
# names has gone missing, which fails the run rather than publishing a map that
# points at nothing.
stage "Build the data lineage" python scripts/build_lineage.py

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    echo "### Build"
    echo
    echo "| Stage | Time |"
    echo "| --- | --- |"
    printf '%s\n' "${TIMINGS[@]}"
    echo
  } >> "$GITHUB_STEP_SUMMARY"
fi

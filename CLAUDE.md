# Align Resi Dashboard

Static dashboard published with GitHub Pages, fed by a daily metrics pipeline.

## Workflow

**Commit and push small changes directly to `main`. Do not open a pull request
unless I ask for one.** This is a solo repo with no CI and no required reviews,
so a PR per change just adds a merge step. Push straight to `main` and tell me
what changed.

Use a branch and a PR **only when I explicitly ask for one.** Do not decide a
change is big or risky enough to warrant a PR on your own — that call is mine.
If something seems large enough to be worth reviewing first, say so and let me
ask for the PR; do not open one preemptively.

## Layout

| Path | Purpose |
| --- | --- |
| `docs/index.html` | The whole dashboard: markup, CSS, and Chart.js rendering in one file |
| `docs/metrics.json` | Data the page fetches at load; written by the pipeline, not by hand |
| `scripts/` | `fetch_drive.py` pulls source reports, `build_metrics.py` writes `metrics.json` |
| `config/` | `properties.json` and `report_map.json` — property list and report routing |
| `data/` | Scrubbed per-property pipeline output. Raw reports live in `_downloads/` and are never committed |

## Refreshing The Landing

`docs/landing.json` is generated from the analyst workbook, not by the daily
cron. To refresh with new reports:

1. Paste the new reports into the workbook's grey `Source *` tabs.
2. **Open it in Excel and let it recalculate, then save.** The extractor reads
   cached formula results; a workbook saved without recalculating has none, and
   every derived number would come out null. The extractor detects this and
   refuses rather than publishing nulls.
3. `python scripts/extract_landing.py <workbook.xlsx>`

It prints a check table and exits non-zero if anything would put wrong numbers
on the page — a shifted month axis, a unit count that disagrees with `Inputs`,
a broken statement tie-out, a renamed anchor label. Nothing is written on
failure, so the live file keeps the last good data.

`scripts/test_extract_landing.py <workbook.xlsx>` runs the guard tests,
including deliberately broken workbooks that must be refused.

Which report feeds what (the workbook's own `Data Lineage` tab is authoritative):

| Grey tab | Report | Drive folder |
| --- | --- | --- |
| `Source CY25`, `Source Aug25-Jul26` | 12-month accrual statement | T12 Expenses |
| `Source Rent Roll Jul` / `Jun` | SPV PM Deliverable Package, Rent Roll tab | Rent Roll |
| `Source Delinquency` | `rs_rp_DelinquencySummaryReport` | Residential AR Analytics |
| `Source Renewal Tracker` | Landing 2025 Renewal Tracker (monthly + MTM tabs) | *(no Drive folder yet)* |
| `Lease Detail` | RealPage rate tracker — **typed in, not a grey tab** | Weekly Leasing Reports |

T12, Rent Roll and Residential AR Analytics have parsers in
`config/report_map.json`; the rest are `pending`. The renewal tracker has no
Drive folder at all, so its grey tab is refreshed by pasting. Trade-out data
will not update from the grey tabs either — `Lease Detail` is hand-entered.

The workbook was restructured in V37: the `Holdovers` tab became `MTM` (same
content, per-unit vacate flags added), and `MTM Analysis` (tracker
reconciliation — its roster carries tenant names, only aggregates are
extracted), `Scorecard` (scored insights + open questions, published as the
landing page's Insights card) and `Source Renewal Tracker` are new. The
renewal/holdover scenario models charge a recurring incremental-vacancy haircut
on the new run-rate instead of one-time make-ready/downtime costs.

## Refreshing The KPI Scorecard

`docs/scorecard.json` comes from the KPI scorecard workbook, in two steps that
must run **in this order**:

1. `python scripts/extract_scorecard.py <KPI_Scorecard.xlsx>` — the grid's
   hand-set symbols, the metric groups, and (since v10) the published target
   ranges and the Palma lease-up overrides. **This resets every measured value
   to null**, which is why it goes first.
2. `python scripts/populate_scorecard.py --from-landing` — fills the measured
   numbers a report can actually answer and re-derives those cells' status from
   the published band, keeping the workbook's original symbol in
   `status_workbook`. Re-runnable and idempotent; it rebuilds the per-property
   counts and the portfolio roll-up so the matrix, health chart and tally cannot
   drift apart.

A delinquency report answers exactly two of the 28 KPIs:

- `Total Deliquency` — gross resident AR over one month's billed rent, graded
  against the published band. The report alone does not carry the rent, so pass
  `--monthly-rent` when working from a raw report.
- `Split Between 30/60/90` — the report's three past-due buckets printed as
  `31-60/61-90/90+` in dollars. **Reported, not graded:** a distribution has no
  single direction it can be good or bad in (the ranges sheet says as much in
  its own basis note), so the cell carries no symbol and no colour and is left
  out of the at-or-above-target counts. The `UNSCORED` set in
  `extract_scorecard.py` is what marks it, and `docs/scorecard.json` publishes
  the list as `unscored` so the page can render those cells plainly.

`POs over 30 days` and `# of invoices processed` are accounts *payable* and a
resident AR report cannot speak to them.

The v10 legend made the in-range band white — no colour indicator — and
`extract_scorecard.py` fails loudly if the workbook's legend fills change again,
rather than publishing stale semantics.

## Deployment

GitHub Pages serves `docs/` from `main`. Pushing to `main` rebuilds the live
site within a minute or two. `.github/workflows/update.yml` regenerates
`metrics.json` on a daily cron and commits it back.

Changes to `index.html` will not appear until they are on `main`. A hard refresh
is often needed after a deploy, since the page caches aggressively.

### Keeping data out of git history (migration, not yet active)

Committing the data JSON means every past month's financials stay readable in
history forever. `.github/workflows/deploy.yml` fixes that: it deploys `docs/`
to Pages from an artifact assembled at run time, taking the site shell from
`main` and the data JSON from a `data` branch.

`scripts/publish_data.sh` writes that branch as a **single commit with no
parent**, force-replacing it each time, so only the current data exists in git —
verified: three consecutive publishes leave exactly one commit and one
recoverable version.

**One manual step activates this:** Settings → Pages → Build and deployment →
Source → **GitHub Actions**. Until that is flipped, the live site is still served
from `main`. `deploy.yml` falls back to the JSON committed in `main` when the
`data` branch does not exist, so nothing breaks mid-migration.

`deploy.yml` is *not* dormant before the flip — it is not a no-op. It runs on
every push, and `deploy-pages` really does create a Pages deployment, which then
loses a race: GitHub's own `pages build and deployment` also fires on the push
and finishes ~20s later, so the branch build is what ends up live. Observed on
`500b0d5`: our deploy reported success at 01:22:36, the branch build deployed at
01:22:58. Harmless only because both currently publish identical bytes. Once the
data comes from the `data` branch they would differ, and which one wins would be
a coin toss — which is the real reason the flip has to happen before step 2
below, not just a tidiness preference.

After flipping it, in order:

1. `scripts/publish_data.sh` — create the `data` branch.
2. Confirm the site still loads, then stop committing data to `main`: drop
   `docs/*.json` from tracking and change `update.yml` to publish to the `data`
   branch instead of committing.
3. `scripts/purge_data_history.sh --dry-run`, then `--yes-rewrite-history`, to
   remove the data already in history. Tested on a throwaway clone: 63 commits →
   40, every data path gone from every commit, site shell and scripts intact.
   Read the script's header first — it rewrites history, needs a force-push, and
   **cannot un-publish anything that was already public.**

## Tenant names must not leave the pipeline

The rent roll and delinquency reports arrive with tenant names. Parsers read
them (the rent roll needs `resident_code` to tell an occupied unit from a vacant
one) but **nothing may persist them**. `build_metrics.scrub()` strips
`PII_FIELDS` from every report on the way to disk — centrally, in
`store_report`, so a new parser is covered by default rather than by remembering.

`scripts/check_no_pii.py` is the check that this holds, and it runs in both
workflows: `update.yml` will not commit and `deploy.yml` will not publish if it
fails. Three passes — person-shaped keys in the published JSON, raw reports or
per-unit output tracked in git, and (with `--source <report.xlsx>`) every real
name in a source report searched for by word boundary in every published file.
Run it locally the same way after any change to a parser or the extractor.

Raw reports are gitignored (`_downloads/`, `*.xlsx`, `tests/fixtures/`,
`data/*/rent_roll.json`, `data/*/delinquency.json`) because they hold everything.
`data/*/expense_ratio.json` stays tracked: it is aggregate ratios only, and
`build_metrics` reads it back as the rolling-T12 series.

**Anything the page displays is in a file anyone with the URL can download.**
There is no "visible on the page but not otherwise accessible" on a static site
— the page fetches JSON over HTTP. That is why names are dropped from the data
entirely rather than merely hidden from a table. Displaying them would require
encrypting the JSON or putting the site behind real auth.

## Notes

- The page is gated by a client-side password constant in `index.html`. This is
  visibility deterrence, not encryption — the source is public and readable. Do
  not treat it as protecting anything. Real financials need client-side
  encryption of `metrics.json` first.
- `index.html` is the only place the password is entered. Unlocking sets
  `sessionStorage["align-unlocked"]`; `data.html` requires that marker and
  redirects to `index.html?next=data.html` without it, so the data tables are
  not a second way in. The unlock lasts the browser session, not forever. Any
  new gated page should follow the same pattern rather than adding its own
  password field — and note the marker is client-side like the gate itself, so
  it deters, it does not protect.
- `metrics.json` values flow into the DOM. When rendering anything from it,
  prefer `textContent` / `createElement` over `innerHTML` so pipeline data
  cannot inject markup.
- Charts come from a Chart.js CDN script tag. Sandboxed environments often block
  it, producing `Chart is not defined` — that is an environment artifact, not a
  page bug.
- Verify UI changes by serving `docs/` and driving the page in a real browser
  through the password gate, not by reading the diff alone.

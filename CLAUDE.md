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
| `data/` | Raw fetched reports, per property |

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
| `Lease Detail` | RealPage rate tracker — **typed in, not a grey tab** | Weekly Leasing Reports |

Only the T12 has a parser in `config/report_map.json` today; the rest are
`pending`, so a Drive-driven refresh still needs those parsers written. Trade-out
data will not update from the grey tabs at all — `Lease Detail` is hand-entered.

## Deployment

GitHub Pages serves `docs/` from `main`. Pushing to `main` rebuilds the live
site within a minute or two. There is no build step and no deploy workflow —
`.github/workflows/update.yml` only regenerates `metrics.json` on a daily cron
and commits it back.

Changes to `index.html` will not appear until they are on `main`. A hard refresh
is often needed after a deploy, since the page caches aggressively.

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

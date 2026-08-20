# Open Items

State as of 2026-08-20, HEAD `e0ac9bc`. IDs are stable — when an item closes, move
it to *Closed* rather than renumbering, so "A3" means the same thing next week.

**Live and uncertain** marks an item where the dashboard is publishing something
today that depends on the unresolved answer. Those are the ones worth taking
first: everything else is a gap, but these are assertions.

## A · Blocked on the owner (a file, an answer, or a click)

| # | Item | What it blocks | Live and uncertain |
| --- | --- | --- | --- |
| A1 | Re-export the `rs335` T12 statement from Yardi, then delete the `quarantine` block in `config/properties.json` | 335 Third's expense ratio and its revenue denominator. Quarantined 2026-08-19 because the statement's figures are not this building's | no — the figures are withheld, not published |
| A2 | Re-supply `metricsbuilding20260819.csv` | Recording a real `bldg_received_at`. It is `null` for Landing, Chorus, Madelon and 335 Third, so the page falls back to the as-of date (and says so on hover) | no — the fallback is disclosed |
| A3 | Send `…rs335_accrual.xlsx` and `…rspalman_Accrual (3).xlsx` — **or** let me add a header dump to the pipeline log, which needs nothing from you | The two-month offset. The two statements' monthly ratios match at +2 months, so one has the wrong period, and the T12 parser's month columns are hardcoded (`MONTHS_COLS`) with the header found by first-row-containing-a-month | **yes** — Palma's 56.1% ratio and its delinquency denominator ride on these periods |
| A4 | Is the PSF chart's $4.01/sqft for 335 Third asking rent, or wrong? | Correcting either the figure or its "Rent Per Sqft, 30-Day Avg" label. Hand-entered, not pipeline-derived, for a building with no signed leases | **yes** — displayed on the portfolio view now |
| A5 | Which weekly copy is authoritative — the emailed attachment or the Drive file? Should `_Unsorted` be fetched? | The weekly-baseline parser, and with it Closing Ratio, # of Renewals, and the offer/MTM KPIs. The two copies currently carry different weeks; the Aug 18 file sits in `_Unsorted`, which `fetch_drive.py` ignores by design | no |

## B · Blocked on an answer from EliseAI

| # | Item | What it blocks | Live and uncertain |
| --- | --- | --- | --- |
| B1 | What period does the building-metrics export cover? | Trade-out %, Closing Ratio and # of Renewals are all defined on a trailing-3-month basis. The file states its period nowhere inside — only the filename carries a date | **yes** — three KPIs graded against an unconfirmed window |
| B2 | What unit is `AI Response Time`? | Grading Avg First Response Time. Seconds → 0.6 min (green); minutes → ~36 min (red). `RESPONSE_IS_SECONDS` in `populate_building_metrics.py` | no — published value-only for exactly this reason |
| B3 | What does EliseAI count as an "open task"? | Open Elise Tasks is mapped to the daily email's "Review N pieces of pending knowledge" (`OPEN_TASKS_FROM_KNOWLEDGE`). Flat at 4 for eight consecutive days while `escalations_open` moved 0→5→4→3→5→9→5→2 like a live queue should | **yes** — graded green at the band edge (green is ≤ 4) off an assumption |
| B4 | Which delinquency basis is right for The Landing — the export's 11.2% or the workbook's 4.6%? | Whether the export can ever own that cell. The workbook wins today and the export is skipped there | no — the tie-out basis is the one published |
| B5 | Does the export really see 3 of 37 units leased at 335 Third? | Its Leased % of 8.1% is exactly 3/37, but no lease has been signed | no — filled but ungraded under the lease-up rule |

## C · Drive housekeeping (surfaced by the pipeline logs)

| # | Item | Detail |
| --- | --- | --- |
| C1 | A `Delinquency` folder in Drive is not in `report_map.json` | Holds `Delinquency_8_1_2026.xls.xlsx`, ignored every run, and duplicates the file already in `Residential AR Analytics`. Register it or remove it |
| C2 | `Weekly Leasing Reports` is registered but absent from Drive | CLAUDE.md names it as the source for the workbook's `Lease Detail` tab, so either the folder or the documentation is wrong |
| C3 | `_Unsorted` holds the Aug 18 weekly file | Deliberately ignored by `fetch_drive.py`. Tied to A5 |

## D · Parsers not built

Registered in `report_map.json` as `pending`. Each needs one sample file to write
against; none is blocked on anything else.

| # | Drive folder |
| --- | --- |
| D1 | Weekly Leasing Reports (see A5, C2) |
| D2 | EliseAI Reports — the weekly funnel baseline |
| D3 | Property Status |
| D4 | Concession Burnoff |
| D5 | AIRM - Yardi Rev Management |
| D6 | AP Analytics |
| D7 | `Workorders - Mainentance ` (note the typo and trailing space in the folder name) |

## E · Keeping data out of git history

Documented in CLAUDE.md and built but not activated. Strictly ordered.

| # | Step |
| --- | --- |
| E1 | Settings → Pages → Build and deployment → Source → **GitHub Actions**. `deploy.yml` is not dormant before this: it runs on every push and loses a race with GitHub's own branch build, harmless only while both publish identical bytes. Once data comes from the `data` branch they would differ and the winner would be a coin toss |
| E2 | `scripts/publish_data.sh` to create the `data` branch, confirm the site loads, then drop `docs/*.json` from tracking and change `update.yml` to publish to `data` instead of committing |
| E3 | `scripts/purge_data_history.sh --dry-run`, then `--yes-rewrite-history`. Rewrites history, needs a force-push, and cannot un-publish anything already public |

## F · Cosmetic, awaiting a yes/no

| # | Item |
| --- | --- |
| F1 | The floorplan table is still on `data.html`. The card is off the Landing board; the data table stayed because that page exists to show everything the JSON holds |
| F2 | The shared scorecard note prints on every property card, including the line about Palma's lease-up overrides, which reads oddly on Chorus. Can be scoped per property |

## Closed

2026-08-20 — 335 Third identity (the export and `rs335` are the same building; the
statement's figures are not); Palma's expense ratio built from one building
instead of two (127.3% → 56.1%); the mis-attributed "Apr 2026" point in Palma's
trend; Fitzgerald and 2177 Third removed; hand-set colours dropped from
unmeasured cells and the tally rebased on graded cells only (90.37% → 74%);
per-property scorecards on every tab; The Landing's board reordered and Floorplan
Mix removed; measured scorecard values linked to their source rows.

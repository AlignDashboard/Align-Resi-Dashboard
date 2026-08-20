# Open Items

State as of 2026-08-20, HEAD `e0ac9bc`. IDs are stable — when an item closes, move
it to *Closed* rather than renumbering, so "A3" means the same thing next week.

**Live and uncertain** marks an item where the dashboard is publishing something
today that depends on the unresolved answer. Those are the ones worth taking
first: everything else is a gap, but these are assertions.

## A · Blocked on the owner (a file, an answer, or a click)

| # | Item | What it blocks | Live and uncertain |
| --- | --- | --- | --- |
| A3 | Send `…rs335_accrual.xlsx` and `…rspalman_Accrual (3).xlsx` — **or** let me add a header dump to the pipeline log, which needs nothing from you | The two-month offset. The two statements' monthly ratios match at +2 months, so one has the wrong period, and the T12 parser's month columns are hardcoded (`MONTHS_COLS`) with the header found by first-row-containing-a-month | **yes** — Palma's 56.1% ratio and its delinquency denominator ride on these periods |
| A4 | Supply a market-survey export for the PSF chart (subject + comps, 30-day avg rent/sqft — the RealPage market survey or the AIRM feed both carry it). Owner confirmed the $4.01 is old | A live PSF card. The chart now says "hand-entered, date unknown — likely stale" on its face until a feed exists | contained — the staleness is disclosed on the card |
| A5 | ~~Which copy is authoritative~~ **Answered: the Drive files.** Remaining: owner is updating the gmail-filing script (C3) so weeklies land in `Weekly Leasing Reports`; parser is D1, in progress — the inspect workflow can now read `_Unsorted`, so the Aug 18 file's structure is obtainable today | D1 | no |

## B · Blocked on an answer from EliseAI

| # | Item | What it blocks | Live and uncertain |
| --- | --- | --- | --- |
| B2′ | Owner says the unit is **days** — now published as "35–37 days", value-only. That reading is implausible for an AI's first response, so worth an eyeball against a fresh export before anyone acts on it | Grading Avg First Response Time | contained — value-only, basis on hover |
| B3 | What does EliseAI count as an "open task"? | Open Elise Tasks is mapped to the daily email's "Review N pieces of pending knowledge" (`OPEN_TASKS_FROM_KNOWLEDGE`). Flat at 4 for eight consecutive days while `escalations_open` moved 0→5→4→3→5→9→5→2 like a live queue should | **yes** — graded green at the band edge (green is ≤ 4) off an assumption |
| B6 | The bands for Trade-out %, Closing Ratio and # of Renewals are written for a trailing-3-month basis, but the export grading them is trailing-1-month (owner, 2026-08-20) — a volatile month swings the grade more than the bands assume. Either re-band for 1 month or accept the noise | How much a single month can move those three grades | **yes** — three KPIs graded on a shorter basis than their bands assume |
| B4 | Which delinquency basis is right for The Landing — the export's 11.2% or the workbook's 4.6%? | Whether the export can ever own that cell. The workbook wins today and the export is skipped there | no — the tie-out basis is the one published |
| B5 | Does the export really see 3 of 37 units leased at 335 Third? | Its Leased % of 8.1% is exactly 3/37, but no lease has been signed | no — filled but ungraded under the lease-up rule |

## C · Drive housekeeping (surfaced by the pipeline logs)

| # | Item | Detail |
| --- | --- | --- |
| C2 | `Weekly Leasing Reports` is registered but absent from Drive | CLAUDE.md names it as the source for the workbook's `Lease Detail` tab, so either the folder or the documentation is wrong |
| C3 | `_Unsorted` holds the Aug 18 weekly file | Owner is updating the gmail-filing script so weeklies land in `Weekly Leasing Reports`. Meanwhile the inspect workflow (`--all`) can read `_Unsorted` for parser work |

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

2026-08-20 (owner round) — A1: no real T12 exists for 335 Third (new build, no
lease); the Jun 2026 statement is dummy data. The quarantine now carries
`through_period: Jul 2026`, so the dummy stays blocked and the first real
statement flows automatically, like Palma's. A2: `bldg_received_at` backfilled
with the fill's commit time (2026-08-19T19:33:19Z) — the CSV was handed over in
chat, never landed in a mailbox or Drive, so that is its honest arrival. B1: the
export is a snapshot on the filename's date; rate KPIs trail 1 month (spawned
B6). B2: unit is days per the owner — published as such, value-only, flagged as
implausible (B2′). C1: `Delinquency` folder registered as a second
`ar_analytics` source.

2026-08-20 — 335 Third identity (the export and `rs335` are the same building; the
statement's figures are not); Palma's expense ratio built from one building
instead of two (127.3% → 56.1%); the mis-attributed "Apr 2026" point in Palma's
trend; Fitzgerald and 2177 Third removed; hand-set colours dropped from
unmeasured cells and the tally rebased on graded cells only (90.37% → 74%);
per-property scorecards on every tab; The Landing's board reordered and Floorplan
Mix removed; measured scorecard values linked to their source rows.

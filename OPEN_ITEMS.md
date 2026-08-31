# Open Items

State as of 2026-08-31, HEAD `605aff3`. IDs are stable — when an item closes, move
it to *Closed* rather than renumbering, so "A3" means the same thing next week.

**Live and uncertain** marks an item where the dashboard is publishing something
today that depends on the unresolved answer. Those are the ones worth taking
first: everything else is a gap, but these are assertions.

## A · Blocked on the owner (a file, an answer, or a click)

| # | Item | What it blocks | Live and uncertain |
| --- | --- | --- | --- |
| A4 | Supply a market-survey export for the PSF chart (subject + comps, 30-day avg rent/sqft — the RealPage market survey or the AIRM feed both carry it). Owner confirmed the $4.01 is old | A live PSF card. The chart now says "hand-entered, date unknown — likely stale" on its face until a feed exists | contained — the staleness is disclosed on the card |
| A5 | ~~Which copy is authoritative~~ **Answered: the Drive files.** The funnel parser is live for both the `EliseAI Reports` and `Weekly Leasing Reports` folders, so the weeklies parse wherever the gmail-filing fix (C3) lands them. The Aug 18 file parses the day it moves out of `_Unsorted` | C3 only | no |
| A6 | Which property does the concession burn-off export cover? Settled empirically that the file itself cannot answer: the parser now walks it as sections and the only heading text is "Projection by Unit" — report structure, not a property name. Parses and ties out clean every run (−$54,990 recurring concessions as of 08/10), stored nowhere. Needs your word on what "For Selected Properties" selected, or a per-property re-export; the moment a heading or filename names a property, sections route and store by themselves | Concession Load % and the Effective-vs-Gross-Rent card | no — nothing publishes from it yet |
| A8 | Loss to Lease % now grades **red at 27%** against a band whose ceiling is 10%. The threshold sheet's own basis note warned about exactly this: if Yardi `Market rent potential` is aspirational rather than achievable, the KPI reads artificially high — and the market-rent table was revised up sharply from Apr 2026 (TTM reads 17.2% vs the current month's 27%). Wired per your instruction; whether the band or the denominator gets revisited is your call | Whether the red cell is a finding or an artifact of the denominator | **yes** — graded red off a disputed denominator |
| A9 | Controllable OpEx/Unit's cutoffs ($7,200 / $8,600) were bracketed around the old basket's $7,784/unit T12 actual. The basket now excludes taxes, insurance, utilities **and the management fee** (set 2026-08-28), under which the twelve months run $5,659–$8,458 (avg ~$6,997) and July grades exceeding. Worth re-bracketing the cutoffs to the basket they now grade, in the ranges sheet | Whether "exceeding" means outperformance or a band calibrated to a bigger basket | contained — the page's `how` states the live basket; `how_workbook` keeps the sheet's |
| A10 | Extend the COA mapping workbook to cover the 10 JPM accounts (~$115k of T12) it does not map: Carpets, Alarm monitoring, Courtesy patrol, two Turnover lines, Credit reports, Credit Card Fees, Courtesy/Concierge REIT-sensitive, Gross Rec./Bus. Lic. Tax, and a Professional Fees line. The pipeline groups them by label and logs them loudly meanwhile | Clean Align-tree grouping in the Expense Deep Dive and the controllable basket | contained — grouped by label, flagged each run |
| A11 | Confirm the five new folder names and two inferences behind them, before the Apps Script paste makes them real: `Renewal Tracker`, `Prospect Reports`, `Daily Leasing Reports`, `Daily Tracker`, `Demographics`. Each is a one-line change in `gmail_drive_filing.js` + `report_map.json` now, a folder rename later. Two judgement calls inside them: the **box score goes to `Property Status`** (the SOP's own routing table says box score is the property-status report), and **`Daily Tracker` is kept separate from `Daily Leasing Reports`** — the names are confusingly close and I split them on file size (~157KB vs ~55KB) without opening either, so they may be one family | Which folder five report families land in; a parser can be written for each once they land | no — nothing publishes from them |

## B · Blocked on an answer from EliseAI

| # | Item | What it blocks | Live and uncertain |
| --- | --- | --- | --- |
| B2′ | Owner says the unit is **days** — now published as "35–37 days", value-only. That reading is implausible for an AI's first response, so worth an eyeball against a fresh export before anyone acts on it | Grading Avg First Response Time | contained — value-only, basis on hover |
| B3 | What does EliseAI count as an "open task"? | Open Elise Tasks is mapped to the daily email's "Review N pieces of pending knowledge" (`OPEN_TASKS_FROM_KNOWLEDGE`). Flat at 4 for eight consecutive days while `escalations_open` moved 0→5→4→3→5→9→5→2 like a live queue should | **yes** — graded green at the band edge (green is ≤ 4) off an assumption |
| B4 | Which delinquency basis is right for The Landing — the export's 11.2% or the workbook's 4.6%? | Whether the export can ever own that cell. The workbook wins today and the export is skipped there | no — the tie-out basis is the one published |
| B5 | Does the export really see 3 of 37 units leased at 335 Third? | Its Leased % of 8.1% is exactly 3/37, but no lease has been signed | no — filled but ungraded under the lease-up rule |
| B6 | The bands for Trade-out %, Closing Ratio and # of Renewals are written for a trailing-3-month basis, but the export grading them is trailing-1-month (owner, 2026-08-20) — a volatile month swings the grade more than the bands assume. Either re-band for 1 month or accept the noise | How much a single month can move those three grades | **yes** — three KPIs graded on a shorter basis than their bands assume |
| B7 | Ask EliseAI to add **Renewals Signed** and **Lease Expirations** columns to the building-metrics export — it publishes the rate and no count anywhere in its 79 columns. Today the `42/88.9%` cell splices the workbook tracker's count (to 2026-07-26) with the export's trailing rate; same-window columns would make the two halves one number, and give Chorus/Madelon a count at all | A single-basis # of Renewals cell for every property | contained — the split basis is stated on the cell |

## C · Drive housekeeping (surfaced by the pipeline logs)

| # | Item | Detail |
| --- | --- | --- |
| C3 | **`_Unsorted` holds 22 files. The routing fix is written and tested; it needs pasting into Apps Script.** Not one weekly file but four weeks of five report families — the filer matched none of them. `scripts/gmail_drive_filing.js` now routes all 22 (verified against the real filenames by `scripts/test_routing.py`, 21 cases green). Deploy: paste the `.js` into the `file downloader` project, run `previewRouting` and `checkFolders`, then `resortExistingFiles` — `_Unsorted` is a retry queue, so all 22 are rescued in that one run. Nothing moves until that paste happens |
| C4 | **Move the rent roll into the `Rent Roll` folder.** The registered folder is still empty (confirmed in the 2026-08-31 fetch log: `contains 0 file(s)`). The file (`2026-07-14 RentRoll07_14_2026.xlsx`) moved on 2026-08-31 but to `Archive Reports` under `Resi Dashboard` — still outside the folder the fetcher scans, and outside what `resortExistingFiles` can reach, so the script will not rescue it. The parser is written and registered; moving the file is the whole fix. It is also the prerequisite for feeding Month to Month Leases per property from the pipeline rather than the workbook |
| C5 | **`Building Info` has left the scanned folder, and the unit directory has stopped arriving.** The 2026-08-31 fetch log warns `subfolder 'Building Info' not found in Drive parent`; it now sits under `Resi Dashboard` rather than `Report Lander`. Because `data/the-landing/unit_directory.json` is committed, the unit-gaps table still renders — frozen on the 2026-08-25 export, with no error anywhere. Moving the folder back is the fix. Do it **before** the Apps Script paste: the new `Building Info` rule would otherwise create a second, empty folder of that name inside `Report Lander` and orphan the original |
| C6 | Rename `Workorders - Mainentance ` — a misspelling *and* a trailing space, carried in Drive and `report_map.json` both. Three changes that must land together (Drive folder, `report_map.json`, the `.js` rule); `test_routing.py` fails if only one moves. Harmless today because no work-order report has ever arrived |

## D · Parsers not built

Registered in `report_map.json` as `pending`. Each needs one sample file to write
against; none is blocked on anything else.

A parser cannot be truthfully written without a sample file; these folders have
never held one. The day a first file lands, the fetch log lists it (`[skip] …
file(s) waiting`) and the inspect workflow can dump its structure.

D1–D7 have never held a sample. **D9–D13 are different: their samples already
exist**, sitting in `_Unsorted` today, and land in their own folders the moment
C3 is deployed — so these five can be written against real files immediately
after. D3 joins them: the two box-score exports are its first samples.

| # | Drive folder |
| --- | --- |
| D1 | Weekly Leasing Reports — the folder's intended content, the RealPage rate tracker behind the workbook's `Lease Detail` tab, has never appeared (the funnel exports that pass through are D2's, and parse). The folder itself appears the first time a rate tracker arrives — see the closed C2 |
| D3 | Property Status — the two `BoxScoreSummary` exports are its first samples, and land here when C3 is deployed |
| D5 | AIRM - Yardi Rev Management |
| D6 | AP Analytics |
| D7 | `Workorders - Mainentance ` (note the typo and trailing space in the folder name) |
| D9 | Renewal Tracker — `Landing 2025 Renewal Tracker` and `Renewals since 9.15.25`. The workbook's `Source Renewal Tracker` grey tab is pasted by hand today, so a parser here would replace a manual step |
| D10 | Prospect Reports — `8.24-8.30 Prospect and applicant Report` |
| D11 | Daily Leasing Reports — `Daily Report- Week Ending …`, and the Madelon and Chorus daily reports |
| D12 | Daily Tracker — `Daily Tracker (14) (1) (43)` |
| D13 | Demographics — `rs_sql_JPM_Demographics_Combined` |

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
| F3 | Unit 647 is classed `lab21` in the Yardi Unit Directory and `lab9` in the workbook. At 830 sqft it sits inside lab9's range (827–863) and far outside lab21's other units (1,022–1,069), so the directory looks wrong — worth a word to the PM to fix in Yardi. No bedroom impact (both plans are 2-bed) |

## Closed

2026-08-31 — C2: not a discrepancy after all. `Weekly Leasing Reports` is absent
from Drive because the Apps Script filer **creates a folder on first use** and no
file has ever matched its patterns — the weekly funnel export does not, which was
C3. Registering it was never wrong. The rule stays, narrowed to the folder's
intended content (the RealPage rate tracker, `/ratetracker/` and `/realpage/`),
and the funnel now routes to `EliseAI Reports`, which exists. Also closed: the
`AIRM/Yardi Rev Management` and `Workorders/Maintaince` rules named folders that
do not exist — a `/` is legal in a Drive folder name, so the first real report of
either kind would have created a second folder the pipeline never reads, in
silence. Both now name the real folders, and `test_routing.py` fails if either
drifts again. The `Building Info` glob was anchored at `UnitDirectory*.xlsx`,
which the filer's date prefix defeats — the same bug `605aff3` fixed for the
funnel, found by the new check that every glob leads with `*`.

2026-08-28 — a long dashboard session, all pushed to `main` through `4ab9111`:
the scorecard now measures **11 of The Landing's KPIs** (was 7) — `--from-landing`
fills Loss to Lease % (current month, whole percent — spawned A8), NOI Margin %
(current month, TTM recorded beside it per the owner), Controllable OpEx/Unit
(less taxes, insurance, utilities and mgmt fee — spawned A9) and Month to Month
Leases (31/11.8%, the holdover cohort; the tracker's 4-unit overlap is inside
the 31, not beside it), and `# of Renewals` prints the tracker's signed count
beside the export's rate (spawned B7). `# of offers that are 30 days` is dropped
everywhere via `OMITTED_METRICS`; `# of month to month` publishes as
`Month to Month Leases` via `RENAMES`; both survive re-extraction. The Unit
Directory in Drive `Building Info` is parsed, registered and feeding bedrooms
into the unit-gaps table (tie-outs to the cent; spawned F3). The Landing's
scorecard slice hides AR/AP, Maintenance, Resident Experience and Open EliseAI
Tasks with an honest per-tab roll-up. New Operating Summary card from the
pipeline T12 (prev/T3/T12 toggle, columns pinned); Rent Capture is now Loss to
Lease; Expense Load & NOI's third line is controllable expense/door; the unit
gaps table carries beds/SF/expiry-MTM. The mobile layout is fixed (grid
min-width, in-card table scroll, finger-sized controls; verified on seven
device profiles). The rent roll's absence from the pipeline was traced to the
file sitting outside its Drive folder (spawned C4). The data-source map is
pinned as the "Landing Data Lineage" artifact.

2026-08-26 — A7: the statement arrived the day after it was asked for —
`12_Month_Statement_Accrual.xlsx` in `T12 Expenses`, covering all four Landing
codes (p0005611/12/71/40) in one file, on the **JPM tree** (jpm_bf1) rather than
align_resbv. The owner also supplied the COA mapping workbook, distilled into
`config/coa_map.json` by `scripts/extract_coa_map.py`; the parser translates JPM
leaves to Align accounts and groups them by the Align tree's own families,
tying out against the statement's TOTAL EXPENSES to the cent. Both Deep Dive
views now draw from it (T12 total $4.73M matches the workbook TTM opex; every
spot-checked month matches the workbook's monthly opex). The Landing joins the
expense-ratio card at 32.7% (basis: JPM total operating expenses). Going
forward the pipeline warns when a previously-reported code is absent from a new
statement, and lists the 10 JPM accounts (~$115k) the COA workbook does not yet
map — worth extending the mapping to settle them: Carpets, Alarm monitoring,
Courtesy patrol, two Turnover lines, Credit reports, Credit Card Fees,
Courtesy/Concierge REIT-sensitive, Gross Rec./Bus. Lic. Tax, and a Professional
Fees line.

2026-08-24 — A3, by the header dump instead of the re-export: the inspect
workflow now probes every T12 statement (`inspect_report.py --t12` — title rows
verbatim, parsed period, monthly ratios, and a pairwise table of which month
shift aligns two files). The run showed all four statements claim the **same**
period in their own title rows, `Period = Jul 2025-Jun 2026`, so no live
statement is mislabeled — the +2 offset lives inside the quarantined rs335
dummy's fabricated content, whose Sep–Apr columns carry Palma North's Jul–Feb
figures (7/10 overlapping months within 0.15pp, the exact pattern that raised
the item). Palma North's statement is period-consistent (title row = column
headers = parser read) and byte-identical in ratio across the Jul 15 and Jul 16
exports (12/12 at shift 0), so the 56.1% ratio and the delinquency denominator
stand on confirmed periods and the *live and uncertain* flag lifts. No file is
needed from the owner: rs335 has no real T12 until a lease signs, and A1's
`through_period` already lets its first real statement flow.

2026-08-20 (parser round) — D2: `parse_leasing_funnel` live for the `EliseAI
Reports` and `Weekly Leasing Reports` folders; per-community aggregates to
`data/<slug>/leasing_funnel.json`, portfolio-vs-communities tie-out, refusals
tested. D4: `parse_concession_burnoff` live — as-of, unit count and money
totals tied out against the report's own total row, names never emitted; stored
nowhere until A6 settles attribution. D8: the building-metrics CSV is fetched
from Drive (file_glob now honoured, so the CSV and the funnel xlsx in one
folder route separately) and `update.yml` runs `populate_building_metrics.py`
on the newest one with Drive's `landed_at` as the arrival — the A2 hand-off
step is gone. Exports' property labels route through `aliases` in
`config/properties.json`. Guard tests: `scripts/test_funnel_and_concessions.py`
(19 checks, fixture-free).

2026-08-20 (owner round) — A1: no real T12 exists for 335 Third (new build, no
lease); the Jun 2026 statement is dummy data. The quarantine now carries
`through_period: Jul 2026`, so the dummy stays blocked and the first real
statement flows automatically, like Palma's. A2: superseded by the real thing —
with D8 wired, the pipeline refilled the feed from the Drive copy and
`bldg_received_at` is now the CSV's true Drive arrival, 2026-08-19T19:20:41Z
(the commit-time backfill had been 13 minutes late). B1: the
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

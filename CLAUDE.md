# Align Resi Dashboard

Static dashboard published with GitHub Pages, fed by a daily metrics pipeline.

`OPEN_ITEMS.md` carries the current open items, numbered and grouped by what
each one is waiting on. Read it after this file when picking up work — it is
where state that used to arrive as a pasted handoff note now lives.

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
| `docs/data.html` | Two views behind the same gate: the **data-flow** chain, and the **tables** holding every number the JSON carries |
| `docs/lineage.json` | The chain the flow view draws; written by `scripts/build_lineage.py`, never by hand |
| `scripts/` | `fetch_drive.py` pulls source reports, `build_metrics.py` writes `metrics.json`; `gmail_drive_filing.js` is the Apps Script that files reports into Drive in the first place |
| `config/` | `properties.json` and `report_map.json` — property list and report routing; `coa_map.json` — JPM/Rubicon→Align chart-of-accounts mapping (refresh with `scripts/extract_coa_map.py <COA workbook.xlsx>` when the mapping workbook changes) |
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
| `Source Renewal Tracker` | Landing 2025 Renewal Tracker (monthly + MTM tabs) | Renewal Tracker |
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

## The Drive-Only Landing Tab

`Landing (Drive)` sits beside `The Landing` and shows the same building with the
V37 workbook taken out of it: every number on it comes from a report the Gmail
filer drops into Drive and the pipeline parses, so **dropping a fresh direct
export in Drive is the whole refresh**. The Landing tab is still the fuller
view — it just cannot move on its own, because refreshing it means pasting into
grey tabs, recalculating in Excel and re-running `extract_landing.py`.

The rule is applied **per number, not per card**. A card is on the tab only if
every figure on it would move on the next pipeline run.

| Card | Drive source |
| --- | --- |
| Operating Summary | T12 statement → `metrics.json` `monthly_pl` |
| KPI Scorecard — Drive feeds only | the eleven `scorecard.json` cells a Drive report fills |
| Expense Load & NOI | `monthly_pl` + `expense_buckets` + `unit_directory` |
| Expense Deep Dive | `expense_buckets` |
| Delinquency | the two cells the Drive AR report fills — empty whenever the workbook owns them |
| Unit Inventory | `unit_directory` — **frozen until C5**, see below |
| What Feeds This Tab | `lineage.json` — arrivals, and what is missing |

`renderOpSummary` and `renderExpenseDeep` are **shared** with The Landing rather
than copied. Neither ever read the workbook; the workbook half of the deep dive
(its no-statement fallback chart, the tie-out figures and the opportunities
table) is passed in as `wb`, and the Drive tab passes `null` — which is what
makes it tie the statement out against its own P&L line instead. A second copy
of a 200-line chart renderer would have drifted the first time one was edited.

Three things the tab is careful about, because getting them wrong would put an
unrefreshable number on a page that promises only live ones:

- **`measured[slug].kpis` over-reports.** `populate_scorecard` builds it from
  `prop.values`, which earlier runs also wrote, so The Landing's list names
  every cell any run has filled rather than the ones this feed filled. `only`
  in `SCD_DRIVE_FEEDS` narrows the unprefixed family to what
  `facts_from_pipeline` produces. (Same over-report is why the data-flow page
  credits the AR report with more cells than it answers; see open item G1.)
- **Naming the KPIs is not enough — the source has to be checked too.** The
  Drive AR report and the workbook fill *the same two cells* through
  `--from-pipeline` and `--from-landing`, and the last run wins. On 2026-09-03 a
  `--from-landing` run for Concession Load % put the workbook of 2026-07-20 back
  in front of a Drive report of 2026-08-31, so a filter reading the KPI list
  alone would have published a workbook number here. `fromDrive` in
  `SCD_DRIVE_FEEDS` reads the recorded `source` / `received_what` and drops the
  family when the workbook wrote last, which is why the Delinquency card is
  currently empty and says why (open item G3). It fills itself back in the next
  time `--from-pipeline` runs — nothing here needs editing. Note the card cannot
  quote the Drive report's filename in that state: `build_lineage` attributes
  evidence to whichever feed owns the cell, so the Landing row disappears from
  the `delinquency` flow the moment the workbook takes it.
- **`# of Renewals` prints as the rate alone.** The published `42/88.9%` splices
  the workbook tracker's count onto the export's rate, and only the rate comes
  from Drive.
- **NOI margin and controllable/door are derived, not borrowed.** The
  scorecard's cells for both are workbook-owned, so the tab computes them from
  `monthly_pl` / `expense_buckets` and the directory's `residential_units`.

Since `1819adb` and `2f34b17` moved `monthly_pl` and the expense ratio onto the
statement's **total expenses** line, everything on this card reconciles: NOI
margin agrees with the workbook's (72.5% against 72.6% for Jul 2026, the
difference being the revenue basis), the deep dive ties out against the top box
exactly, and the ratio agrees with the Portfolio tab's Expense Ratio card to a
tenth (33.3%). None of that is assumed — the card compares its own figure
against `expense_ratio.ratio_t12` and prints either the agreement or the two
bases, because the anchor is now recorded per property and Palma still keeps the
recoverable one.

One feed on the tab is **Drive-derived but not currently refreshable**, and the
page says so twice — on the Unit Inventory card and under the feed table —
because a frozen feed with a plausible arrival date is worse than a missing one.
`Building Info` sits in the Drive library rather than the drop tree, on purpose,
and `fetch_drive` only scans that tree when `GDRIVE_REFERENCE_FOLDER_ID` is set;
it is not, so the entry is skipped with a log line every run (open item C5). The
`blocked` field on that row in `SCD_FEED_ROWS` is what both notes read, so
closing C5 means deleting one field rather than hunting for prose.

`SCD_MISSING` is the honesty block: eight things The Landing shows that no Drive
export can refresh today, each with why and what would fix it. The counts in the
note under it are computed from the list rather than typed, so they cannot go
stale when a row moves. Five of the eight are one report away and three of those
five are the same one — the rent roll (open item C4).

## Refreshing The KPI Scorecard

`docs/scorecard.json` comes from the KPI scorecard workbook, in two steps that
must run **in this order**:

1. `python scripts/extract_scorecard.py <KPI_Scorecard.xlsx>` — the grid's
   hand-set symbols, the metric groups, and (since v10) the published target
   ranges and the Palma lease-up overrides. **This resets every measured value
   to null**, which is why it goes first.
`OMITTED_METRICS` in `extract_scorecard.py` is the list of grid columns the
dashboard does not publish at all — `# of offers that are 30 days` as of
2026-08-28. They are dropped at extraction rather than hidden on the page, so no
downstream table carries a KPI with no home, and their published range goes with
them. The workbook keeps its own column either way, and the extractor warns if a
name in the list stops matching a column.

2. `python scripts/populate_scorecard.py --from-landing` — fills the measured
   numbers a report can actually answer and re-derives those cells' status from
   the published band, keeping the workbook's original symbol in
   `status_workbook`. Re-runnable and idempotent; it rebuilds the per-property
   counts and the portfolio roll-up so the matrix, health chart and tally cannot
   drift apart.

A delinquency report answers exactly two of the 27 published KPIs:

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

`--from-landing` fills a third KPI the delinquency report cannot: **`Loss to
Lease %`**, the **current month's** loss to lease over market rent potential
from the workbook's Rent Capture series, as a whole number of percent. The
published basis is the current rent roll, so the newest month answers it rather
than the TTM column — which for The Landing differ sharply (27% for Jul 2026
against 17.2% TTM), because Yardi's market-rent table was revised up from Apr
2026. The threshold sheet's own basis note flags the risk this creates: if
`Market rent potential` is aspirational rather than achievable, every property
reads artificially high and grades red against a band whose ceiling is 10%. It
is wired and graded; whether the band or the denominator wants revisiting is
the owner's call.

`--from-landing` also fills **`NOI Margin %`** the same way — the current
month's NOI over revenue from the Expense & NOI series behind that card, to one
decimal. Note the direction of the caveat is the opposite of loss to lease's:
that KPI's published basis *is* the current rent roll, while this one's basis
line says **T12**, and a single accrual month swings well outside the band in
both directions (Apr 2026 reads 47.0% on that month's tax true-up, Jul 2026
reads 72.6% and grades green against a T12 of 66.8%). The month is what is
graded, per the owner; `noi_margin_ttm` is recorded beside it in
`measured[slug]` so the two are never confused.

`--from-landing` also fills **`Budget Variance %`** — calendar-YTD (January
through the T12 statement's newest month) actual controllable operating
expense against the same months of the year's budget, printed as **`$
nominal/% variance`**, signed, positive meaning an overspend. The budget is
the Yardi `12_Month_Budget_Accrual.xlsx` in the Drive **`Budgets`** folder —
the T12 statement's own layout on the JPM tree, so `parse_budget.py` reuses
the T12 parser's anchors, COA translation and Align-tree grouping (and its
to-the-cent tie-out), refusing a file with no `Budget` marker row or a period
that is not Jan–Dec of one year. Both sides of the variance are the **same
basket**: the Align-grouped buckets less `NOT_CONTROLLABLE`, actuals from
`data/<slug>/expense_buckets.json`, plan from `data/<slug>/budget.json`, with
the all-exclusions-found guard on each and a refusal when the budget's year
does not match the statement's. The band grades the **absolute magnitude**,
per its own "how" (a 12% underspend flags exactly like a 12% overrun). The
Landing reads **+$116,402/+12.1%** for Jan–Jul 2026, below; the workbook's
hand-set symbol said in-range and is kept in `status_workbook`. The signed
figures and window live in `measured[slug]` as `budget_variance_dollars` /
`budget_variance_pct` / `budget_variance_basis`. Note the band's cutoffs
predate the 2026-08-28 controllable basket (A9 applies here too).

This cell is filled by the `--from-landing` run but owes the workbook nothing —
both sides are Drive reports — so its provenance is recorded under its own
**`budget_`** family rather than the unprefixed one, and `budget_` is
registered in `SC_FEED_PREFIXES` (and `data.html`'s matching list) so the
budget's own Drive arrival shows on the page, and in `SCD_DRIVE_FEEDS` so the
`Landing (Drive)` tab carries the cell. It needs no `fromDrive` predicate:
unlike the delinquency pair, nothing else writes this KPI.

`--from-landing` also fills **`Concession Load %`** — the current month's
concessions over **market rent potential less loss to lease less vacancy
loss**, per the owner's equation set 2026-09-03. All four series come from the
Rent Capture block behind the Loss to Lease card — the same T12 statement
revenue lines that fill loss to lease — and they reconcile exactly to the
workbook's own rental-income line (GPR − L2L − vacancy − concessions −
allowance = rental income, to the cent), so the denominator is the statement's
rent income before concessions and the employee allowance. The Landing reads
**0.37%** for Jul 2026, exceeding; the workbook's hand-set symbol said in-range
and is kept in `status_workbook`. The ranges sheet's own "how" divided by gross
potential rent over a trailing 3-month window, so `how` is restated
(`CONCESSION_HOW` in `populate_scorecard.py`) with the sheet's wording kept in
`how_workbook`, and the trailing-3 figure (0.14%) is recorded as
`concession_load_t3` in `measured[slug]` beside the graded month. Vacancy loss
can run negative in a true-up month — Jul 2026 does — which per the equation
adds to the denominator rather than being clamped.

`--from-landing` also fills **`Month to Month Leases`** — the workbook's grid
calls that column `# of month to month`, and `RENAMES` in
`extract_scorecard.py` is what publishes it under the clearer name (the ranges
sheet is matched through the same map, so the band follows the rename). The cell
prints **`31/11.8%`**: units past lease expiry and still occupied, then their
share of occupied units. The **share** is what the band grades, per its own basis
line, so the raw value behind the cell stays the ratio. The Landing reads 31/262
for the 2026-07-14 rent roll, which grades below a band whose red line is 5%.

The rent roll has no month-to-month state of its own: the workbook classifies
every unit as Current, On notice, Holdover or Vacant, and those four partition
all 263. So a unit the rent roll calls month-to-month is already a Holdover —
which is why the **4** units the renewal tracker and the rent roll agree on sit
*inside* the 31 rather than beside it, and the total is 31, not 35. Both sides of
the workbook's own reconciliation report that 4 as the overlap. The tracker's MTM
roster is not used as a source: of its 17 units, 13 have a running lease, and it
misses 27 of the 31 holdovers.

`--from-landing` also fills **`Controllable OpEx/Unit`**: the current month's
operating expense **less taxes, insurance, utilities and the management fee**,
per unit, times twelve for the band's per-year basis. The Landing reads $6,697
for Jul 2026 (exceeding). The numerator comes from
`data/<slug>/expense_buckets.json` — the property's own T12 statement grouped on
the Align account tree — because the workbook's Expense & NOI tab carries only a
total and its own controllable cut, on a different basket. The Expense Load & NOI
card's third line is the same figure per month, and starts at the statement's
first month rather than the workbook's.

The band's **cutoffs** are the workbook's and untouched; the **basket** they are
applied to is the owner's, set 2026-08-28. The ranges sheet still describes an
older basket ("Excludes taxes, insurance, management fee", counting utilities as
controllable), so the fill restates `thresholds["Controllable OpEx/Unit"]["how"]`
to what it actually excluded and keeps the sheet's own wording in `how_workbook`
— a definition the published number does not follow is worse than a restated
one. Note the threshold's `basis` note still cites the older basket's $7,784/unit
as the T12 actual. Every exclusion is matched by name against the statement's
account groups and **all of them must be found**; a renamed group leaves the
figure unpublished rather than quietly counting taxes as controllable.

`populate_scorecard.py` merges into `measured[slug]` rather than replacing it,
so running it out of the documented order no longer drops the other feeds'
`bldg_*` and `eliseai_*` keys — and with them their arrival times.

### EliseAI leasing data

Two feeds, per the owner's design: the **weekly EliseAI funnel report**
(`leasing_funnel_report_YYYY-MM-DD.xlsx`, filed into Drive — parsed by
`parse_leasing_funnel` from either the `EliseAI Reports` or `Weekly Leasing
Reports` folder into `data/<slug>/leasing_funnel.json`, aggregates only, with a
portfolio-vs-communities tie-out) is the baseline; the **"Leasing AI Daily
Report" emails** to `dashboard@alignrealestate.com` are the daily updates.
Exports name properties in their own labels ("335 3rd Street"), which route
through each property's `aliases` in `config/properties.json`.

The daily emails list prospects **by name with email and phone**. Only counts
leave the mailbox: they are extracted (by hand, via the Gmail connector — CI has
no mailbox access) into `data/<slug>/eliseai_daily.json`, and
`scripts/populate_eliseai.py` fills the scorecard from that series:

- `# of Tours/Leads/Applications` — tours/leads/apps summed over the trailing
  7 days (ending at the latest recorded day) as a `T/L/A` triple, **value
  only**: the published band is tours per available unit per *month*, so a
  week's totals are shown but never graded. Days with no email count as zero.
- `Open Elise Tasks` — the email's "Review N pieces of pending knowledge" count,
  graded. This assumes pending-knowledge items are what the KPI means by open
  tasks (`OPEN_TASKS_FROM_KNOWLEDGE` in the script turns it off).

A section absent from a daily email means zero that day — EliseAI omits empty
sections. `populate_eliseai.py --add '{"date":...,"tours_today":1,...}'`
records a new day and refills in one step. Run it after `extract_scorecard.py`,
like the other populate step.

**Pass `received_at` — the email's own arrival time — with every `--add`**
(`{"date":"2026-08-17","received_at":"2026-08-17T15:37:21Z",...}`). That
timestamp is what the scorecard reports as "data last updated"; without it the
page falls back to the report date, which cannot show a feed that has stopped
arriving. The script warns when it is missing and refuses a malformed one.

The v10 legend made the in-range band white — no colour indicator — and
`extract_scorecard.py` fails loudly if the workbook's legend fills change again,
rather than publishing stale semantics.

### The building-metrics export

`scripts/populate_building_metrics.py <export.csv>` fills the scorecard from
EliseAI's **building metrics export** (`metricsbuilding<YYYYMMDD>.csv`, 79
columns per property). This is a *third* EliseAI feed, distinct from the two
above: the weekly funnel report and the daily emails.

**`# of Renewals` prints the count beside the rate** — `42/88.9%` for The
Landing. The export carries a `Renewal Rate` and no count of any kind (79
columns, checked), so the count comes from `landing.json`'s
`leasing.renewal_activity.renewals_signed` — the workbook's renewal tracker, the
same source the Trade-outs card draws, as of its own `tracker_date`. The two
halves therefore cover **different periods**: the count is the tracker to
2026-07-26, the rate is the export's trailing window to its filename date. The
count is not the numerator of the rate, `bldg_basis` says so, and the **rate** is
what the band grades. A property with no renewal tracker (Chorus, Madelon) keeps
the rate alone — `RENEWAL_COUNT_SOURCE` is the lookup, so adding one is a line.

It fills nine KPIs where the export column means what the KPI means — Leased %
(from `100 − Exposure Rate`, which matches the KPI's definition better than
`Occupancy Rate`), Trade-out %, Closing Ratio, # of Renewals, % Increase, Total
Deliquency, AI Containment Rate, Avg First Response Time, and the T/L/A triple.

Four rules keep it from overwriting better data or asserting what it cannot:

1. **It never takes a cell another feed owns.** The Landing's and Palma's
   delinquency come from the workbook and the Drive AR report, whose bases are
   known and tie out; the export's delinquency basis is unstated and disagrees
   sharply (Landing: 11.2% in the export vs 4.6% published). 335 Third's T/L/A
   comes from the daily emails, which carry a known 7-day window and a real
   arrival time. `owned_by_other_feeds()` reads `measured[slug]` to find them,
   so a new feed is excluded by default rather than by remembering.
2. **`# of Tours/Leads/Applications` is an `xx/yy/zz` triple** — tours / leads /
   applications — and is **value only**, like the daily fill: the published band
   is tours per available unit per *month*, which cannot grade a count triple.
   The per-unit figure is recorded in `bldg_basis` for reference.
3. **A property in lease-up is not graded on stabilised bands.** Under 50%
   occupancy (`LEASEUP_OCCUPANCY_UNDER`), the occupancy- and rent-derived cells
   in `LEASEUP_UNGRADED` are filled but left ungraded — otherwise an unopened
   building scores red for not having opened. Automation and response-time KPIs
   still grade normally, since they are about conversation handling.
4. **Implausible cells are skipped, loudly.** Chorus reports +119.78% executed
   rent increase against −3.74% offered, so `% Increase` is skipped there and
   Trade-out falls back to `New Lease Trade-Out` alone, recorded in the basis.

Two things the owner settled on 2026-08-20: the export is a **snapshot taken on
the filename's date**, with the rate KPIs (trade-out, closing ratio, renewal
rate) on a **trailing 1-month basis** from that date — note the scorecard's
bands for those KPIs are written for trailing 3 months, so a volatile month
swings the grade more than the bands assume; and **`AI Response Time` is in
days** (`RESPONSE_UNIT`). Taken at face value that reads 35–37 days to first
response at every property, which is hard to square with an AI assistant, so
the figure is published in days but stays value-only rather than graded until
a fresh export makes sense of it.

Run it after `extract_scorecard.py` and after `populate_eliseai.py`. `--dry-run`
reports without writing; `--received-at` records a real arrival time. The CSV
now lands in the Drive `EliseAI Reports` folder and `update.yml` runs this
script on the newest one automatically, passing Drive's `landed_at` as the
arrival — the hand-off step only exists for a CSV that never reached Drive.

### The unit directory

`UnitDirectory<MM_DD_YYYY>.xlsx` in the Drive `Building Info` folder is the
buildings' fixed description — every unit's floorplan code, square footage,
bedrooms and baths, for all properties in one export. `parse_unit_directory`
splits it on the property-code rows inside it and ties each section out against
that section's own `Total <code>` row on all three numbers it publishes (unit
count, rent total, square footage), plus the file's `Grand Total`. A section
that does not tie out is reported rather than stored.

It exists because **nothing else says how many bedrooms a floorplan has.** The
rent roll and the analyst workbook both name the plan (`lab19`) and neither
defines it, so the Landing's unit-gap table joins the plan code to
`data/<slug>/unit_directory.json` for bedrooms and the plan's square-footage
range. Bedrooms belong to the plan, not the unit: a plan whose rows disagree is
flagged, never averaged.

The Landing's directory counts **265 units where the rent roll counts 263** —
`WAITLIST` and `WAIT1B1B` are Yardi placeholders, not apartments. They are
counted as `placeholder_units` rather than dropped, because the export's own
total includes them and the tie-out has to as well; `residential_units` is the
263. One unit (647) is classed `lab21` in the directory and `lab9` in the
workbook, which is why the per-plan counts differ by one in each of those.

A directory carries no resident and no lease, so there is nothing to scrub — it
still goes through `store_report` so the central scrub covers it by default
rather than by remembering that this one is safe.

The **concession burn-off export** (Drive `Concession Burnoff` folder) parses
via `parse_concession_burnoff` — as-of date, unit count and money totals, tied
out against the report's own total row; resident names are read only to tell a
data row from the total row and never emitted. The export says only "For
Selected Properties", naming no property, so until the owner settles which
building it covers the parse is logged and stored nowhere — attribution by
guesswork would file one building's concessions under another.

### "Data last updated" — arrival, not coverage

The scorecard head carries the newest **arrival** time across the feeds behind
its measured cells: when an email landed in the mailbox, or when a report landed
in Drive. This is deliberately not `as_of`, the period the data covers — a
report can be about July and have arrived this morning, or be dated today and
have sat unfetched for a week, and only the arrival time can show a feed that
has stopped running. Both are published, per feed, under `measured[slug]`:

| Field | Meaning |
| --- | --- |
| `received_at` / `eliseai_received_at` / `bldg_received_at` | when it arrived (ISO-8601, UTC) |
| `as_of` / `eliseai_as_of` / `bldg_as_of` | the period the data describes |
| `received_what` / `eliseai_received_what` / `bldg_received_what` | which feed it came from, for the tooltip |

The page enumerates these families from `SC_FEED_PREFIXES` in `index.html` (and
the matching list in `data.html`), so **a new feed needs its prefix added there**
or its arrival will not show up on the page or in the arrivals table.

Where each arrival comes from:

- **EliseAI dailies** — the email's mailbox arrival, recorded per day in
  `data/<slug>/eliseai_daily.json`. For a hand-forwarded email this is when the
  forward arrived, so it can run later than EliseAI's own send time.
- **Drive reports** — `fetch_drive.py` reads Drive's `createdTime`/`modifiedTime`
  and puts the later of the two in the manifest as `landed_at`;
  `build_metrics.store_report` writes it into `data/<slug>/*.json`, and
  `populate_scorecard.py --from-pipeline` publishes it.
- **The analyst workbook** — `landing.json`'s own `generated_at`, since the
  workbook is refreshed by hand and has no arrival of its own.
- **A report run by hand** — no arrival time exists, so pass
  `populate_scorecard.py --received-at <ISO-8601>` to record one. Without it the
  page falls back to the as-of date **and says so on hover** rather than
  presenting a coverage date as a freshness date. Palma's current row is this
  case: it was filled from a report handed over directly, before Drive arrival
  times were captured.

Past `SC_STALE_DAYS` (3, in `index.html`) the timestamp turns red: the daily
EliseAI feed should keep the newest arrival inside a day or two. `data.html`'s
"Feed arrival times" table lists every feed's arrival beside its as-of date.

## The T12 statement's two expense anchors

The 12-month accrual statement carries more than one expense total, and which
one a published figure used has to be recorded rather than inferred:

| Anchor | Row |
| --- | --- |
| `519999-9999` (jpm) / `5999-9998` (align) | TOTAL OPERATING EXPENSES / TOTAL OPERATING EXPENSE RECOVERABLE |
| `549999-9999` (jpm) | TOTAL EXPENSES — operating plus the non-operating 52xxxx region |

**Everything the pipeline publishes now reads the outer one**: the Operating
Summary card (the top box on The Landing tab, moved 2026-09-03), the Expense
Ratio card (moved the same day), and the expense buckets behind the Expense Deep
Dive, which had tied out against `549999-9999` all along. So the three cards
drawing this statement cover the same expense load, which they did not before.

They are not interchangeable. For The Landing the gap is ~$4.4k a month for most
of the year and **$55k in Jul 2026**, so the summary reads $365k for that month
against the $310k the operating anchor gives, and the T12 ratio reads **33.3%
against 32.7%**. The gap is the 52xxxx lines — gross receipts/business licence
tax, non-recoverable concierge, professional fees. Because `549999-9999` is the
row immediately above `599999-9999 TOTAL NET OPERATING INCOME`, revenue less it
reproduces the statement's own NOI line, which is why the summary's third row is
plain **NOI** rather than "Operating NOI".

**The ratio's move departs from the Align definition**, which is the recoverable
line over operating revenue. That is the owner's call, taken so the cards stop
disagreeing; the recoverable figures are still parsed and unchanged
(`opex_recoverable_t12` / `_monthly` on the parse), so the older definition is
one field away. `ratio_basis()` composes the prose the card prints.

**The analyst workbook turns out to have been on the total-expense basis all
along**, which is corroboration rather than coincidence: `landing.json`'s
`expense_noi.ttm.opex_ratio` is 33.15% on opex of $4,728,562, against the
statement's `549999-9999` total of $4,725,421 — a $3,141 gap, 0.07%. So the
Expense Load & NOI card (workbook-fed) and the Expense Ratio card (pipeline-fed)
were reporting the same property on two different expense loads, worst for
**Jul 2026: 27.4% in the workbook against the pipeline's 23.4%**. On the total
anchor the pipeline reads 27.5% and the two agree to a tenth. The workbook's
number was never wrong; the pipeline's denominator of accounts was.

The Align tree has no counterpart to `549999-9999`: below its `5999-9998` sit the
NOI line and then `6000-0000 OTHER EXPENSES` in sections with no grand total. So
a statement on that tree publishes no total-expense row and falls back to the
operating anchor — which means **the ratio is not comparable across account
trees**: Palma's 56.1% is recoverable opex, The Landing's 33.3% is total
expenses. That is why the basis is published per property and the card's eyebrow
reads off the selected one, rather than one basis line printed over both.

Which anchor a point used is recorded on the point:

| Field | Meaning |
| --- | --- |
| `expense_scope` | `"total"` or `"operating"` — the page picks its row and column labels off this |
| `expense_anchor` | the account code, or `null` on the fallback |
| `basis` | the prose the card and the data page print |

`expense_anchor_for()` in `build_metrics.py` makes the choice once for both
stores. Three guards, because all three failures would be invisible in the
numbers:

- **Codes are never summed across anchors.** A property reporting under several
  building codes needs every code on the same row before they can be added;
  one building's total expenses plus another's operating expenses is a figure
  that is neither. Mixed anchors drop to the operating anchor, with a warning.
- **The stitched month series stops where the anchor changes.**
  `stitch_monthly_pl` joins successive statements into one month run, and the
  summary compares a trailing window against the current month — so a window
  straddling the switch would read the gap between the two anchors as a swing in
  spending.
- **The ratio trend stops there too.** `ratio_trend` keeps only the run of
  statement periods measured like the newest one, since the card plots them as a
  line and a point on the other anchor would draw the change as a move in the
  ratio.

Points stored before `expense_scope` existed count as `operating` in both
guards — an absent value is not "matches whatever is newest". Both series
re-lengthen as statements re-arrive on the current anchor.

`scripts/test_monthly_pl.py` holds all of this down — 32 checks against
statements built in a temp dir by `test_expense_buckets`' own builders, no
network and no fixtures. Each guard has a check that fails when the guard is
removed (verified by mutation).

## How reports reach Drive

Nothing in this repo puts files in Drive. A Google Apps Script running under
`dashboard@alignrealestate.com` on an hourly trigger reads the mailbox, matches
each attachment's name against a routing table, and files it into a subfolder of
the Drive **Report Lander** folder — the same folder `fetch_drive.py` scans via
the `GDRIVE_FOLDER_ID` secret. Anything it cannot identify goes to `_Unsorted`.

`scripts/gmail_drive_filing.js` is the version of record for that script. It is
not executed by anything here; it is checked in because **its routing table and
`config/report_map.json` are two halves of one contract** — the script decides
where a report lands, `report_map.json` decides where the pipeline looks — and
when they disagree both sides still look healthy. Apps Script *creates* any
folder it is asked for, and `fetch_drive.py` only logs a folder it does not
recognise, so the report just never gets parsed. That is how the weekly EliseAI
funnel sat in `_Unsorted` for six weeks, and how the `AIRM/Yardi Rev Management`
and `Workorders/Maintaince` rules were one real report away from quietly
starting a second folder each (a `/` is legal in a Drive folder name).

### A new report type makes its own folder

A report matching no rule used to land in `_Unsorted`, which is how four weeks
of arrivals piled up unnoticed. Now the filer boils the filename down to a report
type and files it under that name, so a new type is visible and grouped from the
first email it arrives in. `reportTypeFor_` in `gmail_drive_filing.js` does the
boiling: it strips the extension, the arrival date the filer itself prefixed,
`(1)`-style copy suffixes, `30Days`/`60Days` window markers, every property name,
alias and code from `properties.json`, and any date or bare number left over.

    2026-09-05 8.30.26 - The Madelon - Daily Report.xlsx      -> Daily Report
    2026-09-05 BoxScoreSummary09_05_2026 - 30Days - The Landing.xlsx -> BoxScoreSummary
    2026-09-05 AP Aging Detail 09_05_2026 - Chorus.xlsx       -> AP Aging Detail

**The derived name is a starting point, not an answer.** It can be clumsy
(`Renewals`, `rs sql JPM Demographics Combined`), and two spellings of one report
can make two folders. Both are fixed the same way — add a routing rule naming the
folder you want, and the next `resortExistingFiles` merges them — and the fix is
obvious because the folders are sitting there in Drive. That is the trade: a
slightly untidy tree you can see, instead of a tidy `_Unsorted` you cannot.

Four things stop it running away:

| Guard | Why |
| --- | --- |
| It refuses to guess | A name under 4 characters, or with no run of 3 letters, is not a name. `2026-09-05 The Landing.xlsx` has nothing left after the date and the property, so it goes to `_Unsorted` |
| It reuses an existing folder | Matched on `normalize_`, so "Daily report" files into "Daily Report" rather than starting a sibling |
| `MAX_NEW_PER_RUN` (5) | A mailbox full of one-off attachments cannot carpet the drop tree in one execution. Past the cap, files park in `_Unsorted` and the log says so |
| A rule always wins | Auto-naming only runs when no rule matched, so registered reports are untouched. `test_routing.py` checks all 21 |

`fetch_drive.py` then reports the new folder as `[warn] NEW REPORT TYPE: '…' is
not in report_map.json`, which is the daily prompt to write it a parser.
Promoting a type to a real feed is: add a rule here, add a `report_map.json`
entry, write the parser.

`PROPERTY_WORDS` in the `.js` is generated from `config/properties.json`;
`test_routing.py` fails if a property is added to one and not the other, since a
new property name that is not stripped would end up inside folder names.

Set `AUTO_FOLDER.ENABLED = false` to go back to everything unmatched landing in
`_Unsorted`.

### Folders organise; filenames route

`fetch_drive.py` runs **two passes**, and the difference matters:

1. **The folder pass** — every active entry's own folder, as always. This is what
   the Gmail filer's organisation is for, and it is unchanged. Drive stays
   browsable, one folder per report type, for pulling source data by hand.
2. **The rescue sweep** — then every other folder in the drop tree, `_Unsorted`
   included, looking for unclaimed files matching an entry's `name_patterns`.

The point is that folder organisation is no longer *load-bearing*. Before, a
report's identity came from the folder it sat in, so a routing rule that didn't
match a filename put the report somewhere nothing read — and nothing downstream
could tell. That is how four weeks of reports sat in `_Unsorted`. Now a misfiled
report still reaches its parser, and the log says where it was found
(`[rescued] downloaded _Unsorted/… — filed outside its own folder`).

`name_patterns` is opt-in per entry, matched case-insensitively, and only
`active` entries take part. An entry without it stays strictly folder-bound.

The sweep is scoped, and each limit exists for a reason:

| Limit | Why |
| --- | --- |
| Never the `reference` tree | The library holds superseded copies on purpose. `Archive Reports` has a July rent roll beside four other July exports; sweeping it would publish a seven-week-old rent roll as current |
| Never a folder in `NEVER_SWEEP` | Belt to the tree's braces — an archive stays safe even if it is moved into the drop tree |
| Never a file the folder pass took | `claimed` tracks Drive ids, so nothing is counted twice |
| Never a name two report types claim | Reported and skipped. Entries agreeing on `report_type` *and* `parser` are one claim wearing two folder names (the funnel parses from two folders, delinquency from two), so only a real disagreement is ambiguous |
| Never over an existing download | Two folders holding one filename would overwrite on disk and let the second parse win |

`scripts/test_fetch_sweep.py` holds this down — 12 checks against a stubbed Drive
mirroring the real layout, no network or fixtures. Both archive protections are
tested *independently*: removing either one alone fails a check, since the name
guard would otherwise cover for the missing tree scoping.

### Two Drive trees

`fetch_drive.py` scans **two** parents, because two different kinds of thing live
in Drive:

| Tree | Env var | What it is |
| --- | --- | --- |
| `reports` (default) | `GDRIVE_FOLDER_ID` | **Report Lander** — the Gmail filer's drop folder, one subfolder per report type, churning daily |
| `reference` | `GDRIVE_REFERENCE_FOLDER_ID` | **Resi Dashboard** — the owner's hand-curated library: keys, long-lived documents, the unit directory |

A `report_map.json` entry names its tree; omitted means `reports`. `Building
Info` is the one `reference` entry today: the unit directory is the buildings'
fixed description, not a periodic report, so it belongs in the library rather
than the drop tree — and the pipeline reaches into the library for it instead of
the folder being dragged into Report Lander. `GDRIVE_REFERENCE_FOLDER_ID` is
optional; unset, those entries are skipped with a line in the log rather than a
crash.

**Do not rename `Building Info` in Drive.** It is the one registered folder the
rescue sweep cannot cover: the sweep never reads the `reference` tree, so that a
superseded export in the library can't be republished as current. Renaming it
therefore stops the unit directory with nothing but a log line, while the
unit-gaps table keeps rendering the last committed data. Renaming any
rule-named folder is a three-place change anyway — the Drive folder,
`report_map.json` and the `.js` rule — because `getSubfolder_` skips the
`normalize_` reuse scan for a `fromRule` name and simply recreates the original
beside your rename. Auto-derived folders are the opposite: safe to rename, but
the derived name comes back on the next arrival unless a rule claims it.

The filing script needs the same distinction from the other side, since Apps
Script can only find and create folders *inside* its target folder. A rule whose
folder is in `EXTERNAL_FOLDERS` is resolved by absolute ID, read from a **script
property** (`BUILDING_INFO_FOLDER_ID`) rather than written into the file —
script properties survive a full paste, and this file is public. Unset, matching
files stay in `_Unsorted` and every run logs why; they are never filed somewhere
wrong. `test_routing.py` asserts `EXTERNAL_FOLDERS` and `"tree": "reference"`
name the same folders, so the two halves cannot drift apart.

`scripts/test_routing.py` is the check that they still agree. It reads the rules
out of the `.js` directly, and asserts every rule's folder is a `drive_folder` in
`report_map.json`, that no folder name contains `/`, that every `file_glob`
starts with `*`, that the two trees agree, and that a list of real filenames
still routes where it belongs. Run it after editing either file.

Two traps worth knowing:

- **The filer prefixes the arrival date** (`2026-08-25 leasing_funnel_report_…`),
  and `fetch_drive` matches with `fnmatch`, which tests the whole filename. So
  every `file_glob` must lead with `*`. An anchored pattern matches only the
  hand-placed copies and silently skips everything the filer files.
- **`Workorders - Mainentance `** carries a misspelling *and* a trailing space,
  in Drive and in `report_map.json` both. Renaming it means the Drive folder,
  `report_map.json` and the `.js` rule all change together; `test_routing.py`
  fails if only one moves.

To deploy a routing change: edit the `.js`, run `test_routing.py`, commit, and
get the code into the project — either by pasting it into `script.google.com` →
"file downloader", or automatically via `.github/workflows/deploy_filing_script.yml`
(below). Then run `previewRouting` and `checkFolders` (both dry runs), and only
then `resortExistingFiles`. `_Unsorted` doubles as a retry queue:
`resortExistingFiles` re-scans it, so a new rule rescues files that arrived
before the rule existed. Do **not** re-run `createHourlyTrigger` — the trigger
survives edits, and running it again just creates a duplicate.

### Deploying the script automatically

`deploy_filing_script.yml` runs `test_routing.py`, then pushes
`scripts/gmail_drive_filing.js` into the Apps Script project with `clasp`. It is
a **no-op until two secrets exist**, and says so in the run summary rather than
failing:

| Secret | What |
| --- | --- |
| `CLASPRC_JSON` | the contents of `~/.clasprc.json` after `clasp login` as `dashboard@alignrealestate.com`. Holds an OAuth refresh token — a real credential |
| `APPS_SCRIPT_ID` | the project id from the editor URL. In a secret, not committed, like the Drive folder ids |

The account also has to switch the Apps Script API on once, at
`script.google.com/home/usersettings` — a per-user toggle, unrelated to any
Cloud project setting.

**A service account cannot do this.** `projects.updateContent` rejects
service-account credentials for a user-owned script, so this cannot reuse
`GDRIVE_SA_KEY`; it needs an end-user token.

The workflow `clasp pull`s first and pushes the project's **own**
`appsscript.json` back, replacing only the code. The manifest carries the
timezone, runtime version and any advanced services — rebuilding it from memory
would change how the script runs, and a pull that yields no manifest aborts the
push rather than guessing.

It deliberately does **not** run `previewRouting`, `checkFolders` or
`resortExistingFiles`. Executing a function remotely needs the script published
as an API executable *and* a token carrying the script's own scopes — Gmail read
and Drive write — a far larger grant than pushing code. Reading the dry-run log
before files move is the safety net, so those three stay manual.

`resortExistingFiles` only sees files loose in Report Lander or in `_Unsorted`.
A file outside that folder, or already inside the wrong category folder, has to
be moved by hand.

## The Data-Flow Page

`docs/data.html` opens on **Data flow**: one row per source, laid out on the
same six stages every number travels —

    source -> the report -> pipeline step -> stored -> published -> a card

The **Tables** view behind it is the old page unchanged: every number the JSON
holds, at full precision, with CSV. Deep links still work and still land on
their row — a fragment naming a table or a row switches the view on the way in,
so the scorecard's per-cell links from `index.html` are unaffected.

Each row also links **out**: a card name under "On the dashboard" goes to
`index.html#<cardId>`, and the dashboard selects the owning tab and flashes the
card. Every Portfolio card now carries an id for this (`cExpRatio`, `cExpTrend`,
`cPsf`, `cTradeOutsPortfolio`); the Landing cards already had them, and the
property tabs' scorecard cards are named `psc-<slug>` by `buildPropertyTabs`.

**And every card links back.** Each card on the dashboard carries a small
`Data ↗` in its **top-right corner** that jumps to where its own numbers live
on `data.html` — the table holding them, or the flow row explaining why nothing
holds them yet. The targets are not written into `index.html`: it reads the
`cards` block of `lineage.json`, keyed by card id, so the same generator run
that checks a card anchor exists also checks the table it points at exists.
A card with no entry gets no link, rather than a link to nowhere.

    "cards": { "cRollover": { "primary": "t-l-rollover", "holds": "Rollover schedule",
                              "tables": [...], "flows": ["analyst_workbook"], ... } }

A `dashboard` entry in `build_lineage.py` carries its own `tables`, and
optionally a `primary`. Both matter: without per-card `tables` a card inherits
its whole flow's list, so the seven cards on the analyst workbook all pointed at
"Rent capture"; and without an explicit `primary` the target is whichever flow
happens to sort first, which is the page's reading order, not an answer to
"where are this card's numbers". A `"tile": true` entry stays on the flow page
and out of the card index — the Leased tile is genuinely fed by the export but
is one tile in a row, with no corner to hang a link in.

Three details worth knowing:

- The link is **absolutely positioned** in the card's corner, so `.card-head`
  (which puts the property select and the period toggles hard against the right
  edge) and a direct-child `<h2>` both carry `padding-right` to keep clear of
  it. Verified at 1440 / 900 / 390px with a text-level overlap probe — the
  element boxes still span the full width, so only the painted text tells you
  whether anything actually collides.
- A per-property table family has no single id (`t-expratio-the-landing`,
  `t-expratio-palma`), so a card links to the **prefix** and `data.html`'s
  `focusHashTarget` resolves a fragment that is a prefix of a real id to the
  first table that exists.
- Three `metrics.json` blocks had **no table on the data page at all** —
  `monthly_pl`, `expense_buckets` and `unit_directory`, i.e. everything the
  Drive T12 and the unit directory produce. The page claims to hold every
  number the JSON carries and did not, which is why the Operating Summary card
  had nowhere to link. `t-monthlypl-<slug>`, `t-buckets-<slug>` and
  `t-unitdir-<slug>` now cover them.

Regenerate with `python scripts/build_lineage.py` (`--check` verifies and writes
nothing). `update.yml` runs it after the scorecard fills, so the published chain
reports what that run actually produced.

**Half of it is derived and half is declared, on purpose.**

- The **Drive side comes from `config/report_map.json`**. Every entry becomes a
  row whether or not anyone described it, so a folder registered tomorrow
  appears on the page by itself — flagged as undocumented rather than silently
  missing, and described by its own `_comment` until someone writes it a flow.
- The **first stage is the Gmail filer**, read out of `gmail_drive_filing.js`
  through `test_routing.load_rules()` so the page and the contract test cannot
  parse it differently. Each Drive row names the words the filer matches on to
  put a report in that folder — which is the actual answer to "which report
  goes where". A registered folder with no rule is reported as filling by hand
  only. If the script's shape changes the loader bails and the page drops the
  filer line rather than refusing to build; `test_routing.py` is what fails
  loudly there.
- The **downstream edges are declared** in `DRIVE_FLOWS` / `OTHER_FLOWS` in
  `build_lineage.py`. Nothing in the repo records that `metrics.json`'s
  `expense_buckets` block is what the Expense Deep Dive draws; that edge exists
  only inside `index.html`'s fetch calls, so it is written down once and
  **checked** on every run.
- What has actually arrived is **evidence**, read from the repo as it stands:
  which per-property files exist, the newest source filename, when it landed,
  which scorecard cells each feed ended up owning. A declared flow with no
  evidence is reported as waiting, not as working.

The script **refuses to write** on a card anchor `index.html` does not define, a
table id `data.html` does not build, or a parser module named in the report map
that is not in `scripts/`. A lineage page that has quietly gone stale is worse
than none, because it is read as a map.

Five statuses, and they are the page's whole argument:

| Status | Means |
| --- | --- |
| `live` | A file arrives, the pipeline reads it, something on the dashboard shows it |
| `partial` | It arrives and parses and ties out. Nothing publishes it — the chain stops in `data/` (the funnel, the concession burn-off) |
| `waiting` | Parser written and registered; no file has ever arrived (the rent roll, C4) |
| `no-parser` | Folder registered so a file dropped in it reaches the fetch log; the parser needs one sample file. Collapsed into a single block rather than five identical empty chains |
| `manual` | No feed at all — `expense_trend`, `psf_vs_peers`, `trade_outs` and the placeholder cards are edited into `metrics.json` and carried through each run |

So the T12 points can report an arrival and not just a period,
`store_expense_ratio` / `store_monthly_pl` / `store_expense_buckets` /
`store_monthly_revenue` now record `landed_at` and `source_files` on each point
(`build_metrics.arrival`). Points accumulated before that change carry neither,
and the page says "arrival not recorded" rather than inventing one.

The Monthly P&L table's expense column is headed from `expense_scope`, so it
reads "Total expenses" for The Landing and "Operating expense" for a property on
the Align tree — see the T12 anchors section above.

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

`docs/lineage.json` travels with the other three data files — `update.yml`
commits it, `publish_data.sh` publishes it and `deploy.yml` overlays it.

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

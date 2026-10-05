# Align Resi Dashboard

Static dashboard published with GitHub Pages, fed by a daily metrics pipeline.

`OPEN_ITEMS.md` carries the current open items, numbered and grouped by what
each one is waiting on. Read it after this file when picking up work — it is
where state that used to arrive as a pasted handoff note now lives.

`scripts/open_items_digest.py` turns that file into a PDF of what is still
open, owner-blocked items first and the live-and-uncertain ones above those. It
decides nothing itself — a row is closed when its Item cell is struck through,
which is the file's own way of recording a close without renumbering, and the
`Live and uncertain` column is read as written. `open_items_state.json` is the
previous run, committed so a scheduled run in a fresh checkout can still say
what moved; the PDF is gitignored and rebuilt every run.
`--html` writes the same document without the file wrapper, for the web copy;
a 6am routine republishes that to one fixed URL so the link survives while the
contents move, and it must always publish with that url rather than creating a
second artifact. `scripts/test_open_items_digest.py` is the guard — 31 fixture-free checks, the
load-bearing three (the positional item column, the close convention, escaping
before formatting) verified by mutation. **Clear `__pycache__` between mutation
runs**, the same trap the parser tests record.

`LANDING_DRIVE_PACKET.md` is the working document for the `Landing`
tab (the filename predates the rename): which export feeds which card, where in Drive it goes, and what has
actually arrived. Its current-state section is generated — refresh it with
`python scripts/landing_drive_status.py --write` rather than editing it.

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
| `docs/rental_tracker.enc.json` | The Rental Rate Tracker's lease data, **encrypted**; the Rental Rates tab decrypts it in the page. Written by `scripts/import_rental_tracker.py`, never by hand |
| `docs/reviews.json` | The Landing's Google reviews, coded by hand; the Landing tab's Google reviews view draws it. Written by `scripts/build_reviews_json.py`, never by hand |
| `scripts/` | `fetch_drive.py` pulls source reports, `build_metrics.py` writes `metrics.json`; `gmail_drive_filing.js` is the Apps Script that files reports into Drive in the first place |
| `config/` | `properties.json` and `report_map.json` — property list and report routing; `coa_map.json` — JPM/Rubicon→Align chart-of-accounts mapping (refresh with `scripts/extract_coa_map.py <COA workbook.xlsx>` when the mapping workbook changes) |
| `data/` | Scrubbed per-property pipeline output. Raw reports live in `_downloads/` and are never committed |

### A report can name a building any of three ways

`build_metrics.load_properties()` routes a report to a property on its Yardi
`codes`, its `aliases`, **and its own `name`** — all three, lowercased.

The name was missing until 2026-09-22, and the gap was invisible because the
four buildings a report had ever named happened to carry their own names in
`aliases` as well. The comp export does not play along: it names each building
as the market names it, so the section reading `335 Third Street` parsed, tied
out against its own arithmetic, and then **routed nowhere** — one
`[warn] unknown property code` line and the whole Oakland comp set gone, on the
tab whose job is to check somebody else's number. Twenty-four of the
twenty-eight properties were one export away from the same thing.

A string two properties both claim is **refused, not resolved**: whichever
sorted last would win and nothing downstream could tell. `test_comps.py` checks
both halves — every property routes by its own name, and a shared name raises —
each verified by mutation.

## Refreshing the analyst workbook extract

**`landing.json` no longer feeds a tab.** A workbook-fed `The Landing` tab sat
beside the Drive-fed one until 2026-09-18, when the owner removed it and the
survivor took the plain name `Landing`. **And since 2026-09-29 it fills no
scorecard cell either** (open item H2): the four it used to — `Concession Load
%`, `NOI Margin %`, `Controllable OpEx/Unit` and `Month to Month Leases` — are
the same formulas pointed at the pipeline's own blocks in `metrics.json`, so
they move when a statement or rent roll lands rather than when someone opens
Excel. See **The scorecard cells that used to wait on Excel** below. Everything
here still runs: the extract is written, published and on the data page as the
`t-l-*` tables, and `--from-landing` still reads it for two comparison notes
(`ltl_workbook`, `delq_workbook`) that are never published as a cell.

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
| `Lease Detail` | the weekly leasing workbook — **typed in, not a grey tab** | Daily Leasing Reports |

Every one of those five now has a parser in `config/report_map.json`. The last
two were written 2026-09-11, and the search for them corrected two things this
file used to say:

- **`Lease Detail` is not fed by a RealPage export.** It is Align's own
  `Daily Report- Week Ending <date>.xlsx`, and it has been arriving in the Drive
  `Daily Leasing Reports` folder all along — not `Weekly Leasing Reports`. Its
  `Weekly_Leases` sheet carries the NEW LEASES block, which holds the one field
  nothing else in the pipeline has: `PRIOR LEASE RATE`.
- **The renewal tracker does have a Drive folder**, and files have been landing
  in it since 2026-09-02. `Landing 2025 Renewal Tracker - Full (N).xlsx` carries
  a sheet per month from January 2024 forward plus the `MTM` roster, so one file
  is the whole history rather than a weekly increment.

Both now feed the **Trade-outs card on the `Landing` tab**, which is the
first card on that tab drawing two Drive reports at once. See **The two leasing
parsers** below.

The workbook was restructured in V37: the `Holdovers` tab became `MTM` (same
content, per-unit vacate flags added), and `MTM Analysis` (tracker
reconciliation — its roster carries tenant names, only aggregates are
extracted), `Scorecard` (scored insights + open questions, published as the
landing page's Insights card) and `Source Renewal Tracker` are new. The
renewal/holdover scenario models charge a recurring incremental-vacancy haircut
on the new run-rate instead of one-time make-ready/downtime costs.

## The Landing Tab

Every number on it comes from a report the Gmail filer drops into Drive and the
pipeline parses, so **dropping a fresh direct export in Drive is the whole
refresh**. `LANDING_DRIVE_PACKET.md` is the list of those exports and where each
one goes.

**The tab opens on its first card**, under the View select that chooses between
these cards and the Google reviews summary (see *The Google reviews view*
below). A standing paragraph (`#dIntro`) sat above
the grid explaining that everything here is Drive-fed and that a second,
workbook-fed tab used to sit beside it; it came off 2026-09-29, by request,
along with the Operating Summary's own closing note. Nothing it said is lost:
which report feeds which card is the table below, what the tab cannot show is
the last card, and the workbook tab it referred to has been gone since
2026-09-18.

It was `Landing (Drive)`, beside a workbook-fed `The Landing` that showed the
same building with the V37 workbook still in it. That tab came off on
2026-09-18 and this one took the plain name. What went with it: eleven cards
(Operating Summary, KPI Scorecard — The Landing, the Leased tile row, Loss to
Lease, Trade-outs, Rollover Schedule, Expense Load & NOI, Expense Deep Dive,
Largest Unit Gaps, Delinquency, Insights Scorecard), `loadLanding()` and the
scenario-input helpers only it used.

Three things the removal is careful about:

- **The ids keep their `d-` prefix.** `cdOpSummary`, `dopTbl`, `dkpisSc` and the
  rest are named for a split that no longer exists, and renaming them would
  touch `lineage.json`'s card index, `data.html`'s deep links and every anchor
  in between for no change a reader sees.
- **CSS written for the removed tab was retargeted, not deleted, where the
  surviving card has the same shape.** `#cNoi` → `#cdNoi` and the deep dive's
  toggle geometry (`#cExpDeep` → `#cdExpDeep`, `#lcExpMonth` → `#dexpMonth`)
  were written against the workbook tab's ids and so **never matched the Drive
  card at all** — the Expense Deep Dive's period toggle had the jumping-button
  bug that rule exists to prevent, and now does not. The compound selectors the
  two tabs shared (`#lopTbl table.dt, #dopTbl table.dt`, `:is(#lgTbl, #dgTbl)`)
  were narrowed by hand: a regex over a comma-separated selector list splits it
  in the wrong places, which is how the tables' text-align was broken once
  before.
- **`renderExpenseDeep`'s `wb` branch is kept.** The removed tab was its only
  caller, so every live mount passes `null` — but it is the renderer's only
  no-statement fallback and the shape a second source would mount through.

The rule is applied **per number, not per card**. A card is on the tab only if
every figure on it would move on the next pipeline run.

**Every card on the tab is full width.** Expense Load & NOI and the Expense
Deep Dive were the last pair sharing a grid row, and each took its own row on
2026-09-30, by request, in that order. The `#cdNoi` flex override went with the
change: it existed only because that card was the shorter of the two in one row
and the row stretched it, leaving ~180px empty below its chart, so the chart
was given the slack instead. Spanning the row there is no neighbour to match,
and the chart takes `.card.wide`'s own 320px like every other wide card. If
either ever goes back to half width, that rule has to come back with it.

**The tab carries no footnotes.** The intro paragraph and the Operating
Summary's note came off first; the remaining eleven `.blu-note` elements —
nine per-card notes and the `dMeta` sources line at the bottom — went on
2026-09-30, with the 224 lines of prose that filled them. The other tabs keep
theirs (Budget vs Actual's, and the seven on Market Comps), so this is a
change to one tab rather than to the idiom.

Two things it is careful about:

- **The markup and the code that filled it both went.** An element deleted
  from under a live `document.getElementById(...).textContent =` throws, and
  `section()` would have turned that into `— NOT AVAILABLE` on the card — the
  exact failure the section above documents. Checked in the browser: every tab
  opens, no page errors, nothing fell back.
- **The shared renderers keep their note, optionally.** `renderRentCapture`
  and `renderExpenseDeep` are written to serve any mount and this tab is only
  their current one, so the note is guarded (`if (ids.foot)`, `ids.note ? … :
  null`) and the mount simply stops declaring one — the idiom
  `renderScorecard` and `renderOpSummary` already use.

**Removing them by script needs a real statement scan**, and two shortcuts
corrupted the file before the third attempt worked. These are long `+`
concatenations of prose: a character scan for the closing `;` treats an
apostrophe inside a `//` comment as opening a string and runs off the end of
the statement — it ate the start of the next comment block and left
`a rent roll is one snapshot…` dangling at top level — and "delete lines until
the file parses again" stops one line in, because the concatenation left
behind is itself a valid expression statement. What works is stripping string
literals and `//` comments from each line first, then counting brackets until
the line that closes at depth 0, with `node --check` over the extracted script
at the end. That last check is what caught both of the earlier attempts, and
is worth running after any scripted edit to `index.html`.

### A card that cannot be drawn says so

**Every section on this tab renders inside `section(id, fn)`.** A throw in one
used to take out every card below it, because the tab is one long function of
sequential IIFEs and an exception unwinds the lot.

That is not hypothetical. On 2026-09-21 the delinquency card looked up
`SCD_DRIVE_FEEDS.find(f => f.prefix === "")` — the family the AR cells had
lived in until G3 closed the same week and moved them to `delq_`. The lookup
returned `undefined`, `scdFeedIsDrive` read `.prefix` off it, and
**Delinquency, Unit Inventory and What Feeds This Tab all stopped appearing**.
Three cards gone, one line in the console, nothing on the page to say why —
and it read as though the cards had been deliberately removed.

Two things now stand between a renamed field and a page that looks redesigned:

- **`scdFeedIsDrive` returns `false` for a family the list no longer carries**
  rather than throwing. A feed that does not exist cannot be Drive-fed, which
  is an answer, not an error.
- **`section()` contains a throw to its own card**, which falls back to the
  page's own no-data mark — a rule, `— NOT AVAILABLE`, and a line saying the
  data is missing or has moved and that nothing else on the tab is affected. A
  tile row gets a single `—` tile instead, so the row keeps its shape. The
  error still goes to the console: this hides nothing, it just stops one
  missing feed reading as ten missing cards. An `async` section (the feeds
  card awaits `lineage.json`) has its rejection caught too, since a `try` around
  a promise-returning call catches nothing.

Verified by putting the original bug back: the blast radius is one card, the
other nine draw in full, and the console still carries the TypeError.

**`--check` would not have caught this**, and it is worth being clear why:
`build_lineage` verifies that a card anchor *exists in the markup*, which
`cdDelq` always did. Nothing checks that the code filling it still runs. The
browser check that opens every tab and asserts no page errors is what catches
this class, which is why it is worth keeping in the loop.

| Card | Drive source |
| --- | --- |
| Operating Summary | T12 statement → `metrics.json` `monthly_pl` — a period select on the left, comparison boxes on the right |
| Loss to Lease | one card, two halves: the monthly series from the T12 statement (`rent_capture`) over today's gap in figures from `rent_roll` |
| Four KPI tiles | `scorecard.json` — Leased %, Trade-out %, Budget variance, Delinquency, each with its grade |
| Trade-outs | `lease_tradeout` for the new-lease series, `leasing.renewals` for the renewal side |
| Rollover Schedule | `rent_roll` — lease expirations by month |
| Expense Load & NOI | `monthly_pl` + `expense_buckets` + `unit_directory` |
| Expense Deep Dive | `expense_buckets` |
| Largest Unit Gaps | `rent_roll` + `unit_directory` for the bed/bath join |
| Delinquency | the rate from the EliseAI building-metrics export (the outstanding-balance figure, since 2026-09-29), the 30/60/90 bars from the Drive AR report |
| Unit Inventory | `unit_directory` (**frozen until C5**, see below) + `rent_roll.by_plan` for the leased/vacant split |
| What Feeds This Tab | `lineage.json` — arrivals, and what is missing |

The first rent roll ever to reach the pipeline landed 2026-09-11 and closed C4,
taking the tab from seven cards to ten. `parse_rent_roll` needed no changes:
both published totals tied to the report's own Total row to the cent on the
first run. Three things that matter about how it is read:

- **Occupancy is the parser's `occupied` flag — a resident code AND a non-zero
  rent, never the code alone.** Yardi carries a resident code on vacant units
  too; this export has one on all 263 rows, so a code-only test reads 100%
  occupancy on a property at 97.7%.
- **Loss to lease is measured on occupied units only.** A vacant unit has an
  asking rent and no in-place rent, so counting it books the whole asking rent
  as loss — 38.1% against the 36.5% published.
- **The roll's half is a snapshot; the monthly series sits above it.** A rent
  roll is one point in time, so it reports where the gap sits today, split by
  when each lease comes up. The 19-month view it cannot give came from the
  statement's revenue detail lines later the same day — see the rent-capture
  section below — and the two now share one card: the series as the chart, the
  roll's own figures beneath. The roll's half hides itself when no roll has
  arrived, since the chart above does not depend on one.

  That half used to carry a bar chart too — the gap bucketed into Holdover /
  0–3 / 4–6 / 7–12 / 12 mo+ — and it came off on 2026-09-14. It was the
  **Rollover Schedule** card directly below it re-grouped: the same
  `rr.rollover` array and the same `uncaptured` figures, in coarser buckets.
  The stats stayed, since nothing else on the tab carries the loss-to-lease
  dollars, and the footnote now points at the Rollover card for the split by
  expiry.

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
- **NOI margin and controllable/door are derived, not borrowed.** The
  scorecard's cells for both are workbook-owned, so the tab computes them from
  `monthly_pl` / `expense_buckets` and the directory's `residential_units`.

### The KPI grid became four tiles

A `KPI Scorecard — Drive feeds only` card sat between the Operating Summary and
the tile row until 2026-09-15: every `scorecard.json` cell a Drive report
currently owned, laid out in the workbook's own groups with its bands. It is
four tiles now, in the same row shape as the statement's tiles below them —
**Leased %, Trade-out %, Budget variance, Delinquency**. Nothing changed in
`scorecard.json`, in `populate_scorecard.py` or on any other tab; the other
cells are on the Scorecard tab as before.

Two things the grid did that a bare number does not, and both are kept:

- **The grade.** Each tile's subtitle leads with where the cell sits against
  its published band (`in target range`, `exceeding target`, `below target`),
  and the full prose the grid's cells carried — the band itself, the feed, the
  link hint — is on hover, composed by the same `scCellTitle` the scorecard tab
  uses, so the two cannot word it differently. A cell that is reported but not
  graded gets no grade word rather than an invented one.

  **A below-target tile prints its value red** (`.kpi .v.below`); exceeding and
  in-range keep the amber, so red on this page means one thing rather than "not
  the usual colour". The colour follows the grid's own rule for what may be
  coloured at all — a report supplied the number *and* the published band could
  place it — so a `value_only` cell (a figure the band cannot grade, e.g. a
  property in lease-up) stays amber even where the workbook's hand-set symbol
  says below, and an absent `—` is never red. Verified by mutation: dropping the
  graded check turns the lease-up case red and fails that check. The subtitle
  still says "below target" in words, since the grid's legend went with it and
  colour alone is not a label.
- **The Drive gate.** `scdFeedIsDrive` is asked per tile exactly as the grid
  asked it, so a cell whose family the workbook wrote last reads `— not
  Drive-fed today` rather than quietly borrowing a workbook number — and that
  is told apart from `— awaiting the feed`, a cell no report has ever filled.

### Every tile names the window it covers

Both tile rows carry the period on the label line, in amber (`.kpi .k .per`),
because a month and a year are different measures rather than one measure with
a footnote. The eight tiles on this tab cover five different windows:

| Tile | Window |
| --- | --- |
| Operating revenue, NOI margin | `monthly` — the statement's newest month |
| `T12 NOI` | `annual` — the trailing twelve, span in the subtitle |
| Controllable / door | `annualised` — that month ×12, per the band's basis |
| Leased %, Delinquency | `point in time` — a snapshot, not a period |
| Trade-out % | `trailing 3 mo` — read from `tradeout_months`, the window the band was written for |
| Budget variance | the real window from `budget_as_of`, e.g. `Jan-Aug 2026` |

The four scorecard tiles state theirs per tile because the window is a property
of the **feed**, not of the cell, and `scorecard.json` records it for only one
of them. Budget variance is that one and reads `budget_as_of`, so it lengthens
by a month as statements land instead of going stale. A tile with no value gets
no period: naming the window of a number that is not there would read as though
something had been measured. The hover adds `Covers: <window>` under the feed.

**Finding the words for this turned up a real error.** `T12 NOI` was summing
the whole stitched run and calling it T12. The run is not twelve months — the
join keeps every month any statement reports, so The Landing's is Aug 25–Aug 26,
**thirteen** — and the tile read **$10,694,302 against a true trailing twelve of
$9,928,681, 7.7% high**, on the tile most likely to be quoted. Worse, it
contradicted the T12 column of the Operating Summary directly beneath it, which
has always sliced twelve. The window is now taken from the **end** of the series
and named for the months it actually covers (`T12` at twelve, `T<n>` before
that), which is the rule `renderRentCapture` already applies to its own
footnote. The two now agree to the cent: $14.33M revenue and $9.93M NOI over
Sep 25–Aug 26 on both.

Note the monthly tiles swing hard, which is what makes the label load-bearing:
Aug 2026 books enough reversals (taxes −$118,781, utilities −$31,450) to read a
**96.2% NOI margin** for the month against 69.3% on the T12 beside it.

Two more details worth knowing:

- **Budget variance prints the percentage, with the dollars beneath it.** The
  published cell is `+$116,402/+12.1%`, two figures spliced, and at 20px that is
  wider than a tile is at phone width. `measured[slug]` publishes
  `budget_variance_pct` and `budget_variance_dollars` separately for exactly
  this reason, so the tile reads the halves rather than truncating the cell.
  Both keep their sign: the band grades magnitude, but an overspend and an
  underspend are not the same news.
- **Trade-out % does not jump to the Trade-outs card.** Every tile jumps to the
  card showing the working behind its own number; where no card on this tab
  draws that feed, the jump goes to `What Feeds This Tab`. The tile's 39.8% is
  the Yardi tradeout report's trailing quarter, the card's 82.8% is the weekly
  leasing workbook and the renewal tracker — two feeds, two windows, two
  definitions,
  and landing a reader on one from the other under the same name is the
  disagreement this tab exists to avoid. Leased % is the same case (the tile is
  `100 − exposure` from the export, Unit Inventory is the rent roll's 97.7%),
  and so is Budget variance, which no card draws. Delinquency jumps to
  `cdDelq`, which draws that exact cell.

`SCD_RATE_ONLY` went with the grid: its only consumer was the grid's `# of
Renewals` cell, which is not one of the four tiles.

### The Delinquency card's headings

The left column is **one heading per bar, carrying that bar's own value** —
`$5,121 / 31-60 DAYS` and so on. It used to hold three derived stats (the rate,
the past-30 total, the over-90 figure); the total was the three bars added up
and the over-90 was one of them, so only the rate was not already on the chart,
and it sits in its own `.statrow` above the row.

**Each heading is placed at its bar's centre, read from the chart's own y
scale** (`chart.scales.y.getPixelForValue(i)`), from a plugin hook that fires on
every layout. Spreading them evenly down the block misses: Chart.js insets the
plot area by the x-axis labels at the bottom and by nothing at the top. The
chart's own y-axis labels come off with them — a heading beside a bar names it,
and printing the bucket twice on one row is noise — and the `stacked` fallback
puts them back, for a width narrow enough that the chart wraps onto its own
line and there is nothing left to line up with.

The **eyebrow is the report's as-of date and nothing else**. A `YYYY-MM-DD`
string handed to `new Date()` parses as UTC midnight and renders a day early
west of Greenwich, so the parts are passed to the constructor separately; this
is the one place on the page formatting a date with no time in it.

**`.chartwrap` carries `min-width: 0`**, which is the same trap `.grid > *`
guards against one level further in: a flex item's default min-width is its own
content's, and a Chart.js canvas holds the pixel width it last rendered at, so
a chartwrap in a flex row never shrinks — it keeps its first-render width at
every viewport below it. That wrapped the delinquency row at every width under
1440 (leaving the headings lining up with a chart 222px further down) and held
Unit Inventory's chart at 902px inside a 340px card, **scrolling the whole page
sideways by 555px at phone width**. Both were fixed by the one rule; it is a
no-op for a chartwrap in normal block flow, where min-width is already 0.

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

`SCD_MISSING` is the honesty block: four things The Landing shows that no Drive
export can refresh today, each with why and what would fix it. The counts in the
note under it are computed from the list rather than typed, so they cannot go
stale when a row moves. **Only one of the four is still waiting on a report** —
a concession burn-off run for The Landing (the one on file is Palma's, A6). The other three are pipeline
or page work on feeds that have already arrived: the holdover reconciliation
needs the rent roll and the tracker joined unit by unit, the delinquency aging
needs publishing out of a parse that already runs, and the Insights scorecard is
a judgement no report produces.

It was five until 2026-09-11, when the **monthly loss-to-lease series** came off
the list: it wanted the statement's revenue detail lines, and the parser now
reads them — see the rent-capture section below. The rent roll's arrival the
same day had already closed three rows before that.

### The Google reviews view

A **View** select sits above the Landing tab's grid (2026-10-05, by request:
"a dropdown menu under the Landing tab"). `Operations` is the default and is
every card above, unchanged; `Google reviews` swaps the grid for an executive
summary of The Landing's Google Maps reviews: four tiles, a bottom line with
what is going well and where to improve, what reviewers raise, tone and owner
replies by period, problems and highlights with what reviewers say, two further
notes, and every review in a collapsed table.

**There is no feed behind it**, and that is the first thing to know:

- Google answers the pipeline's network, and a headless browser in a cloud
  session, with its "unusual traffic" page. The reviews arrive as the Google
  Maps list **copied by hand** (newest first) and pasted into a session; the
  2026-09-30 copy took a network-policy change just to reach Google, and the
  scrape still hit the CAPTCHA.
- **The copy carries no star ratings.** Google draws them as an icon and copied
  text leaves it out, so tone (Positive / Mixed / Negative / Unclear / No text)
  is read from each review's visible text, and the pane says so above its first
  card. No rating is published. Stars need the Business Profile (Takeout or its
  API) or a console snippet run in the reader's own browser on the Maps page.
- **Dates are relative.** "3 months ago" is `months_ago: 3`, so a month is
  approximate, and "a year ago" covers 12 to 23 months: the older group is
  "12+ months ago" and the copy may stop before its oldest review.
- 25 of the 53 reviews were cut at Google's "More" link and are coded from what
  was visible.

`scripts/build_reviews_json.py` holds the coding, one row per review: tone, the
themes it raises, the owner's reply (`Yes`, `No`, or `Before edit` when the
reply predates the reviewer's latest edit and so answers an older version),
whether the reviewer has moved out, whether the review is about touring,
applying or moving in, staff praised by name, and a shortened verbatim excerpt.
It writes `docs/reviews.json`; never edit the JSON. The script asserts the
tallies made by hand when the rows were first coded (33 reviews in the last 12
months, the per-theme counts, negatives and replies per window), so a slipped
row cannot change the view unnoticed. Change those numbers deliberately, with
the rows.

**Every figure on the pane is computed from the rows in the page**, each
bottom-line sentence and its lead included: "Reviews have turned more
negative" becomes "more positive" if the shares do. The theme descriptions,
the assessment's findings and next steps, and the watch notes are the only
typed prose, and they cite review numbers rather than counts. So recoding a row
and rerunning the script is the whole refresh.

**The Bottom Line card carries the assessment** (2026-10-05, by request): under
the computed summary, *What we're doing well* and *Where we need to improve*,
each point a finding that cites review numbers and a `Next:` step. They are
`assessment` in `reviews.json`, and each names the theme whose count the page
prints in front of it ("8 of 33 reviews this year"), or `metric: "replies"` for
the owner's reply rate, so a recount moves those figures without touching the
prose. The five suggested actions that had a card of their own became those
next steps, and that card keeps the two remaining watch notes as *Also Worth
Knowing*. The two groups stack and lay their points in two columns: side by
side, three strengths beside six improvements left half the card empty.

Reviewer names are never recorded and unit numbers come out of excerpts; staff
a review praises by name keep the name, staff it criticises by name are
replaced with their role. `docs/reviews.json` is in `check_no_pii.py`'s
`PUBLISHED` list, so the structural pass covers it, and its keys avoid `name`.

Three things about how the pane is built:

- **Two panes, one tab.** The operations grid is `#dOpsPane` and the reviews
  grid `#dRevPane`, each a `.grid` carrying `data-pane`, and `setLandingPane()`
  switches them. `.grid[hidden]` is in the sheet because `.grid`'s
  `display: grid` outranks the UA `[hidden]` rule, the trap `.opsel` records. A
  deep link to a card in the hidden pane (`index.html#cdRevTone`) switches the
  select on the way in, in `focusCardFromHash`.
- **Lazy, like the tabs.** `reviews.json` is fetched the first time the pane is
  chosen, so its canvases are visible and sized when built, and each card draws
  inside `section()`: a missing file reads `— not available` card by card.
- **Colours.** Problems and negative are the page's red (`C.red`); highlights
  and positive the Rental Rates blue `#3987e5`, the pair validated on both
  themes' surfaces (the dashboard's teal fails the chroma floor and 3:1 on
  white). Mixed is `C.muted`, which `restyleCharts` swaps per theme, and segment
  labels choose their ink by contrast, so the grey takes dark ink on dark and
  white on light. Below 520px of chart width the axis labels wrap to two lines;
  Chart.js clips them at the canvas edge otherwise ("partments & building").

It has no lineage entry, so its cards carry no `Data ↗` link and `reviews.json`
is neither on the data page nor in What Feeds This Tab; the pane's own Every
Review card is the table behind it.

Verified in the browser through the gate at 1440, 1100 (light) and 390px: every
tab opens with no page errors and no sideways scroll, all seven sections draw,
both charts settle on their own scales, the deep link switches the pane, and
switching back restores the operations cards. **Judge the charts once they
settle**: Playwright's full-page capture resizes the viewport and catches
Chart.js mid-animation, which reads as bars a quarter of their length.

## The Market Comps Tab

`Market Comps` sits beside `Landing` and is the only tab drawing a
report about **the market** rather than about an Align building. It exists for
one reason: the Yardi **market rent** column is set by the property team, it is
the denominator of loss to lease on the Landing tab and of the whole Rent
Capture block, and until 2026-09-18 nothing in the pipeline could tell whether
it was right.

It can now. The Landing's rent roll of 2026-09-11 carries a market rent table
**9.7% above what the submarket supports** — $176,953 a month, $2.12M a year —
and the same file dates the step to between 2026-08-25 and 2026-09-11.

**That step was intended** (owner, 2026-09-18), and more like it are expected
over the following months. So the tab is not an audit finding, and its prose
does not read as one: it measures how far ahead of its submarket a deliberately
aggressive table sits, and — through days on market and concessions — whether
the market is paying it. Two consequences are worth holding on to:

- **A moving table needs a moving reference.** The comp file is one vintage. A
  table that steps again while the comp set stays at 2026-09-15 reports a gap
  that is partly just a stale reference, so this feed wants a regular export
  cadence rather than the single drop it has. Nothing in the pipeline can tell
  the two apart, which is why the `One vintage` line in the tab's own limits
  block matters more than it reads.
- **The premium baseline will eventually absorb the policy.** `premium.median`
  is taken across every quarter in the file, and a building that now runs
  20–30% over its ring by design will, given enough quarters, pull that median
  up — and the comp-implied figure with it, shrinking the reported gap while
  the building moves *further* above the market. A median over fourteen
  quarters takes years to flip, so this is a slow drift rather than a live
  problem, but it is the one way this tab could quietly stop reporting the
  thing it was built to report. The footnote's own trailing-run detector is
  what would show it first.

### Four readings of one number

The verdict card is deliberately four figures for one number, and three of them
are the building's own:

| Reading | The Landing | vs comp-implied |
| --- | --- | --- |
| Rent roll 2026-09-11 — the market rent column, unit by unit | $2,004,929 | **+9.7%** |
| Unit directory 2026-08-25 — each plan's published range, midpoint | $1,805,509 | −1.2% |
| T12 statement Aug 2026 — gross market rent potential, the same table booked as revenue | $1,804,359 | −1.3% |
| Comp-implied — comp median by bedroom × this building's own premium | $1,827,976 | — |

A single comparison against the comps could only say a number looks high. Three
internal copies that agree with the market and disagree with the fourth **date
the change**, which is what makes it actionable rather than arguable: the
directory and the GL agree to 0.06% with each other and sit inside 1.5% of the
comps, so whatever moved, moved after 2026-08-25.

The statement's own gross potential says the same thing over thirteen months:
$5,164/unit in Aug 2025, $5,768 by Jun 2026 — then **+12.1% in Jul, +6.1% in
Aug, and +11.1% again by the roll**. +32.2% in three months, against a comp set
that moved 2–6% over the same stretch.

### How the comp-implied figure is built

Per bedroom, because that is the unit the market quotes in and the only one
size-match can be checked on:

| | Units | Building | Comp median (n) | Market rent | Yardi's own |
| --- | --- | --- | --- | --- | --- |
| 1 bed | 137 | 639 sf | $5,646 at 627 sf (60) | $5,992 | $5,738 |
| 2 bed | 110 | 981 sf | $7,475 at 982 sf (48) | $7,932 | $8,044 |
| 3 bed | 16 | 1250 sf | 2 listings — not priced | $8,410 (Yardi's) | $8,410 |

The size match is near exact on the two bedrooms that matter (+1.9% and 0.0%),
which is what lets a median rent be compared without adjusting it. Three things
the build-up is careful about:

- **The premium is the subject's own, and it is bed-weighted.** A comp median is
  the middle of the submarket; a building that has asked 6% over that middle for
  three years is worth 6% over it today. The figure is the median of the
  quarterly premium across the whole file (+6.1% over 13 quarters), taken **per
  bedroom** and weighted back together by the subject's own listing counts — a
  pooled ratio moves with the unit MIX as much as with price, and 2025Q1 reads
  −16.0% pooled against −3.6% bed-weighted purely because of what happened to be
  vacant. A median rather than a mean, so the quarter being measured can sit
  inside the baseline without moving it.
- **A bedroom the ring cannot price keeps the building's own rent.** The
  submarket has two 3-bed listings; two asking prices is not a market
  (`MIN_BED_FOR_IMPLIED`). Those 16 units stay in the total at Yardi's own
  figure, so the gap the tab reports is the one that survives leaving them
  alone.
- **The answer carries its own sensitivity.** The same build-up at every ring
  the export is cut into: **+12.9%** against the nine buildings inside 0.75 mi,
  **+9.7%** against the seventeen inside 1.35 mi, **+19.0%** against all 33 in
  the file. A gap that survives three comp sets is a finding; one that does not
  is a choice of radius.

Restated on a comp-supported market rent, the published **loss to lease falls
from 36.5% to 30.4%** — still far above the band's 10% ceiling, so this does not
answer A8's band question, but it moves the number A8 is arguing about. And with
further steps expected, that KPI climbs with each one: its denominator is now a
pricing position rather than a measurement, which is the live half of A14.

### The market's own answer, which agrees

Two figures on the same export, neither of them a rent:

- **Days on market: 44 against the ring's 26** (91 closed listings against
  1,056, trailing twelve months). The building takes 69% longer to let a unit.
- **Concessions: none advertised, against 22% of the ring.** So the gap on an
  effective-rent basis is wider than the asking figures show.

One unit has been listed at $6,323 since 2026-04-15 — 153 days.

### What the tab cannot say, and says so

`cmcMethod` is the honesty block, and every line of it is read from the file
rather than typed: asking rents are not signed rents; the 3-bed units are
unverified and named; floor, view and finish are not controlled (the premium is
the stand-in for whatever this building is actually worth over its neighbours);
it is a single vintage until a second export lands; and **only aggregates are
published** — the listing rows are a licensed vendor dataset, and everything
`docs/` holds is downloadable by anyone who can open the page, which is the same
reasoning that keeps resident names out of `data/`.

### The feed

`HelloData - Simple - <market> Comps.xlsx` in the Drive **`Comps`** folder, two
flat tables: `Property Data` (one row per building) and `Availability` (one row
per listing, three years deep). `parse_comps.py` cuts it from each Align
building's point of view — every property in `config/properties.json` that
appears in the file gets its own section and its own comp set, so Chorus and
Madelon are on the tab's property select already.

**The export arrives as a pair**, and the second file is `HelloData - Full -
…xlsx`: the same market as a twenty-sheet formatted workbook with no parseable
table in it. The entry's `file_glob` is `*` so it claims **both** — a narrower
pattern is how `Landing 2026 Resi Budget.xlsx` went unread for weeks — and the
parser then *skips* the formatted one with a line saying which file it is and
that nothing is missing. A skip with a reason, not an error, because both files
belong in that folder.

#### Two markets, and ninety extracts of them

The folder is organised by **market, then by which of the paired exports it
is**, because those are the two things a reader picks between and neither is a
property of the other:

    Comps/
      San Francisco/ Simple/   Full/
      Oakland/       Simple/   Full/
      Archive/       San Francisco - Full/   Oakland - Full/

San Francisco is the Mid Market / Mission / Dogpatch–Mission Bay set that
covers The Landing, Chorus and Madelon; Oakland is **335 Third Street**, whose
ring is Jack London Square. `fetch_drive`'s folder pass descends **two** levels
for exactly this shape — see *Folders organise; filenames route*.

`Simple/` holds **every extract**, not the newest one: 46 for Oakland and 45
for San Francisco as of 2026-09-21, and more arrive hourly. They are not copies
of each other and they are not successive slices of a window either — each is
the same three-year history as the vendor understood it on its own as-of date.
Three things follow, and the first two were found the hard way:

- **A later extract is not a superset of an earlier one.** HelloData revises
  its own history. Of the 739 listings in the 2026-08-11 Oakland file, 43 are
  absent from the 2026-09-20 one — and every one of those 43 is a unit still in
  the newer file under a revised `First Listed` date. No building and no unit
  went away; the dates moved.
- **Arrival order does not track vintage, and not by a little.** A copy that
  landed 2026-09-21 carries an as-of of **2026-08-05**, six weeks behind one
  that landed three days earlier. So `store_comps` keeps the newest **`as_of`**
  and refuses to go backwards, and says so in the log when it refuses. Reading
  "whichever parsed last" would have moved the Market Comps tab to an August
  reading of the market with nothing on the page to say so — on the one tab
  built to check somebody else's number.
- **The ledger is published.** `vintages` on each `comps.json` is every as-of
  the store has been offered, so the tab's own limits block counts the extracts
  rather than claiming one. That is the `One vintage` caveat A14 asked about,
  answered from the data instead of retyped.

Only the `Full` twins are archived, in `Comps/Archive/` — `Archive` is in
`NEVER_SWEEP`, so neither pass reads it. Nothing is deleted; they are simply
2–4 MB apiece, no parser reads them, and fetching ninety of them daily is the
kind of cost open item A15 is about. The newest of each stays live under
`<market>/Full/` for anyone who wants to open one, and **the entry's
`skip_subfolders: ["Full"]` keeps those out of the download too** — an archive
guard would have been the wrong tool there, since those files are current
rather than superseded. It is matched by folder name at any depth, like
`NEVER_SWEEP`, and logged every run for the same reason.

**The filer writes this tree itself**, market folder and kind folder both, from
the export's own name — see *Two folders are split inside* below. It does not
yet do so in Drive, because the deployed script is sixteen days behind the repo
(A16's dead credential, consequence recorded as C9).

**There is no total row to tie out against.** Every other parser here checks
itself against the report's own arithmetic; a comp export has none, so two
structural reconciliations stand in and both refuse the file:

- **Every building in `Availability` must be described in `Property Data`.** The
  rings are built by distance and the coordinates live only in that table, so a
  listing whose building is missing drops silently out of every ring and the
  comp set quietly becomes whatever happened to be described.
- **`Days on Market` must reconcile to the listing's own dates** — `(removed −
  first listed) + 1`, which holds on all 6,096 closed listings in the first
  file. If the column stops meaning that, half the evidence that an asking rent
  is too high is measuring nothing.

Four more things it is careful about:

- **Align's own buildings are not comps.** Three of the 36 buildings in the file
  are Align's. They are excluded by resolving each building against
  `config/properties.json` — the property master, not the export's own
  `Management Company` string, which is free text — so a property added there
  leaves the comp sets without anyone remembering this file exists.
- **A floorplan row is not a unit** (`Is Floorplan`), and counting them weights a
  building by how many plans it publishes.
- **A listing is current only on the file's own as-of date.** Every row carries
  the snapshot that observed it, three years deep, and the market in this file
  moved +64% across that span.
- **The ring is cut on every bedroom the MARKET has**, not only the ones the
  subject has listed. A building can go three years without listing one of its
  bedroom types, and falling back to Yardi's rent because nobody collected the
  market is a different thing from falling back because the market is too thin
  to read. Only the second is a finding.

**A building is not a person.** The parser publishes building names under
`building`, not `name`: `name` is in `build_metrics.PII_FIELDS` and the central
scrub drops it from everything on its way to `data/`, which emptied the comp
table on the first run. Weakening a scrub that exists to keep residents out of a
public file, in order to publish a comp table, would be the wrong way round.

`scripts/test_comps.py` holds it down — 58 fixture-free checks against exports
built in a temp dir. The eight load-bearing guards were each verified by
mutation (the two reconciliations, the floorplan skip, the as-of cut, the Align
exclusion, the bed-weighted premium, the thin-bedroom fallback and the
market-wide ring). **Clear `__pycache__` between mutation runs** — the same trap
the leasing parsers' tests record.

Tables: `t-comps-<slug>`, `t-compstrend-<slug>`, `t-compscheck-<slug>` and
`t-compsleasing-<slug>` on the data page, under a `Market Comps` group. The
last is the two figures on this export that are not rents — days on market and
the concession share, each side's listing count beside it — plus what the
subject has listed today. It was added 2026-09-28 because the card drawing
them had nowhere to link: they were published and no table held them.

### Refreshing the tab on its own, daily

`scripts/refresh_comps.py <file-or-dir> [--landed-at ISO] [--dry-run]` parses
comp exports and rewrites **only** `metrics["comps"]`, leaving every other
block in `docs/metrics.json` exactly as it found it (checked, not assumed).

It exists because the daily cron cannot carry this feed on its own. The export
arrives several times a day, for every market Align asks for, and the cron runs
once. (When this was written it also took five hours and its push-retry loop
copied its output over anything newer — A15, since fixed.) So "the comps tab is
refreshed daily" needs something that runs the one feed and touches nothing
else.

It is the same code either way: the block is built by
`build_metrics.comps_block`, which both callers use, so the published figures
cannot depend on which of the two wrote them. Three things it is careful about,
all of which a scheduled caller depends on:

- **An older export cannot walk the tab backwards.** `store_comps` keeps the
  newest `as_of`, which matters more here than anywhere — a scheduled run is
  handed whatever *arrived*, and arrival order does not track vintage in this
  feed.
- **A file it cannot read is skipped, not fatal.** The export is a pair and the
  formatted twin has no parseable table, so a batch that died on the first
  unreadable file would die on every batch.
- **`--dry-run` writes nothing**, which is how the run asks "is there a newer
  vintage?" before touching the repo.

**`.github/workflows/refresh_comps.yml` runs it daily**, at 21:30 UTC — after
`update.yml` has normally finished, so the two are not usually building at
once. It is `fetch_drive.py --only market_comps` then `refresh_comps.py`, and
it commits only when a vintage actually moved: a no-change run leaves the tree
byte-identical, so a quiet day produces no commit at all.

Its push race is handled the way `update.yml`'s now is too: it **resets to
main and re-runs the refresh** — `store_comps` then reads whatever stores main
now carries and keeps the newest as-of either way. Replaying the computation is
safe where replaying the output is not. This workflow did it first because its
rebuild costs seconds; `update.yml` followed on 2026-10-05, once its own build
was down to minutes (see *The commit step rebuilds on a newer main*).

`--only <report_type>` is new with it: the daily pipeline never passes it and is
unchanged, but the whole fetch has taken four and a half hours and this feed
arrives several times a day. A scoped run also skips the unmapped-folder scan,
which walks every folder in the drop tree and is most of what the scan costs.
An unknown type is refused rather than quietly fetching nothing.

**A Claude Routine is not the tool for this, and it was tried.** One existed
alongside the workflow for about an hour on 2026-09-22 and was deleted, because
a fired Routine session here starts with neither half of what the job needs: no
Google Drive connector (`create_trigger` refuses the `connectors` parameter for
this org, and the fired session reports Drive as `enabledInChat: false`) and no
repo source (it is created with `sources: []`, and the session has no
`add_repo` tool or working checkout). Both would have to be attached by hand in
the claude.ai Routines UI, and neither is reachable from the API.

The workflow needs none of that — it has the pipeline's own service account and
the repo it runs in. And the case the Routine was meant to cover barely exists:
a new market arrives as a new subfolder inside `Comps`, which the two-level
descent picks up by itself, and a genuinely new top-level folder is still
reported every day by `update.yml`'s unmapped-folder scan. Worth knowing before
anyone reaches for a Routine here again.

### A property with no rent roll still gets a check

The headline is the newest Yardi reading of the table, which is normally the
rent roll — per-unit, current, and the denominator loss to lease actually uses.
Where no roll has reached the pipeline the **unit directory stands in** and the
card names which reading it measured rather than going blank: Chorus reads
**−4.3%**, i.e. its published table sits *under* the market, which is the
opposite finding and worth having. The loss-to-lease restatement needs the roll
and is left out there. A property with no directory at all gets the market side
of the tab and a card saying why the check cannot be made — that is Madelon
today.

## The Rental Rates Tab

`Rental Rates` is the **Rental Rate Tracker** — a separate dashboard at
`github.com/dbalduc/rental-rates` covering The Landing, Chorus, The Madelon,
Ansel and The Fitzgerald — brought onto this one in its own chart format:
per-building tiles, trade-out % and renewal % by lease date, the new-lease $/sqft
trend, prior → new $/sqft per lease, the weekly summaries and the lease detail
table, all under one Timeframe (Max / QTR / Month) and rent-basis (Effective /
Gross) row. It replaced a two-card test built from the pipeline's own Landing
feeds while the tracker's data was out of reach.

**The data stays encrypted here, as it is at source** (owner's call, 2026-09-23).
The tracker publishes only ciphertext that decrypts in the browser with its
password, and everything `docs/` holds is readable by anyone with the URL — a
plaintext copy would have published what its owner chose not to.
`docs/rental_tracker.enc.json` is PBKDF2-SHA256 (600,000 iterations; the
tracker's own is 200,000) into AES-256-GCM under **the tracker's password**, and
the tab decrypts it with WebCrypto. The password is never in the repo, never
sent anywhere and never stored: what `sessionStorage` keeps (`align-rt-key`) is
the derived key for that one file, so a reload stays unlocked, a re-import (new
salt) asks again, and **Lock** drops it. In the clear: the snapshot date, the
import time and the row counts, so the tab can say what it holds and how old it
is before it is unlocked.

### Refreshing it, daily

`.github/workflows/refresh_rental_tracker.yml` does it at **15:00 UTC**: clone
the tracker, run the import with `--quiet`, commit only if the data moved. The
tracker is rebuilt every morning — its repo is one commit, force-replaced, and
the first one seen was built at 11:09 UTC — so four hours of slack covers a
late build. **GitHub starts scheduled runs late, though:** the first six
started between 18:28 and 21:10 UTC, so once the secret is set, expect the
day's snapshot around midday Pacific rather than before the working day.

**It needs one secret, `RENTAL_TRACKER_PASSWORD`** — the tracker's password,
under Settings → Secrets and variables → Actions, **set 2026-09-29** (A18,
closed). Without it every run is a no-op that says so in its summary rather
than failing, the way `deploy_filing_script.yml` waits for its two. The password sits only in the
environment of the steps that need it, and Actions masks it in the log.

Four things it is careful about:

- **It prints totals and a date, and nothing else.** This repo is public and
  so are its Actions logs. `--quiet` drops the import's per-building breakdown
  — that is the tracker's encrypted content — and leaves what the file already
  shows in the clear. `test_rental_tracker.py` fails if quiet output names a
  building, verified by mutation.
- **It touches one file.** Nothing else writes `docs/rental_tracker.enc.json`,
  and this writes nothing `update.yml` does, so neither can clobber the other.
  A rejected push only means main moved: the run resets to it and re-imports,
  as `refresh_comps.yml` does, because the inputs are still on the runner and
  the import takes seconds. Simulated against a local remote: a quiet day, a
  changed day and a lost race each end with main holding the tracker's copy.
- **A quiet day commits nothing.** The import leaves an unchanged file alone.
- **The importer's guard tests run first.** The whitelist that keeps the
  tracker's resident names out of this repo is only as good as the code
  enforcing it.

It does **not** regenerate `lineage.json`, so the data-flow page's arrival for
this feed lags by up to a day, until `update.yml`'s next run. Regenerating it
here would flip other flows' evidence every morning, since this runner has none
of the gitignored stores a pipeline run does.

The tab's snapshot line turns red past `SC_STALE_DAYS` (3) — the page's one
definition of a daily feed gone quiet. The tracker rebuilds daily and this
copies it daily, so a snapshot that old means one of the two is not happening,
and the line **links to this workflow's run list** (`RT_WORKFLOW_URL`), where
the newest run's summary says which: `not refreshed` while the secret is
unset, `already current` when the tracker itself has not moved. It said "see
the Refresh Rental Rates workflow" in plain text until 2026-09-29, which read
as a link and was not one.

**Every run before the secret existed was that first case**, and that is what
the red line on 2026-09-29 was: six scheduled runs and one started by hand, each
skipping from the password check to the end. The snapshot was refreshed by hand
that afternoon (the command below), and the secret went in that evening: run #8,
dispatched to check it, ran every step, decrypted the tracker, found the tab
already current and committed nothing — the quiet-day path, and the first
evidence that the password in the secret is the tracker's own.

By hand, for a snapshot now:

    git clone --depth 1 https://github.com/dbalduc/rental-rates /tmp/rental-rates
    RENTAL_TRACKER_PASSWORD=... python scripts/import_rental_tracker.py /tmp/rental-rates

That needs `pycryptodome` (or `cryptography`); neither is in
`requirements.txt`, since only this workflow and a person ever run it.

The import **refuses rather than publishes**, and a refusal writes nothing, so
the file keeps its last good copy:

- **Free text never passes.** The tracker's renewal notes name residents — most
  carry text, and several name a tenant — so the output is a whitelist, field by
  field (`LEASE`, `RENEWAL`, `WEEKLY`, `MTM`), and a field nobody listed is
  dropped and counted rather than carried: a note column added upstream
  tomorrow cannot reach this repo. It is **Tenant names must not leave the
  pipeline** applied inside the encryption too — a password is one leak away
  from being plaintext. The one prose that passes is the tracker's subtitle, its
  own line on which system each building's numbers come from, and it is refused
  if it carries an email or phone shape.
- **Every value has a shape.** Real calendar dates; units and terms matching a
  label pattern; numbers that are finite numbers, not text and not booleans. A
  value that fails refuses the import and is **never echoed** — a field failing
  its pattern is exactly the one that might be carrying text.
- **Each row is checked against its own arithmetic** — a trade-out % against one
  of its two rents over the prior, a renewal's increase against its two rates,
  $/sqft against rent over footage. Warnings rather than refusals: the tracker
  corrects source errors by hand, and says so in the notes this drops.
- **Unchanged data leaves the file alone.** A fresh salt and IV make every
  encryption differ, so re-encrypting identical data would commit a new
  ciphertext and a new import time on every run.

`scripts/test_rental_tracker.py` holds it down — 35 fixture-free checks against
tracker pages built and encrypted in a temp dir. The five load-bearing guards
(the whitelist, the unit pattern, the refusal, the unchanged-data skip and the
quiet log) were each verified by mutation. **Clear `__pycache__` between
mutation runs.** **Every figure in its `data()` is invented**, and must stay
so: this file is public and the tracker's data is not. The first version reused
a few real rows, and they are still in history (open item A19).

**Nothing tracker-derived belongs in prose either** — not in this file, a code
comment or a commit message. The tab shows its figures once it is unlocked;
describing them here would publish what the encryption withholds. The five
building names are fine: the tracker's own gate page shows them.

The file lives in **main, with the site shell**, not on the data branch:
`deploy.yml` overlays only the four data files, and ciphertext is safe in history
in a way the plaintext JSON is not.

### Where it departs from the tracker, and why

- **No colour carries a building alone.** No set of five colours clears the
  colour-vision floors for every pair on a scatter (checked against the palette
  validator: the worst pair is indistinguishable to a deuteranope in the dark
  theme), so every chart names its buildings some other way too. The colours
  (`--rt-1`..`--rt-5` on the two `:root` blocks) are each theme's own step of one
  validated categorical order.

  **Every chart on the tab is one chart, with a box per building** (owner's
  call, 2026-09-29) — each was five small panels until then. On every one,
  each building also wears its own marker (`RT_SHAPES`,
  in the colours' fixed order, three longer than the palette so a sixth to
  eighth building, which share the neutral colour, still get one each), drawn
  in its box as well as on the plot. Each $/sqft fit line is named at **its
  own** end, on a backing of the card's surface — not in a column down the
  right, where a line that stops early would sit its name level with one
  that runs on. And the tooltip names the building for every mark it
  covers, since two buildings' leases on one point are hovered together. A
  line every mark in such a stack shares is said once in the heading, and a
  stack past `RT_TIP_MAX` (4) is cut, because any number of marks can share
  one point and a tooltip taller than the chart is clipped by it. The cut
  takes one of each building before a second of any, and the rest are
  counted by building, so a stack never hides which buildings are in it.
  Hover goes to the nearest **dot** only (`rtDots`): Chart.js's own nearest
  mode also weighs a fit line's invisible end points, and the tooltip filter
  runs after it, so pointing at a line's end showed an empty tooltip over a
  real lease. On the prior → new card the distance is to the whole stem, so
  pointing at a grey tick is pointing at that lease. `rtOverlay` draws all
  four:

  - **The boxes are per card**, kept across a timeframe, basis or theme change
    (`RT.hide`) and dropped on Lock.
  - **A building with nothing in the timeframe keeps its box**, struck through
    and inert, with the reason on hover — the Budget vs Actual property row's
    rule, so the grid says where a building went rather than losing it. A
    timeframe with nothing at all drawn shows the card's empty state instead.
  - **A box that cannot be ticked filters nothing.** A building switched off
    stays so through a timeframe change, but where its box is struck through
    or no grid is drawn its leases are listed as if it were on: a note
    shaped by a setting the reader cannot see or change would undercount.
  - **The time axis holds still and the vertical axis rescales** to the
    buildings shown, so switching an outlier's building off lets the rest fill
    the height. Everything off keeps the last scale, and the note says no
    building is selected.
  - **The note and the canvas label follow the boxes**, per-building figures
    and all, the way Budget vs Actual's note follows its basket.

  **The prior → new $/sqft card draws each lease as a stem on its lease
  date** (`rtSpans`): a grey tick at the prior rent, a line in the
  building's colour, and the building's marker at the new rent. It was two
  cards of bars in lease order, one row per building, and a building's own
  lease order is not an axis two buildings can share — so the overlay puts
  them on the same date axis as the cards above it, and the vertical axis
  takes in both ends of every stem shown. What a view cannot draw (a lease
  with no prior rent or square footage, a renewal with no square footage) is
  counted in its note by building and reason, under the box rule above, and
  a building with nothing drawable keeps a struck-through box saying why.

  **New leases and renewals are one card, on a switch** (`cRtPriorNew`,
  owner's call, 2026-09-30) — the Lease Detail card's `New leases` /
  `Renewals` pair, in the card head. The two had been separate cards with
  the same stems and the same axes, so the switch changes what is drawn and
  nothing about how. Three things about it:

  - **One set of boxes serves both views** (`RT.hide.pn`). A building
    switched off stays off across the switch, as it does across a timeframe;
    the box rule still holds per view, so a building struck through in one
    view has its leave-outs listed there whatever it was set to in the other.
  - **The switch is a view, like Lease Detail's**: it holds through a
    timeframe, basis or theme change and through Lock, which drops only the
    boxes. The rent basis moves the New leases view and not the Renewals one,
    and each view's eyebrow and note say which.
  - **It sits below Renewal %**, so both % charts its empty-box hovers point
    a reader to are above it.
- **Every tile carries the rent-weighted trade-out beside the tracker's mean.**
  The mean stays the headline, so the two dashboards agree on it, and the
  weighted figure beside it is the statistic the Landing tab grades; one
  concession-bought prior can swing a mean. It is taken over the **same
  leases** as the mean, because the tracker withholds a trade-out on a few
  leases that do carry a prior.
- **A cut is drawn as a cut.** The tracker stacks the change on the prior, so a
  lease that came in below the one it replaced hangs below the axis. Here a
  cut's stem runs **down** from its tick, is dashed, and on a filled marker
  ends hollow — the hollow is what shows a cut too small to have a visible
  stem. A cross is all rim already, so there the direction, the dash and the
  tooltip carry it. The note names the largest eight cuts and counts the rest.
- **Occupancy is the newest week by date.** The tracker takes whichever weekly
  row comes last in its file, which is not always the newest. A building with no
  weekly report shows the figure the tracker types in, and the tile says
  nothing dates it.
- **Trade-out % is as each source reports it, and that is not one basis.** Only
  a handful of leases have a gross and effective rent far enough apart to tell,
  and they do not agree on which one the trade-out follows. So the card counts
  what it can tell on the data in front of it rather than asserting a rule per
  source.

The data-flow page carries it as its own flow (origin `site`) with **no table
behind it, on purpose**: the page could only show these numbers by decrypting
them. Every card's `Data ↗` lands on that row instead.

## Refreshing The KPI Scorecard

`docs/scorecard.json` comes from the KPI scorecard workbook, in two steps that
must run **in this order**:

1. `python scripts/extract_scorecard.py <KPI_Scorecard.xlsx>` — the grid's
   hand-set symbols, the metric groups, and (since v10) the published target
   ranges and the Palma lease-up overrides. **This resets every measured value
   to null**, which is why it goes first.
`OMITTED_METRICS` in `extract_scorecard.py` is the list of grid columns the
dashboard does not publish at all — `# of offers that are 30 days` (2026-08-28)
and `# of accepted/pending offers` (2026-09-17, owner's call). They are dropped
at extraction rather than hidden on the page, so no downstream table carries a
KPI with no home, and their published range goes with them. The workbook keeps
its own column either way, and the extractor warns if a name in the list stops
matching a column.

**`populate_scorecard.prune_omitted` applies the same list on every fill**, so
the live page does not wait for a workbook refresh. Extraction is the real
fix, but it needs the `.xlsx` and is run by hand, so a KPI removed today would
otherwise sit on the page for as long as that takes; the daily cron runs
`populate_scorecard`, so the page catches up on its own and the next
re-extraction is a no-op rather than a correction. It removes only the metric —
the coverage counts and `by_metric` are left to `recompute`, so the grid and
the figures under it cannot disagree.

It **reads** the list out of `extract_scorecard.py`'s source rather than
importing it: that file has no `__main__` guard and opens the workbook at
module level, so importing it would demand the `.xlsx` in CI. One list read
from the one place it is defined still beats a second copy, and it is the same
idiom `test_routing.load_rules()` uses on the `.js`. `omitted_metrics()`
returns **`None`, not an empty set**, when the read fails — mutation shows why
that matters and how little separates the two: an empty set prunes nothing
*and says nothing*, so the removal quietly stops working while every count
still adds up. `scripts/test_scorecard_omissions.py` is the guard — 23
fixture-free checks.

Removing `# of accepted/pending offers` moved **no graded figure**: it was a
hand-set symbol no report had ever measured, so `scored` and `at_or_above`
are untouched at 31 and 64.52%, and only the cell counts fall — 27 KPIs to 26,
135 cells to 130, the five lost cells all previously `awaiting a feed`.

2. `python scripts/populate_scorecard.py --from-landing` — fills the measured
   numbers a report can actually answer and re-derives those cells' status from
   the published band, keeping the workbook's original symbol in
   `status_workbook`. Re-runnable and idempotent; it rebuilds the per-property
   counts and the portfolio roll-up so the matrix, health chart and tally cannot
   drift apart.

**`status_workbook` is written once per cell and never replaced.** It is what
the data page prints as "Workbook had", and only the *first* restatement since
extraction knows the workbook's symbol — from the second on, the status being
replaced is the previous run's grade. All three writers (`populate_scorecard`,
`populate_eliseai`, `populate_building_metrics`) used to record it on every
change, so by 2026-09-28 six cells quoted a grade the workbook never set
(Chorus's Leased % read "in range" over a workbook that said below). They now
all go through `populate_scorecard.keep_workbook_status`, the six were restored
from the last extraction (`c0d760e`, 2026-08-10), and
`scripts/test_status_workbook.py` holds it down — 14 fixture-free checks, the
helper and the end-to-end run each verified by mutation. Re-extracting resets
the entries, which is the only thing that should.

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

**Since 2026-09-29 the report fills only the split wherever the EliseAI
building-metrics export covers the property** — owner's call, closing B4: the
export's `Delinquency Rate` is the outstanding-balance figure, and it fills
`Total Deliquency` for Chorus, The Landing, Madelon and 335 Third.
`AR_FROM_EXPORT` in `populate_scorecard.py` is that list, and must equal
`populate_building_metrics.HEADING_TO_SLUG`'s values; Palma is not in the export
and keeps the report's rate. It is a static list rather than whichever writer
ran last, because a last-run-wins race over one cell is what G3 took a week to
get out of. Three things hold it, each verified by mutation in
`scripts/test_delinquency_source.py` (21 fixture-free checks):

- `--from-pipeline` for a covered property writes the split and **not** the
  rate, and records only what *this run* filled under `delq_kpis` — reading the
  cell instead would claim the export's figure back and strip it from
  `bldg_kpis`.
- `populate_building_metrics` takes the rate even where `delq_kpis` still names
  it (`EXPORT_OWNS`, an exemption from its rule 1), and takes it off every other
  family's list, the same hand-over the tradeout and `delq_` families do.
- The Landing tab's Delinquency card follows whichever family lists the rate,
  labels it `outstanding balance · EliseAI export as of …`, and says the export
  does not state a denominator — so the rate is no longer described as a ratio
  of the bars beneath it.

On the 09-28 export that moved The Landing from 10.2% (the report's gross AR
over a month's revenue) to 7.7%, and Chorus from a stale 17.7% to 8.0% — the
report had claimed Chorus's cell once it started routing, so the export was
skipping it and the page showed the 08-31 figure with no date on it.

**`Loss to Lease %` is the rent roll's** — owner's call, 2026-09-15, closing
open item A8. Market rent less in-place rent over market rent, across
**occupied units**, from the Drive rent roll: The Landing reads **37%**
($713,920 across 257 units on the roll of 2026-09-11).

That is what the band's own published `how` always said — "(Market rent −
in-place rent) / market rent, current rent roll" — and what the previous fill
never was. Until 2026-09-15 the cell came from the workbook's Rent Capture
series, i.e. the T12 statement's monthly revenue lines: a different measurement
of a similarly named thing, reading 27% for Jul 2026 against the roll's 37% and
17.2% on the TTM column. No `how` restatement was needed here, unlike the
controllable basket or the concession equation — the definition was right and
the source was wrong.

`rent_roll_ltl()` reads the **published aggregate in `metrics.json`**, not
`data/<slug>/rent_roll.json`, which is gitignored (unit level, arrives with
names) and so exists only during a pipeline run. `build_metrics` writes
`metrics.json` before this script runs and the block is committed, so the same
figure is available in CI and locally.

**Both fill paths read it**, `--from-pipeline` and `--from-landing` alike, from
that one aggregate. So unlike the delinquency pair this cell has no
last-run-wins race to sequence around: whichever runs last writes the same
number. It records under its own **`rentroll_`** family (registered in
`SC_FEED_PREFIXES`, `data.html`'s matching list and `SCD_DRIVE_FEEDS`), so the
rent roll's own arrival shows on the page and the Drive tab carries the cell.
The workbook's figure is kept in `measured[slug].ltl_workbook` as a note and
never published.

Occupied units only, per the roll's own basis: a vacant unit has an asking rent
and no in-place rent, so counting it books the whole asking rent as a loss —
38.1% against the 37% published.

**A8's underlying question is not closed by this.** The threshold's own basis
note warned that if Yardi `Market rent potential` is aspirational rather than
achievable, every property reads artificially high against a band whose ceiling
is 10% — and the roll shows that table revised up **+17.9% in eight weeks**
while in-place rent moved +0.07%. The cell now measures what the band says it
measures; whether the band's 10% ceiling is right for that measurement is still
open (A9 is its sibling for the controllable basket).

**The comp export answers the first half of that warning.** `Market rent
potential` is not merely aspirational — as of the 2026-09-11 roll it is **9.7%
above what the submarket supports**, and the same three feeds that carry the
table date the change to after 2026-08-25. So the cell's 37% is measured
correctly against a denominator that is itself too high: restated on a
comp-supported market rent it reads **30.4%**. See **The Market Comps Tab**.
That narrows A8 without closing it: 30% is still three times the ceiling.

`--from-landing` also fills **`NOI Margin %`** the same way — the current
month's NOI over revenue from `metrics.json`'s `monthly_pl`, the series the
Landing tab's NOI tiles draw, to one decimal (from the workbook's Expense & NOI
tab until H2, 2026-09-29). Note the direction of the caveat is the opposite of loss to lease's:
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
any budget in the Drive **`Budgets`** folder — `12_Month_Budget_Accrual.xlsx`
is the Yardi export's own name, but not the only one that arrives: a budget
uploaded by hand is named whatever the person named it. The entry's
`name_patterns` is therefore the single word `budget`, matching the filer's
own `/budget/` rule rather than any export's filename, because a pattern
narrower than the filer's means a file the filer puts in this folder that the
pipeline then refuses to claim — routed correctly and never read. That is what
`Landing 2026 Resi Budget.xlsx` hit on 2026-09-16, and `test_routing.py`'s
check 10 is what now fails when the two halves drift apart. It is
the T12 statement's own layout on the JPM tree, so `parse_budget.py` reuses
the T12 parser's anchors, COA translation and Align-tree grouping (and its
to-the-cent tie-out), refusing a file with no `Budget` marker row or a period
that is not Jan–Dec of one year. Both sides of the variance are the **same
basket**: the Align-grouped buckets less `NOT_CONTROLLABLE`, actuals from
`data/<slug>/expense_buckets.json`, plan from `data/<slug>/budget.json`, with
the all-exclusions-found guard on each and a refusal when no plan on file
covers the statement's year. The band grades the **absolute magnitude**,
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
`Landing` tab carries the cell. It needs no `fromDrive` predicate:
unlike the delinquency pair, nothing else writes this KPI.

`data/<slug>/budget.json` now holds **one point per budget year** rather than a
single plan, so this fill picks the plan for the **statement's own year** —
taking the newest would grade this year's actuals against next year's plan. See
**Budget vs Actual (Portfolio tab)** below for why the years accumulate. The
figure above is Jan–Jul 2026 against the statement that ended Jul 2026; the
statement has since moved to Aug 2026, so the next `populate_scorecard` run
will restate it on the Jan–Aug window.

`--from-landing` also fills **`Concession Load %`** — the current month's
concessions over **market rent potential less loss to lease less vacancy
loss**, per the owner's equation set 2026-09-03. All four series come from
`metrics.json`'s `rent_capture` (the workbook's Rent Capture block until H2) —
the block behind the Loss to Lease card — the same T12 statement
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
prints **`30/11.5%`**: units past lease expiry and still occupied, then their
share of occupied units. The **share** is what the band grades, per its own basis
line, so the raw value behind the cell stays the ratio. Since H2 (2026-09-29) it
is the Drive rent roll's own holdover count, `rent_roll.holdovers` in
`metrics.json` — 30 of 260 occupied on the roll of 2026-09-21 — filled
identically by `--from-landing` and `--from-pipeline` like loss to lease, and
recorded under the `rentroll_` family beside it. Until then it was the
workbook's count, 31/262 on the 2026-07-14 roll, which grades the same: below a
band whose red line is 5%. The paragraph below is how the workbook counted.

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

### The Scorecard tab's property filter

A **Property:** select sits in the card head on the `Scorecard` tab. `All
properties` is the default and renders exactly the matrix that card has always
shown; picking one narrows the matrix to that property's row **and recomputes
the head from that property alone** — a headline reading "HEALTH ACROSS 5
PROPERTIES · 65%" over a single row is a figure that gets quoted at the wrong
scale.

The head is not a second opinion on the published numbers. It comes from
`scRollUp(p, SC.groups)` — the same function the property tabs use — over
**every** group rather than the property-tab subset in `SC_HIDDEN_GROUPS`, and
that reproduces `scorecard.json`'s own per-property `scored` / `counts` /
`coverage` / `at_or_above` exactly (checked in-browser against The Landing:
13 of 27 graded, 6/3/4, 69%).

Three things it does deliberately:

- **The chart stays portfolio-wide.** It ranks every property by the share of
  its graded KPIs at or above target, which is where the selected property
  *sits against the others* — a question filtering would destroy rather than
  answer. (This tab has no note block to say so — see below.)
- **The filter is a view of this card, not of the data.** Only a mount that
  declares `ids.select` gets one, so the property tabs' slices of the same
  matrix — same function, same `scorecard.json` — have no select and never
  filter. The Portfolio view carried a second full copy of this card, also
  without a select, until it was removed by request on 2026-09-28; the
  Scorecard tab is the only place the whole matrix is drawn now.
- **The single-property figure is coloured, the portfolio's is not.** Worst
  state across one building's cells is unambiguous (`scTone`), which is why the
  property tabs colour theirs; an average across five buildings has no band
  that turns it into a verdict, which is why the portfolio's stays plain.

A property with **no slug** — on the scorecard but not yet in the property
master, which the note already names — is still selectable, keyed on its label.
It gets no "data last updated" line rather than the portfolio's, because
`scUpdatedEl` reads a falsy slug as "every feed".

**This tab carries no closing note.** The standing paragraph that used to end
the card came off 2026-09-16, by request. `ids.note` is optional now: a mount
that does not declare one renders without it, and `renderScorecard` returns
before building it. The Portfolio view's copy was the other mount declaring a
note and went with the card on 2026-09-28, so the property tabs are what keep
that path alive, through `renderPropertyScorecard`.

What that paragraph carried is still on the card, which is why dropping it
loses nothing material: coverage (`31 of 135 graded · 12 reported, not graded ·
92 awaiting a feed`) is in the eyebrow, the `reported, not graded` and
`awaiting a feed` markers are in the legend, and each cell's band, feed and
as-of date are on its own hover through `scCellTitle`. Three things were only
there — "most below-target KPIs", the Palma lease-up-override sentence and the
source workbook's filename — and those are a click away under `Data ↗`. The
load-failure path still reports through the eyebrow (`SCORECARD UNAVAILABLE`),
which is why it does not depend on a note block existing.

The `<h2>` moved inside a `.card-head` to make room for the select. That is
also what keeps the corner `Data ↗` link clear: `.card > h2` no longer matches
it and `.card-head` carries the 62px inset instead, so the two rules do not
double up — see the "Reserve the corner" CSS note. Verified with an overlap
probe at 1440 / 1100 / 900 / 700 / 390px.

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

It fills eight KPIs where the export column means what the KPI means — Leased %
(from `100 − Exposure Rate`, which matches the KPI's definition better than
`Occupancy Rate`), Closing Ratio, # of Renewals, % Increase, Total Deliquency,
AI Containment Rate, Avg First Response Time, and the T/L/A triple.

It filled **Trade-out %** as well until 2026-09-17, when that cell moved to the
Yardi lease tradeout report — see below. Nothing in this script changed: rule 1
already refuses a cell another feed owns, and `owned_by_other_feeds()` finds the
new one by reading every non-`bldg_` `*kpis` key in `measured[slug]`, which is
what "excluded by default rather than by remembering" buys.

Four rules keep it from overwriting better data or asserting what it cannot:

1. **It never takes a cell another feed owns** — with one exception since
   2026-09-29: `Total Deliquency` is the export's outright for every property
   it covers (`EXPORT_OWNS`), because its `Delinquency Rate` is the
   outstanding-balance figure (owner's call, closing B4; see the delinquency
   notes above). Palma, which the export does not cover, keeps the Drive AR
   report's rate. 335 Third's T/L/A
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

### The lease tradeout report

`LeaseTradeoutReport-<property>.XLS` in the Drive **`Historical Tradeout
Reports`** folder is the Yardi lease tradeout report, and since 2026-09-17 it is
what fills **`Trade-out %`** — the tile on the `Landing` tab and the
scorecard cell behind it. The Landing's first file covers 2024-08-01 to
2026-09-16: 247 new leases, each with the lease it replaced beside it.

It is the only feed with a trade-out **history**. The weekly leasing workbook
covers a fortnight, and the EliseAI building-metrics export publishes a rate
with no rows behind it at all, on a trailing month. This one carries the rows,
so the window is a choice the pipeline makes rather than whatever an export
happened to cover:

| Window | The Landing |
| --- | --- |
| T3 (**graded**) | **39.8%**, 26 leases, Jul–Sep 2026 |
| T6 | 32.5%, 68 leases |
| T12 | 30.7%, 121 leases |
| The whole file | 23.4%, 247 leases, Aug 2024 – Sep 2026 |

**Trailing three months, because that is the basis the published band was
written for.** The export this replaced was a trailing *one* — open item B6,
"a volatile month swings the grade more than the bands assume". B6 is closed for
this KPI and still open for Closing Ratio and # of Renewals, which the export
still fills. `TRADEOUT_WINDOW` in `populate_scorecard.py` is the one constant.

**The percentage is rent-weighted, never the mean of the per-lease rates.**
The report's own figure is total current effective rent over total previous
effective rent, and that is what is graded. The mean of its own `Trade Out %`
column is a different number — **70.1% against the weighted 23.4%** over the
same 247 leases — because a concession drives a *previous* effective rent toward
zero and the ratio explodes: one lease reads $86 previous against a $62,716
concession and prints 6,136%. A mean of ratios over a denominator that can
approach zero is not a rate. Both are published (`mean_pct` beside `pct`, and
`tradeout_mean` on the scorecard) so the two are on the record rather than
confused — the Trade-outs card's *other* feed reports a mean, and these are not
interchangeable.

Four things the parser is careful about, each of which publishes a number
rather than an error:

- **The header is two rows and half its names appear twice.** `Rate Type`,
  `Lease Start`, `Term`, `Prem`, `Gross Rent`, `Conc` and `Eff Rent` sit once
  under `Current Lease` and again under `Previous Lease`; only the merged
  banner above tells them apart, and only its first cell carries text. So the
  group row is forward-filled and joined to the column row. Matching the column
  row alone takes whichever came first and **inverts the sign of the whole
  report** — and a file read that way still ties out against itself.
- **Yardi names it `.XLS` and writes an `.xlsx`.** The bytes start `PK\x03\x04`.
  openpyxl refuses a path ending `.xls` before it looks at the file, so the
  parser reads the bytes and dispatches on the magic number; a genuine OLE2
  `.xls` is named as such rather than left to fail further in. The folder's
  `file_glob` is `*` for the same reason — neither extension describes it.
- **`(2.5%)` is a negative percentage**, parenthesised with the sign marker
  *outside* the percent sign, while the dollar column on the same row uses
  `-$78`. A pattern expecting `)` before `%` drops 42 of the 247 leases to
  `None` and averages only the positive ones, which is invisible.
- **Every figure ties out against the file's own `Grand Total:` row** on current
  effective rent, previous effective rent and trade-out dollars. A file that
  cannot reproduce its own total is refused — silently dropping a floor-plan
  section would understate the building. The `Subtotal:`/`Average:`/`Total:`
  rows are skipped by label first, so a subtotal is never read as a
  1,458-month lease.

**Leases accumulate; files do not supersede each other.** The window is chosen
at export time, so the next file's may be narrower, wider or offset, and taking
the newest whole would throw away every lease outside it. `store_lease_tradeout`
keys on `(unit, signed date, previous lease start)` — a unit can turn over twice
inside one window (102 does), so unit and date alone are not unique — and each
file's own period and tie-out stay in `files`, because a tie-out is a statement
about one export and stops meaning anything once several are merged.

The cell records under its own **`tradeout_`** family (registered in
`SC_FEED_PREFIXES`, `data.html`'s matching list and `SCD_DRIVE_FEEDS`), and
**both fill paths read the same published aggregate**, so like the rent roll's
loss to lease it has no last-run-wins race. Taking the cell also removes it from
every other family's `*kpis` list: `bldg_kpis` still *named* Trade-out % from
before this feed existed, and the page picks a cell's feed by whichever family
lists it — so the tile went on hovering "EliseAI building-metrics export · as of
2026-08-31" over a figure from a report of 2026-09-16. That is the over-report
this file warns about, fixed in the data rather than worked around on the page.

`scripts/test_lease_tradeout.py` holds it down — 47 fixture-free checks against
workbooks built in a temp dir. The six load-bearing guards (the forward-filled
header, the parenthesised negative, the magic-number open, the Grand Total
tie-out, the skipped subtotal rows and the narrowest-window-wins tagging behind
the per-lease table) were each verified by mutation; removing any one of them
fails a check. Tagging widest-last still ties out cumulatively and leaves every
`T3` filter empty, which is why that one has a check of its own. **Clear `__pycache__` between mutation runs** —
the same trap the leasing parsers' tests record.

Three tables on the data page, in this order, and the middle one is the answer
to "which leases is the tile made of":

| Table | Holds |
| --- | --- |
| `t-tradeout-<slug>` | every month, the three windows and the weighted-vs-mean note |
| **`t-tradeout-tile-<slug>`** | **the leases the graded window is made of, and nothing else** — 26 rows for The Landing |
| `t-tradeout-leases-<slug>` | every lease in the report, 247 of them, each tagged with the window it falls in |

The per-lease rows were in `data/<slug>/lease_tradeout.json` (tracked — a
trade-out report carries no resident) but nowhere on the page, so the tile's
39.8% could not be taken apart from the dashboard. `tradeout_lease_rows` in
`build_metrics.py` publishes them under `lease_tradeout.properties[].leases`.

**The tile table is its own table rather than a filter on the full one.** The
`Window` column makes the graded leases reachable, but only to a reader who
knows to filter — and "which leases is this figure made of" is the question the
tile raises, so it gets a table whose rows ARE the answer. Two things it does:

- **Which window is graded is read from `scorecard.json`'s own
  `tradeout_months`** — the field the tile itself reads — rather than fixed at
  3 in the page, so the table and the tile cannot come to disagree about what
  is being graded. If `TRADEOUT_WINDOW` moves to 6, the table follows. With
  `scorecard.json` unreadable the table is left out rather than guessed at, and
  the full one below still carries every lease with its window on it.
- **It recomputes the published figure from the rows on show and says whether
  they agree** — both the rate and the lease count. A table that claims to *be*
  a published figure has to be able to reproduce it; the note reads "these rows
  reproduce the published 39.8% and its lease count exactly" today, and names
  both figures if that ever stops being true rather than quietly showing a
  different number.

Three things about the rows themselves:

- **The `window` column is read back out of the published windows themselves,
  not recomputed from the dates.** `window()` counts a window in calendar
  months present in the file, so a second implementation of that rule here
  would eventually tag a lease into a window whose own total does not contain
  it. Each lease carries the *narrowest* window it falls in, which is what the
  tile table above is cut on — verified in the browser: 26 rows, matching the
  published T3 count and reproducing its 39.8%, and 26/68/121 cumulatively
  across T3/T6/T12.
- **The published row is a strict subset of the stored one**, built key by key
  rather than by copying and deleting, so a field added to the parse cannot
  arrive on the page by default.
- **$/sqft is derived on the page, not published.** It is effective rent over
  sqft, and a stored copy is a second place for it to be wrong.

One page fix came with it. `sourceOf` in `data.html` built the `From:` line one
entry per matched *pattern*, so a flow naming both a family and a narrower one
inside it (`t-tradeout-*` and `t-tradeout-leases-*`) printed the same report
twice. It dedupes by flow id now; tables genuinely fed by several flows still
list them all (`t-sc-measured` shows five).

**It feeds the Trade-outs card too, not just the tile.** That card's teal series
was the weekly leasing workbook, which carries **one week per file** — four weeks
on file meant four leases in two months, two lonely bars against three years of
renewal offers. It is the tradeout report's 26 months now, and the card fills.

| | Weekly workbook | Tradeout report |
| --- | --- | --- |
| New leases on the 24-month axis | 4, in 2 months | **231, in 24 months** |
| Average new-lease trade-out | 71.1% | **25.5%** |

The two also *measure* slightly differently, which is why the card says so: the
report works on **effective** rent, net of concessions on both the new lease and
the one it replaced, where the workbook compares rent to prior rate. A previous
lease bought down by a concession therefore shows a larger trade-out here.

**Both series moved to rent-weighted**, and the plain mean went to the tooltip —
the swap of what the card used to do. The report's own percentage is the
weighted one, so the card and the tile now grade the same statistic; and the mean
cannot carry this axis, since Nov 2024 reads 550.9% as a mean against 55.7%
weighted. On the renewal side the two agree to within half a point every month,
so that series moved in name only.

**Weighting protects a month only when there are enough leases in it.** Sep 2026
reads **149%** on two leases in a half month — the report's window ends on the
16th — and one of those two replaced a lease whose $3,678 gross carried a $2,207
concession, i.e. $1,471 effective. That one lease carries the month. The bar is
drawn rather than capped or dropped, because it is the report's own arithmetic
and the tile's T3 window includes it; the footnote names it, computed against the
series' own median and lease counts so it cannot go stale as months arrive. The
same note names the part month.

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
Selected Properties" and names no building, so it is stored against
`report_map.json`'s `unattributed_property` — **Palma**, the owner's answer of
2026-09-21 (A6). That is a fallback for a file that names nothing, not an
override: a file whose sections name their buildings still routes by those
names.

**Until 2026-10-05 it was stored nowhere, for three reasons stacked on each
other**, each of which alone was enough:

- **The parser read the projection table as a second building.** Below the
  concession table's own `Totals` row the export carries a footnote and then a
  different table, `Projection by Unit` — the same units with one column per
  future month. Walked as a section it became a building called "Projection by
  Unit" whose October–December burn landed in the money columns. That is the
  original misreading behind "For Selected Properties means several
  buildings"; the 2026-08-10 file is one building, **−$27,495** of recurring
  concessions across 19 units, tying to its own `Totals` row. (A6 had recorded
  −$54,990, exactly twice that; how is not reproducible from here, and the
  table plus the projection would have read −$29,328.) The walk now stops at that heading (`PROJECTION_HEADING`) and
  records the stop in `checks`.
- **So the file never counted as unattributed** — one section carried a label —
  and the fallback was never consulted.
- **And had it been, `process_manifest` dropped it anyway.** The `[warn]
  unknown property code … skipping` and its `continue` sat one level too far
  out, so they ran after a successful `[attributed]` line too. They now run only
  for a file that names a property nobody registered, and a section with no
  heading at all in an unattributed file no longer logs as an "unknown code".

`test_funnel_and_concessions.py` section 7 builds the real layout with invented
units and drives it through `process_manifest` to `data/palma/concessions.json`;
each of the three was verified by mutation. Nothing on the dashboard draws the
store yet, so the flow stays `partial`.

### Occupancy on the Unit Inventory bars

**The bars are cut on beds AND baths** since 2026-09-30, by request. Bedrooms
alone is not the inventory: The Landing has **11 two-bed units with one bath
and 97 with two**, so the largest bar on the card was two products at different
rents drawn as one. Seven bars now where there were three, and the wrapper
grows with them rather than squeezing them into the three bars' 210px.

The bedroom reading is not lost, and that matters because the bedroom is what
the market quotes in and what the whole Market Comps build-up is cut on: each
bar's hover closes with its share of its bedroom type (`97 of the 111 2-bed
units in the building`), rolled up **from the bars' own totals** rather than
from the directory, so it cannot disagree with the bar it describes. A bedroom
with only one bath variant gets no such line rather than one saying 11 of 11.
The line and the bedroom totals behind it reproduce the old bars exactly —
136 / 111 / 16.

`planLabel`, `planShort`, `planKey`, `planKeyLabel`, `planKeyCmp` and
`planKeyBeds` sit beside `fmPct` because **two cards draw a floorplan** — these
bars and Largest Unit Gaps' rows — and spelling it in two places would
eventually have one calling a plan a 2-bed and the other a 2x2. Three things
they are careful about, and only the first is exercised by The Landing's own
data:

- **A half bath is real** (four of The Landing's plans), so `baths` is a float
  and the trailing `.0` is dropped rather than printed.
- **A missing half is dropped, not invented.** The parser flags a plan whose
  rows disagree on baths and leaves it `null`; that plan reads `2 bed`, not
  `2 bed · 0 bath`, and only a plan with neither is `Unknown`. Zero bedrooms is
  a studio, tested with `Number(b) === 0` rather than `!b` so a null never
  lands there.
- **The keys are strings and the comparator subtracts**, so studios sort first
  and unknown last, fewest baths first inside a bedroom — and a ten-bed plan
  would not sort between 1 and 2 the way `localeCompare` puts it.

The `Beds` column on **Largest Unit Gaps** reads `2 BR / 2 BA` for the same
reason; the baths were on the hover only. Its fixed column widths are
content-derived and sum to 100, so the wider column took five points back off
the money and date columns — checked for overflow at 1440 / 1100 / 900 / 700 /
390px, where only the painted text tells you, since `table-layout: fixed`
leaves the boxes the width the rule gives them either way.

The card's bars are units by bedroom and bath type, each one stacked vacant (teal) from
the axis then leased (amber), so the two segments partition the bar rather than
adding to it. Vacant is first in `datasets` and that is the whole of what puts
it on the left — Chart.js stacks in dataset order. Hovering a segment gives its
count, its share of that bedroom type, and the group's whole
leased/vacant/occupied line. The Landing reads 97.7% leased —
1 bed 135/2, 2 bed 106/4, 3 bed 16/0.

The column beside the bars is the **unit count per bedroom type** and nothing
else — 137 / 110 / 16 — as of 2026-09-14. It is built from the same keys and the
same totals the chart draws, so a figure there cannot disagree with the bar it
sits next to, and a studio or an undescribed plan gets a line the day it gets a
bar. It replaced a five-stat block (apartments, leased %, floorplans, average
sqft, average directory rent). Nothing was lost from the card: the apartment and
floorplan counts are in the eyebrow, and the leased share is on the hover and in
the table's own Leased and Vacant columns.

It takes two reports, because neither can draw it alone. The rent roll knows
which units are let but not how many bedrooms a floorplan has; the unit
directory knows what a floorplan is and nothing about who is in it. So
`rent_roll_summary` publishes `by_plan` — `{units, leased, vacant}` per plan
code — and the page rolls those onto the directory's beds and baths.

`by_plan` is **counts only**, which is what lets it leave `data/`. The roll
itself is unit level and arrives with resident names, so `rent_roll.json` stays
gitignored; a plan with one unit says that plan has one unit, which the
directory already says in public.

**The roll is its own census, not an overlay on the directory's.** The two count
different things and always will:

| Source | Counts |
| --- | --- |
| Unit directory | Every row the export lists — 265 for The Landing, including two Yardi waitlist placeholders and a 56,120 sf `The Landing - PDR` record under `p0005640` with no floorplan and no rent |
| Rent roll | Leasable apartments — 263 |

Reconciling them into one bar would mean deciding which is wrong, so each bar is
the roll's own count for its bedroom type — leased plus vacant equals the bar by
construction — and the directory supplies only the bedrooms. The difference is
printed in the note rather than absorbed. A plan on the roll the directory has
never described lands in an `Unknown` bar and is **named**, because that is a
join failure worth fixing rather than a category. With no roll at all the bars
are the directory's plain count and the card says so.

**Leased is the same `occupied` flag the rest of the block uses** — a resident
code *and* a non-zero rent — so a unit on notice or holding over counts as
leased: it has someone in it. That is occupancy, not risk; holdover and
month-to-month remain a different question and stay in `SCD_MISSING`.

One fix came with it. `parse_rent_roll._property` searched only the first 30
rows, and `RentRoll09_11_2026.xlsx` says just "For Selected Properties" at the
top and names the buildings in a summary block at **row 278**, below every unit.
So the roll parsed and then routed nowhere — `[warn] unknown property code
'None' … skipping` — and a pipeline run left the whole feed untouched, silently
reusing whatever `metrics.json` already held. The header is still searched
first; the rest of the sheet is a fallback. That roll names two codes
(`p0005611` and `The Landing - PDR(p0005640)`); the first wins, which is the
residential one, and the unit count tying out against the report's own Total row
is what would catch it if that ever stopped being true.

The page-side helpers are checked by driving them directly in node rather
than by a fixture — nineteen cases covering the studio, half-bath, missing-half
and sort branches The Landing's own data never reaches.
`scripts/test_occupancy.py` holds the pipeline side down — 28 checks against a
roll and a directory built in a temp dir, no network and no fixtures. The ones that matter
are the invisible failures: a vacant unit carrying a market rent must not count
as leased, a unit on notice must, nothing unit level may reach the published
block, a plan the directory cannot describe must be named rather than dropped,
and a roll naming its property below the unit rows must still route.

### The two leasing parsers

`parse_daily_leasing.py` and `parse_renewal_tracker.py` were written against
real exports on 2026-09-11, and both publish to the **Trade-outs card** on the
`Landing` tab through the `leasing` block in `metrics.json`.

**`parse_daily_leasing`** reads the NEW LEASES block on the `Weekly_Leases`
sheet into per-lease trade-outs, and `store_daily_leasing` accumulates one entry
per week in `data/<slug>/leasing_detail.json`, keyed on the week-ending date —
the filer keeps several copies of the same week, so re-processing must replace
rather than double. Three things it is careful about:

- **The file names its property in three places and they disagree.** Chorus's
  2026-09-09 copy says "Chorus / 416 units" in the `Weekly_Leases` header and
  "The Landing / 263 units" on its `Information` sheet, which is a template
  field nobody updated. Order of trust: the filename, then the sheet header,
  then `Information` — and a disagreement is reported, never silently resolved.
  The Landing's own file needs the second source, because its name carries no
  property at all.
- **The week a file covers comes from its FILENAME, not its own cell.** The
  sheet's "Week Ending" value drifts between snapshots of one week — the
  2026-08-31 and 2026-09-08 copies of "Week Ending 9.7.26" say 2026-09-07 and
  2026-09-06 — and `store_daily_leasing` keys on it, so reading the cell filed
  one week under two keys and counted it twice. The label is the LAST date in
  the name (the week, since the filer prefixes its arrival date at the front;
  for Chorus's `09.07.2026- 09.13.2026-` range that is the end of it), except
  where the only date IS that prefix, which says nothing about the week and
  hands back to the sheet. The sheet's answer is kept in `week_ending_sheet`
  and a disagreement is reported.
- **The blocks below the leases overlap their columns.** A cancellation row puts
  its scheduled move-in date where a lease's rent goes, and the WEEKLY AVERAGE
  row carries a real number there. The `STOP` markers are the primary guard; a
  numeric-type check on the rent is the backstop that stops a stray date from
  crashing a pipeline run instead of reporting one bad row.
- **Every lease is checked against the report's own arithmetic** — rent less
  prior rate must equal the trade-out it prints, and the percentage must equal
  that over the prior rate.

**`parse_renewal_tracker`** reads all 36 month sheets plus `MTM`. The hard part
is that the layout changed between vintages and **the same label means different
things**: `BEST OFFER $` is the offer *difference* on the May 2025 sheet
(4932 × 9.9% = 488) and the offered *rate* on June 2025's (4326 × 1.0499 =
4542), one month apart. So the offered rent is resolved by **arithmetic, not by
label** — a value near the current rent is a rate, one near zero is a difference
— and a row that resolves to neither is left out rather than published as an
increase that is off by a whole rent. Two more things:

- **Money is text on the 2025 sheets** (`'$4,326'`), so a numeric-only read sees
  a month of renewals as an empty month.
- **A sheet whose header cannot be matched is recorded as unread**, never read
  with the wrong columns, and the skipped sheets are surfaced as a problem.
- **A month can be two sheets.** From the 2026-09-15 copy the Landing splits
  December 2026 and January 2027 by lease end — `December First 2026` to about
  the 15th, `December Second 2026 ` (trailing space) after it — with a
  month sheet's own columns and no unit on both. They are **joined** into one
  month (`halves` on the point, both titles in `sheet`), not weighed against
  each other as a duplicated sheet is: taking the fuller half would drop the
  other half's offers. A month with one half on file is published from it and
  flagged as short. Until 2026-10-05 the halves read as "not a month sheet",
  which cost December's offers (16 on the 09-21 copy, against the 6 the 09-08
  copy's single sheet carried) and made the copy look a month older than it was
  — see *A snapshot report never walks backwards*.

The monthly offer counts tie out against the 2026-09-08 weekly email's own
renewal table — 18 / 7 / 13 / 6 for September through December — which is an
independent check on the whole chain.

**The card averages both sides the same way, which the workbook-fed one could
not.** The removed tab's Trade-outs card drew its new-lease side as a plain mean
and its renewal side rent-weighted — its own footnote said the workbook's offer data
"carry no per-renewal rows to average". `parse_renewal_tracker` reads those rows,
so `mean_increase` sits beside `wtd_increase` on every month and the Drive card
plots one mean against another, with the weighted figure on the tooltip. Two
things the card is careful about: the axis ends at the newest month either feed
reports having *happened*, because renewal offers run ahead of it (December's
are already out) and a forward offer must not drag the window past the data
behind it; and each stat is scoped to the chart's own window with the number of
months in its label, because the feeds cover wildly different ground — two weeks
of new leases against three years of offers — and an unscoped count reads "434
renewal offers" beside "3 new leases".

The Landing reads **82.8%** mean new-lease trade-out against **+6.0%** mean
renewal increase: a turned unit captures roughly ten times what a renewal does,
which is the comparison the card exists to make. Capture at signing is absent
and the card says so — the leasing workbook carries no market rent at signing.

`scripts/test_leasing_and_renewal.py` holds both down: 41 checks against
workbooks built in a temp dir, no fixtures and no network, since the real files
carry names and are gitignored. The five load-bearing guards — the STOP
markers, the arithmetic offer resolution, the money coercion, the filename week
label and the arrival-prefix exception — were each verified by mutation, as
were the half-month join and its recognition (2026-10-05), and
two were found to be *untested* on the first attempt because the synthetic rows
did not reproduce the real column overlap. **Clear `__pycache__` between
mutation runs**: restoring a file with `cp` can leave an older mtime, and
Python then keeps the mutated bytecode and reports failures against code that
is no longer on disk.

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

### The Operating Summary's two controls

The card used to carry three toggles — Prev month / T3 / T12 — each swapping in
one comparison against the current month, with the current month fixed. Both
sides are a choice now:

- a **Comparison:** select on the **left of the card**, under the eyebrow, for
  what the card is read from — **Current Month or T3**;
- the **clickable boxes on the right** for what that is measured against, and
  **which boxes exist follows the select**.

| Selected | Boxes offered |
| --- | --- |
| Current Month | Prev Month, T3, T12 |
| T3 | T6, T12 |

**A window is never set against one it contains.** T3 is May–Jul, so measuring
it against the current month would put a quarter beside its own last third and
read the overlap as a variance — so T3's boxes are the two windows that extend
past it. Current Month has no such problem: Prev Month is the month before, not
inside it, so it keeps all three.

`CHOICES` is `["cm", "t3"]`; T6 and T12 are comparison targets only, since
reading the card from the year round would only restate the same variances
inverted.

Switching the select **keeps the comparison where the new set still offers it** —
Current Month with T12 showing stays on T12 when it becomes T3. Prev Month is
not in T3's set, so that pair falls to T6.

**Every pair is an annual run rate — each period's own total scaled to twelve
months — except Current Month against Prev Month**, which is left as reported.
Both headings carry their own multiplier, because either side can be scaled and
a figure twelve times August under a header reading `Current Month (Aug 26)`
would be read as August:

| Pair | Left column | Right column |
| --- | --- | --- |
| Current Month vs Prev Month | Aug as reported | Jul as reported |
| Current Month vs T3 | `Current Month (Aug 26) ×12` | `T3 (Jun 26–Aug 26) ×4` |
| Current Month vs T12 | `Current Month (Aug 26) ×12` | `T12 (Sep 25–Aug 26)` |
| T3 vs T6 | `T3 (Jun 26–Aug 26) ×4` | `T6 (Mar 26–Aug 26) ×2` |
| T3 vs T12 | `T3 (Jun 26–Aug 26) ×4` | `T12 (Sep 25–Aug 26)` |

Annualizing is what lets windows of different lengths sit side by side: a month
against a quarter is otherwise three times the period as well as a different
one, and the variance reads as both at once. The exception is the pair that
needs none of it — a month against the month before is already like for like,
and the actual month-over-month totals are what that pair is read for.

**The variance percentages do not depend on this at all.** Scaling both columns
by the same factor cancels, so only the magnitudes and the `Variance $` column
move; the shape of the card is unchanged. Two of the five pairs were already
annualized (both T12 comparisons cover twelve months by definition) and the
month-against-month pair is untouched, so the owner's 2026-09-17 call moved
exactly two: Current Month vs T3 and T3 vs T6.

`scaling(base, cmp)` is the one function that decides it, returning the target
window and a multiplier per column. The table and the note under it both read
it, so they cannot describe different arithmetic — which they could when each
recomputed the multiplier for itself.

**One caveat the card cannot fix.** An accrual statement books reversals in the
month it finds them, and Aug 2026 carries a −$118,781 tax true-up: total
expenses read $48,572 for that month against $365,241 in July. Annualized that
is $583k against a T3 of $2.99M — an 80.5% "saving" painted green, which is a
timing difference and not money unspent. The percentage was the same before
this change; annualizing only makes the dollar figure larger. Budget vs Actual
on the Portfolio tab names the reversal months for the same reason.

Four data columns: the two periods, then the variance in **dollars** and in
**percent**. A percentage alone hides the size of the thing — 15% on the expense
row is $55k over a month and $660k over a year. Both are coloured by
favourability rather than by sign, so less expense is green, and both use the
same typographic minus, since they sit in adjacent columns at 15px and a hyphen
beside a minus is visible.

A window is **offered only when the series holds it** — `avail()` checks the
window starts at or after the first month rather than clamping, and it filters
the boxes as well as the select. Clamping would print "T12" over eight months of
data, which is the kind of label that gets quoted. Twelve months today, so both
choices and every box are live; a shorter run simply offers fewer.

**The card ends at the table.** The paragraph under it — which pair is being
compared, which windows the buttons offer, what the scaling is and how the
variance is coloured — came off 2026-09-29, by request. `ids.note` is optional
now, the same way `renderScorecard`'s is: a mount that does not declare one
renders without it, and `reserveTallest` is not asked to hold room for a note
that is not there. `noteFor` stays, since it is the prose a mount declaring a
note would get, and `headOf` already puts each column's window and multiplier
on the column itself — which is where the note's load-bearing half was.

`renderOpSummary` was shared with the workbook-fed Landing tab until that came
off on 2026-09-18, so both cards always changed together. It is still written to
serve any mount rather than one card.

## The T12 statement's two expense anchors

The 12-month accrual statement carries more than one expense total, and which
one a published figure used has to be recorded rather than inferred:

| Anchor | Row |
| --- | --- |
| `519999-9999` (jpm) / `5999-9998` (align) | TOTAL OPERATING EXPENSES / TOTAL OPERATING EXPENSE RECOVERABLE |
| `549999-9999` (jpm) | TOTAL EXPENSES — operating plus the non-operating 52xxxx region |

**Everything the pipeline publishes now reads the outer one**: the Operating
Summary card (the top box on the Landing tab, moved 2026-09-03), the Expense
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
expenses. That is why the basis is published per property, and why the Expense
Ratio card carries each line's own on its tooltip and in its footnote rather
than printing one basis over both. Until 2026-09-17 that card showed one
property at a time and the eyebrow carried the selected one's basis; the
properties are toggles now, so the eyebrow flags the disagreement
(`TWO EXPENSE BASES`) and the per-property prose moved down to the lines
themselves.

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

## Expense Load & NOI (Portfolio tab)

**The Landing tab's Expense Load & NOI card, across the portfolio** (by request,
2026-09-30). A **Measure:** select in the card head picks one of that card's
three readings — **NOI margin**, **Expense ratio** or **Controllable expense /
door** — and a box per building picks whose lines are drawn. It was the
`Expense Ratio` card and still opens on that measure; the id stays `cExpRatio`,
for the reason the Landing tab's `d-` ids stay — `lineage.json`'s card index and
`data.html`'s links name it.

**One measure at a time, not the Landing card's three at once.** Two are shares
of revenue and the third is dollars a door, which is why that card needs a
second axis for it; several buildings on two axes is a chart nobody can read.

Every line is the Landing card's own arithmetic, so a building reads the same on
both tabs:

| Measure | Line | Figure on the left | The Landing | Palma |
| --- | --- | --- | --- | --- |
| NOI margin | `noi / revenue`, the stitched `monthly_pl` run | trailing twelve of that series | **69.3%** | 43.9% |
| Expense ratio (default) | `opex / revenue`, the same run | the block's own published `ratio_t12` | **30.7%** | 56.1% |
| Controllable expense / door | `controllableMonthly()` over the unit directory's `residential_units`, $ a month | twelve months per door — a year | **$6,977** | no door count |

`controllableMonthly()` sits beside `NOT_CONTROLLABLE`, and **both Expense Load
& NOI cards call it**, so what a door costs is one calculation wherever it is
drawn. The Landing tab's own copy of the loop came out with this change; its
line and its `$6,757` tile are unchanged, since the arithmetic is the same in
the same order.

**The per-door figure is not the scorecard's, and the note says so.** The card's
$6,977 is Sep 25–Aug 26 added up per door; `Controllable OpEx/Unit` grades
$6,757, the newest month ×12. Both are per door per year, over different
windows. A run shorter than twelve months is labelled `T<n>` on all three
measures, and on the per-door figure it is also annualised, since seven months
of cost beside twelve would read as a cheaper building.

**The boxes are the portfolio** — `metrics.json`'s `properties` block, the
rule Budget vs Actual's property row follows — not whichever buildings a feed
happens to cover. A building the measure cannot draw keeps its box, struck
through and inert, with the reason on hover, and the note groups the reasons
rather than repeating one per building:

| Measure | Drawn today | Struck through |
| --- | --- | --- |
| NOI margin, Expense ratio | The Landing, Palma | Chorus, Madelon, 335 Third Street — no 12-month statement on file |
| Controllable / door | The Landing | Palma — no door count (the unit directory does not list it); Chorus — no statement; Madelon, 335 Third — neither |

Palma will not gain a door count by itself: the unit directory is a legacy
report that will never change (C5), so that box stays struck through until a
unit count comes from somewhere else.

Three things about how the boxes behave:

- **Rebuilt on every switch, in one fixed order** — the buildings any measure
  can draw first, each group in portfolio order — so a switch changes which
  boxes are live and never moves one.
- **A building switched off stays off across switches**, including through a
  measure where its box is struck through. A struck-through box shows unticked
  and filters nothing, since it has no line to hide.
- **Colour follows the building, never the measure.** A building some measure
  can draw wears its `propColor` on all three, struck through or not; one no
  measure can draw wears the page's muted ink rather than a series colour it
  has no line in.

**Every box off keeps a frame** rather than collapsing to a 0–1% axis: the scale
last drawn, or, when a switch arrives with everything already off, the range of
every line the measure could show. Chart.js swaps `opts.scales` for its own
merged copy on construction, and that copy is the object to change — the same
thing the Rental Rates overlays rely on.

**The select holds still.** The eyebrow beside it changes length with the
measure, so the heading block has a zero flex basis (`#cExpRatio .card-head >
:first-child`, the deep dive's fix for its jumping period toggle), and a select
is as wide as its widest option whichever is chosen.

A measure no building can draw shows the page's empty state with every reason
in the note, and a `metrics.json` with no statement data at all hides the
select and says so, rather than leaving a blank canvas.

### What it kept from the Expense Ratio card

**The line has been `monthly_pl` since 2026-09-17, not the `expense_ratio`
block's own series.** That block's `trend_values` are one point per
*statement*, so The Landing's line was **two points** where its P&L carries
thirteen months, and it lengthened only when a new file landed rather than as
the stitch grows. Checked before switching, and this is what makes it a change
of *source* rather than of measurement: the ratio off `monthly_pl` reproduces
the block's published `latest_monthly_ratio` **to the tenth on every
overlapping month, for both properties**. The Landing simply gains the
thirteenth month (Aug 25, 32.6%).

`test_monthly_pl.py` pins that agreement, because the expense-ratio view shows
one store's line beside another store's headline figure: if the two stopped
describing the same expense row, the line would disagree with the number next
to it and nothing on the page would say so. Two checks, both verified by
mutation — the published monthly ratio must equal `monthly_pl`'s own
opex/revenue, and the two stores must record the same `expense_scope` and
`expense_anchor`.

**The T12 figures are the headline, one per building shown,** because a single
accrual month swings hard: The Landing's expense ratio reads **3.8% for Aug 26**
on the tax reversal and **52.9% for Apr 26** on the annual assessment, against a
T12 of 30.7%, and its NOI margin reads 96.2% for Aug 26 against 69.3%. The note
says so and points at the figures rather than at the line.

Everything the **Expense Trend** section below says about the union month axis,
the `null`-not-zero gaps, `spanGaps`, the mixed-anchor flag and the typographic
minus applies here for the same reasons. The axis is the union over the
buildings the *measure* can draw, ticked or not, so it holds still while boxes
change, and it differs between measures only where their data does: the
per-door line is the newest statement's twelve months, Sep 25–Aug 26, where the
P&L lines run Jul 25–Aug 26. **The anchor disagreement reaches all three
measures.** The Landing's expense row is total expenses (`549999-9999`) and
Palma's is recoverable opex, so Palma's NOI margin is taken after a different
row too — the `not comparable across account trees` point made under **The T12
statement's two expense anchors**. The eyebrow flags it (`TWO EXPENSE BASES`),
each tooltip line names its own row where the lines disagree, and the note
gives each building's basis.

**One colour per property across the tab.** `propColor` keys the line colour on
the slug and is seeded from `monthly_pl` before any card mounts, so a building
is the same colour here and on Expense Trend.

The card's `Data ↗` keeps `t-expratio-*` as its primary — the figures it opens
on — and its tables are the Landing card's list plus that one: `t-monthlypl-*`
for the lines, `t-buckets-*` and `t-unitdir-*` for the per-door view. The unit
directory's flow now declares **both** Expense Load & NOI cards, with no primary
and their tables given explicitly (left out, each would inherit that flow's
`t-l-units`, which is the workbook's unit table). It did not declare the
Landing one before either, though that card has always divided by the
directory's door count.

Verified in the browser at 1440 / 1100 / 900 / 700 / 390px: every figure above
against a reproduction from `metrics.json`, the boxes through every switch, no
sideways scroll and no overlap with the corner link at any width, and every tab
opening with no page error. The branches today's data never reaches — no
`properties` block, a one-building portfolio (no grid), no directory, a
seven-month run, a missing published T12, a statement that stops naming one of
the four exclusions, and no data at all — were each driven by serving a
doctored `metrics.json` to the real page.

## Expense Trend (Portfolio tab)

One line per property, over the union of their statement months, each property
selectable on a checkbox above the chart. Full width since 2026-09-17: it was
the left half of a row shared with `PSF vs Other Properties`, and removing that
card left it alone against an empty half. Fourteen monthly ticks were crowded
at half width anyway. Until 2026-09-17 the card was three
hand-typed expense categories for **one** building — Marketing, Utilities and
General & Admin, with taxes and insurance left out so monthly movement stayed
visible — and it moved only when someone edited `metrics.json`. It is now
derived, and `expense_trend` came off the `manual` list on the data-flow page
with it.

The series is `monthly_pl`'s own `opex`, not a second reading of the statement:
`expense_trend()` in `build_metrics.py` is handed the same `pl_props` the
Operating Summary is published from, so a month on this card and the same month
on that one cannot disagree.

Three things it is careful about, and each would be invisible in the numbers:

- **The axis is the union of the properties' months, keyed on `YYYY-MM`.** The
  statements do not cover the same window — The Landing's runs Aug 25–Aug 26
  and Palma's Jul 25–Jun 26 — so aligning the series by position would plot
  Palma's July against The Landing's August and draw the one-month offset as a
  swing in spending. A property with no statement for a month gets `null`, not
  zero, and `spanGaps` stays false so the line stops rather than being drawn
  across the gap.
- **The labels carry the year.** `monthly_pl`'s own labels are the bare month,
  which is unambiguous over one statement's twelve columns. This axis is
  fourteen months across two calendar years and holds two Julys, so it reads
  `Jul 25` / `Jul 26`. The data page's table publishes the month **key** in its
  own column for the same reason.
- **The lines are not all the same expense row.** The Landing's is total
  expenses (`549999-9999`); Palma's is recoverable operating opex, because the
  Align tree has no counterpart to that row — see **The T12 statement's two
  expense anchors** above. `mixed_scope` is the pipeline saying so, and the
  card puts it in the eyebrow (`TWO EXPENSE BASES`), on every tooltip line and
  in the footnote, rather than printing one basis over two different expense
  loads. It is the same trap the Expense Load & NOI card below it carries a
  per-property basis for.

**The card names its own outliers, and they are mostly timing.** An accrual
statement books true-ups and reversals in the month it finds them, so the
biggest features on this chart are not spending: The Landing reads **$624k for
Apr 26** (the annual tax assessment lands in one month) and **$49k for Aug 26**
(its reversal — the same $48,572 the Budget vs Actual note describes), against
a $365k run rate; Palma runs **−$94k in Jun 26**. Without a word about them the
chart reads as a collapse and a blowout. The footnote is computed from the
series against **each line's own median** — a shared threshold would flag every
month of the smaller building — so it cannot go stale as months arrive, and it
names the months without asserting a cause this card has not checked.

Two smaller things:

- **The grid hides itself below two properties.** A control that cannot change
  anything is worse than no control — the same rule the Budget vs Actual basket
  row follows. Unticking everything is allowed and the footnote says so rather
  than leaving an empty chart unexplained.
- **The minus is the typographic one in all three places it can appear** — the
  y ticks, the tooltip and the footnote. A reversal month is genuinely negative
  here, and Chart.js's default tick prints a hyphen, which would sit on the
  same card as the footnote's minus.

`scripts/test_monthly_pl.py` covers it — the union axis, null-not-zero, the
per-line scope and the mixed flag. The two load-bearing ones were verified by
mutation: aligning by position instead of by month key fails the alignment and
the null checks, and never flagging a mixed anchor fails the flag check.

## Budget vs Actual (Portfolio tab)

The Portfolio tab's `Budget vs Actual` card has **two views**, on a `Total` /
`Categories` toggle in its head, both over the statement's trailing twelve
months.

### Total — the default

Two lines over the whole expense basket: the plan **dashed and muted**, the
actual **solid in the page's accent**. The plan is a yardstick rather than a
series, which is the same idiom the Categories view's net line uses.

Where the category boxes sit in the other view, Total lists **every month's
variance and the two totals that get quoted**:

| Summary | Window | The Landing |
| --- | --- | --- |
| **YTD** | calendar year to date — Jan through the statement's newest month | **−$99k**, −3.3% of $3.04M |
| **T12** | the window the chart draws, Sep–Aug | **−$44k**, −1.0% of $4.45M |

Both are on the card because they are **different windows, not two goes at one
figure** — and YTD is deliberately the scorecard's own window, so the two are
comparable once you also match the basket (the KPI takes the controllable one;
see the presets below).

The monthly figures are coloured by **favourability, not by sign** — over plan
red, under plan green — the way the Operating Summary's variance columns are.
On expense, less than planned is the good direction whatever the arithmetic
sign.

**Total always draws every category.** The basket presets are a Categories-view
control, and a "total" that quietly left four groups out would not be one — so
the note reads it as the whole basket whatever `hidden` happens to hold from a
previous visit to the other view.

### Categories

One bar a month, actual less plan, **stacked into the same Align-tree
categories the Expense Deep Dive uses** and painted in the same colours, so a
reader can move between the two cards without relearning which colour is what.
Above the line is an overspend, below it an underspend.

The card drew the plan and the actual as two bars side by side until
2026-09-16, and was variance-only until the Total view arrived later the same
day. Twenty-four bars a screen answered "how big is this building" — which the
Expense Deep Dive already answers — where the difference answers "how far off
the plan was it", which nothing else did. Total is the default because that is
the card's first question; Categories is where you go once the answer is yes
and the next one is which category did it.

A dashed **net line** rides over the bars. A month with offsetting misses
stacks positives up and negatives down and leaves its net in neither
direction, so without the line the card cannot answer "did this month run
over" at a glance. The net **follows the checkbox grid** rather than staying
on the whole basket: unticking Taxes and leaving a line drawn through
$270k of tax reversal would put it a screen away from the bars it claims to
summarise.

The shared palette is a real shared thing rather than two copies:
`BUCKET_PAL`, `bucketColor` and `bucketOrder` in `index.html` are what both
cards call. The order is the deep dive's own — largest first, `Other` last,
computed once from the actuals — so toggling categories never re-sorts and
nothing is repainted under the reader. A category only the *budget* names is
appended after and steps past any hue already spoken for.

### The property row

A **row of property toggles** sits under the card head — one `.tog` button per
building **in the portfolio**, single-select, matching the `Total` /
`Categories` pair above it rather than the checkbox grids the Expense Load & NOI
and Expense Trend cards use. Those two overlay several properties on one axis;
this card cannot, because both its views are one building at a time (two lines,
or category bars that would be meaningless stacked across buildings) and the
variance list and note are that building's own figures. So it switches rather
than overlays, and the eyebrow leads with the property name once there is more
than one — `PLAN vs ACTUAL · SEP 25–AUG 26` does not say whose.

It replaced a `<select>` that was **hidden whenever fewer than two properties
had both halves** — which is every day so far, so the card has never offered a
property control at all.

**A building the card cannot draw is listed and disabled, not left out.** Palma
has a 12-month statement and no budget on file, so it can never be drawn here;
leaving it off the row states nothing, while a struck-through `PALMA` whose
tooltip reads `no budget on file` is the answer to "why is this card showing
one building". The note carries the same sentence in prose, and names the Drive
`Budgets` folder as the fix. That is why the row does not follow the
hides-below-two rule the basket presets and the Expense Trend grid do: those
hide because they have nothing to *say*, and this one does.

The row hides itself only when there is a single property in total — then it
has neither anything to switch nor anything to explain.

**The row is the portfolio, not this card's own two feeds.** It was the union
of the buildings with actuals and those with plans until 2026-09-29, which
listed The Landing and Palma and left **Chorus, Madelon and 335 Third out
entirely** — so a reader saw a two-building portfolio rather than three
buildings waiting on a report. It reads `metrics.json`'s **`properties`** block
now: the active entries of `config/properties.json`, which is the one place the
portfolio is defined. Five buttons today, one drawable.

Active only. The master carries 23 inactive entries — former Align properties
— and a row of 28 buttons where 27 are disabled answers nothing. The union is
kept as the fallback for a `metrics.json` written before the block existed:
fewer buttons is a worse row, an empty one is a broken card.

Each undrawable button says **which half is missing**, and both where both are:
`no budget on file`, `no 12-month statement to measure its plan against`, or
`no 12-month statement or budget on file`. Drawable ones sort first, then by
name.

The note **groups the undrawable by reason** rather than listing one clause per
building, because the row is now the whole portfolio and most of it can be
undrawable at once — naming the same reason four times buries the one building
whose reason differs. It names both Drive folders that would fix it, `Budgets`
and `T12 Expenses`, and only the ones that apply.

Verified by injecting a synthetic second budget into a copy of `metrics.json`
and driving the page: the toggle switches the chart, the variance list, the
eyebrow and the note, a view switch stays on the selected property, and
switching back restores the first. The variance list does go stale while
Categories is showing — it is `hidden` there and rebuilt on the way back to
Total, so it is never visible stale, which was checked rather than assumed.

### The two basket presets

A **Basket** row sits above the per-category grid with two boxes —
**Controllable** and **Non-controllable** — each switching its whole group of
categories. They are the same split the scorecard's `Budget Variance %` grades
on, off the same shared `NOT_CONTROLLABLE`, so "controllable" means one thing
on this page.

They are worth having because **the two baskets point opposite ways**, and the
whole basket hides it:

| Basket | Sep 25–Aug 26 variance |
| --- | --- |
| Whole | **−$44k** on $4.45M — a 1.0% **under**spend |
| Controllable | **+$170k** on $1.66M — a 10.3% **over**spend |
| Non-controllable | **−$214k** on $2.79M — a 7.6% underspend, nearly all of it Aug's tax reversal |

So the building is running 10% over on what a PM is answerable for, and the
headline reads 1% under because a tax true-up in the newest month more than
covers it. That is the card's most useful reading and it was invisible until
the presets existed.

Three things about how they behave:

- **Tri-state.** A box standing for a group is not on or off when only some of
  its categories are shown, so it reads `mixed` and draws a dash — a tick there
  would be a lie. `ckGrid` gained that third state and a repaint-all, because a
  grid that drives another grid has to redraw the one it drove.
- **They hand over rather than empty the chart.** Turning off the only group
  still showing switches the other one on as it goes — which is what "show me
  one or the other" wants, and the only case the two boxes behave as a pair
  rather than independently. Every other click is plain: not-fully-on turns the
  group fully on, fully-on turns it off.
- **The note follows them.** It reported the whole basket whatever was ticked
  until the presets arrived, which was defensible when the only reason to untick
  anything was to see past Taxes. The point of a Controllable preset is to get
  the controllable variance, so the figures, the months-that-ran-over list and
  the closing comparison against the scorecard all recompute from what is shown
  and the sentence names which basket it is talking about.

A group with no members is not offered, and with fewer than two the row hides
itself: a property whose account groups name no tax, insurance, utilities or
management fee has nothing for the non-controllable box to switch, and an empty
control that does nothing is worse than no control.

### One definition of "controllable" on the page

`NOT_CONTROLLABLE` was written out **twice** in `index.html` as prefix-anchored
regexes, and a third time in `populate_scorecard.py` as substrings. That is one
definition in three copies, and two of them were not the same rule: `/^tax/`
misses **`Real estate & other taxes`**, which is what the Align tree calls that
group. Checked against the real bucket names — The Landing matches 4 of 4 either
way, so nothing it publishes moves, but **Palma matches 3 of 4 on the prefix
rule**, which trips the all-exclusions-found guard and withholds its
controllable figures for a name the pipeline reads without trouble.

There is now one `NOT_CONTROLLABLE` on the page, matched as the pipeline
matches it, with `isNotControllable()` and `controllableMissing()` beside it;
both existing callers and the presets read it.

Both sides are the same basket by construction. `parse_budget` is a thin
wrapper over the T12 parser, so a budget is grouped through the same COA
mapping and refused unless its groups tie out against its **own** TOTAL
EXPENSES row month by month — exactly as the actuals are. One grouping, two
files, each checked against itself.

**Budgets are kept per YEAR, not per property.** A budget is a calendar year
and the window this card draws is not: the statement runs Sep–Aug today, so a
store that held only the newest year would leave four months of the window
with no plan and the card would report a gap where the file that answers it
had simply been overwritten. `store_budget` keys on the year and accumulates,
the way `expense_buckets` keeps a point per statement period; re-filing a year
replaces that year's point, so re-processing a re-export is idempotent and the
year before is untouched.

`metrics.json`'s `budget` block therefore publishes **explicit `YYYY-MM`
keys** rather than the statement's bare `Jan`..`Dec` labels. Bare labels cannot
say which year a month belongs to and this series spans two by design.

### Three things both views are careful about

Each would be invisible in the numbers:

- **A month in a year with no budget on file publishes `null`.** Zero would
  read as a plan of nothing and turn an unplanned month into a 100% overspend.
  Categories draws no bar there, Total breaks the plan line and its list says
  `no plan`, and both leave the month out of their totals rather than counting
  it as a saving.
- **A category a *planned* year does not name is a real zero.** That year's
  buckets tie out against its own total expenses, so nothing is missing from
  it — the plan for that category is nil, not unknown. The distinction is the
  whole reason the two cases are `0` and `null` rather than both blank.
- **Reversal months are drawn, not absorbed, and are named as timing.** An
  accrual statement books reversals and true-ups in the month it finds them,
  and the newest month carries most of them — Aug 2026 reads Taxes −$118,781
  and Utilities −$31,450 for a net of $48,572, which `monthly_pl` agrees with.
  Against plan that is a −$276k "underspend" in one month, which is a timing
  difference and not money unspent; the note says which months carry credits
  and says exactly that. It is also what sets the y scale for all twelve
  months, which is why the note points at the Taxes checkbox.

**This card and the scorecard's `Budget Variance %` measure different things
off the same two files, and can point opposite ways.** The card is the whole
expense basket over the statement's twelve months — Sep 25–Aug 26 nets
**−$44k on a plan of $4.45M, a 1.0% underspend**, though **nine of the twelve
months ran over** (worst Mar 26 +$64k, Dec 25 +$62k, Feb 26 +$59k) and the
year only nets down because of Aug's tax reversal. The KPI is the
*controllable* basket — taxes, insurance, utilities and the management fee
taken out — over the calendar year to date. Taxes are ~46% of the basket, so
they are most of the difference between the two. The card says so on its face
rather than leaving a reader to find it.

`budget_variance_ytd` picks the plan for the **statement's own year**, not the
newest one on file. With several years stored, taking the newest would measure
this year's actuals against next year's plan and publish the difference as a
variance.

Both plans reached the pipeline as `Landing 2025 Resi Budget.xlsx` and
`Landing 2026 Resi Budget.xlsx`, in the Drive `Budgets` folder. The 2026 file
is the plan the earlier `12_Month_Budget_Accrual.xlsx` carried, to the cent on
all thirteen buckets and on both the revenue and operating-expense lines —
which is corroboration rather than coincidence, since the two exports name
different property codes in their header (four against one). The four codes
were the report's filter, not its scope.

`scripts/test_budget_vs_actual.py` holds it down — 23 fixture-free checks
against budgets and a statement built in a temp dir. The load-bearing three
(per-year storage, null-not-zero for an unplanned month, and picking the
statement's year) were each verified by mutation.

## The statement's rental-income section (Loss to Lease)

The same T12 statement carries, above the expense region, the section the Loss
to Lease card draws: `410400-0000 RESIDENTIAL RENTAL INCOME`, gross market rent
potential and the four deductions that bridge it to accrued rent, closed by
`410499-9999 TOTAL RESIDENTIAL RENTAL INCOME`.

**The analyst workbook's Rent Capture block is that section retyped.** Checked
2026-09-11 against The Landing's `12_Month_Statement_Accrual.xlsx` (Aug 25–Jul
26): all six series — market rent potential, loss to lease, vacancy loss,
employee rent allowance, concessions and accrued income — agree **to the cent
in all twelve overlapping months**, and both TTM totals match exactly
($16,903,452 potential, $13,559,273.34 income). `capture_rate` and `ltl_pct`
are ratios of two of them.

So **the card never needed the rent roll.** The Drive tab's honesty block said
it did until 2026-09-11; that reason belonged to Largest Unit Gaps and Rollover,
which sit beside it and do need per-unit data. Loss to Lease is portfolio-level
monthly off the P&L and never touches a unit.

`parse_t12_statement.rent_capture()` reads the section, `store_rent_capture`
keeps it per property, `stitch_rent_capture` joins successive statements the
way `stitch_monthly_pl` does, and `metrics.json` publishes `rent_capture`.
`renderRentCapture` in `index.html` draws it on **both** Landing tabs — the base
tab still passes `landing.json`'s block, the Drive tab passes the pipeline's,
and the two sources publish the same shape precisely so one renderer serves
both. Table: `t-rentcap-<slug>` on the data page.

Four things worth knowing:

- **Signs are flipped to the workbook's convention.** The statement records a
  deduction as negative; the workbook records it as the size of the loss, i.e.
  positive. The published block follows the workbook so either source renders
  unchanged. `DEDUCTIONS` in the parser is the list that gets negated.
- **The tie-out is the whole section, not the five named lines.** Every other
  leaf under `410400-` is summed into `other` — the COA map shows real codes
  the section can carry (administrative units, bad-debt recovery, a second
  vacancy-loss code) — and the section must then reproduce its own
  `410499-9999` month by month or it is refused. Dropping a leaf would
  understate a loss and read as rent the building never billed.
- **The Align tree has the five accounts but no section total.**
  `config/coa_map.json` maps them to `4050-5100/5105/5110/5115/5120`, so a
  statement on that tree is read, but accrued income is *derived* from the
  lines rather than read from a total row, and the point says so. The stitch
  cuts the run where the basis changes, so no chart spans a read section and a
  derived one. **Unverified against a real Align statement** — Palma's has not
  been parsed for this yet; it is written from the COA mapping.
- **Twelve months, then longer.** One statement is twelve columns, so the Drive
  card starts at twelve where the workbook's shows nineteen, and lengthens as
  statements accumulate. The footnote reads `T<n>` rather than `TTM` when the
  window is not twelve, and the TTM figures are computed from the stitched run
  rather than the newest file's Total column — those agree today and would not
  once the run runs past one statement.

`scripts/test_rent_capture.py` holds it down — 21 fixture-free checks covering
the sign flip, the `other` bucket, the refusals, the Align path and the stitch.
The basis-cut guard is verified by mutation: removing it fails a check.

`Concession Load %` derives from these series, and since 2026-09-29 from the
pipeline's copy of them rather than the workbook's (H2). `Loss to Lease %` no
longer does: it moved to the rent roll on 2026-09-15 (A8), which is a different
source from this section entirely — see the scorecard notes above.

### The scorecard cells that used to wait on Excel

Open item H2, closed 2026-09-29. `NOI Margin %`, `Concession Load %` and
`Month to Month Leases` were read from `docs/landing.json`, which is refreshed
by hand, so they stood at the workbook's July extract while the statement
reached August. Each is now the fill's own formula over a block the pipeline
already publishes:

| KPI | Formula | Read from | Family |
| --- | --- | --- | --- |
| NOI Margin % | newest month's NOI ÷ revenue; T12 recorded beside it | `monthly_pl` | `t12_` |
| Concession Load % | concessions ÷ (market potential − loss to lease − vacancy); T3 beside it | `rent_capture` | `t12_` |
| Controllable OpEx/Unit | already `expense_buckets`; now dated by the statement too | `expense_buckets` | `t12_` |
| Month to Month Leases | holdover units, and their share of occupied | `rent_roll.holdovers` | `rentroll_` |

`statement_noi_margin`, `statement_concession_load` and `rent_roll_mtm` in
`populate_scorecard.py` are the three readers; the unit count for the per-door
figure is the unit directory's `residential_units`, with the workbook's as a
fallback. Three things they are careful about:

- **Provenance follows the source.** The statement's cells are recorded under a
  new `t12_` family — its newest file and arrival from
  `data/<slug>/monthly_pl.json` — registered in `SC_FEED_PREFIXES`, `data.html`'s
  arrivals list and `SCD_DRIVE_FEEDS`. `--from-landing` writes **no**
  unprefixed family any more (`no_report`): that family would date these cells
  by an Excel extract that no longer feeds one of them.
- **Both fill paths agree.** The daily run calls `--from-landing` and then
  `--from-pipeline`; the second fills month to month from the same aggregate,
  so the file is byte-identical after both, as it is for loss to lease.
- **A gap is a gap.** A month without revenue is skipped rather than graded as
  zero, T12 is published only with twelve months on file, and a non-positive
  concession denominator publishes nothing.

What moved on 2026-09-29 for The Landing: NOI margin **72.6% (Jul) → 96.2%
(Aug)**, concession load **0.37% → 0.25%**, month to month **31/11.8% →
30/11.5%**; every grade unchanged. The 96.2% is August's tax and utility
reversals, the timing effect the Operating Summary notes already describe — the
month is what is graded (owner, 2026-09-03), and the T12 beside it reads 69.3%.

`scripts/test_statement_kpis.py` holds it down — 17 fixture-free checks with
the workbook's own readings planted at different values, so reading the wrong
source fails. The three guards (the published source, no unprefixed family, the
pipeline path's month to month) were each verified by mutation.

The data-flow page follows: the T12 and rent-roll flows now publish these
cells, the analyst workbook flow publishes only `landing.json` and draws no
card, and the Delinquency flow reads its own `delq_` family — it had been
reading the unprefixed one, which credited it with Loss to Lease %.

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

1. **The folder pass** — every active entry's own folder, **and two levels of
   subfolders inside it**. This is what the Gmail filer's organisation is for.
   Drive stays browsable, one folder per report type, for pulling source data
   by hand.
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

**A registered folder's own subfolders are read as part of it**, two levels
deep. The sweep is no backstop for a file below the top level, because it walks
the drop tree's top level too — so before the descent existed such a file was
invisible to *both* passes and the folder simply reported empty, with nothing
in the log to say otherwise. That is what `Budgets/Landing/` did on
2026-09-16: two budgets sat in a per-property subfolder the owner had made,
and neither pass could see them. Those two were moved back up into `Budgets`
by hand, so the descent is not what is carrying them today — it is what stops
the next such grouping from stranding a report, the same way the rescue sweep
stopped a misfiled name from stranding one.

**Two levels, because that is what the groupings are.** Budgets is grouped once,
by property. The comp exports are grouped twice — by market and then by which of
the paired exports it is (`Comps/Oakland/Simple/`) — so a one-level walk would
report `Comps` as holding nothing while ninety files sat under it. A fixed
depth, not a recursion, and never into a `NEVER_SWEEP` name: an archive nested
inside a live folder is still an archive, and walking arbitrarily deep would
eventually find one under a name the list does not know. `MAX_SUBFOLDER_DEPTH`
is the one constant, and a folder deeper than it gets a `[warn]` line rather
than silence — an unread folder that says nothing is exactly how
`Budgets/Landing/` stranded two budgets. `test_fetch_sweep.py` covers all of
it, each guard verified by mutation.

**A folder several active entries share is split by `name_patterns`.**
`Daily Leasing Reports` holds four report families (A11), two with parsers, and
the folder pass used to hand every `*.xlsx` in it to both — so each file was
downloaded twice and each Madelon daily report loaded in full by the
renewal-tracker parser only to be rejected. Now a file another sharing entry
claims by name, and this one does not, goes to that entry alone. A file **no**
entry claims by name still goes to every entry, exactly as before: narrowing
further would let a renamed export sit unread, which is the failure the Budgets
entry's one-word pattern exists to prevent. Checked against run #97's real
listing before it went in — every one of the 53 parses that succeeded that run
is still sent to its parser. `test_fetch_sweep.py` check 7 holds both halves,
each verified by mutation.

The sweep is scoped, and each limit exists for a reason:

| Limit | Why |
| --- | --- |
| Never the `reference` tree | The library holds superseded copies on purpose. `Archive Reports` has a July rent roll beside four other July exports; sweeping it would publish a seven-week-old rent roll as current |
| Never a folder in `NEVER_SWEEP` (`Archive Reports`, `Archive`) | Belt to the tree's braces — an archive stays safe even if it is moved into the drop tree, which `Comps/Archive/` is. The folder pass checks the same list at every level, so an archive nested inside a live folder is skipped rather than descended into |
| Never a file the folder pass took | `claimed` tracks Drive ids, so nothing is counted twice |
| Never a name two report types claim | Reported and skipped. Entries agreeing on `report_type` *and* `parser` are one claim wearing two folder names (the funnel parses from two folders, delinquency from two), so only a real disagreement is ambiguous |
| Never over an existing download | Two folders holding one filename would overwrite on disk and let the second parse win |

`scripts/test_fetch_sweep.py` holds this down — 30 checks against a stubbed Drive
mirroring the real layout, no network or fixtures. Both archive protections are
tested *independently*: removing either one alone fails a check, since the name
guard would otherwise cover for the missing tree scoping.

### A snapshot report never walks backwards

`process_manifest` walks the run's files **in filename order, which is not date
order.** The filer prefixes its arrival date (`2026-10-05 RentRoll10_05_2026.xlsx`)
and a hand-dropped export carries none (`RentRoll09_28_2026.xlsx`), so the newer,
filed report sorts first — `2` before `R` — and the older one is processed after
it. The six stores that keep one file per property (rent roll, delinquency, unit
directory, funnel, concession burn-off, renewal tracker) all write through
`store_report`, which used to take whichever parse came last: every step green,
the page a week stale, nothing in the log.

**`store_report` keeps the newest `as_of` now**, per property. A parse older than
the stored one is refused with a `[keep]` line naming both files, and the caller
is told (`KEPT_NEWER`) so it does not also log `[ok] stored`. An **equal** as-of
still replaces, so a corrected re-export of the same date wins. The comparison
(`older_as_of`) only makes a claim when both dates are ISO at the same precision
— `YYYY-MM-DD`, or `YYYY-MM` for the renewal tracker — so a missing or
unreadable date stores exactly as before rather than blocking.

**The renewal tracker compares arrivals instead** (`vintage="landed_at"`, since
2026-10-05). Its `as_of` is its furthest-forward month *sheet* — how far ahead
the copy reaches, not when it was made — so one sheet the parser could not read
made a newer copy look older. That happened the day the guard went in: the
Landing's 2026-09-21 copy split December into two half sheets, read as reaching
only November, and the 2026-09-08 copy displaced it — two weeks of statuses
and a 33-unit MTM roster back to 31, on the Trade-outs card. So the later Drive
arrival (`older_landed`) wins there, and `as_of` decides only when either side
has no arrival time, as in a local run. The parser reads half sheets now too
(see *The two leasing parsers*), but a sheet it cannot read should cost that
sheet, not the whole file.

In CI the gitignored stores (`rent_roll.json`, `delinquency.json`) do not exist
at the start of a run, so the guard decides between files **within** one run;
locally it also protects whatever is already on disk. `stitch`-style series
(the T12 stores, budgets, comps, lease trade-outs, the weekly leasing workbook)
are keyed on their own period and were never exposed to this.

`scripts/test_snapshot_order.py` holds it down — 30 fixture-free checks with the
parser stubbed, driving `process_manifest` through both of its store call sites
(the single-property shape and the sectioned delinquency shape) with the newer
file sorting first, and the tracker's 2026-10-05 case by arrival. Seven guards
verified by mutation: the comparison, each call site's `KEPT_NEWER` check, the
precision match, the tracker's arrival vintage, its refusal of an earlier
arrival, and its fall-back to `as_of` without one. **Clear `__pycache__`
between mutation runs.**

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
still routes where it belongs. Check 7d extends that last one past the category
folder: a real filename must land in the right *subfolder* of it, a name that
cannot say must land at the top rather than in a guess, and the deepest split
must stay within `fetch_drive`'s `MAX_SUBFOLDER_DEPTH`. Run it after editing
either file.

Two traps worth knowing:

- **The filer prefixes the arrival date** (`2026-08-25 leasing_funnel_report_…`),
  and `fetch_drive` matches with `fnmatch`, which tests the whole filename. So
  every `file_glob` must lead with `*`. An anchored pattern matches only the
  hand-placed copies and silently skips everything the filer files.
- **`Workorders - Mainentance `** carries a misspelling *and* a trailing space,
  in Drive and in `report_map.json` both. Renaming it means the Drive folder,
  `report_map.json` and the `.js` rule all change together; `test_routing.py`
  fails if only one moves.

### Five folders are split inside, and `SPLIT_INSIDE` is how

Since 2026-09-23 **`Rent Roll`, `Delinquency` and `Residential AR Analytics`
split by property** as well (the last has no Drive folder yet: every delinquency
summary so far matched the `Delinquency` rule first),
off the same `PROPERTY_FOLDERS` table as the leasing reports. Yardi's rent roll
names no property in its filename (`RentRoll09_15_2026.xlsx` — the building is
only inside, at row 278), so in practice rolls stay at the top of `Rent Roll`;
the delinquency summary names its building (`… - Chorus.xlsx`) and splits.
Nothing downstream reads the subfolders, and one level is well within
`MAX_SUBFOLDER_DEPTH`.

Since 2026-09-21 (A11, owner's call) `Renewal Tracker`, `Prospect Reports`,
`Daily Tracker` and `Daily Leasing Reports` are **one Drive folder** —
`Daily Leasing Reports` — with a **subfolder per property inside it**.
`Demographics` stays separate: it is a resident-profile export, not a leasing
report.

Four routing rules still point there, not one. The pipeline picks a parser by
`name_patterns`, never by folder, so collapsing the four patterns into a single
rule would file the families together and leave nothing able to tell a renewal
tracker from a daily report.

`Comps` is the second, and it is split **twice** — by market and then by which
of the paired exports it is, matching the tree under *Two markets, and ninety
extracts of them* above. So the filer writes
`Comps/San Francisco/Simple/…` rather than dropping everything at the top.

**Both splits happen at filing time, from the attachment's own name**, because
that is the only place the market or the property is knowable. `SPLIT_INSIDE`
in the `.js` maps a category folder to the tables it is split by, one segment
per table — `PROPERTY_FOLDERS` for the leasing families, `COMP_MARKETS` then
`COMP_KINDS` for the comps — and all three tables are the same
`{folder, words}` shape matched by one `firstMatch_`, so a third split is a
table and a line rather than a second mechanism.

Three things about how it behaves:

- **A partial read is not a partial file.** A comp export whose market matches
  and whose kind does not lands at the **top** of `Comps` with a log line, not
  in the market folder alone — a reader opening `Comps/Oakland/` would take it
  for the whole of Oakland. Same rule as a leasing report with no property in
  its name, and the same rule that kept the concession burn-off unattributed
  for six weeks.
- **Nothing downstream depends on it.** These subfolders are for a human
  browsing Drive; attribution comes from the filename and the file's contents,
  as it always has. A market nobody has listed still parses — it just sits at
  the top of `Comps`, which `fetch_drive` reads first.
- **`applySplit_` is shared with `resortExistingFiles`**, so a re-sort lands a
  file exactly where an arrival would. It did not before, which meant running
  the documented recovery step put files somewhere a fresh arrival never goes.

**A rule's own `folder` still never carries a `/`.** Nesting is `SPLIT_INSIDE`'s
job. A `/` is legal in a Drive folder name, so a rule naming
`Comps/Oakland/Simple` would create one folder called that — the accident
`test_routing.py` check 2 exists to catch, and the reason this is a table
rather than a path.

`PROPERTY_FOLDERS` is generated from `config/properties.json` and has the same
contract `PROPERTY_WORDS` does — `test_routing.py` check 7b fails if a property
is added to one and not the other, and check 7c fails if the four families stop
sharing the folder. A building missing from the list files at the top for ever,
which looks exactly like a report that has no property in its name. **That was
the renewal trackers until 2026-09-23**: they name their building as a bare
`Landing 2025 …`, and the master's words were only `The Landing` / `.Landing`,
so the whole family filed at the top. `Landing` is an alias now (C10), and
check 7d pins the tracker and the Landing daily tracker into `The Landing/`.
The comp exclusion matches whole names, so the alias drops only a comp building
called exactly "Landing".

`COMP_MARKETS` has no such generator — there is no market list in the repo to
generate it from — so check 7d pins it against real filenames instead, and
**check 7d also holds the one cross-file contract that has no other guard**:
the deepest split must be within `fetch_drive`'s `MAX_SUBFOLDER_DEPTH`. Add a
third table to a split and every file under it is filed perfectly and never
read again, with nothing anywhere to say so.

Deploying it needs the `.js` pushed and `resortExistingFiles` run; **files
already in the three old folders have to be moved by hand**, since that function
only sees files loose in Report Lander or in `_Unsorted`. Nothing stops parsing
meanwhile — the rescue sweep finds them by `name_patterns` wherever they sit.

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
`cBudgetActual`); the Landing cards already had them, and the property tabs'
scorecard cards are named `psc-<slug>` by `buildPropertyTabs`.

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

**A card's `primary` is declared on exactly one flow, and two checks hold that
down.** Several flows land on one card and each may name its own tables; only
one of them may say which is *the link*. Where two named **different** ones the
winner was whichever sorted last — not an answer, and not visible from either
declaration. Four cards were in that state on 2026-09-28: `cdTradeOuts`,
`cdInventory`, `cdRentCapture` and `cScorecard`. Flows naming the *same*
primary are fine and stay as they are (seven do for the scorecard), since the
resolved link is the same either way.

The second check is subtler, and is what made the Trade-outs card's link wrong
rather than merely arbitrary. A wildcard primary is stripped to its stem for
the href (`t-tradeouts-*` → `t-tradeouts`) and `focusHashTarget` resolves it by
trying `getElementById` **first**, falling back to the prefix scan. So a stem
that is *itself* a table id lands on that table instead of on the family it
names — silently, and on a real table, which is why nothing downstream could
tell. The Landing tab's Trade-outs card pointed at the **Portfolio tab's
hand-authored `t-tradeouts`**, a different card's placeholder data.
`build_lineage` refuses to write on either condition now, each verified by
mutation.

Both were found by checking the rendered links rather than the declarations:
open every tab, read each card's `a.cardsrc` href, follow it into `data.html`
and print which table it actually resolves to. Note the gate marker lives in
`sessionStorage`, which is per **tab**, so a probe like that has to navigate
one page from `index.html` to `data.html` rather than opening a second one —
and it has to visit every tab first, since the property-tab cards and the
placeholder grid are built on demand. All **43** rendered links land on a real
target as of 2026-09-30 (46 when first counted on 2026-09-28; cards have come
off since, and the two prior → new $/sqft cards became one). Count rendered
links, not card ids: the Rental Rates cards and the placeholder cards are
generated, so keying the probe on a card `id` missed them — 35 at the first
count.

**Resolving is not the same as landing on the right table**, and reading the
46 against what each card actually draws turned up two more:

- **`cmcEvidence` ("How It Is Actually Leasing") pointed at the comp set.**
  That card draws days on market and concessions — and `t-comps-<slug>` holds
  property, distance, units, listing counts and bed medians, none of it. The
  figures were in `metrics.json`'s `comps` block (`days_on_market`,
  `concessions`, `subject_listings`) with **no table anywhere on the page** —
  the same gap `monthly_pl`, `expense_buckets` and `unit_directory` were in.
  `t-compsleasing-<slug>` now carries them, one row per measure with each
  side's listing count beside it, and the card points there.
- **`cdFeeds` ("What Feeds This Tab") pointed at the T12 statement's flow
  row.** That card reads `lineage.json`'s whole flow list — every feed's
  arrival — so one flow row is not its numbers; it was the `tables: []`
  fallback taking whichever flow sorted first. Its primary is now **`flow`**,
  the data-flow view itself, which is what the card is a summary of.
  `focusHashTarget` already answers `#flow` and `#tables` by switching view, so
  `VIEW_ANCHORS` in `build_lineage` lets a primary name one and the table
  checks skip it.

One trap came with that table. `build_lineage` reads a table's title out of
`data.html`'s **source** rather than running it, so a `title:` written with a
`\uXXXX` escape reached the card tooltip as those six characters. Titles use a
literal em-dash like every other table, and the extractor decodes the escape
anyway so the next one cannot repeat it.

Three links are a judgement rather than an error, and are left as they are: the
four property-tab scorecard cards point at `t-sc-measured` rather than
`t-sc-matrix` (they are about one property's measured cells and their feeds),
`cBudgetActual` points at the plan rather than the actuals it is subtracted
from, and `cmcMethod` — the limits block — points at the comp set.

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
- **A block with no flow row still gets a table.** `properties` — the active
  property master, published 2026-09-29 so the page can enumerate the
  buildings rather than infer them from whichever block a card happens to
  read — comes from `config/properties.json`, which is a config file rather
  than a report, so no flow claims it and `sourceOf` returns nothing for it.
  `t-properties` carries it anyway, with its provenance in its own note:
  the page holds every block `metrics.json` carries, and this one decides
  which buildings the Budget vs Actual card offers a tab for.
- Three `metrics.json` blocks had **no table on the data page at all** —
  `monthly_pl`, `expense_buckets` and `unit_directory`, i.e. everything the
  Drive T12 and the unit directory produce. The page claims to hold every
  number the JSON carries and did not, which is why the Operating Summary card
  had nowhere to link. `t-monthlypl-<slug>`, `t-buckets-<slug>` and
  `t-unitdir-<slug>` now cover them, and `t-budget-<slug>` covers the `budget`
  block — every month of every year on file, not just the year in progress,
  since the card's window crosses the calendar boundary.

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
- **A store this checkout cannot read falls back to what it published.**
  `data/<slug>/rent_roll.json` and `delinquency.json` are gitignored (per-unit,
  they arrive with names), so they exist only during a pipeline run — and
  reading the stores alone reported the rent roll, live since 2026-09-11, as
  `waiting` in every fresh clone. Every field the evidence needs is already in
  the published aggregate, which IS committed, so `evidence_from_published`
  reads it from there and the row says where it was read from. Closes open item
  G4; a lineage page regenerated outside CI is now the same page CI writes.

The script **refuses to write** on a card anchor `index.html` does not define, a
table id `data.html` does not build, or a parser module named in the report map
that is not in `scripts/`. A lineage page that has quietly gone stale is worse
than none, because it is read as a map.

Five statuses, and they are the page's whole argument:

| Status | Means |
| --- | --- |
| `live` | A file arrives, the pipeline reads it, something on the dashboard shows it |
| `partial` | It arrives and parses and ties out. Nothing publishes it — the chain stops in `data/` (the funnel, the concession burn-off) |
| `waiting` | Parser written and registered; no file has ever arrived. **No flow is in this state today** — the rent roll was the last one and it landed 2026-09-11, closing C4 |
| `no-parser` | Folder registered so a file dropped in it reaches the fetch log; the parser needs one sample file. Collapsed into a single block rather than five identical empty chains |
| `manual` | No feed at all — the ten placeholder cards are edited into `metrics.json` and carried through each run. Three blocks have left this row: `expense_trend` on 2026-09-17, derived from the T12 statement now, and `psf_vs_peers` the same day and `trade_outs` on 2026-09-28, each with the card it fed. A fourth card left without its block — the `noiMargin` placeholder on 2026-09-30, one entry out of the `placeholders` array rather than a block of its own |

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

### The cron run re-syncs to `main` before it builds

A scheduled run checks out `main` at **run start**, and the run is long — the
Drive fetch alone was 4h34m on 2026-09-16. Everything after it therefore built
the repo as it was that morning, and the push-retry loop's replay then put that
output over whatever had landed since. Every step green, nothing in the log.

That is not hypothetical. Run #86 checked out `b8bcf4d` at 15:20 and committed
at 19:55; because its `build_metrics.py` predated the budget work it published a
`metrics.json` with **no `budget` block** (the Budget vs Actual card read
"no budget has reached the pipeline" with two budgets sitting parsed in Drive),
rewrote `data/the-landing/budget.json` in the older single-year shape, and
dropped a hand-added EliseAI day with the scorecard cells behind it — four
commits undone.

So `update.yml` re-syncs **once, immediately after the fetch**:
`git fetch origin main` and, if it moved, `git reset --hard` onto it.
`_downloads/` is gitignored, so the reports this run just fetched survive the
reset and nothing is downloaded twice.

**That placement rests on a premise that is false, and open item A15 is the
evidence.** The premise was that everything below the re-sync is minutes rather
than hours, so one sync closes almost the whole window. Run #88 on 2026-09-18
fetched Drive in **2m26s** and then spent **4h54m in `build_metrics.py`**: the
re-sync fired at 14:50:56 and correctly found main unmoved, the Market Comps
work merged at 17:08, and at 19:44 the retry loop below replayed the run's
stale `metrics.json` and `lineage.json` over it — blanking a live tab. The long
pole was the build, not the fetch, and the guard covered the wrong one. What
covers the build window now is the commit step, which rebuilds on top of
anything that lands during it rather than over it — see *The commit step
rebuilds on a newer main* below (A15, closed 2026-10-05).

**Why the build took hours** (found 2026-09-28, after runs #94–#97 were all
cancelled at GitHub's six-hour job limit): openpyxl does not store a sheet's
`max_row` or `max_column` — every access scans every cell — and
`xlsx_anchors.header_map` read them once per cell it looked at. Harmless on a
report; ruinous on the Madelon daily report, whose first sheet is 51 MB of XML
and ~2.3 million cells. One copy took **262 s** to parse, 3,338 full scans of
the sheet, and one arrives every day and every run re-parses every copy, so the
build grew by minutes a day until it could not finish. Two fixes:

- **`xlsx_anchors.dims(ws)` reads both once**, and every parser loop that asked
  per row or per cell now asks once. The same Madelon file parses in 17 s, and
  a full renewal tracker in 1.7 s rather than 14.6 s — each checked
  byte-identical against the old code's output. `test_xlsx_dims.py` counts the
  property reads and fails if any helper goes back to per-row.
- **A shared folder hands each file to the entry that claims it by name** — see
  *Folders organise; filenames route*. Before, both leasing parsers got every
  file in `Daily Leasing Reports`, so the renewal-tracker parser loaded each
  Madelon daily report in full just to reject it.

**Verified on the runner the same day**: run #98 (`workflow_dispatch` on
`22c80d4`) built in **9m29s** and the whole job in 20 minutes, pushing on the
first attempt — against runs #94–#97, cancelled after ~5h50m each. Its own
unbuffered log puts **7.4 of those 9.5 minutes in the Madelon daily reports,
~16 s apiece**, and 1.3 in the comps.

What is **not** fixed: the build still re-parses every file ever filed, every
run, so it still grows — by about 16 s a day, one Madelon report's worth, which
is years from the limit rather than days. The ten-minute build is also what
made the commit step's rebuild affordable — see below. The job now runs with
`PYTHONUNBUFFERED`, so the next slow file names itself in the log's
timestamps; until then, stdout flushed in 8 KB blocks and a 45-minute gap could
belong to any file in the block.

It takes the newer **data** as well as the newer code, which is the half that
saves a hand-added feed: the build then accumulates onto the current stores
rather than the run-start ones.

### The commit step rebuilds on a newer main

Until 2026-10-05 a rejected push reset to the new `main`, copied this run's
files back over it and committed. That was a clobber, not a merge: anything
newer in those paths was overwritten by a build that never saw it, which is how
run #88 blanked the Market Comps tab, and the only trace was a warning inside a
green run. (Before *that*, a `git pull --rebase` between tries conflicted on
the run's own files and spun in a half-rebase — nothing published 2026-09-13 to
09-15.)

**The old step ran once more after the fix was on `main`.** Run #106 was
dispatched at 17:28 on 2026-10-05, nine minutes before `3516699` replaced the
step, and a run keeps the workflow file of the commit it started from. It lost
its push to `f07404a` at 17:53 and copied its own copy of
`data/335-third-street/eliseai_daily.json` back over that commit's new
`resident_calls` field — every step green, the file named only in a warning.
`e8e9994` restored it three minutes later. So a run already queued when a
workflow fix lands still runs the old steps, and is worth watching through.

It **rebuilds on the new `main` instead**. The reports are still on the runner
(`_downloads/` is gitignored, so a reset leaves them), so resetting to the newer
`main` and running the same build again produces what a run starting now would:
the newer commits' code *and* data — a hand-added EliseAI day, a newer comps
vintage, a fixed parser — with this run's reports on top. It was only
affordable once the build took minutes rather than hours.

Two scripts carry it, so that the rebuild cannot drift from the build:

- **`scripts/build_pipeline.sh`** is everything the run derives, in order:
  metrics, the three scorecard fills in the order G3 and H1 settled, the
  lineage. The workflow's build step runs it, and the commit step runs it again
  for a rebuild. It replaced five workflow steps; run side by side against this
  repo's own stores it wrote the same files as those steps, differing only in
  two wall-clock timestamps. It times each stage in the run's summary.
- **`scripts/commit_and_push.sh`** commits and pushes:
  1. a rejection with `main` **unmoved** is not a race (GitHub returns the odd
     500), so the same commit is pushed again, with no rebuild;
  2. `main` **moved**: reset to it, rebuild, commit, push — and the log lists
     the commits it is building on and which of this run's paths they touched;
  3. `main` **keeps moving**: after three rebuilds it gives up and **fails the
     run**, overwriting nothing. A red run is a signal somebody receives; an
     overwrite never was;
  4. **`check_no_pii.py` runs before every commit it makes**, rebuilt ones
     included — it used to be its own step, which guarded the first commit
     and not the replay.

  Also: a push that landed but reported failure is recognised as landed rather
  than rebuilt, and a `git commit` that fails fails the run rather than reading
  as "nothing to commit". The rebuild reinstalls `requirements.txt` first,
  since the newer `main` may have added a dependency.

`scripts/test_push_race.py` holds it down — 46 checks with real git against a
bare repository in a temp dir: a shallow runner clone (as `actions/checkout`
makes it, since the script leans on `HEAD^` and `base..tip`), a second clone that pushes
"someone else's" commits mid-run, and a fake build whose output is derived from
the repo it runs in, so "rebuilt on the new main" is something a check can see.
Mutation-tested: putting the old replay back fails 15 checks, and removing any
one of the other five guards fails that guard's own checks. A `git clean` in
the first draft turned out to be dead — everything the first build wrote is in
the run's own commit, which the reset already discards — and was dropped
rather than kept as a guard that guards nothing.

**Verified on the runner the same day, with a real race.** Run #107
(`workflow_dispatch` on `3516699`) re-synced onto `e8e9994` after its Drive
fetch and built for 7m11s; `890c4d8` was pushed while it built, to put the new
step through a race. Its first push was rejected at 18:14, it annotated the run
`main moved under this run; rebuilding on 890c4d8 rather than overwriting it`,
rebuilt in about seven minutes, ran the personal-data check again, and logged
`Pushed d4dfe5f on attempt 2, after 1 rebuild(s) on a newer main`. Its commit
sits on `890c4d8` with that commit's notes and `e8e9994`'s `resident_calls`
intact — the same shape of race #106 had lost twenty minutes earlier. The run summary
says when this happens (`rebuilt N time(s) on a newer main`).

A rebuild costs a whole build, so on a day when commits land every few minutes
a run can lose the race more than once; after three rebuilds it fails rather
than overwrite, and the next run carries the reports.

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

**Every workflow that commits to main is in `deploy.yml`'s `workflow_run`
list** — `Update Dashboard Metrics`, `Refresh Market Comps`, `Refresh Rental
Rates`. A push made with a workflow's own token starts no other workflow, so
after the flip a refresh would otherwise sit on main unpublished until the next
metrics run. Before it, the branch build publishes them regardless, and the
extra deploy publishes the same bytes. A new workflow that commits needs adding
there too.

After flipping it, in order:

1. `scripts/publish_data.sh` — create the `data` branch.
2. Confirm the site still loads, then stop committing data to `main`: drop
   the four data files from tracking and change `update.yml` to publish to the
   `data` branch instead of committing. **Not `docs/rental_tracker.enc.json`**,
   which is ciphertext and belongs with the site shell — see **The Rental Rates
   Tab**; a `docs/*.json` glob would take it too.
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
fails. In `update.yml` it runs inside `commit_and_push.sh`, before every commit
that script makes — a commit rebuilt after a lost push race included. Three passes — person-shaped keys in the published JSON, raw reports or
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
- **The dashboard no longer says that itself.** A standing footer sat under
  every tab in two lines — where the numbers come from, and that the gate is
  client-side only and real financials want AES first — and it came off
  2026-09-30, by request, with its `#footer` element, its fill and the `footer`
  CSS rule. It is the page-wide sibling of the Landing tab's footnotes, removed
  the same day. So the caveat now lives here and in the comment above `#gate`,
  and a reader of the page is not told it — worth knowing before anyone reads
  the gate as protection.

  The other line is not lost either: which report feeds every number is the
  data-flow page, and each card's own `Data ↗` is a shorter route to it than a
  sentence at the bottom ever was. **`data.html` keeps its own footer**, which
  was not part of the request and says something the dashboard's did not — that
  the tables page carries every figure at full precision. `metrics.json`'s
  `meta.note` is the string the removed line interpolated and is now read by
  nothing; it stays, because the pipeline preserves that block rather than
  writing it, so deleting it would be a hand edit to a data file for no gain.
- `index.html` is the only place the password is entered. Unlocking sets
  `sessionStorage["align-unlocked"]`; `data.html` requires that marker and
  redirects to `index.html?next=data.html` without it, so the data tables are
  not a second way in. The unlock lasts the browser session, not forever. Any
  new gated page should follow the same pattern rather than adding its own
  password field — and note the marker is client-side like the gate itself, so
  it deters, it does not protect.
- **The header's right side is the `Updated <time>` stamp and the `External
  Links` menu** (2026-09-30, by request). The stamp is `metrics.json`'s
  `generated_at` in the reader's own time zone: what is left of the
  `<portfolio> · updated <time>` line the menu first replaced outright. The
  timestamp came back the same day; the portfolio name, which only repeated
  the title, did not. The two are one flex item (`.hright`), so at phone width
  they wrap under the title as a pair, right-aligned, the stamp above the
  button. The menu holds Align Yardi, JPM Yardi, XXX Yardi, Elise AI, Real
  Page and Google Drive, each opening in a new tab. It is a `<details>` rather
  than a `<select>` because these are links — a middle click or "open in new
  tab" works on each like any other — and it opens without script; the script
  only closes it (a pick, a click or focus elsewhere, Esc). **XXX Yardi has no
  address yet** and is listed muted with `no link yet`: to give it one, turn
  its `span.xl-none` into an `<a>` like its neighbours. The Elise AI address
  carries a login `state=` token copied from an address bar, so if it starts
  landing on an error page, swap in the plain sign-in URL. Two traps it
  records: the header centres its row (baseline alignment hung the bordered
  button 4px below the title), and the menu's rows carry **no colour
  transition**, because they are not rendered while it is shut and a theme
  switched meantime replayed as a fade on the next open. The menu is inside
  `#app`, so it is behind the gate — which, as above, hides it from sight and
  not from the source.
- `metrics.json` values flow into the DOM. When rendering anything from it,
  prefer `textContent` / `createElement` over `innerHTML` so pipeline data
  cannot inject markup.
- Charts come from a Chart.js CDN script tag. Sandboxed environments often block
  it, producing `Chart is not defined` — that is an environment artifact, not a
  page bug.
- **Dark is the default, on both pages.** `index.html` and `data.html` each set
  `data-theme` from `localStorage["align-theme"]` in a script before the
  stylesheet, so a stored choice never flashes the other theme; with nothing
  stored it is `dark` rather than the machine's `prefers-color-scheme`, which
  is what it read until 2026-09-29. A dashboard is one artefact shown on
  screens nobody here controls, and a reader on a light laptop was getting a
  light copy of a page whose charts and colour bands were chosen on a dark one.
  The toggle still wins, still persists and still carries between the two
  pages — a default is what you get before you choose, not instead of choosing,
  and clearing the stored value returns to dark. Each `:root` block also
  declares its own `color-scheme`, so the browser's own chrome — scrollbars,
  the select popup, focus rings — follows the page rather than the machine;
  without it the dark default arrives with light scrollbars down the deep
  dive's table on exactly the machines the change was made for.
- Verify UI changes by serving `docs/` and driving the page in a real browser
  through the password gate, not by reading the diff alone.

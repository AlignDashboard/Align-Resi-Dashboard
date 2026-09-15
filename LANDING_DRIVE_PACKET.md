# The Landing (Drive) — report packet

What to pull, and where to drop it, to make the `Landing (Drive)` tab update
completely. That tab is the one that **moves on its own**: every number on it
comes from a report the Gmail filer drops into Drive and the pipeline parses, so
dropping a fresh direct export in Drive is the whole refresh. (`The Landing` tab
beside it is the fuller view and cannot move on its own — it needs pasting into
the analyst workbook's grey tabs, recalculating in Excel and re-running
`extract_landing.py`.)

This is a working document. Section 1 is the standing list and changes only when
a card or a feed does. Section 2 is **generated** — do not hand-edit it. Section
3 is what the packet cannot fix.

---

## 1 · The packet

Ten cards, nine feeds. The filer routes on the **filename**, so naming the export
correctly is the whole job — no folder navigation needed, and a file that lands
in the wrong folder is still found by the rescue sweep (one exception, below).

| # | Report (as exported) | Filename must contain | Drive folder | Cadence | Cards it moves |
| --- | --- | --- | --- | --- | --- |
| 1 | 12-Month Statement, **Accrual** | `12_Month_Statement` | `T12 Expenses` | monthly | Operating Summary, Expense Load & NOI, Expense Deep Dive, Loss to Lease (series) |
| 2 | 12-Month **Budget**, Accrual | `12_Month_Budget` | `Budgets` | annual / on reforecast | Budget variance tile |
| 3 | **Rent Roll** | `RentRoll` | `Rent Roll` | weekly | Loss to Lease (today's gap), Rollover Schedule, Largest Unit Gaps, Unit Inventory |
| 4 | `rs_rp_DelinquencySummaryReport` | `Delinquency` | `Residential AR Analytics` | monthly | Delinquency card + tile |
| 5 | `Daily Report- Week Ending <date>` | `Daily Report` + `Week Ending` | `Daily Leasing Reports` | weekly | Trade-outs (new leases) |
| 6 | Landing 2025 Renewal Tracker – Full | `Renewal Tracker` | `Renewal Tracker` | weekly | Trade-outs (renewals) |
| 7 | Yardi **Unit Directory** | `UnitDirectory` | `Building Info` ⚠️ | on floorplan change | Unit Inventory, Largest Unit Gaps (bedroom join), Expense Load & NOI (per-unit) |
| 8 | EliseAI **building metrics** export | `metrics-building` | `EliseAI Reports` | monthly | Leased %, Trade-out % tiles |
| 9 | EliseAI weekly **funnel** | `leasing_funnel_report` | `EliseAI Reports` | weekly | — (has never covered The Landing) |

Four things worth knowing about this table:

- **#7 goes to the Drive library, not Report Lander.** `Building Info` is in the
  `reference` tree, which the filename rescue sweep never reads — deliberately,
  so a superseded export there cannot be republished as current. It is therefore
  the one report where dropping a copy in the wrong place means it is never
  found, and the one folder that must not be renamed.
- **#5 is Align's own weekly workbook, not a RealPage export.** Its
  `Weekly_Leases` sheet carries `PRIOR LEASE RATE`, which nothing else in the
  pipeline has. The week it covers is read from the **filename**, not from the
  sheet's own cell, which drifts between snapshots of one week.
- **#6 is the whole history in one file**, a sheet per month from January 2024
  plus the `MTM` roster — not a weekly increment. A newer copy supersedes.
- **#3 and #4 arrive with tenant names.** They parse, but nothing persists a
  name; `check_no_pii.py` gates every commit. Nothing extra to do when sending
  them.

---

## 2 · Current state

<!-- BEGIN STATUS -->
_Feed state as of 2026-09-15 — regenerate with `python scripts/landing_drive_status.py --write`._

| Feed | Covers | Landed | Status |
| --- | --- | --- | --- |
| T12 statement | Aug 2026 | 2026-09-14 | 1d — current |
| Budget | Jan 2026-Dec 2026 | 2026-09-03 | 12d — current |
| Rent roll | 2026-09-11 | 2026-09-11 | 4d — current |
| Delinquency | 2026-09-08 | 2026-09-08 | 7d — current |
| Weekly leasing | 2026-09-13 | 2026-09-13 | 2d — current |
| Renewal tracker | 2026-12 | 2026-09-08 | 7d — current |
| Unit directory | 2026-08-25 | 2026-08-26 | 20d — refresh on change only |
| EliseAI bldg metrics | 2026-08-31 | 2026-08-31 | 15d — current |
| **EliseAI funnel** | — | — | **never arrived** |
<!-- END STATUS -->

The script reads only published JSON — `docs/metrics.json`, `docs/scorecard.json`
and `data/the-landing/*.json` — so it needs no Drive access and runs anywhere the
repo is checked out. `Covers` is the period the data describes; `Landed` is when
it reached Drive. Those are different questions and the packet keeps them apart:
a report can be about July and have arrived this morning, and only the arrival
can show a feed that has stopped running.

Two rows read differently from the rest:

- **Unit directory** has no cadence. It is the buildings' fixed description, so
  it is only due when a floorplan changes — but it is also the feed that has gone
  longest without one, and a stale directory shows up as wrong bedroom counts
  rather than as a missing card.
- **Delinquency** shares its two scorecard cells with the analyst workbook, last
  run wins (open item G3). When the workbook has written last the script says
  so on that row, because the arrival date alone would imply a Drive report that
  is not what the page is showing.

---

## 3 · What this packet cannot fix

Sending more reports will not move these. Each is pipeline or page work on data
that has already arrived.

| | Item | Why |
| --- | --- | --- |
| **H1** | Five scorecard cells do not follow the statement | `update.yml` runs `populate_scorecard --from-pipeline` and nothing else, so NOI Margin %, Concession Load %, Controllable OpEx/Unit, Budget Variance % and Month to Month Leases only move when `--from-landing` is run by hand. Two are demonstrably stale whenever a statement lands without that run |
| **H2** | Three KPIs are read from the hand-refreshed workbook | Loss to Lease % moved to the rent roll on 2026-09-15; NOI Margin % and Concession Load % still come from `landing.json`, so they are pinned to the workbook's last extract no matter how many statements arrive |
| **A6** | Concession burn-off names no property | The export says only "For Selected Properties", so it parses and is stored nowhere. This is the **only** one of the four that is still waiting on a report — one that names its building |
| — | Holdover reconciliation, delinquency aging, the Insights scorecard | The first two need the rent roll and tracker joined unit by unit and a parse published; the third is a judgement no report produces |

---

## Log

Newest first. Add a line when a feed, a card or a packet row changes — not for
routine arrivals, which section 2 already reports.

- **2026-09-15** — Created. Nine feeds, ten cards. Eight of nine feeds current;
  the EliseAI weekly funnel has never covered The Landing, and the unit directory
  is the oldest arrival at 20 days. `scripts/landing_drive_status.py` added so
  section 2 is generated rather than remembered.

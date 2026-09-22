# Open Items

State as of 2026-09-22. IDs are stable — when an item closes, move
it to *Closed* rather than renumbering, so "A3" means the same thing next week.

**Live and uncertain** marks an item where the dashboard is publishing something
today that depends on the unresolved answer. Those are the ones worth taking
first: everything else is a gap, but these are assertions.

## A · Blocked on the owner (a file, an answer, or a click)

| # | Item | What it blocks | Live and uncertain |
| --- | --- | --- | --- |
| A5 | ~~Which copy is authoritative~~ **Answered: the Drive files.** The funnel parser is live for both the `EliseAI Reports` and `Weekly Leasing Reports` folders, so the weeklies parse wherever the gmail-filing fix (C3) lands them. The Aug 18 file parses the day it moves out of `_Unsorted` | C3 only | no |
| A6 | ~~Which property does the concession burn-off export cover?~~ **Answered 2026-09-21: Palma.** The file itself never could say — it reads only "For Selected Properties" and its one heading is "Projection by Unit", report structure rather than a name — so the answer lives in `report_map.json` as `unattributed_property` on the burn-off entry. It is a fallback, not an override: a file that names its own sections still routes by those names, which is the distinction that kept six weeks of parses from being filed under the wrong building | Nothing now — the −$54,990 recurring concessions store against Palma on the next run | no |
| A8 | ~~Loss to Lease % grades red off a disputed denominator~~ **Denominator settled 2026-09-15: the rent roll.** The cell now reads **37%** — market rent less in-place rent over market rent across the 257 occupied units on the roll of 2026-09-11 — which is what the band's own published `how` always said and what the workbook fill (27%, the T12's monthly revenue lines) never was. Filled from the published aggregate by both `populate_scorecard` paths, so it has no last-run-wins race; its own `rentroll_` feed family carries the roll's arrival. **What is still open is the band, not the source**: 37% grades red against a 10% ceiling, and the roll shows Yardi's market-rent table revised up +17.9% in eight weeks while in-place rent moved +0.07% — the threshold sheet's own basis note warned about exactly that. Re-bracketing the band is the sibling of A9, and **A14 is the other half of it**: the denominator itself now measures 9.7% above the submarket, which restates the cell to 30.4% without touching the band | Whether a 10% ceiling is the right band for the measurement the cell now makes | **yes** — measured correctly, graded against a band set for something else |
| A9 | ~~Controllable OpEx/Unit's cutoffs were bracketed around the old basket~~ **Rebracketed 2026-09-21 on the owner's call.** $7,200/$8,600 → **$6,400/$7,800**: both cutoffs shift down by the $845 the basket itself moved ($7,784/unit on the old basket against $6,939 on the live one), keeping the $1,400 width — a tolerance in dollars per unit is not a statement about which cost categories are in the basket. Rescaling by ratio instead gives $6,419/$7,666, within $70 on the green cutoff, so nothing turns on the choice; it is still a choice. Restated in `populate_scorecard` (`CONTROLLABLE_CUTOFFS`) rather than edited into `scorecard.json`, because `extract_scorecard` resets every band from the ranges sheet — the sheet's own numbers are kept in `*_workbook`. The Landing's Aug 2026 cell moves **exceeding → in range** at $6,757, which is the point: it was grading a smaller basket against a bigger basket's yardstick | nothing | no |
| A10 | ~~Extend the COA mapping workbook to cover the 10 unmapped JPM accounts~~ **Answered 2026-09-21: lump them into one section.** An account the COA map does not translate now goes to a single `Unmapped (JPM accounts not in the COA map)` bucket instead of being guessed into a real Align group by a keyword in its label — seven different groups on the strength of a substring, which presented ~$115k of T12 as though the COA map had placed it. **One consequence is not presentational:** `520510-0007 Gross Rec./Bus. Lic. Tax` matched `tax` and so sat in Taxes, which the controllable basket excludes; in one section it is controllable. The parser now publishes `reclassified_controllable` naming every account that crosses that line, so the next pipeline run reports the size of it rather than letting the KPI drift. Extending the mapping workbook is still the real fix and is no longer urgent | Clean Align-tree grouping — now one honest bucket rather than seven plausible ones | **watch** — the controllable figure moves on the next pipeline run by whatever that tax line is worth |
| A11 | ~~Confirm the five folder names in the routing table~~ **Answered 2026-09-21: `Daily Leasing Reports`, split by property inside it.** Renewal Tracker, Prospect Reports and Daily Tracker fold into it; **Demographics stays separate** — a resident-profile export, not a leasing report. Four routing rules still, not one: the pipeline picks a parser by `name_patterns`, so collapsing the patterns would leave nothing able to tell a renewal tracker from a daily report. The per-property split happens at **filing** time from the attachment's own name (`PROPERTY_FOLDERS`, generated from the property master and checked against it by `test_routing` 7b); a file whose name carries no property lands at the top of the folder rather than in a guessed building. Nothing downstream depends on the subfolders — `fetch_drive` already reads one level inside a registered folder, and attribution has always come from the filename and the file's contents. **Not yet deployed:** the `.js` still has to be pushed and `resortExistingFiles` run, and files already sitting in the three old folders must be moved by hand — the sweep rescues them by `name_patterns` meanwhile, so nothing stops parsing in the interim | nothing | no |
| A12 | `scripts/gmail_drive_filing.js` carries `TARGET_FOLDER_ID` as a literal, and it is now committed to a public repo — while the same ID is a *secret* (`GDRIVE_FOLDER_ID`) on the pipeline side. A Drive folder ID is not a credential (it grants nothing without permission), but the two halves treat it inconsistently and history cannot be un-published without E3's rewrite. Your call: move it to a script property like `BUILDING_INFO_FOLDER_ID`, or accept it and drop the secret | Nothing today — noting it rather than deciding it for you | no |
| A15 | **The cron's re-sync guards the fetch window, but the long step is the build — so a run can still publish over commits made while it ran.** Run #88 (2026-09-18) checked out `7a06c0f` at 14:48, fetched Drive in **2m26s**, re-synced at 14:50:56 — correctly finding main unmoved — and then spent **4h54m inside `build_metrics.py`** (14:50:56→19:44:37). The Market Comps merge landed on main at 17:08, three hours into that build, and at 19:44 the push was rejected and the retry loop did what it is written to do: reset to main, copy this run's output back over, commit. Result: a `metrics.json` with no `comps` block, and the Market Comps tab blank on the live site until it was rebuilt by hand. The loop prints `::warning::main moved under this run` and names every file it overwrites — `docs/metrics.json`, `docs/lineage.json`, all three `data/*/comps.json` — but a green run's log is not read. **CLAUDE.md's premise that "everything below the re-sync is minutes, not hours" is false**, and was probably always false: runs #86–#88 all took 4.5–5h, and #88 shows the time is in the build, not the fetch. Two independent halves: (1) cover the build — re-check before the commit and rebuild on the new main rather than replaying over it, or refuse and let the next run carry the day's data; (2) make the retry loop refuse rather than clobber when main carries a file this run also wrote. Worth finding out **why `build_metrics` takes five hours** before choosing, since a rebuild is only an option if it is cheap | Any change merged while a cron run is building — a window of several hours, every day | **yes** — it has already blanked a live tab once, and nothing outside the run log said so |
| A14 | **The Landing's market rent table is deliberately ~10% ahead of its submarket, and more steps are expected.** The comp export (HelloData, 36 buildings, as of 2026-09-15) puts the whole table at **$1,827,976/mo** against the rent roll's **$2,004,929** — $176,953 a month, $2.12M a year. The unit directory of 2026-08-25 ($1,805,509) and the statement's Aug 2026 gross potential ($1,804,359) agree with each other to 0.06% and sit within 1.5% of the comps, so the step sits in the roll alone: +12.1% in Jul, +6.1% in Aug, +11.1% again by the roll, **+32.2% in three months** against a comp set that moved 2–6%. **Settled 2026-09-18: the revision was intended, and jumps like it may continue over the next couple of months.** So this is a pricing position rather than an error, and what stays open is what it does to everything reading the table. Three things follow. (1) The published **Loss to Lease KPI climbs with every step** — 36.5% on the roll against 30.4% on a comp-supported rent, already three times its band's 10% ceiling, so A8's band question is now moving away from an answer rather than toward one. (2) ~~**The comp file is a single vintage.**~~ **Answered 2026-09-21: the cadence is there and it is roughly daily.** The Drive folder holds 45 San Francisco extracts and 46 Oakland ones, and more arrive hourly, so a moving table is no longer being measured against a fixed reference. Two things had to be true before that helped, and neither was: a later extract is **not** a superset of an earlier one (HelloData revises its own history — 43 of the 2026-08-11 Oakland file's 739 listings carry a different `First Listed` date in the 2026-09-20 one), and arrival order does **not** track vintage (a copy that landed 2026-09-21 is as of 2026-08-05, six weeks behind one that landed three days earlier). `store_comps` now keeps the newest `as_of` and publishes the ledger of what it was offered, so the tab counts its extracts instead of claiming one. What is still worth having is a **vintage-over-vintage read** — the data is on file to plot the comp set moving against the table, and nothing draws it yet. (3) **The evidence that the position is working is the thing to watch, not the gap** — 44 days on market against the ring's 26, and no concession advertised where 22% of the ring offers one, both measured before this step landed | Whether the Loss to Lease band means anything while its denominator is a deliberate moving target, and whether the market pays the new rates | **yes** — the published 37% KPI and both Landing tabs read off a denominator that is a position rather than a measurement |
| A16 | **The filing script has not deployed since 2026-09-02 — the `CLASPRC_JSON` refresh token is dead.** Every run since has failed the same way, in seconds, on `invalid_grant` / `invalid_rapt`: a Workspace reauth policy expiring the token on a schedule, not anything in this repo. Runs #8 (09-04), #9 (09-17) and #10 (09-18) are identical; `test_routing.py`, `node --check` and the deployer's own 20 guard tests all pass first, so the repo copy is validated on every push and simply never sent. **Three routing rules have landed since the last good deploy and are not in the live project** — `Budgets`, `Historical Tradeout Reports` and `Comps` — so a report of one of those types arriving *by email* would be auto-named or left in `_Unsorted` rather than routed. All three have been fed by hand-placed files so far, and `fetch_drive`'s rescue sweep covers a misfiled name, which is why nothing has visibly broken. The fix is yours and takes three steps: `clasp login` as `dashboard@alignrealestate.com`, paste `~/.clasprc.json` into the `CLASPRC_JSON` secret, re-run the workflow. The deploy now prints exactly that on this error rather than Google's bare JSON | Any routing change reaching the filer. The script already in the project keeps running — it just stops being updated from here | **yes** — the repo and the deployed filer have been diverging for a fortnight |

## B · Blocked on an answer from EliseAI

| # | Item | What it blocks | Live and uncertain |
| --- | --- | --- | --- |
| B2′ | Owner says the unit is **days** — now published as "35–37 days", value-only. That reading is implausible for an AI's first response, so worth an eyeball against a fresh export before anyone acts on it | Grading Avg First Response Time | contained — value-only, basis on hover |
| B3 | What does EliseAI count as an "open task"? | Open Elise Tasks is mapped to the daily email's "Review N pieces of pending knowledge" (`OPEN_TASKS_FROM_KNOWLEDGE`). Flat at 4 for eight consecutive days while `escalations_open` moved 0→5→4→3→5→9→5→2 like a live queue should — then it moved: 4→13→16→16→16 across 08-28..09-01, which is the first evidence the number is not pinned. It now grades **below** rather than green, so the assumption is no longer flattering the score | **yes** — now red off the same assumption; 335 Third reports 1 below of 3 in its at-or-above tally and this is the one |
| B4 | **The export's `Delinquency Rate` does not survive contact with its own row.** Every export so far says `Paid-Up Units % = 100` and `Delinquent Units (1x/2x/3x+) = 0/0/0` at every property, while the same row's rate reads 17–25%. It also climbs in near-lockstep at all three occupied properties — Chorus 8.32→11.85→17.69, Landing 11.23→16.45→25.53, Madelon 9.63→13.98→21.40 across 08-19/08-26/08-31 — which is an accumulator rather than resident behaviour, and makes the number depend on the day the export was pulled rather than the month it covers. At the one property with a tie-out it is out by 3.8× (25.53% against the 6.7% the pipeline publishes), and the gap is widening (2.4× on 08-19, 5.5× against the 4.6% the workbook carried until the 2026-09-01 run). That run replaced the workbook tab with the Drive `rs_rp_DelinquencySummaryReport` of 2026-08-31 as the owner of that cell, so the export is now contradicting a same-week report rather than a hand-pasted tab — the comparison got stronger, not weaker. Ask EliseAI what the column measures and over what window | **Chorus (17.7%) and Madelon (21.4%) grade red on the live page from this column** — nothing else fills their AR cell. The Landing and Palma are shielded by the never-take-an-owned-cell rule | **yes** — two red AR grades off a column that contradicts its own row |
| B5 | ~~Does the export really see 3 of 37 units leased at 335 Third?~~ **Answered 2026-09-21: yes, as of now.** The 8.1% is exactly 3/37 and it is real; no lease has been *signed*, which is a different question from what the export counts as leased. The cell stays filled and ungraded under the lease-up rule, which is what it should be for a building that has not opened | nothing | no |
| B6 | The bands for Trade-out %, Closing Ratio and # of Renewals are written for a trailing-3-month basis, but the export grading them is trailing-1-month (owner, 2026-08-20) — a volatile month swings the grade more than the bands assume. **Closed for Trade-out % on 2026-09-17**: that cell moved to the Yardi lease tradeout report, which carries per-lease rows and so can be read over any window, and it is now graded on the trailing 3 months the band was written for (39.8%, 26 leases, Jul–Sep 2026, against the export's trailing-month 34.9%). The other two still come from the export and still grade on one month. Either re-band those for 1 month or accept the noise | How much a single month can move the remaining two grades | **yes** — two KPIs graded on a shorter basis than their bands assume |
| B7 | Ask EliseAI to add **Renewals Signed** and **Lease Expirations** columns to the building-metrics export — it publishes the rate and no count anywhere in its 79 columns. Today the `42/88.9%` cell splices the workbook tracker's count (to 2026-07-26) with the export's trailing rate; same-window columns would make the two halves one number, and give Chorus/Madelon a count at all | A single-basis # of Renewals cell for every property | contained — the split basis is stated on the cell |
| B8 | 335 Third's `Total Deliquency` arrived for the first time in the 08-31 export as **0.0%** and grades **exceeding** — trivially true across the 4 paid-up units of a building that has not opened. `LEASEUP_UNGRADED` covers the occupancy- and rent-derived cells but not delinquency, so the lease-up rule's own reasoning (an unopened building should not be scored on stabilised bands) is not applied to its mirror case, where not having opened reads as outperformance | 335 Third's at-or-above rate — 0.500 → 0.667 on this one cell — and the portfolio roll-up, 0.630 → 0.655 | **yes** — a green AR grade off 4 occupied units |

## C · Drive housekeeping (surfaced by the pipeline logs)

| # | Item | Detail |
| --- | --- | --- |
| C8 | ~~The Budgets folder held one year, and `fetch_drive` could not see into it~~ **Closed 2026-09-16.** `Landing 2025 Resi Budget.xlsx` and `Landing 2026 Resi Budget.xlsx` were dropped into a new `Budgets/Landing/` subfolder. They landed in a `Budgets/Landing/` subfolder with no `.xlsx` in their titles, and could not be read: neither the folder pass nor the sweep descended, and `name_patterns` claimed neither name. Fixed from both ends — the files were moved up into `Budgets` and their extensions restored in Drive, `name_patterns` became the single word `budget` to match the filer's own rule (`6e4d86c`, with `test_routing.py` check 10 as the guard), and the folder pass now reads one level of subfolders so the same grouping cannot strand a report a second time. `budget.json` now keeps a point per year, which is what lets the new **Budget vs Actual** card on the Portfolio tab draw a T12 window that crosses the calendar boundary — Sep 25–Aug 26 has a plan for all twelve months. The 2026 file is the same plan the earlier `12_Month_Budget_Accrual.xlsx` carried, to the cent, on all thirteen buckets |
| C3 | ~~22 files in `_Unsorted`~~ **Mostly moot as of 2026-09-11.** The rescue sweep now reaches the two families that matter: `name_patterns` on `Daily Leasing Reports` and `Renewal Tracker` pull their stranded copies out of `_Unsorted` by filename, so running `resortExistingFiles` is tidiness rather than recovery. Checked against the real 32-file `_Unsorted` inventory: 9 daily leasing reports and 1 renewal tracker are picked up. Note the four stranded Landing weeklies add **no new leases** — they are earlier, less complete snapshots of the two weeks already held, and the store keeps the fullest copy. What they do add is Madelon. Still unmatched on purpose: `Renewals since 9.15.25` (a different, unexamined report family, ~18KB and daily), `Daily Tracker`, `Prospect Reports`, box scores and demographics — none has a parser. | **The new routing rules are live in Apps Script** (deployed 2026-09-02T00:03:55Z, confirmed by the project's Drive modifiedTime). Two things remain, both cosmetic: the 22 files already in `_Unsorted` are sorted by running `previewRouting` → `checkFolders` → `resortExistingFiles` in the editor, and `BUILDING_INFO_FOLDER_ID` can be set as a script property so unit directories file into the library rather than `_Unsorted`. Neither affects a published number: the pipeline finds reports by filename wherever they sit |
| C4 | ~~The rent roll has never reached the pipeline~~ **Closed 2026-09-11.** `RentRoll09_11_2026.xlsx` was dropped into the `Rent Roll` folder and parsed on the first attempt — 263 units, both published totals tying to the report's own Total row to the cent, stopping correctly at the `Future Residents/Applicants` marker. `parse_rent_roll` needed no changes. It now feeds three new cards on the Landing (Drive) tab (Loss to Lease, Rollover Schedule, Largest Unit Gaps) through the `rent_roll` block in `metrics.json`. Two things it surfaced: the Yardi market-rent table has been revised up **+17.9% in eight weeks** while in-place rent moved +0.07%, taking loss to lease from 26.8% to 36.5% (see A8 — this is the evidence that item was waiting for); and Month to Month Leases can now be fed per property from the pipeline rather than the workbook, which is not yet wired |
| C5 | ~~Set `GDRIVE_REFERENCE_FOLDER_ID` and the `BUILDING_INFO_FOLDER_ID` script property~~ **Answered 2026-09-21: the unit directory is a legacy report that will never change.** So there is no fresher export waiting to be scanned and nothing is frozen — the figures are *final*, not stale. The Landing tab's `blocked` note now says that instead of naming this item, because an old date with no explanation reads as a feed that has stopped. Setting the two IDs is still what a *future* reference-tree feed would need; it buys nothing today | nothing | no |
| C9 | **The comp exports file themselves, because the deployed filer predates the `Comps` rule — this is A16's first measurable consequence.** The rule (`folder: 'Comps'`) was committed 2026-09-18T01:20Z, sixteen days after the last successful deploy; eight minutes later the live filer auto-derived `HelloData Simple` and `HelloData Full` at the top of the drop tree, and files arriving 2026-09-21 still land there. So A16 is no longer only a broken workflow — a routing rule written since 2026-09-02 has never taken effect, and this is what that looks like from Drive. **The repo side is now done** (2026-09-22): `SPLIT_INSIDE` files a comp export into `Comps/<market>/<Simple\|Full>` from its own name, `applySplit_` makes `resortExistingFiles` land it in the same place, and `test_routing.py` check 7d pins the real filenames and the depth contract against `fetch_drive`. Nothing of it reaches Drive until A16 is fixed and `resortExistingFiles` is run; meanwhile arrivals keep recreating the two top-level folders and the rescue sweep keeps claiming them, so no number is affected — only the tidiness of the tree |
| C10 | **The renewal trackers file at the top of `Daily Leasing Reports`, not under The Landing.** A11's per-property split matches on the words `config/properties.json` knows, and that building's are `The Landing` and `.Landing`; the tracker names itself `Landing 2025 Renewal Tracker - Full (N).xlsx`, so the whole family reads as having no property in its name. Found while generalising the split for the comps (C9) and **pinned as it behaves** in `test_routing.py` check 7d rather than quietly fixed, because the fix is not local: a bare `Landing` would have to be added as an alias in the property master, which also feeds `PROPERTY_WORDS` (the report-type stripper, which would then strip `Landing` out of every derived folder name) and `parse_comps`'s Align-building exclusion (which would then drop any comp building whose name contains the word). Cosmetic today — the split is for a human browsing Drive and the pipeline attributes by filename — and not live at all until A16 deploys. Your call whether the alias is worth those two side effects |
| C6 | Rename `Workorders - Mainentance ` — a misspelling *and* a trailing space, carried in Drive and `report_map.json` both. Three changes that must land together (Drive folder, `report_map.json`, the `.js` rule); `test_routing.py` fails if only one moves. Harmless today because no work-order report has ever arrived |
| C7 | **Renaming a folder a routing rule names creates a duplicate rather than moving the feed.** `getSubfolder_` short-circuits on `fromRule` before the `normalize_` reuse scan, so the filer recreates the rule's exact name beside the renamed one and `fetch_drive` logs `subfolder 'X' not found`. Harmless for the eight active `reports`-tree feeds — the rescue sweep still finds their files by filename wherever they sit — but **`Building Info` has no such backstop**: it is in the `reference` tree, which the sweep never reads (by design, so an archived July export cannot be republished as current), so renaming it stops the unit directory silently while the unit-gaps table keeps rendering frozen data. Renaming any registered folder is a three-place change (Drive, `report_map.json`, the `.js` rule) — `test_routing.py` enforces the last two, nothing can see the first. Auto-derived folders are unaffected: they are safe to rename, but the name regenerates unless a rule is added |

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
| D1 | ~~Weekly Leasing Reports — the RealPage rate tracker has never appeared~~ **Closed 2026-09-11 — and the premise was wrong twice over.** The report behind `Lease Detail` is not a RealPage export: it is Align's own `Daily Report- Week Ending <date>.xlsx`, and it lands in `Daily Leasing Reports`, not `Weekly Leasing Reports`. Nine copies were already in Drive. `parse_daily_leasing.py` reads its NEW LEASES block — unit, plan, sqft, new rent, concession and `PRIOR LEASE RATE`, the one field nothing else in the pipeline carries — and checks every row against the report's own trade-out arithmetic. Accumulating into `data/<slug>/leasing_detail.json`, one entry per week, and published through the `leasing` block to the **Trade-outs card on the Landing (Drive) tab** |
| D3 | Property Status — the two `BoxScoreSummary` exports are its first samples, and land here when C3 is deployed |
| D5 | AIRM - Yardi Rev Management |
| D6 | AP Analytics |
| D7 | `Workorders - Mainentance ` (note the typo and trailing space in the folder name) |
| D9 | ~~Renewal Tracker~~ **Closed 2026-09-11.** `Landing 2025 Renewal Tracker - Full (N).xlsx` has been filing into the Drive `Renewal Tracker` folder since 2026-09-02. `parse_renewal_tracker.py` reads all 36 month sheets (January 2024 forward — one file is the whole history) plus the `MTM` roster of 31 units. Its monthly offer counts tie out against the 2026-09-08 weekly email's own renewal table, 18/7/13/6 for Sep–Dec. Stored at `data/<slug>/renewal_tracker.json` and published to the **Trade-outs card on the Landing (Drive) tab** — its per-offer rows are what let that card average renewals the same way it averages new leases, which the workbook-fed card cannot do |
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
| F5 | **The `Landing` tab scrolls sideways at phone width** — 449px of content in a 390px viewport, from a `table.dt` that cannot shrink below its own columns. Same class of bug as the `.chartwrap` min-width note in CLAUDE.md, and the same fix: wrap the table in `.sc-scroll`, which is what the Portfolio tab's matrix and the new Market Comps tables use (both measure clean at 390). Found while probing the comps tab, not caused by it |
| F4 | CLAUDE.md still says the directory "counts **265 units** where the rent roll counts 263". Since `d2a5d36` split the PDR space out it publishes **266** — 263 apartments + 2 Yardi waitlist placeholders + 1 commercial record. Two lines to correct; no published number is affected |

## G · Found while building the Drive-only Landing tab

None is blocked on anyone, and each was visible only once a page had to state
per-cell provenance out loud. G3 is the one to take first: it is live.

| # | Item | What it blocks | Live and uncertain |
| --- | --- | --- | --- |
| G1 | **`measured[slug].kpis` names cells this feed did not fill.** `populate_scorecard` builds it from `prop.values`, which earlier runs also wrote, so a `--from-pipeline` run for The Landing records six KPIs against the Drive AR report when that report answers two — the other four are `--from-landing` fills off the workbook. Two consequences today: the data-flow page credits the AR report with "6 KPI cell(s)", and `scKpiAsOf` hands a workbook-fed cell the AR report's as-of date. The fix is to record the KPIs *this run* filled (the `filled` loop already knows them) as a separate key, leaving `kpis` alone so the arrivals table does not change shape. Until then `SCD_DRIVE_FEEDS` in `index.html` narrows the family by hand | Honest per-cell provenance anywhere the page reads `<prefix>kpis` | contained — the Drive tab narrows it explicitly and says so |
| G2 | **Publish an aggregate delinquency block.** `data/<slug>/delinquency.json` is gitignored because it is unit level, so the only delinquency numbers that reach the page are the two scorecard cells — the rate and the 30/60/90 split. But `summary` already holds the aggregate the aging chart needs (gross owed, the four buckets, unit counts) and carries no names. Publishing that block into `metrics.json` from `store_report`'s already-scrubbed output would give the Drive tab a real aging chart and a gross-owed figure, and cost nothing in exposure — the aggregates are strictly less than what the scorecard cell already publishes | The Drive tab's delinquency card is a rate and a split where it could be the chart The Landing has | no |
| G6 | **Is a 10% controllable overspend the story the scorecard should be telling?** The Budget vs Actual card's basket presets put the two side by side for the first time: Sep 25–Aug 26 the controllable basket is **+$170k / +10.3% over** while the whole basket is **−$44k / −1.0% under**, the difference being Aug's tax true-up. The scorecard's `Budget Variance %` already grades the controllable basket, so it is not wrong — but it grades calendar-YTD, and the card's T12 is the window a reader compares against the rest of the Portfolio tab. Worth a look at whether the +10.3% is concentrated (Jul 26 alone is +$36k on payroll) or spread | Nothing on the page; this is a question about the building, not the pipeline | no — both figures are correctly based and both are stated with their basket and window |
| G3 | ~~A `--from-landing` run took The Landing's delinquency cells back off the Drive report, unnoticed.~~ **Answered 2026-09-21: the Drive pipeline owns these cells outright** — "there shouldn't be anything pulling from a 6 week old workbook". `--from-landing` no longer reads the workbook's delinquency tab at all (its reading is kept as `delq_workbook`, never published), the AR report records under its own `delq_` family so the last run can no longer relabel it, and `kpis` now names the cells *this* run filled rather than every cell any run ever filled — which closes **G1** for this family. Verified by running `--from-landing` against the live scorecard: 3.9% and 5,121/5,251/1,059 survive where they used to be replaced by a workbook's 4.6% | nothing | no |

## H · How the scorecard actually refreshes

Found 2026-09-15 by checking the published cells against what a fill would
produce today. H1 closed 2026-09-16; what is left is about *where* a cell is
read from rather than what it means, which is why it does not show up as a
wrong-looking number on the page.

| # | Item | What it blocks | Live and uncertain |
| --- | --- | --- | --- |
| H2 | **The three workbook-fed KPIs cannot follow the statement at all.** Loss to Lease %, NOI Margin % and Concession Load % are read from `docs/landing.json`, which is refreshed by hand in Excel, so they are pinned to the workbook's last extract (Jul 2026) no matter how many statements arrive. The pipeline now carries the same series to the cent — `metrics.json` `rent_capture` is on Aug 2026, thirteen months — so all three could be sourced from it and would then move on their own. That is the rewiring of `facts_from_landing` flagged when the block was built: not hard, but it decides which feed owns those cells, so it wants doing with G3 rather than before it | Three KPIs that move when a report arrives rather than when someone opens Excel | contained — the figures are right for the month they name |

## Closed

2026-09-18 — **a lineage page regenerated outside CI no longer downgrades a
gitignored feed (G4).** `evidence_for_store` read `data/<slug>/*.json`, and the
rent roll's and delinquency's stores are gitignored because they are per-unit
and arrive with resident names — so any fresh clone reported the rent roll,
live since 2026-09-11, as `waiting`, and would have published a map saying a
working feed had never arrived. Worked around by hand last time. Fixed now:
`evidence_from_published` falls back to the published aggregate in
`metrics.json`, which is committed and carries all three fields the evidence
reads, and the row says where it was read from. Verified by regenerating in
this checkout — rent roll back to `live`, and the delinquency flows'
attribution now follows `scorecard.json` as it stands rather than as it stood
when the file was last written in CI.

2026-09-17 — **PSF vs Other Properties removed, closing A4.** The card compared
335 Third's $4.01/sqft against nine named comps averaging $3.85, and every one
of those figures was typed in by hand with no known date — the card said so on
its own face (`HAND-ENTERED, DATE UNKNOWN — LIKELY STALE`) and A4 had been open
since, waiting for a market-survey export that never came. Removed by request
rather than rebuilt, so the question A4 asked no longer has anything to block:
the card, its `t-psf` table and the `psf_vs_peers` block are all gone, and
`build_metrics` only writes the blocks it derives, so the block stays gone
without anything to remember. If a market survey does arrive later this is a
new card, not a revived one. The `psf` formatter on the data page stays — the
rent roll's market and in-place $/sqft, the leasing tables and the workbook's
own figures all use it, and none of them came from this card.

2026-09-16 — **the daily cron published four-hour-old code over the day's work.**
The Budget vs Actual card read "no budget has reached the pipeline" with two
budgets sitting parsed in Drive. Drive was fine and nothing had been renamed:
run #86 checked out `b8bcf4d` at 15:20:19Z, ran 4h34m (the Drive fetch is nearly
all of it) and committed at 19:54:51Z. Its `build_metrics.py` predated the
budget work, so it wrote a `metrics.json` with **no `budget` block**, rewrote
`data/the-landing/budget.json` in the older single-year shape, and — because the
push-retry loop replays this run's files over whatever landed since — dropped a
hand-added EliseAI day and the scorecard cells behind it. Four commits undone
with every step green and nothing in the log to say so; the cadence makes it
routine rather than unlucky, since runs #83–#86 each took four to five hours.
`update.yml` now re-syncs to `main` **once, right after the fetch** — the one
place where the sync is cheap (everything below it is minutes), the reports
survive it (`_downloads/` is gitignored), and it takes the newer data as well
as the newer code, which is the half that saves a hand-added feed. Verified
against both a normal and a genuinely shallow clone. The clobbered data was
rebuilt from the same two budget files and the store now carries 2025 and 2026,
each tying out to the cent. Residual: the minutes between building and pushing
are still the replay's, which is a window worth watching but not one that
undoes a morning.

Two items went with it. **G5** self-corrected exactly as predicted — the run
restated `Budget Variance %` from `+$116,402/+12.1%` (Jan–Jul) to
`+$152,298/+14.2%` (Jan–Aug), and the same figure comes back from the per-year
store, which is the check that the new selection picks the statement's own year.
**H1** was fixed by `200198d`: the cron runs `--from-landing` before the
`--from-pipeline` loop, so the five cells it owns alone now follow the
statement — Controllable OpEx/Unit moved to $6,757 with it.

One thing `build_lineage.py` had quietly got wrong came out of the same repair:
`evidence_for_store` knew the flat shape and the `points` shape, so the per-year
budget store read back as `as_of: null, source_file: null` and the page credited
the budget flow with an arrival it could not name. It reads `years` now, and the
detail line names every year on file rather than a single date, because a store
that accumulates years is answering "is there a plan for the month I am looking
at" and one date cannot say that.

2026-09-11 — **the monthly loss-to-lease series, without the rent roll.** The Drive
tab listed Loss to Lease as unrefreshable, needing per-unit market rent against
in-place rent. That was wrong: the card plots accrued rental income against market
rent potential, and both are GL lines in the T12 statement the pipeline already
fetched daily, under `410400-0000 RESIDENTIAL RENTAL INCOME`. The analyst
workbook's Rent Capture block turned out to be that section retyped — all six
series agree **to the cent** across the twelve overlapping months, and both TTM
totals match exactly. `parse_t12_statement.rent_capture` now reads it, flipping the
deduction signs to the workbook's convention so one renderer draws either source;
every unnamed leaf under `410400-` is summed into `other` and the section must
reproduce its own `410499-9999` month by month or it is refused. The Align tree's
five counterparts come from `coa_map` and are read, but that tree has no section
total, so income is derived there and the point says so — **still unverified
against a real Align statement**. 21 fixture-free checks; the basis-cut guard
verified by mutation. Spawned H2.

2026-09-03 — **Budget Variance % and Concession Load % wired.** Budget Variance is
calendar-YTD actual controllable opex against the same months of the year's budget,
printed as `$ nominal/% variance` and graded on absolute magnitude per its own band;
the budget is the Yardi `12_Month_Budget_Accrual.xlsx` now registered as a Drive
`Budgets` folder, parsed by `parse_budget.py` reusing the T12 parser's anchors and
tie-outs and refusing a file that is not a Jan–Dec budget. Concession Load is
concessions over market rent potential less loss to lease less vacancy loss, the
owner's equation — which freed A6, since that cell no longer waits on the burn-off.
Both restate a `how` the sheet wrote for a different basis and keep the sheet's
wording in `how_workbook`. Note both bands' cutoffs predate the 2026-08-28
controllable basket (A9).

2026-09-02 — a new report type now makes its own folder. Anything matching no routing rule used to land in `_Unsorted`, which is how four weeks of arrivals went unnoticed; the filer now derives a report type from the filename — stripping the arrival date, copy suffixes, `30Days`/`60Days` window markers, every property name, alias and code, and any leftover date — and files under that. It refuses to guess below four characters, reuses a folder that normalises the same rather than starting a sibling, caps itself at five new folders per run, and never overrides a rule. `fetch_drive` then flags the folder as `NEW REPORT TYPE … not in report_map.json`, which is the daily prompt to write a parser. Derived names are clumsy on purpose-ish — the point is that a wrong one is visible in Drive and fixed by adding one rule, rather than invisible in `_Unsorted`. `test_routing.py` covers 14 naming cases plus the property-list contract, each verified to fail when its guard is removed.

2026-09-02 — A13: the filing script deploys itself. `CLASPRC_JSON` and `APPS_SCRIPT_ID` are set, and `deploy_filing_script.yml` pushes `gmail_drive_filing.js` into the Apps Script project on every change, after `test_routing.py` passes — so a routing table that disagrees with `report_map.json` cannot reach Google at all.

It does **not** use clasp, which cost three failed runs for reasons unrelated to the job: `clasp pull --force` is not a valid flag, and the credential clasp 3.x writes (a `{"default": {...}}` profile store) is unreadable by clasp 2.4.2, which fails with "Cannot read properties of undefined" and explains nothing. `scripts/deploy_apps_script.py` calls the two REST endpoints clasp wraps, using only the standard library, and finds the credential fields under any of their spellings so every clasp layout works. It never writes the manifest and never deletes a file; `test_deploy_apps_script.py` covers 17 cases against a stubbed HTTP layer.

Getting the credential needed Google Cloud Shell — a work laptop blocked the Node install, and GitHub Codespaces was disabled for the org at the time. Worth knowing if it ever has to be reissued.

2026-08-31 — folder organisation is no longer load-bearing. `fetch_drive` does its normal folder pass and then sweeps the drop tree for unclaimed files matching an entry's `name_patterns`, so a report filed into the wrong folder still reaches its parser and the log says where it was found. Drive's folders are untouched — they are still what the Gmail filer maintains and still how source data is pulled by hand — they just stopped being the only way a report can be identified. The sweep will not read the reference tree, a folder in `NEVER_SWEEP`, a file the folder pass took, a name two report types claim, or over an existing download; `test_fetch_sweep.py` checks all twelve properties, with the two archive protections verified independently. This is what made the deploy-automation question optional rather than load-bearing: the script now only affects tidiness.

2026-08-31 — C5's first reading, withdrawn: `Building Info` had not "drifted out" of the scanned folder by accident. It sits in the Drive library on purpose — keys and long-lived reference documents — and the owner confirmed it stays there. The pipeline now reaches into the library for it (a second `reference` tree in `fetch_drive.py`) rather than the folder being dragged into the drop tree. Filed as a correction because the original item recommended exactly the wrong move.

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

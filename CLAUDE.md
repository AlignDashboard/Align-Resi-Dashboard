# Align Resi Dashboard

Static dashboard published with GitHub Pages, fed by a daily metrics pipeline.

## Workflow

**Commit and push small changes directly to `main`. Do not open a pull request
unless I ask for one.** This is a solo repo with no CI and no required reviews,
so a PR per change just adds a merge step. Push straight to `main` and tell me
what changed.

Use a branch and a PR only when I ask, or when a change is large enough that I'd
want to look it over before it goes live — a redesign, restructuring the data
pipeline, anything touching `scripts/`.

## Layout

| Path | Purpose |
| --- | --- |
| `docs/index.html` | The whole dashboard: markup, CSS, and Chart.js rendering in one file |
| `docs/metrics.json` | Data the page fetches at load; written by the pipeline, not by hand |
| `scripts/` | `fetch_drive.py` pulls source reports, `build_metrics.py` writes `metrics.json` |
| `config/` | `properties.json` and `report_map.json` — property list and report routing |
| `data/` | Raw fetched reports, per property |

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
- `metrics.json` values flow into the DOM. When rendering anything from it,
  prefer `textContent` / `createElement` over `innerHTML` so pipeline data
  cannot inject markup.
- Charts come from a Chart.js CDN script tag. Sandboxed environments often block
  it, producing `Chart is not defined` — that is an environment artifact, not a
  page bug.
- Verify UI changes by serving `docs/` and driving the page in a real browser
  through the password gate, not by reading the diff alone.

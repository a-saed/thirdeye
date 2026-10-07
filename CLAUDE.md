# Third Eye — project context

## What this is

A location-intelligence product for Greater Cairo + Giza + Qalyubiya +
Alexandria, built on free and open geodata.

The **feasibility study is closed** (2026-08-21). Its verdict was a qualified
yes: the data supports a *descriptive* product, and the *predictive* thesis is
unproven because the tests that would have measured it never ran. Read
`research/VERDICT.md` before making product claims — several intuitive
statements about this data are measurably wrong.

## Layout

```
research/     FROZEN. The study: test.md, VERDICT.md, output/, scripts/.
              Provenance for every rule in the pipeline. Do not extend it,
              do not run new analysis in it.
pipeline/     Python, batch, runs monthly.
  sources/    one module per source (overture, fsq, open buildings, ghsl, ...)
  resolve/    entity resolution, name matching
  aggregate/  H3 cells + metrics
  qa/         QA gate + regression fixtures
  config/     coverage polygon, categories, thresholds, shared _common
api/          Go. Loads parquet into RAM at startup, serves from maps.
web/          React + MapLibre
data/         gitignored. raw/ (immutable snapshots) and derived/
docs/
```

**`research/` is frozen.** Its scripts are kept as provenance, not as live
code — the working modules were *moved* into `pipeline/`, so most
`research/scripts/*.py` no longer import cleanly. That is expected. Their
outputs in `research/output/` are the durable artifact. If you need something
from there, port it into `pipeline/` rather than reviving it in place.

## Hard rules

1. **Never fabricate a number.** If a query fails, times out, or returns
   nothing, say exactly that. A reported failure is a valid result. This rule
   caught real problems repeatedly during the study.
2. **Free data only.** No paid APIs or billable services. Free accounts with
   no card are fine; a "free" tier whose *programmatic* access is paid is not.
3. **Provenance is not optional.** Every number the API returns carries
   confidence, contributing sources, and `as_of`. The Go types enforce this
   structurally — do not add a path that returns a bare float.
4. **Validate out-of-sample before trusting any matcher.** The duplicate
   matcher scored 100% on its in-sample suite and **25%** against fresh
   human verdicts. In-sample suites are regression guards, not evidence.
5. **Report per district / per cell.** Never average across districts —
   data quality varies enormously by neighbourhood income, and averaging
   hides exactly the thing that matters.
6. **State the direction of "good" explicitly** for every derived metric.
   More population good, more competitors bad. Getting this backwards
   silently invalidates everything downstream.

## Architecture decision: no database

res-8 + res-9 is **79,041 cells**; `h3_metric` is **109,996 rows**. On disk
the four parquet tables total **6.11 MB** compressed. The Go API loads them
into maps keyed by h3 index at startup and serves every request as a hash
lookup plus an h3 k-ring. No PostGIS, no DB server, no hosting cost.

Radius queries are computed **at read time** via k-ring so radii stay
flexible, rather than precomputed per radius.

**The exception:** `h3_metric_history` stays on disk and is queried lazily via
parquet-go streaming, never loaded whole (`api/history.go`; the DuckDB
driver was skipped deliberately — it is cgo, see the note in that file).

Restart the API after a monthly pipeline run; there is no hot reload. **On
Cloud Run this means rebuild and redeploy**, not restart: the parquet tables
are baked into the image because a Cloud Run instance is the image and nothing
else. The upside is that a bad data build rolls back by routing traffic to the
previous revision.

## Findings that constrain the product

These are measured. Contradicting them requires new evidence, not intuition.

- **84–86% of cells are single-source for business data.** Only 47–54% have
  both sources at all, and where both exist the median count-agreement ratio
  is ~0.50 — the sources typically disagree by 2×.
- **Overture and Foursquare are not independent.** Foursquare is itself an
  Overture contributor (17.1% / 10.6% / 1.3% of Overture records in the three
  Cairo study districts). "Corroborated" means partially-overlapping feeds
  agree. Worse, the overlap is largest exactly where corroboration is most
  achievable.
- **Zero OSM contribution** in six districts across two cities.
- **The growth signal fires only on greenfield.** Saturated districts (≥40%
  built-up) read flat because they are built out — that means "no new
  construction", not "no commercial change".
- **Position accuracy is block-level**: median 10.2 m, p90 58.5 m, max 381.7 m.
  Fine for 500 m catchments, unsafe for address-level claims.
- **Duplicates are not merged.** 3.2–6.3% record inflation is disclosed, not
  fixed. Do not add a dedup step without fresh out-of-sample validation.
- **Overture's `confidence` field is withdrawn as a quality proxy.** It
  tracked coverage quality in Cairo and does not in Alexandria.
- **Land fraction is required.** Alexandria Corniche cells are ~half sea
  (0.52 measured). Every catchment metric divides by land area, never raw area.
- **Population is a 2023 vintage** served as present-day, flagged stale in
  cells with measured construction since.
- **Overture's category vocabulary changed on 2026-09-23.** The `categories`
  column was REMOVED; `taxonomy` succeeds it and is *not* a rename — it
  revises 31% of values in our bbox (`dentist`→`dental_clinic`,
  `mosque`→`muslim_place_of_worship`, `car_dealer`→`auto_dealer`). Of the five
  counted groups only `restaurant` is touched, by two renames worth 80 places;
  `pipeline/config/categories.py` now carries **both** spellings so old and new
  snapshots stay comparable. `archive_release.py` detects the column per
  release and records it as `_category_source` in each manifest.
- **The same release backfilled previously-NULL categories, and it is not
  growth.** Cafe counts rose 18% (8,127 → 9,587) between 2026-08-19.0 and
  2026-09-23.1, but **1,304 of the +1,460 (89%) are places that existed in
  August with a NULL category**. Only 270 are new IDs. The backfill is
  concentrated almost entirely in one group: 13.6% of September cafes came
  from NULL, against 1.0% restaurant, 0.5% grocery, 0.1% pharmacy, 0% gym.
  **The bulk-import detector does not catch this** — `BULK_JUMP_PCT = 40.0`
  in `pipeline/qa/qa.py` and this is 18%. Do not lower that threshold; it is
  tuned for a different signature (jump then flat). Before `h3_metric_history`
  is rebuilt with this snapshot, add a null-backfill check: the share of a
  group's count whose category was NULL in the prior snapshot.

## Monthly operations

`pipeline/sources/archive_release.py` **must run monthly.** It failed silently
on 2026-09-23 (Overture dropped `categories`; the job exited leaving an empty
snapshot directory) and nobody noticed for two days — the argument for
scheduling it is that a scheduler *notices*, not that it runs. Overture's S3
retains only ~2 releases and the community mirror lags by months; a release
missing from both is gone forever (2026-06-17.0 already is). The 23-snapshot
archive exists only because releases were captured, not merged.

**Scheduled since 2026-10-01:** `.github/workflows/archive.yml` runs weekly,
archives any new release to `gs://thirdeye-demo-260906-data/raw/overture/`
(the archive of record, not the laptop), and fails red, which emails, on any
error or a snapshot under 100k rows. The repo is public, so GitHub disables
the schedule after 60 days without a push.

## Deployment

**Live at https://thirdeye-466032735471.us-central1.run.app** (Cloud Run,
`us-central1`, 1 GiB, scale-to-zero, project `thirdeye-demo-260906`). Deployed
2026-09-07.

**The public link is https://thirdeye-app.web.app** (Firebase Hosting, a pure
rewrite to the same service; see `docs/DEPLOYMENT.md`). Rate limiting
identifies the visitor correctly through both entrances, verified in
production 2026-10-07. Share this one, not the run.app URL.

The 404-status bug is **fixed** — `api/spa.go` serves the SPA and gives unknown
paths a 404 status while still returning the app shell, guarded by
`api/spa_test.go`. Still open: a budget kill-switch (GCP budget alerts
notify, they do not stop spending), and narrowing the deployer's storage role
(see `docs/DEPLOYMENT.md`, "Still open").

Deploy: `gcloud builds submit --tag <repo>/api:vN . && gcloud run deploy
thirdeye --image <repo>/api:vN --region us-central1`. See
`docs/DEPLOYMENT.md` for the gotchas — several cost real time to find.

## Known gaps

- ~~`h3_metric_history` is not built yet~~ — **out of date**. It is built
  (`data/derived/h3_tables/h3_metric_history_res{8,9}.parquet`, 23 snapshots,
  ~1.2M rows) and served lazily by `api/history.go` via parquet-go streaming
  rather than DuckDB — see the note at the top of that file. Corrected
  2026-09-10.
- ~~`api/` is a scaffold~~ — **out of date**. Parquet loading and
  `BuildReport` are implemented and serving in production: the deployed
  service loads 310,190 places and both resolutions in ~1s and returns real
  reports. Corrected 2026-09-07.
- Open Buildings is ingested for **2023 only**. Multi-year needs the
  documented super-pixel optimisation in `pipeline/sources/ob_worker.py`.

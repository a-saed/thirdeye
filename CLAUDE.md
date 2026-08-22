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
DuckDB, never loaded whole. (Not built yet — see below.)

Restart the API after a monthly pipeline run; there is no hot reload.

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

## Monthly operations

`pipeline/sources/archive_release.py` **must run monthly.** Overture's S3
retains only ~2 releases and the community mirror lags by months; a release
missing from both is gone forever (2026-06-17.0 already is). The 23-snapshot
archive exists only because releases were captured, not merged.

## Deployment

Not deployed yet. `docs/DEPLOYMENT.md` records the open tasks, including the
404-status fix (the SPA fallback currently returns 200 for unknown paths) and
the missing scheduler for the monthly archive.

## Known gaps

- `h3_metric_history` is **not built yet**. The 23 archived Overture snapshots
  are on disk in `data/raw/overture/` but have not been aggregated into a
  history table.
- `api/` is a scaffold: types, store shape and handler exist; parquet loading
  and `BuildReport` are unimplemented and fail loudly rather than serving
  zeros.
- Open Buildings is ingested for **2023 only**. Multi-year needs the
  documented super-pixel optimisation in `pipeline/sources/ob_worker.py`.

# Third Eye

Location intelligence from open data — and an honest account of where that data
isn't.

Businesses, population and construction trend for any point on the map. Every
figure names its sources and its date, and where the record runs out the map
stays grey rather than guessing.

> **Read [`research/VERDICT.md`](research/VERDICT.md) first.** Before any of
> this was built, a two-week feasibility study tested whether free geodata is
> good enough for the job. The verdict was a *qualified yes*, and several
> intuitive statements about this data turned out to be measurably wrong. Every
> rule in the pipeline traces back to a finding in there.

## What it answers

Pick a point and get, for a walkable catchment: how many competitors of a given
category the sources list, how many people live within reach, how densely built
the area is, whether it is still being built, and how much each of those numbers
can be trusted.

Then it shows you the individual records behind the count, so someone who knows
the street can check whether we are wrong.

## What this is not

- **No foot traffic.** No free source measures it. A busy street and a dead one
  look identical here.
- **No rents or property prices.** No open source covers them for this region.
- **No predictions.** The study found the predictive thesis unproven, and
  nothing here forecasts anything.
- **Not address-level.** Cross-source position disagreement is 10.2 m median
  and 58.5 m at p90 — fine for a 500 m catchment, useless for "this side of the
  street".
- **Not an exact count.** Duplicates are disclosed, never merged: 3.2–6.3%
  record inflation, stated on every report.

## Quickstart

Requires Python 3.10+, Go 1.23+, Node 20+.

```bash
git clone git@github.com:a-saed/thirdeye.git && cd thirdeye

python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # add a Foursquare token; free, no card

# Rebuild the data from public sources. Takes a while the first time.
.venv/bin/python pipeline/sources/ingest_static_sources.py
.venv/bin/python pipeline/aggregate/h3_pipeline.py
.venv/bin/python pipeline/aggregate/export_places.py
.venv/bin/python pipeline/aggregate/export_coverage_geojson.py

cd web && npm install && cd ..
./scripts/dev.sh              # API on :8080, web on :5173
```

**No data is committed** — see [docs/LICENSING.md](docs/LICENSING.md) for why.
The pipeline reproduces everything from public sources, which is a stronger
claim than shipping a snapshot: you can rebuild it and check our numbers rather
than trusting them.

## Architecture

```
sources ──> pipeline (Python, monthly) ──> parquet ──> API (Go) ──> web (React)
```

No database. The four parquet tables total ~6 MB compressed; the Go API loads
them into maps keyed by H3 index at startup and answers every request as a hash
lookup plus a k-ring walk. Radius queries are computed at read time so catchment
sizes stay flexible. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Coverage

Live regions come from `config/regions.json` and are rebuilt by the pipeline —
no place name is hardcoded in the UI. Adding a region is a config change plus a
pipeline run, not a code change.

## Licence

Code is MIT. **Data is not distributed here** and its sources carry their own
licences, some with obligations that attach to derived databases. See
[docs/LICENSING.md](docs/LICENSING.md).

# Licensing

**Code and data are separate questions, and they have different answers.**

## Code — MIT

Everything in `pipeline/`, `api/`, `web/`, `scripts/`, `config/` and `research/`
is MIT licensed. See [`../LICENSE`](../LICENSE).

## Data — not distributed here, deliberately

**No derived data is committed to this repository.** `data/` is gitignored, and
so are the derived artefacts that live outside it (`coverage-res8.geojson`, the
land-fraction tables, the study's parquet outputs).

Two reasons, and the second is the one that matters:

1. Tens of megabytes of binary in git bloats every clone forever and produces
   meaningless diffs.
2. **The sources carry mixed licences, and some attach obligations to derived
   databases.** ODbL in particular has share-alike provisions that can follow a
   derived database. Deciding exactly where those obligations land for a
   multi-source aggregate is a genuine legal question, and nobody should have to
   answer it in order to read this code.

The pipeline reproduces everything from public sources. That is a **stronger**
claim than shipping a snapshot: anyone can rebuild the data and check our
numbers rather than trusting them.

## Sources, and what each one obliges

| source | provides | licence | what it obliges |
|---|---|---|---|
| [Overture Maps](https://overturemaps.org) | business listings | ODbL (places theme) / CDLA-Permissive-2.0 (others) | Attribution. **Share-alike may follow a derived database** — the reason data is not committed here. |
| [Foursquare OS Places](https://location.foursquare.com/products/open-source-places/) | business listings | Apache 2.0 | Attribution and licence notice. No share-alike. |
| [Kontur Population](https://data.humdata.org/dataset/kontur-population-dataset) | population, native H3 res-8 | CC BY 4.0 | Attribution. Derived from GHSL + OSM, so OSM's ODbL sits upstream of it. |
| [GHSL](https://human-settlement.emergency.copernicus.eu/) | built-up surface, land mask | CC BY 4.0 | Attribution. |
| [Google Open Buildings](https://sites.research.google/open-buildings/) | building footprints | CC BY 4.0 | Attribution. |
| [OpenStreetMap](https://www.openstreetmap.org/copyright) | place names, basemap | ODbL | Attribution. **Used for labels only** — never counted, compared, or fed into a metric. |
| [CARTO](https://carto.com/attributions) | basemap style | CARTO terms | Attribution, displayed in the map's ⓘ control. |

## Attribution in the product

Attribution is a **licence condition, not a credit roll**. It appears in three
places and must not be removed:

- The map's ⓘ control carries the OpenStreetMap and CARTO credits.
- The footer lists every source with its licence.
- Every number the API returns carries `contributing_sources` and
  `source_snapshots` — provenance is structurally required by the Go types,
  with no code path that returns a bare float.

## If you redistribute the derived data

You are then distributing a derived database built partly from ODbL sources.
Work out your own obligations before doing so; this project avoids the question
by not distributing it at all.

"""
Exports the res-8 coverage layer as GeoJSON for the map.

WHY GEOJSON, NOT PMTILES: res-8 across all four governorates is 9,938 cells.
That is small enough to serve as a single static file — gzipped it is a few
hundred KB — so the map needs no tile pipeline, no tile server, and no API
call to render. PMTiles would be the right answer at res-9 (69,103 cells) or
if this grew to several cities; it is unnecessary weight here.

The map must render WITHOUT hitting the API, so every property it needs is
baked into the file.

Confidence shown is the BUSINESS track (business_count.total), because that
is the layer the study found weakest and the one a user most needs to see
before trusting a location. Cells with no business metric are 'unavailable',
which is deliberately distinct from a count of zero.

THE INHABITED FILTER, AND WHY IT EXISTS.
Coverage over the full operational polygon is a misleading denominator. The
polygon is the four governorate boundaries plus a 2 km dilation ring (so
catchments near an edge are not silently truncated), and it therefore contains
open desert, the dilation ring itself, and a long tail of Nile-valley farmland.
Those cells have no business data because there are no businesses, not because
the sources failed. Scoring them as coverage failures understates the product.

The filter is POPULATION >= 100 AND BUILT-UP >= 5% OF CELL AREA, and it needs
BOTH because each alone admits a different kind of non-market cell:

  - population alone: at res-8 a cell is 0.74 km2, and Nile-valley farmland
    carries real residents spread through fields. pop>=100 keeps 54.9% of
    cells - more than half the polygon - including large stretches of Delta
    agriculture with no urban fabric to put a shop in.
  - built-up alone: builtup>=5% keeps 43.5%, and admits industrial zones,
    desert-edge compounds under construction, and the Cairo/Alexandria
    airports and cemeteries - built, but not a market.

Requiring both keeps 4,007 cells (40.3%). The thresholds are floors, not
optima: 100 people in 0.74 km2 is ~135/km2, low enough to keep genuine village
fabric, and 5% built-up is ~37,000 m2 of building footprint, which is a
settlement rather than a scatter of structures.

SENSITIVITY, so the number is not read as precise. Measured 'no business
data' share under every filter shape that requires urban fabric:
    all cells (no filter)          55.8%
    pop>=100 AND builtup>=5        22.3%   <- shipped
    (that) OR builtup>=15          22.5%
    (that) OR builtup>=10          22.5%
    builtup>=5 alone               23.5%
    pop>=100 OR builtup>=10        36.4%
The result is insensitive to the exact definition: everything in the first
family lands at 22-24%. Only the last line moves it, and it moves it by
re-admitting the farmland the filter exists to remove - a disjunction lets a
cell qualify on population alone, which is precisely the Delta-agriculture
case. So the shipped filter is chosen for being the simplest member of a
family that all agree, not because 100 and 5 are special numbers.

WHAT THE FILTER DELIBERATELY GETS WRONG.
It is defined only on population and built-up, never on whether WE have data
for the cell. Defining the served area by where our sources happen to have
records would guarantee a good coverage number by construction - the same
circularity that made an agreement tolerance set at the observed median
disagreement unusable.
The cost is real and is 1.7% of all business records: 1,276 excluded cells
hold at least one record, and the largest is a Giza cell with 164
corroborated businesses at 21% built-up but only 48 residents - new
commercial development in the 6th October / Sheikh Zayed corridor, which is
genuinely served and genuinely not residential. Adding an escape hatch for
those cells (variant 'OR builtup>=10' above) recovers most of the records and
changes the headline by 0.2pp, which is not worth complicating the definition
for. The exclusion is a known, bounded, stated error rather than a hidden one.
"""
import json
import sys
from pathlib import Path

import h3
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.config._common import ROOT, threshold

TABLES = ROOT / "data" / "derived" / "h3_tables"
OUT = ROOT / "web" / "public" / "coverage-res8.geojson"
REGIONS_IN = ROOT / "pipeline" / "config" / "regions.json"
REGIONS_OUT = ROOT / "web" / "public" / "regions.json"
RES = 8

# See the module docstring for why both conditions are required.
POP_MIN = threshold("inhabited", "population_min")
BUILTUP_PCT_MIN = threshold("inhabited", "builtup_pct_min")

CLASSES = ["corroborated", "single_source", "unavailable"]


def split(frame):
    """Confidence counts + percentages for one subset of cells."""
    counts = frame.confidence.value_counts()
    total = len(frame)
    return {
        "cells": int(total),
        "counts": {k: int(counts.get(k, 0)) for k in CLASSES},
        "pct": {k: round(100 * counts.get(k, 0) / total, 1) for k in CLASSES}
        if total
        else {k: None for k in CLASSES},
    }


def main():
    cells = pd.read_parquet(TABLES / f"h3_cell_res{RES}.parquet")
    metrics = pd.read_parquet(TABLES / f"h3_metric_res{RES}.parquet")

    biz = metrics[metrics.metric == "business_count.total"][
        ["h3_index", "value", "confidence", "overture", "fsq", "agreement_ratio"]
    ].rename(columns={"value": "business_count"})
    pop = metrics[metrics.metric == "population"][["h3_index", "value"]].rename(
        columns={"value": "population"}
    )
    df = cells.merge(biz, on="h3_index", how="left").merge(pop, on="h3_index", how="left")

    # No business metric at all is NOT zero businesses - it is no coverage.
    df["confidence"] = df.confidence.fillna("unavailable")
    df["business_count"] = df.business_count.fillna(0)
    # Missing population IS zero here: Kontur covers the whole country, so an
    # absent cell is unpopulated rather than unmeasured.
    df["population"] = df.population.fillna(0)

    df["inhabited"] = (df.population >= POP_MIN) & (df.builtup_pct >= BUILTUP_PCT_MIN)

    feats = []
    for r in df.itertuples():
        try:
            boundary = h3.cell_to_boundary(r.h3_index)
        except Exception:
            continue
        ring = [[lng, lat] for lat, lng in boundary]
        ring.append(ring[0])
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {
                "h3": r.h3_index,
                "conf": r.confidence,
                "n": int(r.business_count),
                "gov": r.governorate,
                "sat": r.saturation_class,
                "land": round(float(r.land_fraction), 3),
                # inh drives the map's "hide uninhabited" toggle. 1/0 rather
                # than true/false to keep the file small.
                "inh": 1 if r.inhabited else 0,
                "pop": int(r.population),
                "bu": round(float(r.builtup_pct), 1),
            },
        })

    fc = {"type": "FeatureCollection", "features": feats}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(fc, separators=(",", ":")))

    inh = df[df.inhabited]
    all_split, inh_split = split(df), split(inh)

    print(f"wrote {OUT} — {len(feats):,} hexes, {OUT.stat().st_size/1048576:.1f} MB")
    print(f"\ninhabited filter: population >= {POP_MIN:.0f} AND builtup_pct >= {BUILTUP_PCT_MIN:.0f}")
    print(f"  {inh_split['cells']:,} of {all_split['cells']:,} cells "
          f"({100*inh_split['cells']/all_split['cells']:.1f}%)\n")
    print(f"  {'class':16s}{'all cells':>20s}{'inhabited only':>20s}")
    for k in CLASSES:
        a, i = all_split, inh_split
        print(f"  {k:16s}{a['counts'][k]:8,} ({a['pct'][k]:4.1f}%){i['counts'][k]:9,} ({i['pct'][k]:4.1f}%)")

    by_gov = {}
    print(f"\n  inhabited-only, per governorate:")
    print(f"  {'governorate':14s}{'cells':>7s}{'corrob':>9s}{'single':>9s}{'none':>9s}")
    for gov, g in inh.groupby("governorate"):
        s = split(g)
        by_gov[gov] = s
        print(f"  {gov:14s}{s['cells']:7,}{s['pct']['corroborated']:8.1f}%"
              f"{s['pct']['single_source']:8.1f}%{s['pct']['unavailable']:8.1f}%")

    summary = {
        "res": RES,
        "inhabited_filter": {
            "population_min": POP_MIN,
            "builtup_pct_min": BUILTUP_PCT_MIN,
            "rationale": (
                "The operational polygon is four governorates plus a 2 km dilation ring, "
                "so it includes desert, the ring itself, and Nile-valley farmland. Those "
                "cells lack business data because they lack businesses. Both conditions "
                "are required: population alone admits farmland with no urban fabric, "
                "built-up alone admits airports, cemeteries and industrial land."
            ),
        },
        "all_cells": all_split,
        "inhabited": inh_split,
        "inhabited_by_governorate": by_gov,
    }
    (OUT.parent / "coverage-summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nwrote {OUT.parent / 'coverage-summary.json'}")

    # Live regions, filtered to what the pipeline actually produced. The UI
    # renders this list rather than naming any city in a sentence, so adding a
    # region is a config change and the status line can never over-claim.
    cfg = json.loads(REGIONS_IN.read_text())
    have = set(df.governorate.dropna().unique())
    live = [{"id": g["id"], "name": g["name"],
             "governorates": [x for x in g["governorates"] if x in have],
             "cells": int(df.governorate.isin(g["governorates"]).sum())}
            for g in cfg["groups"]]
    live = [g for g in live if g["governorates"]]
    REGIONS_OUT.write_text(json.dumps(
        {"regions": live, "roadmap_note": cfg["roadmap_note"]}, indent=2))
    print(f"wrote {REGIONS_OUT} — live regions: "
          f"{', '.join(g['name'] for g in live)}")


if __name__ == "__main__":
    main()

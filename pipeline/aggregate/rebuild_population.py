"""Rebuild ONLY the population rows in h3_metric_res{8,9}.parquet.

A full h3_pipeline run re-reads every Overture and Foursquare snapshot to
rebuild business counts that are not affected by this defect. This rewrites the
population rows in place, using the same population_metric() the pipeline now
uses, so the tables and the pipeline cannot disagree.

Everything else in the table is left byte-identical.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.config._common import ROOT
from pipeline.aggregate.h3_pipeline import population_metric, PIPELINE_VERSION

TABLES = ROOT / "data" / "derived" / "h3_tables"


def main():
    for res in (8, 9):
        cell_p = TABLES / f"h3_cell_res{res}.parquet"
        met_p = TABLES / f"h3_metric_res{res}.parquet"
        cells = pd.read_parquet(cell_p)
        m = pd.read_parquet(met_p)

        before = m[m.metric == "population"]
        keep = m[m.metric != "population"].copy()

        g = population_metric(res, cells)
        # Same downstream treatment the pipeline applies to every metric.
        g = g.merge(cells[["h3_index", "land_area_m2"]], on="h3_index", how="left")
        g["value_per_land_km2"] = np.where(
            g.land_area_m2 > 0, g.value / (g.land_area_m2 / 1e6), np.nan).round(2)
        g["h3_res"] = res
        g["pipeline_version"] = PIPELINE_VERSION
        g["computed_at"] = pd.Timestamp.utcnow().isoformat()
        g = g[g.h3_index.isin(set(cells.h3_index))]

        if "native_res" not in keep.columns:
            keep["native_res"] = res
        keep["native_res"] = keep.native_res.fillna(res).astype(int)

        out = pd.concat([keep, g], ignore_index=True)
        out = out[[c for c in m.columns if c in out.columns] +
                  [c for c in out.columns if c not in m.columns]]
        out.to_parquet(met_p, index=False)

        print(f"res-{res}: population rows {len(before):,} -> {len(g):,} "
              f"| sum {before.value.sum():,.0f} -> {g.value.sum():,.0f} "
              f"| table {len(m):,} -> {len(out):,} rows")


if __name__ == "__main__":
    main()

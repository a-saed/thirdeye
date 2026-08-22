"""
Reports the numbers needed to (a) choose the business-layer corroboration
tolerance honestly and (b) narrow the population-staleness flag.

WHY THIS EXISTS: the first pipeline run set the tolerance at 0.5, which was
the OBSERVED MEDIAN disagreement between the two sources. That makes
"corroborated" mean "these sources disagree by the typical amount", which is
circular. This script reports the rate at several tolerances so the threshold
is a decision rather than an artifact of the data it is measuring.
"""
import json
import sys
from pathlib import Path

import h3
import numpy as np
import pandas as pd
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import ROOT

OUT = ROOT / "data" / "derived" / "h3_tables"
GH = ROOT / "data" / "ghsl_cache"
TOLERANCES = [0.5, 0.667, 0.8]


def ghsl_by_cell(epoch: int, res: int) -> pd.DataFrame:
    acc = {}
    for tile in ("R6_C22", "R6_C21"):
        p = GH / f"GHS_BUILT_S_E{epoch}_GLOBE_R2023A_4326_3ss_V1_0_{tile}.tif"
        if not p.exists():
            print(f"    (missing {p.name})")
            continue
        with rasterio.open(p) as src:
            data = src.read(1); tr = src.transform
        rows, cols = np.nonzero(data > 0)
        if not len(rows):
            continue
        vals = data[rows, cols].astype(np.float64)
        lon = tr.c + (cols + 0.5) * tr.a
        lat = tr.f + (rows + 0.5) * tr.e
        for la, lo, v in zip(lat, lon, vals):
            c = h3.latlng_to_cell(la, lo, res)
            acc[c] = acc.get(c, 0.0) + v
        del data, rows, cols, vals
    return pd.DataFrame({"h3_index": list(acc), f"builtup_{epoch}": list(acc.values())})


def main():
    print("=" * 88)
    print("BUSINESS-LAYER CORROBORATION — SENSITIVITY TO TOLERANCE")
    print("=" * 88)
    for res in (8, 9):
        m = pd.read_parquet(OUT / f"h3_metric_res{res}.parquet")
        cells = pd.read_parquet(OUT / f"h3_cell_res{res}.parquet")
        b = m[m.metric == "business_count.total"].merge(
            cells[["h3_index", "governorate"]], on="h3_index", how="left")
        n_cells = len(b)
        both = (b.overture > 0) & (b.fsq > 0)
        ratio = np.where(both, np.minimum(b.overture, b.fsq) /
                         np.maximum(b.overture, b.fsq).replace(0, np.nan), 0.0)
        print(f"\n--- res-{res}: {n_cells:,} cells with any storefront record ---")
        print(f"  both sources present: {both.sum():,} ({100*both.mean():.1f}%)")
        print(f"  ONE source only:      {(~both).sum():,} ({100*(~both).mean():.1f}%)")
        r = pd.Series(ratio[both])
        print("\n  min/max count-agreement ratio among both-present cells:")
        for q in (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95):
            print(f"    p{int(q*100):02d}: {r.quantile(q):.3f}")
        print(f"    mean {r.mean():.3f}   share at exactly 1.000: "
              f"{100*(r >= 0.999).mean():.1f}%")
        print("\n  corroboration rate by tolerance:")
        for t in TOLERANCES:
            k = int((both & (ratio >= t)).sum())
            print(f"    tol {t:.3f} ({1/t:.2f}x): {k:6,} cells = {100*k/n_cells:5.1f}% of all cells, "
                  f"{100*k/both.sum():5.1f}% of both-present")
        print("\n  single_source share by governorate (tol 0.667):")
        b["_corr"] = both & (ratio >= 0.667)
        for gov, g in b.groupby("governorate"):
            if gov == "outside" or len(g) < 20:
                continue
            print(f"    {gov:12s} {len(g):6,} cells | single_source {100*(~g._corr).mean():5.1f}%")

    print("\n" + "=" * 88)
    print("MEASURED-GROWTH STALENESS FLAG (GHSL 2015 -> 2025)")
    print("=" * 88)
    for res in (8, 9):
        print(f"\n  res-{res}: aggregating GHSL epochs ...")
        a = ghsl_by_cell(2015, res); c = ghsl_by_cell(2025, res)
        g = a.merge(c, on="h3_index", how="outer").fillna(0.0)
        g["abs_growth_m2"] = g.builtup_2025 - g.builtup_2015
        g["pct_growth"] = np.where(g.builtup_2015 > 0,
                                   100 * g.abs_growth_m2 / g.builtup_2015, np.nan)
        cells = pd.read_parquet(OUT / f"h3_cell_res{res}.parquet")
        g = g[g.h3_index.isin(set(cells.h3_index))]
        print(f"    cells with GHSL data: {len(g):,}")
        print("    pct_growth distribution:")
        for q in (0.5, 0.75, 0.9, 0.95, 0.99):
            print(f"      p{int(q*100)}: {g.pct_growth.quantile(q):.1f}%")
        for thr in (10, 20, 50):
            n = int(((g.pct_growth >= thr) & (g.abs_growth_m2 >= 1000)).sum())
            print(f"    growth >= {thr}% AND >= 1000 m2 absolute: {n:,} cells "
                  f"({100*n/len(cells):.1f}% of all cells)")
        g.to_parquet(OUT / f"ghsl_growth_res{res}.parquet", index=False)


if __name__ == "__main__":
    main()

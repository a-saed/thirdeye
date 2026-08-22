"""
Test 2C, leg E (added mid-study): DLR World Settlement Footprint Evolution
(WSF Evolution), 30m resolution, global settlement extent 1985-2015.

Free, anonymous, no registration - plain HTTP index at
download.geoservice.dlr.de. Tiled 2deg x 2deg, one file covers our whole
study area (WSFevolution_v1_30_30.tif, bounds ~[29.99,32.01] both axes -
covers all 3 district bboxes from a single ~6MB download).

Pixel value = the YEAR that pixel was first detected as built-up
(1985-2015), or 0 if never settled by 2015 (confirmed directly by
inspecting unique values in the file - not assumed). This means the
FULL annual evolution 1985-2015 comes from ONE file: built-up-by-year(Y)
= count of pixels with 0 < value <= Y.

This is the longest-baseline signal available (30 years vs GHSL's 3
epochs, Open Buildings' 8 years, or Overture's 2.4 years) - useful for
seeing each district's long-run development stage, not just recent
trend.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import requests
from rasterio.windows import from_bounds

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import ROOT, load_districts

TILE_BASE = "https://download.geoservice.dlr.de/WSF_EVO/files"
CACHE_DIR = ROOT / "data" / "wsf_evolution_cache"
YEARS = list(range(1985, 2016))

# WSFevolution_v1_30_30 (nominal SW corner lon=30,lat=30) does NOT reach
# far enough south for Maadi (ymin=29.95) - its actual bottom edge is
# 29.9899, discovered when Maadi's window read came back empty. Maadi
# needs the tile one step south, nominal lat=28.
DISTRICT_TILE = {
    "Sheikh Zayed": "30_30",
    "Imbaba": "30_30",
    "Maadi": "30_28",
}


def ensure_tile(tile_id: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"WSFevolution_v1_{tile_id}.tif"
    path = CACHE_DIR / fname
    if not path.exists():
        url = f"{TILE_BASE}/WSFevolution_v1_{tile_id}/{fname}"
        print(f"downloading {url}")
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        path.write_bytes(r.content)
    return path


def main():
    districts = load_districts()
    tile_cache = {tid: ensure_tile(tid) for tid in set(DISTRICT_TILE.values())}

    rows = []
    for name, d in districts.items():
        tile_path = tile_cache[DISTRICT_TILE[name]]
        bbox = d["bbox"]
        with rasterio.open(tile_path) as src:
            win = from_bounds(bbox["xmin"], bbox["ymin"], bbox["xmax"], bbox["ymax"], src.transform)
            data = src.read(1, window=win)
        total_px = data.size
        if total_px == 0:
            print(f"WARNING: {name} window is empty against tile {DISTRICT_TILE[name]} - bbox falls outside this tile")
            continue
        for year in YEARS:
            settled_px = int(((data > 0) & (data <= year)).sum())
            rows.append({
                "district": name, "year": year,
                "settled_px": settled_px, "total_px": total_px,
                "pct_settled": round(100.0 * settled_px / total_px, 2),
            })

    df = pd.DataFrame(rows)
    out_path = ROOT / "output" / "test2c_wsf_evolution_annual.csv"
    df.to_csv(out_path, index=False)
    print(f"Wrote {out_path}")

    print("\n% of bbox settled by year (every 5 years shown):")
    sample = df[df["year"].isin(range(1985, 2016, 5))]
    print(sample.pivot(index="year", columns="district", values="pct_settled").to_string())

    print("\n1985 -> 2015 change:")
    for name in districts:
        sub = df[df["district"] == name].sort_values("year")
        first, last = sub.iloc[0], sub.iloc[-1]
        pct_change = round(100 * (last["pct_settled"] - first["pct_settled"]) / first["pct_settled"], 1) if first["pct_settled"] else float("inf")
        print(f"  {name:14s} {first['pct_settled']:.2f}% -> {last['pct_settled']:.2f}%  ({pct_change:+.1f}% relative)")


if __name__ == "__main__":
    main()

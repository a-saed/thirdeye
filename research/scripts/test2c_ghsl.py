"""
Test 2C, leg D (added mid-study): JRC Global Human Settlement Layer,
GHS-BUILT-S product (R2023A, EPSG:4326, ~100m/3-arcsec resolution).

Free, anonymous, no registration - a plain browsable HTTP index at
jeodpp.jrc.ec.europa.eu (no login redirect, unlike EOG). Confirmed via
direct download.

This is the fix for the "no calendar-year overlap" problem: GHSL spans
2015/2020/2025, i.e. both the Open Buildings era (2016-2023) and the
Overture release-history era (2024-2026), so it can corroborate across
that boundary directly (same years available on both sides).

Tiling: 10deg x 10deg grid, WGS84, files named ..._R<row>_C<col>.zip,
row1 = [80,90]N going south in 10deg steps, col1 = [-180,-170] going
east in 10deg steps (verified directly by downloading and checking a
tile's bounds - not assumed from GHSL docs). Cairo/Giza needs 2 tiles:
R6_C22 ([20,40)... actually [30,40)N x [30,40)E) for Sheikh Zayed and
Imbaba, R7_C22 ([20,30)N x [30,40)E) for Maadi, since our 3 district
bboxes straddle the lat=30 tile boundary.

Pixel value = built-up surface area in m^2 within that pixel (confirmed
directly: max observed value ~6458 m^2 is a plausible fraction of a
~92.5m x 92.5m pixel's ~8556 m^2 area at this latitude). Summed over a
district's window = total built-up m^2, comparable epoch to epoch and,
in principle, to Open Buildings' presence-based area (different sensor/
methodology, so absolute values won't match, but both should agree on
DIRECTION if the underlying growth is real).
"""
import sys
import zipfile
from pathlib import Path

import pandas as pd
import rasterio
import requests
from rasterio.windows import from_bounds

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import ROOT, load_districts

BASE = "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_BUILT_S_GLOBE_R2023A"
EPOCHS = [2015, 2020, 2025]
TILE_CACHE = ROOT / "data" / "ghsl_cache"

# district -> which 10deg tile it falls in. Verified directly by checking
# actual tile bounds (NOT assumed from clean 10deg math - the grid is
# offset, e.g. R6/R7 boundary is at lat 29.0996, not 30.0 or 29.0999 -
# first attempt used a hand-computed R7_C22 for Maadi, based on assuming
# exact 10deg boundaries from 90N, and got 0.0% built-up back, which is
# how the offset was caught).
DISTRICT_TILE = {
    "Sheikh Zayed": "R6_C22",
    "Imbaba": "R6_C22",
    "Maadi": "R6_C22",
}


def tile_zip_url(epoch: int, tile: str) -> str:
    folder = f"GHS_BUILT_S_E{epoch}_GLOBE_R2023A_4326_3ss"
    fname = f"{folder}_V1_0_{tile}.zip"
    return f"{BASE}/{folder}/V1-0/tiles/{fname}"


def ensure_tile(epoch: int, tile: str) -> Path:
    TILE_CACHE.mkdir(parents=True, exist_ok=True)
    tif_name = f"GHS_BUILT_S_E{epoch}_GLOBE_R2023A_4326_3ss_V1_0_{tile}.tif"
    tif_path = TILE_CACHE / tif_name
    if tif_path.exists():
        return tif_path

    url = tile_zip_url(epoch, tile)
    zip_path = TILE_CACHE / f"{tif_name}.zip"
    print(f"  downloading {url}")
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    zip_path.write_bytes(r.content)
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if name.endswith(".tif"):
                zf.extract(name, TILE_CACHE)
                extracted = TILE_CACHE / name
                if extracted != tif_path:
                    extracted.rename(tif_path)
    zip_path.unlink()
    return tif_path


def main():
    districts = load_districts()
    rows = []
    for epoch in EPOCHS:
        print(f"[{epoch}]")
        tile_data = {}
        for tile in set(DISTRICT_TILE.values()):
            tif_path = ensure_tile(epoch, tile)
            tile_data[tile] = tif_path

        for name, d in districts.items():
            tile = DISTRICT_TILE[name]
            bbox = d["bbox"]
            with rasterio.open(tile_data[tile]) as src:
                win = from_bounds(bbox["xmin"], bbox["ymin"], bbox["xmax"], bbox["ymax"], src.transform)
                data = src.read(1, window=win)
            built_up_m2 = float(data.sum())
            rows.append({
                "district": name, "epoch": epoch,
                "built_up_m2": round(built_up_m2, 1),
                "built_up_km2": round(built_up_m2 / 1e6, 4),
                "pct_of_bbox": round(100 * built_up_m2 / 2_250_000, 2),
            })
            print(f"    {name:14s} built-up: {built_up_m2:>12.0f} m^2  ({100*built_up_m2/2_250_000:.2f}% of bbox)")

    df = pd.DataFrame(rows)
    out_path = ROOT / "output" / "test2c_ghsl_annual.csv"
    df.to_csv(out_path, index=False)
    print(f"\nWrote {out_path}")

    print("\n" + "=" * 70)
    print("Built-up surface (% of 2.25 km^2 bbox), by district and epoch:")
    print(df.pivot(index="epoch", columns="district", values="pct_of_bbox").to_string())


if __name__ == "__main__":
    main()

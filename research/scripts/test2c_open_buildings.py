"""
Test 2C, satellite leg B: Google Open Buildings 2.5D Temporal.

Public GCS bucket `open-buildings-temporal-data`, confirmed anonymously
readable (no account/key). Manifests are Earth Engine ingestion manifests
(v1/manifests/<chunk>_EPSG_<utm-epsg>_<year>_06_30.json); tile URLs are
built by concatenating `uriPrefix` directly with each tile's `uris` entry
(NO extra "/" - uriPrefix ends mid-folder-name, e.g. ".../geotiffs/00" +
"afc_2016_06_30/tile_X.tif" = ".../geotiffs/00afc_2016_06_30/tile_X.tif".
Adding a slash 404s - this took a lot of trial and error to figure out).

For our UTM zone (EPSG:32636, Cairo/Giza), manifest chunk "15" is the one
whose tiles actually cover our districts (chunk "17" does not).

Bands used, per Google's own Earth Engine catalog documentation (checked
directly, not assumed):
  - building_fractional_count: range 0-0.0216, unitless. Google's own
    description: "source data for deriving building counts for a given
    AOI" - NOT itself a calibrated building count. Summed over a
    district's window it is a relative built-up-area intensity index,
    valid for year-over-year comparison within the same location, NOT
    interpretable as "there are N buildings here." Reported as
    `built_up_area_index`, never as "building count."
  - building_height: 0-100m, "building height relative to terrain."
    Reported as `mean_height_where_present_m` - the mean over pixels
    where building_presence > 0.5, i.e. mean height where a building is
    actually believed present (averaging over empty ground pixels too
    would just dilute this toward 0 and mean nothing).
  - building_presence: 0-1, model confidence a pixel is part of a
    building. Per Google's docs these scores are UNCALIBRATED (0.8 does
    not mean "80% probability") - used here only for thresholding
    (>0.5) to select "building-ish" pixels for the height average, not
    reported as its own quantity.

Districts spanning a tile boundary (Sheikh Zayed, Maadi) are read from
each overlapping tile and summed over the non-overlapping intersection of
[district bbox] x [tile extent], so no double-counting at boundaries.
"""
import json
import sys
import time
from pathlib import Path

import pandas as pd
import pyproj
import rasterio
from rasterio.windows import from_bounds

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import ROOT, load_districts

MANIFEST_BASE = "https://storage.googleapis.com/open-buildings-temporal-data/v1/manifests/"
CHUNK = "15"  # the manifest chunk covering our UTM zone; verified by tile-overlap test
UTM_EPSG = "EPSG:32636"
YEARS = list(range(2016, 2024))

import requests


def manifest_url(chunk: str, epsg: str, year: int) -> str:
    epsg_code = epsg.split(":")[1]
    return f"{MANIFEST_BASE}{chunk}_EPSG_{epsg_code}_{year}_06_30.json"


def load_manifest(chunk: str, epsg: str, year: int) -> dict:
    r = requests.get(manifest_url(chunk, epsg, year), timeout=60)
    r.raise_for_status()
    return r.json()


def tile_url(manifest: dict, uri: str) -> str:
    prefix = manifest["uriPrefix"].replace("gs://open-buildings-temporal-data/", "")
    return f"https://storage.googleapis.com/open-buildings-temporal-data/{prefix}{uri}"


def tile_extent(source: dict) -> tuple:
    at = source["affineTransform"]
    dim = source["dimensions"]
    xmin = at["translateX"]
    ymax = at["translateY"]
    xmax = xmin + dim["width"] * at["scaleX"]
    ymin = ymax + dim["height"] * at["scaleY"]
    return xmin, ymin, xmax, ymax


def district_bbox_utm(bbox: dict, transformer: pyproj.Transformer) -> dict:
    x1, y1 = transformer.transform(bbox["xmin"], bbox["ymin"])
    x2, y2 = transformer.transform(bbox["xmax"], bbox["ymax"])
    return {"xmin": min(x1, x2), "xmax": max(x1, x2), "ymin": min(y1, y2), "ymax": max(y1, y2)}


def main():
    con_transformer = pyproj.Transformer.from_crs("EPSG:4326", UTM_EPSG, always_xy=True)
    districts = load_districts()
    district_utm = {name: district_bbox_utm(d["bbox"], con_transformer) for name, d in districts.items()}

    rows = []
    for year in YEARS:
        t0 = time.time()
        manifest = load_manifest(CHUNK, UTM_EPSG, year)
        sources = manifest["tilesets"][0]["sources"]

        for name, dbbox in district_utm.items():
            total_frac_count = 0.0
            total_valid_px = 0
            height_sum_where_present = 0.0
            n_present_px = 0
            n_tiles_used = 0

            for s in sources:
                txmin, tymin, txmax, tymax = tile_extent(s)
                ixmin, ixmax = max(dbbox["xmin"], txmin), min(dbbox["xmax"], txmax)
                iymin, iymax = max(dbbox["ymin"], tymin), min(dbbox["ymax"], tymax)
                if ixmin >= ixmax or iymin >= iymax:
                    continue  # no overlap with this tile

                url = "/vsicurl/" + tile_url(manifest, s["uris"][0])
                with rasterio.open(url) as src:
                    win = from_bounds(ixmin, iymin, ixmax, iymax, src.transform)
                    frac = src.read(1, window=win)
                    height = src.read(2, window=win)
                    presence = src.read(3, window=win)
                valid = frac > -90
                present = valid & (presence > 0.5)
                total_frac_count += frac[valid].sum()
                total_valid_px += int(valid.sum())
                height_sum_where_present += float(height[present].sum())
                n_present_px += int(present.sum())
                n_tiles_used += 1

            mean_height = round(height_sum_where_present / n_present_px, 2) if n_present_px else None
            rows.append({
                "district": name, "year": year,
                "built_up_area_index": round(total_frac_count, 1),
                "mean_height_where_present_m": mean_height,
                "n_present_px": n_present_px,
                "valid_px": total_valid_px,
                "n_tiles": n_tiles_used,
            })
        print(f"[{year}] done in {round(time.time()-t0,1)}s: " +
              ", ".join(f"{r['district']}=(area={r['built_up_area_index']}, height={r['mean_height_where_present_m']}m)"
                        for r in rows if r["year"] == year))

    df = pd.DataFrame(rows)
    out_csv = ROOT / "output" / "test2c_open_buildings_annual.csv"
    df.to_csv(out_csv, index=False)
    print(f"\nWrote {out_csv}")

    print("\n" + "=" * 70)
    print("Built-up area index by district and year (NOT a building count - see docstring):")
    print(df.pivot(index="year", columns="district", values="built_up_area_index").to_string())
    print("\nMean building height where present (m), by district and year:")
    print(df.pivot(index="year", columns="district", values="mean_height_where_present_m").to_string())

    import matplotlib.pyplot as plt
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    for name in districts:
        sub = df[df["district"] == name].sort_values("year")
        ax1.plot(sub["year"], sub["built_up_area_index"], marker="o", label=name)
        ax2.plot(sub["year"], sub["mean_height_where_present_m"], marker="o", label=name)
    ax1.set_xlabel("Year"); ax1.set_ylabel("Built-up area index (sum of building_fractional_count)")
    ax1.set_title("Built-up area index, 2016-2023")
    ax1.legend()
    ax2.set_xlabel("Year"); ax2.set_ylabel("Mean building height where present (m)")
    ax2.set_title("Mean building height, 2016-2023")
    ax2.legend()
    fig.suptitle("Open Buildings 2.5D Temporal")
    fig.tight_layout()
    chart_path = ROOT / "output" / "test2c_open_buildings_annual.png"
    fig.savefig(chart_path, dpi=150)
    print(f"Wrote {chart_path}")


if __name__ == "__main__":
    main()

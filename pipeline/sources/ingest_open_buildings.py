"""
Open Buildings 2.5D Temporal -> per-H3-cell built-up metrics, 2023 only.

This is the one expensive ingest. Measured cost: ~4.6 s per 2km x 2km
2-band windowed read; the 8,708 km^2 operational polygon is ~2,177 such
windows, i.e. ~2.8 h single-threaded for one year. Parallelised across
workers (independent HTTP range reads) this comes down to ~20-40 min.

TWO NON-OBVIOUS THINGS, both learned the hard way and easy to get wrong:

 1. TILE URLs. The manifest's `uriPrefix` ends MID-FOLDER-NAME and must be
    concatenated to each tile's uri with NO separator:
      ".../geotiffs/00" + "afc_2023_06_30/tile_X.tif"
    Inserting a "/" yields a 404.

 2. UTM ZONES. The coverage area spans TWO zones - Cairo/Giza/Qalyubiya in
    36N, Alexandria straddling into 35N. Both manifests are required
    (chunk 15, EPSG:32635 and EPSG:32636); using only 36N silently drops
    western Alexandria.

BANDS: building_presence (band 3) is used for extent, NOT
building_fractional_count (band 1). The fractional-count band was shown to
be unreliable in dense informal fabric - it reported Imbaba declining -14.4%
2016-2023 where the presence band and GHSL both say flat.

Output: data/derived/h3/res=<8|9>/metric=builtup_presence_m2/... per the
Part II layout, with resolver_version and source snapshot recorded.

RESUMABILITY (added v4, 2026-08-20):
Each worker spools its tile result to data/derived/_spool/OB_<year>/ and the
parent merges at the end. Re-running skips tiles that already have a spool
file, so the job is resumable.
This exists because the earlier version accumulated everything in the parent
and wrote nothing until all tiles finished. It reached 150/152 tiles, then
wedged for over two hours on the last two with network throughput measured
at 3 KB/s (a hung-but-open HTTP socket, which GDAL retries do not cover).
Killing it discarded all 150 completed tiles. Worker-side HTTP timeouts now
make a wedged socket fail fast instead of hanging.
"""
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import requests
from rasterio.windows import from_bounds
from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.config._common import ROOT
from pipeline.sources.ob_worker import process_tile, spool_path

RESOLVER_VERSION = "ob-v1"
YEAR = 2023
CHUNK = "15"
ZONES = ["32635", "32636"]
MANIFEST_BASE = "https://storage.googleapis.com/open-buildings-temporal-data/v1/manifests/"
DERIVED = ROOT / "data" / "derived" / "h3"
SPOOL = ROOT / "data" / "derived" / "_spool" / f"OB_2023"
PRESENCE_THRESHOLD = 0.5
PIXEL_AREA_M2 = 0.25          # 0.5m x 0.5m
WORKERS = int(os.environ.get("OB_WORKERS", "5"))

# GDAL's /vsicurl block cache is PER PROCESS and unbounded by default. With 8
# workers it grew to ~1.4-2 GB each (~11 GB total) and drove the box to 1.1 GB
# free mid-run on 2026-08-20, forcing a kill. Since this job writes nothing
# until the very end, an OOM here loses the entire run - so the cache is capped
# explicitly and worker count reduced. Must be set BEFORE rasterio/GDAL loads.
# (GDAL config is applied per-worker via rasterio.Env in scripts/ob_worker.py -
# module-level env vars are too late, GDAL has already initialised.)


def manifest_url(zone: str) -> str:
    return f"{MANIFEST_BASE}{CHUNK}_EPSG_{zone}_{YEAR}_06_30.json"


def tile_url(prefix: str, uri: str) -> str:
    p = prefix.replace("gs://open-buildings-temporal-data/", "")
    return f"https://storage.googleapis.com/open-buildings-temporal-data/{p}{uri}"


def tile_extent(s):
    at, d = s["affineTransform"], s["dimensions"]
    xmin = at["translateX"]; ymax = at["translateY"]
    return xmin, ymax + d["height"] * at["scaleY"], xmin + d["width"] * at["scaleX"], ymax


def main():
    g = gpd.read_file(ROOT / "pipeline" / "config" / "coverage_area.gpkg")
    op = g[g["name"] == "operational"].geometry.iloc[0]

    tasks = []
    for zone in ZONES:
        m = requests.get(manifest_url(zone), timeout=300).json()
        prefix = m["uriPrefix"]
        opu = gpd.GeoSeries([op], crs="EPSG:4326").to_crs(f"EPSG:{zone}").iloc[0]
        b = opu.bounds
        n_tiles = 0
        for src_t in m["tilesets"][0]["sources"]:
            ext = tile_extent(src_t)
            if not box(*ext).intersects(opu):
                continue
            n_tiles += 1
            tasks.append((tile_url(prefix, src_t["uris"][0]), zone, ext, b, [8, 9], str(SPOOL)))
        print(f"  zone {zone}: {n_tiles} tiles")
    print(f"Open Buildings {YEAR}: {len(tasks)} TILES across zones {ZONES}, {WORKERS} workers")

    SPOOL.mkdir(parents=True, exist_ok=True)
    already = sum(1 for t in tasks if spool_path(str(SPOOL), t[0]).exists())
    if already:
        print(f"  resuming: {already}/{len(tasks)} tiles already spooled")

    errors, done, px_total = [], 0, 0
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(process_tile, t): t[0] for t in tasks}
        for f in as_completed(futs):
            res, npx = f.result()
            done += 1
            if "_error" in res:
                errors.append(res["_error"]); continue
            px_total += npx
            if done % 5 == 0 or done == len(tasks):
                el = time.time() - t0
                print(f"  {done}/{len(tasks)} tiles | {px_total:,} presence px | "
                      f"{el/60:.1f} min elapsed | eta {(el/done)*(len(tasks)-done)/60:.1f} min", flush=True)

    print("merging spooled tiles ...")
    totals = {8: {}, 9: {}}
    for sf in SPOOL.glob("*.json"):
        try:
            d = json.loads(sf.read_text())
        except Exception as e:
            errors.append(f"unreadable spool {sf.name}: {e}"); continue
        for r in (8, 9):
            acc = totals[r]
            for c, v in d.get(str(r), {}).items():
                acc[c] = acc.get(c, 0) + v

    for r in (8, 9):
        df = pd.DataFrame([{"h3_index": c, "h3_res": r,
                            "metric": "builtup_presence_m2",
                            "value": n * PIXEL_AREA_M2,
                            "n_pixels": n} for c, n in totals[r].items()])
        d = DERIVED / f"res={r}" / "metric=builtup_presence_m2" / f"resolver={RESOLVER_VERSION}" / f"snapshot=OB_{YEAR}"
        d.mkdir(parents=True, exist_ok=True)
        df.to_parquet(d / "cells.parquet", index=False)
        (d / "_manifest.json").write_text(json.dumps({
            "metric": "builtup_presence_m2", "track": "built_environment",
            "h3_res": r, "resolver_version": RESOLVER_VERSION,
            "source_snapshots": {"open_buildings": f"v1_{YEAR}_06_30"},
            "band": "building_presence>0.5 (NOT building_fractional_count)",
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "cells": len(df), "tiles": len(tasks), "tile_errors": errors,
        }, indent=2))
        print(f"res-{r}: {len(df):,} cells -> {d/'cells.parquet'}")

    print(f"\ntotal {time.time()-t0:.0f}s | errors: {len(errors)}")
    for e in errors[:5]:
        print("  ", e)


if __name__ == "__main__":
    main()

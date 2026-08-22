"""
STEP 2 (revised 2026-08-20): canonical coverage polygon + per-cell land
fraction for the launch coverage area.

Coverage area is now FOUR governorates (OSM admin_level=4 relations):
  Cairo       4103336
  Giza        3824206
  Alexandria  3061846
  Qalyubiya   4103337   (Shubra El Kheima - previously flagged, now agreed)

Same treatment as before: admin boundary INTERSECT GHSL built-up mask,
dilated 2 km. Both Giza (Western Desert) and Alexandria (coastal strip
running west toward Matruh) legally extend far into sparsely-built desert,
so the mask is what keeps the operational polygon honest.

LAND FRACTION (new, and a CORRECTNESS requirement not an enhancement):
Alexandria is a linear coastal city. A 500m catchment on the Corniche is
roughly half sea. Without normalising by habitable land area, competitor
counts and population both read low there and the product would score a
prime waterfront pitch as "low competition" when it is actually "half
water". The same failure applies at desert edges and along the Nile.

Source: GHSL GHS-LAND R2022A, 100m, Mollweide (ESRI:54009), tile R6_C21.
NOTE the tiling scheme differs from GHS-BUILT-S 4326_3ss (which uses
R6_C21/R6_C22 on a DIFFERENT grid) - same-looking tile ids, different
projections and different extents. Do not assume they correspond.
Value semantics, verified empirically rather than assumed: land fraction
is scaled 0..10000 (83% of pixels are exactly 10000 = fully land), and
65535 is the nodata sentinel (NOT a valid high value - naive use would
read nodata as 6.5x fully-land).

Land fraction is computed by bucketing 100m land pixels into H3 cells
(forward aggregation), not by per-cell polygon masking - ~570k pixels over
the coverage area is far cheaper than ~50k per-cell raster masks.
"""
import json
import sys
from pathlib import Path

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import pyproj
import rasterio
from rasterio import features as rio_features
from rasterio.windows import from_bounds
from shapely.geometry import LineString, MultiLineString, shape
from shapely.ops import linemerge, polygonize, unary_union

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.config._common import ROOT

CONFIG_DIR = ROOT / "pipeline" / "config"
GHSL_DIR = ROOT / "data" / "ghsl_cache"
BUILT_S_TILES = [
    GHSL_DIR / "GHS_BUILT_S_E2025_GLOBE_R2023A_4326_3ss_V1_0_R6_C22.tif",
    GHSL_DIR / "GHS_BUILT_S_E2025_GLOBE_R2023A_4326_3ss_V1_0_R6_C21.tif",
]
LAND_TILE = GHSL_DIR / "GHS_LAND_E2018_GLOBE_R2022A_54009_100_V1_0_R6_C21.tif"

RELATIONS = {"Cairo": 4103336, "Giza": 3824206, "Alexandria": 3061846, "Qalyubiya": 4103337}
GEOM_FILES = [Path("/tmp/gov_geom.json"), Path("/tmp/alex_qal_geom.json")]

BUILT_UP_MIN_M2 = 500
BUFFER_M = 2000
LAND_SCALE = 10000.0
LAND_NODATA = 65535


def build_admin_polygons() -> dict:
    """Keyed by OSM relation ID, not name - OSM's name:en for these is
    "Aj Jiza" / "Al Qalyubiya", which do not match our labels. Matching on
    the stable numeric id avoids silently dropping a governorate."""
    by_id = {}
    for f in GEOM_FILES:
        if not f.exists():
            continue
        for el in json.loads(f.read_text())["elements"]:
            lines = []
            for m in el.get("members", []):
                if m.get("role") != "outer":
                    continue
                g = m.get("geometry")
                if not g or len(g) < 2:
                    continue
                lines.append(LineString([(p["lon"], p["lat"]) for p in g]))
            if not lines:
                continue
            built = list(polygonize(linemerge(MultiLineString(lines))))
            if built:
                by_id[el["id"]] = unary_union(built)
    return {label: by_id[rid] for label, rid in RELATIONS.items() if rid in by_id}


def build_builtup_mask(clip_geom):
    """Dilate in RASTER space, then vectorise once.

    The obvious implementation (polygonize every built-up pixel, then
    .buffer(2km) in vector space) OOM-kills on this coverage area: the Nile
    Delta and valley produce millions of disconnected pixel polygons and the
    unary_union over them exhausts memory. Dilating the binary mask first
    merges those into a handful of large blobs, so vectorisation is cheap.
    It is also more faithful to the intent - a true 2km dilation of the
    built-up surface, rather than a buffer of its polygonised approximation."""
    from scipy.ndimage import binary_dilation

    polys = []
    for tif in BUILT_S_TILES:
        if not tif.exists():
            continue
        with rasterio.open(tif) as src:
            minx, miny, maxx, maxy = clip_geom.bounds
            minx = max(minx, src.bounds.left); maxx = min(maxx, src.bounds.right)
            miny = max(miny, src.bounds.bottom); maxy = min(maxy, src.bounds.top)
            if minx >= maxx or miny >= maxy:
                continue
            win = from_bounds(minx, miny, maxx, maxy, src.transform)
            data = src.read(1, window=win)
            transform = src.window_transform(win)

        mask = data >= BUILT_UP_MIN_M2
        del data
        if not mask.any():
            continue

        # pixel size in metres at this latitude (3 arcsec grid)
        mid_lat = (miny + maxy) / 2.0
        px_m = abs(transform.a) * 111320.0 * np.cos(np.radians(mid_lat))
        iters = max(1, int(round(BUFFER_M / px_m)))
        cross = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=bool)
        mask = binary_dilation(mask, structure=cross, iterations=iters)

        for geom, val in rio_features.shapes(mask.astype(np.uint8), mask=mask, transform=transform):
            if val == 1:
                polys.append(shape(geom))
        del mask

    if not polys:
        raise RuntimeError("no built-up pixels found - check threshold/tiles")
    return unary_union(polys)


def area_km2(geom) -> float:
    return gpd.GeoSeries([geom], crs="EPSG:4326").to_crs("EPSG:32636").area.iloc[0] / 1e6


def cells_for(geom, res: int) -> set:
    parts = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
    cells = set()
    for p in parts:
        cells.update(h3.polygon_to_cells(h3.geo_to_h3shape(p.__geo_interface__), res))
    return cells


def land_fraction_by_cell(geom, resolutions=(8, 9)) -> dict:
    """Bucket 100m GHS-LAND pixels into H3 cells and return
    {res: DataFrame[h3_index, land_fraction, n_pixels, n_nodata_pixels]}."""
    to_moll = pyproj.Transformer.from_crs("EPSG:4326", "ESRI:54009", always_xy=True)
    to_wgs = pyproj.Transformer.from_crs("ESRI:54009", "EPSG:4326", always_xy=True)

    minx, miny, maxx, maxy = geom.bounds
    corners_x, corners_y = to_moll.transform([minx, minx, maxx, maxx], [miny, maxy, miny, maxy])
    mminx, mmaxx = min(corners_x), max(corners_x)
    mminy, mmaxy = min(corners_y), max(corners_y)

    with rasterio.open(LAND_TILE) as src:
        mminx = max(mminx, src.bounds.left); mmaxx = min(mmaxx, src.bounds.right)
        mminy = max(mminy, src.bounds.bottom); mmaxy = min(mmaxy, src.bounds.top)
        win = from_bounds(mminx, mminy, mmaxx, mmaxy, src.transform)
        data = src.read(1, window=win)
        transform = src.window_transform(win)

    rows, cols = np.indices(data.shape)
    xs = transform.c + (cols.ravel() + 0.5) * transform.a
    ys = transform.f + (rows.ravel() + 0.5) * transform.e
    lons, lats = to_wgs.transform(xs, ys)

    vals = data.ravel().astype(np.float64)
    is_nodata = vals == LAND_NODATA
    frac = np.where(is_nodata, np.nan, np.clip(vals, 0, LAND_SCALE) / LAND_SCALE)

    out = {}
    for res in resolutions:
        idx = np.array(h3.latlng_to_cell(lats, lons, res)) if False else np.array(
            [h3.latlng_to_cell(la, lo, res) for la, lo in zip(lats, lons)])
        df = pd.DataFrame({"h3_index": idx, "frac": frac, "nodata": is_nodata})
        g = df.groupby("h3_index").agg(
            land_fraction=("frac", "mean"),
            n_pixels=("frac", "size"),
            n_nodata_pixels=("nodata", "sum"),
        ).reset_index()
        g["land_fraction"] = g["land_fraction"].fillna(0.0).round(4)
        out[res] = g
    return out


def main():
    CONFIG_DIR.mkdir(exist_ok=True)
    admin = build_admin_polygons()
    missing = [k for k in RELATIONS if k not in admin]
    if missing:
        raise RuntimeError(f"missing admin geometry for: {missing}")

    admin_full = unary_union(list(admin.values()))
    print("=" * 78)
    print("ADMIN (legal governorate boundaries, OSM admin_level=4)")
    for k in RELATIONS:
        print(f"  {k:12s} {area_km2(admin[k]):>10,.0f} km^2")
    a_full = area_km2(admin_full)
    print(f"  {'UNION':12s} {a_full:>10,.0f} km^2")

    print("\nBuilding built-up mask (GHSL BUILT-S 2025, 2 tiles) ...")
    builtup = build_builtup_mask(admin_full)
    operational = admin_full.intersection(builtup)
    a_op = area_km2(operational)
    print(f"  operational = admin ∩ built-up+{BUFFER_M}m : {a_op:,.0f} km^2 ({100*a_op/a_full:.1f}% of admin)")

    print("\nComputing H3 cells + land fraction ...")
    lf = land_fraction_by_cell(operational, (8, 9))

    summary = {}
    for res in (8, 9):
        cells = cells_for(operational, res)
        df = lf[res]
        df = df[df["h3_index"].isin(cells)].copy()
        # cells with no land pixels at all are pure water - drop from coverage
        land_cells = df[df["land_fraction"] > 0]
        dropped = len(cells) - len(land_cells)
        no_lf = len(cells) - len(df)
        summary[res] = {
            "cells_in_polygon": len(cells),
            "cells_with_land": int(len(land_cells)),
            "cells_dropped_pure_water": int(dropped),
            "cells_without_land_data": int(no_lf),
            "mean_land_fraction": round(float(land_cells["land_fraction"].mean()), 4),
            "cells_land_fraction_below_0.9": int((land_cells["land_fraction"] < 0.9).sum()),
            "cells_land_fraction_below_0.5": int((land_cells["land_fraction"] < 0.5).sum()),
        }
        out_csv = CONFIG_DIR / f"h3_land_fraction_res{res}.csv"
        land_cells.to_csv(out_csv, index=False)
        s = summary[res]
        print(f"  res-{res}: {s['cells_in_polygon']:>7,} cells in polygon | "
              f"{s['cells_with_land']:>7,} with land | {s['cells_dropped_pure_water']:>5,} pure-water dropped")
        print(f"          mean land fraction {s['mean_land_fraction']:.3f} | "
              f"{s['cells_land_fraction_below_0.9']:,} cells <0.9 | {s['cells_land_fraction_below_0.5']:,} cells <0.5")
        print(f"          -> {out_csv}")

    gdf = gpd.GeoDataFrame({"name": ["admin_full", "operational"], "area_km2": [a_full, a_op]},
                           geometry=[admin_full, operational], crs="EPSG:4326")
    gdf.to_file(CONFIG_DIR / "coverage_area.gpkg", driver="GPKG")

    meta = {
        "governorates": RELATIONS,
        "built_up_mask": {"dataset": "GHSL GHS-BUILT-S R2023A 2025, tiles R6_C21+R6_C22 (EPSG:4326)",
                          "min_builtup_m2_per_pixel": BUILT_UP_MIN_M2, "buffer_m": BUFFER_M},
        "land_fraction": {"dataset": "GHSL GHS-LAND R2022A 100m, tile R6_C21 (ESRI:54009)",
                          "scale": LAND_SCALE, "nodata": LAND_NODATA,
                          "note": "REQUIRED field on every cell; all catchment metrics must normalise by land area"},
        "areas_km2": {"admin_full": round(a_full, 1), "operational": round(a_op, 1)},
        "h3": summary,
    }
    (CONFIG_DIR / "coverage_area.json").write_text(json.dumps(meta, indent=2))
    print(f"\nWrote {CONFIG_DIR/'coverage_area.gpkg'} and coverage_area.json")


if __name__ == "__main__":
    main()

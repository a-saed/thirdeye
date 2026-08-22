"""
H3 AGGREGATION PIPELINE — builds h3_cell and h3_metric.

=============================================================================
THREE RULES ARE BAKED IN HERE ON PURPOSE. EACH EXISTS BECAUSE OF A SPECIFIC
MEASURED FINDING. DO NOT "SIMPLIFY" THEM AWAY.
=============================================================================

RULE 1 — EVERY CATCHMENT METRIC NORMALISES BY LAND AREA, NEVER RAW CELL AREA.
  Finding: Alexandria's Corniche cells are ~half sea. A res-9 cell at Stanley
  measured land_fraction 0.521; Zamalek (Nile island) 0.697. Without land
  normalisation a prime waterfront pitch scores as "low competition" when the
  truth is "half the catchment is water". Same failure at desert edges and
  along the Nile. `value_per_land_km2` is MATERIALISED so no caller can
  accidentally divide by raw cell area.

RULE 2 — NO DUPLICATE MERGING. COUNTS ARE RAW.
  Finding: the duplicate matcher's out-of-sample precision is 25% (25/100
  human-verified pairs), against an in-sample suite that claimed 100%.
  Merging on a 25%-precision matcher would delete real, distinct businesses.
  49,129 flagged pairs imply only 8,620-16,854 true duplicates = 3.2-6.3%
  record inflation, which is DISCLOSED rather than silently "fixed".
  Do not add a dedup step here without a fresh out-of-sample validation.

RULE 3 — NON-STOREFRONT RECORDS ARE EXCLUDED FROM BUSINESS COUNTS.
  Finding: 2,986 campus-interior records citywide (College Classroom, Student
  Center, College Lab, campus_building...), plus offices/residential/freight/
  government pages. A campus emits dozens of fake "places": 208 res-9 cells
  hold >=20 such records, worst 130. Exclusion is CATEGORY-BASED only - a
  name-regex pass was tried and over-matched badly (swept in medical labs,
  dental labs, "Block cafe"). Cells that were distorted are flagged via
  `density_distorted`, because filtering fixes the count but such a cell was
  never comparable to a normal one.
=============================================================================

CONFIDENCE MODEL (per metric per cell, never per cell alone):
  corroborated  - 2+ independent sources within the same track agree
  single_source - only one source has it
  unavailable   - no source covers it
Cross-track agreement is meaningless and is never used (a built-out district
can have flat construction and active business churn simultaneously).
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import pyproj
import rasterio
from rasterio.windows import from_bounds
from shapely.geometry import Point
from shapely.prepared import prep

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.config._common import threshold, ROOT
from pipeline.config.categories import GROUPS as OV_GROUPS, FSQ_GROUPS, fsq_group_match
from pipeline.qa.qa import check_non_storefront, DENSITY_DISTORTION_MIN

CONFIG = ROOT / "pipeline" / "config"
RAW = ROOT / "data" / "raw"
DERIVED = ROOT / "data" / "derived"
OUT = DERIVED / "h3_tables"

RESOLUTIONS = (8, 9)
PIPELINE_VERSION = "h3-v1"

# Saturation thresholds (GHSL built-up % of cell)
SATURATED_PCT = threshold("saturation", "saturated_pct")
GREENFIELD_PCT = threshold("saturation", "greenfield_pct")

# RULE: count-agreement tolerance for business-layer corroboration.
# "Both sources non-zero" is agreement on EXISTENCE, not on COUNT - one cafe
# in each source could be two different cafes.
#
# SET TO 0.667 (neither source exceeds 1.5x the other). An earlier version used
# 0.5, which was the OBSERVED MEDIAN disagreement (p50 = 0.462 at res-8,
# 0.500 at res-9) - i.e. "corroborated" would have meant "these sources
# disagree by the typical amount", which is circular. Measured sensitivity:
#     tol 0.500 (2.00x): 26.3% of res-8 cells / 23.8% of res-9
#     tol 0.667 (1.50x): 14.2% of res-8 cells / 13.0% of res-9   <-- production
#     tol 0.800 (1.25x): 11.0% of res-8 cells / 10.4% of res-9
# 0.667 roughly halves the corroborated set versus 0.5. That is the honest
# number, not a worse one.
COUNT_AGREEMENT_MIN_RATIO = threshold("corroboration", "min_ratio")

# Kontur vintage. Used as present-day, which it is not.
MIN_LAND_FRACTION_FOR_DENSITY = threshold("land_fraction_floor", "value")
POPULATION_AS_OF = "2023-11-01"

# Measured-growth staleness thresholds (GHSL 2015 -> 2025), land-normalised.
GROWTH_PCT_MIN = 50.0
GROWTH_LAND_FRAC_MIN = 0.05

GOV_RELATIONS = {"Cairo": 4103336, "Giza": 3824206, "Alexandria": 3061846, "Qalyubiya": 4103337}
GEOM_FILES = [Path("/tmp/gov_geom.json"), Path("/tmp/alex_qal_geom.json")]
BUILT_S_2025 = [
    ROOT / "data/ghsl_cache/GHS_BUILT_S_E2025_GLOBE_R2023A_4326_3ss_V1_0_R6_C22.tif",
    ROOT / "data/ghsl_cache/GHS_BUILT_S_E2025_GLOBE_R2023A_4326_3ss_V1_0_R6_C21.tif",
]
# Snapshot-versioned path. A loose copy of the same file also existed at
# data/kontur/, byte-identical, which broke the raw/ convention: inputs are
# immutable snapshots so a rebuild can name exactly which vintage it used.
KONTUR = ROOT / "data/raw/kontur/snapshot=20231101/kontur_population_EG_20231101.gpkg"


# ---------------------------------------------------------------- helpers
def load_governorates() -> dict:
    from shapely.geometry import LineString, MultiLineString
    from shapely.ops import linemerge, polygonize, unary_union
    by_id = {}
    for f in GEOM_FILES:
        if not f.exists():
            continue
        for el in json.loads(f.read_text())["elements"]:
            lines = [LineString([(p["lon"], p["lat"]) for p in m["geometry"]])
                     for m in el.get("members", [])
                     if m.get("role") == "outer" and m.get("geometry") and len(m["geometry"]) > 1]
            if lines:
                built = list(polygonize(linemerge(MultiLineString(lines))))
                if built:
                    by_id[el["id"]] = unary_union(built)
    return {lab: by_id[rid] for lab, rid in GOV_RELATIONS.items() if rid in by_id}


def cell_centroid(cells):
    return [h3.cell_to_latlng(c) for c in cells]


def ghsl_builtup_by_cell_epoch(epoch: int, res: int) -> pd.DataFrame:
    """Sum GHS-BUILT-S for a given epoch (m^2 per pixel) into H3 cells."""
    acc = {}
    tiles = [ROOT / f"data/ghsl_cache/GHS_BUILT_S_E{epoch}_GLOBE_R2023A_4326_3ss_V1_0_{t}.tif"
             for t in ("R6_C22", "R6_C21")]
    for tif in tiles:
        if not tif.exists():
            continue
        with rasterio.open(tif) as src:
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
    return pd.DataFrame({"h3_index": list(acc), f"builtup_m2_ghsl_{epoch}": list(acc.values())})


def ghsl_builtup_by_cell(res: int) -> pd.DataFrame:
    """Sum GHS-BUILT-S 2025 (m^2 per pixel) into H3 cells."""
    acc = {}
    for tif in BUILT_S_2025:
        if not tif.exists():
            continue
        with rasterio.open(tif) as src:
            data = src.read(1)
            tr = src.transform
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
    return pd.DataFrame({"h3_index": list(acc), "builtup_m2_ghsl": list(acc.values())})


# ---------------------------------------------------------------- stage 1
def build_h3_cell(res: int, govs: dict) -> pd.DataFrame:
    lf = pd.read_csv(CONFIG / f"h3_land_fraction_res{res}.csv")
    df = lf[["h3_index", "land_fraction"]].copy()
    df["h3_res"] = res
    df["cell_area_m2"] = [h3.cell_area(c, unit="m^2") for c in df.h3_index]
    # RULE 1: land area, not cell area, is the denominator everywhere downstream
    df["land_area_m2"] = df.cell_area_m2 * df.land_fraction

    cents = cell_centroid(df.h3_index.tolist())
    prepared = {k: prep(v) for k, v in govs.items()}
    df["governorate"] = [next((k for k, pg in prepared.items() if pg.contains(Point(lo, la))), "outside")
                         for la, lo in cents]

    g = ghsl_builtup_by_cell(res)
    df = df.merge(g, on="h3_index", how="left")
    df["builtup_m2_ghsl"] = df.builtup_m2_ghsl.fillna(0.0)
    df["builtup_pct"] = np.where(df.land_area_m2 > 0,
                                 100 * df.builtup_m2_ghsl / df.land_area_m2, 0.0).clip(0, 100)
    df["saturation_class"] = np.select(
        [df.builtup_pct >= SATURATED_PCT, df.builtup_pct < GREENFIELD_PCT],
        ["SATURATED", "GREENFIELD"], default="DEVELOPING")

    ob_path = (DERIVED / "h3" / f"res={res}" / "metric=builtup_presence_m2" /
               "resolver=ob-v1" / "snapshot=OB_2023" / "cells.parquet")
    if ob_path.exists():
        ob = pd.read_parquet(ob_path)[["h3_index", "value"]].rename(columns={"value": "ob_presence_m2"})
        df = df.merge(ob, on="h3_index", how="left")
    else:
        df["ob_presence_m2"] = np.nan
    df["coverage_ratio"] = np.where(df.builtup_m2_ghsl > 0,
                                    df.ob_presence_m2 / df.builtup_m2_ghsl, np.nan).round(3)

    # POPULATION STALENESS — MEASURED GROWTH, not saturation class.
    # Kontur is a 2023 vintage used as present-day. The first version flagged
    # every GREENFIELD/DEVELOPING cell, which fired on 95.9% of res-8 cells and
    # 93.8% of res-9 - useless as a discriminator, because most cells sit in the
    # 2km dilation ring around built-up area and are legitimately low-built-up.
    # Now flags cells with MEASURED construction between the GHSL 2015 and 2025
    # epochs: >=50% increase in built-up surface AND new built-up covering >=5%
    # of the cell's LAND area. The second term is land-normalised so the rule
    # behaves the same at both resolutions (a res-8 cell is ~7x a res-9 cell, so
    # a fixed m^2 threshold would flag 26% vs 6% for the same real phenomenon).
    g15 = ghsl_builtup_by_cell_epoch(2015, res)
    df = df.merge(g15, on="h3_index", how="left")
    df["builtup_m2_ghsl_2015"] = df.builtup_m2_ghsl_2015.fillna(0.0)
    abs_growth = df.builtup_m2_ghsl - df.builtup_m2_ghsl_2015
    pct_growth = np.where(df.builtup_m2_ghsl_2015 > 0,
                          100 * abs_growth / df.builtup_m2_ghsl_2015, np.inf)
    new_frac = np.where(df.land_area_m2 > 0, abs_growth / df.land_area_m2, 0.0)
    df["builtup_growth_pct_2015_2025"] = np.round(np.where(np.isfinite(pct_growth), pct_growth, np.nan), 1)
    df["population_stale"] = (pct_growth >= GROWTH_PCT_MIN) & (new_frac >= GROWTH_LAND_FRAC_MIN)
    return df


# ---------------------------------------------------------------- stage 2
def load_places(govs: dict) -> pd.DataFrame:
    snaps = sorted((RAW / "overture").glob("snapshot=*"))
    ov = pd.read_parquet(snaps[-1] / "places.parquet")
    ov_snap = snaps[-1].name.split("=", 1)[1]
    ov["source"] = "overture"

    fsnaps = sorted((RAW / "fsq").glob("snapshot=*"))
    fs = pd.read_parquet(fsnaps[-1] / "places_egypt.parquet")
    fsq_snap = fsnaps[-1].name.split("=", 1)[1]
    fs = fs.rename(columns={"latitude": "lat", "longitude": "lon"})
    fs["source"] = "fsq"
    fs["category"] = fs.fsq_category_labels.apply(lambda l: l[-1] if l is not None and len(l) else None)
    fs = fs[(fs.lon.between(29.5803, 31.8979)) & (fs.lat.between(29.1717, 31.352))]

    cols = ["source", "name", "category", "lat", "lon"]
    d = pd.concat([ov[cols], fs[cols + ["fsq_category_labels"]]], ignore_index=True)

    # RULE 3: exclude non-storefront (offices / residential / freight /
    # government / campus interiors) from all business counts.
    ns = check_non_storefront(d[cols])
    key = set(map(tuple, ns[["source", "name", "lat", "lon"]].astype(object).values.tolist()))
    d["_ns"] = [tuple(x) in key for x in d[["source", "name", "lat", "lon"]].astype(object).values.tolist()]
    kept = d[~d._ns].copy()
    return kept, ov_snap, fsq_snap, int(d._ns.sum())


def business_metrics(places: pd.DataFrame, res: int, ov_snap, fsq_snap) -> pd.DataFrame:
    p = places.copy()
    p["h3_index"] = [h3.latlng_to_cell(a, b, res) for a, b in zip(p.lat, p.lon)]
    p["cat_str"] = p.category.astype(str)

    rows = []
    groups = list(OV_GROUPS.keys())
    for grp in groups + ["total"]:
        if grp == "total":
            m = pd.Series(True, index=p.index)
        else:
            ov_m = (p.source == "overture") & p.cat_str.isin(OV_GROUPS[grp])
            fsq_m = (p.source == "fsq") & p.fsq_category_labels.apply(
                lambda l: fsq_group_match(l, grp) if l is not None else False)
            m = ov_m | fsq_m
        sub = p[m]
        if not len(sub):
            continue
        g = sub.groupby(["h3_index", "source"]).size().unstack(fill_value=0)
        for c in ("overture", "fsq"):
            if c not in g:
                g[c] = 0
        g = g.reset_index()
        g["value"] = g.overture + g.fsq

        # CHANGE (2026-08-21): corroboration requires COUNT AGREEMENT, not just
        # co-existence. Both non-zero AND min/max ratio >= tolerance.
        both = (g.overture > 0) & (g.fsq > 0)
        ratio = np.where(both, np.minimum(g.overture, g.fsq) / np.maximum(g.overture, g.fsq).replace(0, np.nan), 0.0)
        g["agreement_ratio"] = np.round(ratio, 3)
        g["confidence"] = np.where(both & (ratio >= COUNT_AGREEMENT_MIN_RATIO),
                                   "corroborated", "single_source")
        g["n_sources"] = (g.overture > 0).astype(int) + (g.fsq > 0).astype(int)
        g["metric"] = f"business_count.{grp}"
        g["track"] = "business"
        g["as_of"] = ov_snap[:10]
        g["source_snapshots"] = json.dumps({"overture": ov_snap, "fsq": fsq_snap})
        rows.append(g)
    return pd.concat(rows, ignore_index=True)


def population_metric(res: int, cells: pd.DataFrame) -> pd.DataFrame:
    """Population per cell, from Kontur.

    KONTUR IS NATIVELY H3 RES-8. It ships an `h3` column, and its polygons match
    res-8 cells exactly (measured: IoU > 0.99 on every feature sampled, mean
    area 0.86 km2 against res-8's 0.74). It is not a 400 m grid that happens to
    resemble h3 - it IS h3, at res-8.

    THE BUG THIS REPLACES. The previous version indexed each Kontur hexagon by
    the h3 cell containing its CENTROID, at whatever resolution was being built.
    At res-8 that is an identity mapping and correct. At res-9 a parent's
    centroid falls inside exactly one of its seven children, so every hexagon
    dumped its entire population into a single child and the other six got
    nothing. Measured: 100% of parents had exactly one child carrying the value,
    only 12.9% of res-9 cells had a population row at all, and single res-9
    cells of 0.105 km2 held 40,241 people - 383,000/km2, roughly four times the
    densest place on earth.
    It survived QA because the CITY TOTAL still reconciled: 34.0M at both
    resolutions. Every cell was wrong; the sum was right. Reports run at res-9,
    so a seven-cell catchment picked up either ~0 people or one entire res-8
    hexagon's worth depending on whether the ring happened to contain a carrier
    child, and people-per-outlet inherited the noise.

    WHY THIS IS INTERPOLATED AND SAYS SO. Because the source is res-8, there is
    no finer measurement to go back to - res-9 population cannot be observed,
    only apportioned. Each parent's population is therefore spread across its
    children in proportion to their LAND area (RULE: land, never raw area, so
    that a child which is half river does not receive half the people). Uniform
    density within the parent is the no-information answer, and it is the honest
    one: we know how many people live in a 0.74 km2 hexagon and we do not know
    where inside it they are. Weighting by built-up area would look sharper and
    would be a guess dressed as a measurement.
    The rows carry native_res=8 so nothing downstream can mistake an
    interpolated figure for an observation.
    """
    gdf = gpd.read_file(KONTUR)
    # Use the index Kontur ships rather than re-deriving it from geometry.
    if "h3" in gdf.columns:
        parent = gdf["h3"].astype(str)
    else:
        gw = gdf.to_crs("EPSG:4326")
        cen = gw.geometry.centroid
        parent = pd.Series([h3.latlng_to_cell(y, x, 8) for x, y in zip(cen.x, cen.y)])
    at8 = (pd.DataFrame({"h3_index": parent.values, "value": gdf["population"].values})
           .groupby("h3_index", as_index=False)["value"].sum())

    if res == 8:
        g = at8
    else:
        # Apportion each parent across its children by land area.
        kids = cells[["h3_index", "land_area_m2"]].copy()
        kids["parent"] = [h3.cell_to_parent(c, 8) for c in kids.h3_index]
        tot = kids.groupby("parent")["land_area_m2"].transform("sum")
        # A parent whose children are all water gets an equal split rather than
        # a divide-by-zero; its population is ~0 anyway.
        kids["w"] = np.where(tot > 0, kids.land_area_m2 / tot,
                             1.0 / kids.groupby("parent")["h3_index"].transform("size"))
        g = (kids.merge(at8.rename(columns={"h3_index": "parent", "value": "parent_pop"}),
                        on="parent", how="inner"))
        g["value"] = g.parent_pop * g.w
        g = g[["h3_index", "value"]]
        # Drop rows that round to nobody, so "no row" keeps meaning "no people"
        # rather than "a rounding artifact".
        g = g[g.value >= 0.5]

    g["metric"] = "population"
    g["track"] = "population"
    g["native_res"] = 8
    # Kontur is the ONLY population source available. Calling it corroborated
    # because it looks plausible would be exactly the confidence inflation this
    # study spent days catching.
    g["confidence"] = "single_source"
    g["n_sources"] = 1
    g["as_of"] = POPULATION_AS_OF
    g["source_snapshots"] = json.dumps({"kontur": "20231101"})
    g["overture"] = 0; g["fsq"] = 0; g["agreement_ratio"] = np.nan
    return g


def builtup_metric(res: int, cells: pd.DataFrame) -> pd.DataFrame:
    p = (DERIVED / "h3" / f"res={res}" / "metric=builtup_presence_m2" /
         "resolver=ob-v1" / "snapshot=OB_2023" / "cells.parquet")
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)[["h3_index", "value"]]
    df["metric"] = "builtup_presence_m2"
    df["track"] = "built_environment"
    df["as_of"] = "2023-06-30"

    # Two INDEPENDENT built-environment sources exist per cell: Open Buildings
    # presence (0.5m optical, 2023) and GHSL BUILT-S (100m, 2025 epoch). They
    # measure built-up extent by different sensors and methods, so agreement
    # between them is genuine corroboration - the same standard applied to the
    # business track. Same count-agreement tolerance is used.
    g = cells[["h3_index", "builtup_m2_ghsl"]]
    df = df.merge(g, on="h3_index", how="left")
    df["builtup_m2_ghsl"] = df.builtup_m2_ghsl.fillna(0.0)
    both = (df.value > 0) & (df.builtup_m2_ghsl > 0)
    ratio = np.where(both,
                     np.minimum(df.value, df.builtup_m2_ghsl) /
                     np.maximum(df.value, df.builtup_m2_ghsl).replace(0, np.nan), 0.0)
    df["agreement_ratio"] = np.round(ratio, 3)
    df["confidence"] = np.where(both & (ratio >= COUNT_AGREEMENT_MIN_RATIO),
                                "corroborated", "single_source")
    df["n_sources"] = both.astype(int) + 1
    df["source_snapshots"] = json.dumps({"open_buildings": "v1_2023_06_30",
                                         "ghsl_built_s": "R2023A_E2025"})
    df["overture"] = 0; df["fsq"] = 0
    return df.drop(columns=["builtup_m2_ghsl"])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    govs = load_governorates()
    places, ov_snap, fsq_snap, n_ns = load_places(govs)
    print(f"storefront places: {len(places):,} (excluded {n_ns:,} non-storefront)")

    summary = {}
    for res in RESOLUTIONS:
        print(f"\n=== res-{res} ===")
        cells = build_h3_cell(res, govs)

        # density_distorted flag (RULE 3 companion)
        ns_rows = check_non_storefront(
            pd.concat([pd.read_parquet(sorted((RAW / "overture").glob("snapshot=*"))[-1] / "places.parquet")
                       .assign(source="overture")[["source", "name", "category", "lat", "lon"]]],
                      ignore_index=True))
        if len(ns_rows):
            nsc = pd.Series([h3.latlng_to_cell(a, b, res) for a, b in zip(ns_rows.lat, ns_rows.lon)]).value_counts()
            distorted = set(nsc[nsc >= DENSITY_DISTORTION_MIN].index)
        else:
            distorted = set()
        cells["density_distorted"] = cells.h3_index.isin(distorted)
        cells["pipeline_version"] = PIPELINE_VERSION
        cells.to_parquet(OUT / f"h3_cell_res{res}.parquet", index=False)
        print(f"  h3_cell: {len(cells):,} cells")

        m = pd.concat([business_metrics(places, res, ov_snap, fsq_snap),
                       population_metric(res, cells), builtup_metric(res, cells)], ignore_index=True)
        # native_res records the resolution a metric was MEASURED at. Only
        # population differs from the table's own resolution; everything else
        # is observed where it is stored.
        if "native_res" not in m.columns:
            m["native_res"] = np.nan
        m["native_res"] = m.native_res.fillna(res).astype(int)
        m = m.merge(cells[["h3_index", "land_area_m2"]], on="h3_index", how="left")
        # RULE 1 materialised, WITH A FLOOR ON THE DENOMINATOR.
        # Dividing by habitable land is right, but as the land share approaches
        # zero the quotient stops describing geography: an Alexandria Corniche
        # cell that is 99.99% sea produced 8,260,594 people/km2. The floor is
        # 0.05, chosen from the distribution - land_fraction exceeds 0.95 for
        # 95% of res-9 cells and only 0.34% fall below 0.05 - so it discards
        # almost nothing and removes every cell where the denominator does more
        # work than the numerator. NaN is honest; 8 million is not.
        m = m.merge(cells[["h3_index", "land_fraction"]], on="h3_index", how="left")
        usable = (m.land_area_m2 > 0) & (m.land_fraction >= MIN_LAND_FRACTION_FOR_DENSITY)
        m["value_per_land_km2"] = np.where(
            usable, m.value / (m.land_area_m2 / 1e6), np.nan).round(2)
        m = m.drop(columns=["land_fraction"])
        m["h3_res"] = res
        m["pipeline_version"] = PIPELINE_VERSION
        m["computed_at"] = datetime.now(timezone.utc).isoformat()
        m = m[m.h3_index.isin(set(cells.h3_index))]
        m.to_parquet(OUT / f"h3_metric_res{res}.parquet", index=False)
        print(f"  h3_metric: {len(m):,} rows, {m.metric.nunique()} metrics")
        summary[res] = (cells, m)

    print("\n" + "=" * 78)
    for res, (cells, m) in summary.items():
        print(f"\nres-{res} confidence by track:")
        t = m.groupby(["track", "confidence"]).size().unstack(fill_value=0)
        t["total"] = t.sum(1)
        for c in ("corroborated", "single_source"):
            if c in t:
                t[c + "_%"] = (100 * t[c] / t.total).round(1)
        print(t.to_string())
        print(f"  saturation: {cells.saturation_class.value_counts().to_dict()}")
        print(f"  population_stale cells: {int(cells.population_stale.sum()):,} "
              f"({100*cells.population_stale.mean():.1f}%)")
        print(f"  density_distorted cells: {int(cells.density_distorted.sum()):,}")


if __name__ == "__main__":
    main()

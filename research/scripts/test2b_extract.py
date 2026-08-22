"""
Test 2B extraction: El Shabab Street (Sheikh Zayed) and 90th Street (New
Cairo) - THIRD-SOURCE COMPARISON against Google Maps, NOT ground truth.
Google only shows what's open today, so this measures coverage gap vs
Google; it cannot detect stale records or businesses missing from every
source. Do not compute a recall figure from these files.

Both streets are too long to ground-truth in full (5.4km and 24.4km).
scripts/street_window_selector.py picked the highest-Overture+FSQ-POI-
density 500m window on each, 150m buffer either side - the commercial
"heart" of the street, per user direction (2026-08-18), not a guessed
sub-stretch.
"""
import pickle
import sys
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import ROOT, PLACES_PATH, get_con

FSQ_PARQUET = ROOT / "data" / "fsq_shabab_90th.parquet"
BUFFER_M = 150


def normalize_name(name) -> str:
    import re
    if not name or pd.isna(name):
        return ""
    name = str(name).lower().strip()
    name = re.sub(r"[^\w\s]", "", name, flags=re.UNICODE)
    return re.sub(r"\s+", " ", name)


def get_overture_rows(buf):
    con = get_con()
    minx, miny, maxx, maxy = buf.bounds
    base = f"read_parquet('{PLACES_PATH}', hive_partitioning=1)"
    q = f"""
        SELECT names.primary AS name, categories.primary AS category,
               ST_X(geometry) AS lon, ST_Y(geometry) AS lat
        FROM {base}
        WHERE bbox.xmin <= {maxx} AND bbox.xmax >= {minx} AND bbox.ymin <= {maxy} AND bbox.ymax >= {miny}
    """
    df = con.execute(q).fetchdf()
    df = df[df.apply(lambda r: buf.contains(Point(r["lon"], r["lat"])), axis=1)].copy()
    df["source"] = "overture"
    df["date_created"] = ""
    return df[["source", "name", "category", "lat", "lon", "date_created"]]


def get_fsq_rows(buf):
    con = get_con()
    minx, miny, maxx, maxy = buf.bounds
    q = f"""
        SELECT name, fsq_category_labels, latitude AS lat, longitude AS lon, date_created
        FROM read_parquet('{FSQ_PARQUET}')
        WHERE longitude BETWEEN {minx} AND {maxx} AND latitude BETWEEN {miny} AND {maxy}
    """
    df = con.execute(q).fetchdf()
    if len(df):
        df = df[df.apply(lambda r: buf.contains(Point(r["lon"], r["lat"])), axis=1)].copy()

    def leaf_category(l):
        try:
            if l is not None and len(l) > 0:
                return l[-1]
        except TypeError:
            pass
        return None
    df["category"] = df["fsq_category_labels"].apply(leaf_category) if len(df) else []
    df["source"] = "fsq"
    return df[["source", "name", "category", "lat", "lon", "date_created"]]


def match_across_sources(df: pd.DataFrame) -> pd.DataFrame:
    df = df.reset_index(drop=True)
    df["norm_name"] = df["name"].apply(normalize_name)
    df["in_both_sources"] = "n"
    ov_idx = df[df["source"] == "overture"].index
    fsq_idx = df[df["source"] == "fsq"].index
    for i in ov_idx:
        for j in fsq_idx:
            d_m = (((df.loc[i, "lat"] - df.loc[j, "lat"]) * 111320) ** 2 +
                   ((df.loc[i, "lon"] - df.loc[j, "lon"]) * 111320 * 0.868) ** 2) ** 0.5
            if d_m <= 20 and SequenceMatcher(None, df.loc[i, "norm_name"], df.loc[j, "norm_name"]).ratio() >= 0.82:
                df.loc[i, "in_both_sources"] = "y"
                df.loc[j, "in_both_sources"] = "y"
    return df.drop(columns=["norm_name"])


def extract_one(pkl_path, out_csv, street_label, endpoint_link_a, endpoint_link_b, landmarks):
    with open(pkl_path, "rb") as f:
        result = pickle.load(f)
    buf = result["polygon_wgs84"]

    ov = get_overture_rows(buf)
    fsq = get_fsq_rows(buf)
    combined = pd.concat([ov, fsq], ignore_index=True)
    combined = match_across_sources(combined)
    combined["exists_today"] = ""
    combined["category_correct"] = ""
    combined["notes"] = ""
    combined = combined.sort_values(["source", "name"])

    minx, miny, maxx, maxy = buf.bounds
    map_link = f"https://www.openstreetmap.org/export#map=16&bbox={minx:.5f}%2C{miny:.5f}%2C{maxx:.5f}%2C{maxy:.5f}"

    header_lines = [
        f"# THIRD-SOURCE COMPARISON (vs Google Maps) - NOT ground truth - {street_label}",
        f"# Google shows only what's open today: this measures coverage gap vs Google only.",
        f"# It cannot detect stale records or businesses missing from every source. Do not compute recall from this file.",
        f"# Buffer width: {BUFFER_M}m either side of the chosen 500m window (highest Overture+FSQ POI density on the street)",
        f"# Window: {result['start_latlon']} -> {result['end_latlon']}  (street total length {result['total_street_length_m']:.0f}m)",
        f"# Map: {map_link}",
        f"# Nearby cross-streets/landmarks: {landmarks}",
        f"# Overture: {len(ov)} places  |  FSQ: {len(fsq)} places",
    ]
    with open(out_csv, "w") as f:
        for line in header_lines:
            f.write(line + "\n")
        combined.to_csv(f, index=False)

    print(f"\n=== {street_label} ===")
    print(f"  Overture: {len(ov)}  FSQ: {len(fsq)}  in_both=y: {(combined['in_both_sources']=='y').sum()}")
    print(f"  Map: {map_link}")
    print(f"  Wrote {out_csv}")


def main():
    extract_one(
        "/tmp/shabab_best.pkl",
        ROOT / "output" / "gcheck-elshabab.csv",
        "El Shabab Street, Sheikh Zayed",
        None, None,
        "Streets 2,3,5,6,10,12,22,25,26,27,29,33,36,37; Al Zohour St; Al Mostakbal Rd (Future Rd); "
        "Dr. Atef Sedky St; Dr. Ali Lotfi St; Gamal El Din El Afghani St",
    )
    extract_one(
        "/tmp/ninetieth_best.pkl",
        ROOT / "output" / "gcheck-90thstreet.csv",
        "90th Street, New Cairo (Tagamoa)",
        None, None,
        "El Orouba Axis (major intersection) and Side El Orouba Axis; Al Moshir Tantawy Bridge; "
        "Al Liwaa Zaki Baqe Youssef Tunnel; Ahmed Aboud Pasha St; Qassem Amin St; Mai Zeyada St",
    )


if __name__ == "__main__":
    main()

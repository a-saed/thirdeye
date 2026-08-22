"""
Test 2b (pre-check before Test 2) - Is there enough OSM POI history in
this market to carry the temporal feature (Test 3, Test 5)?

Overture Places here has zero OpenStreetMap contribution (test1b_1 showed
100% Meta/Foursquare/Microsoft/PinMeTo/AllThePlaces). The planned temporal
signal comes from ohsome, which is OSM-only. If OSM POI density in Egypt
is too thin, that signal is noise regardless of how good Overture's
snapshot is.

For each district:
  1. Current OSM counts (ohsome /elements/count, single timestamp) for
     amenity=cafe, amenity=restaurant, amenity=pharmacy,
     shop=supermarket|convenience, amenity=fast_food.
  2. Same groups from mapped Overture categories, for a side-by-side
     ratio.
  3. Annual OSM counts 2015 -> now (ohsome /elements/count, P1Y) for the
     same five groups.

Uses ohsome's actual max data timestamp (checked via /v1/metadata) rather
than an assumed "today", since ohsome's underlying OSM history extract has
a fixed cutoff independent of the current date.
"""
import sys
import time
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import ROOT, PLACES_PATH, get_con, load_districts, bbox_where
from scripts.categories import CAFE, RESTAURANT, PHARMACY

OHSOME_BASE = "https://api.ohsome.org/v1"

# OSM filter <-> Overture mapped-category-set pairs, kept 1:1 so the ratio
# is a fair comparison (e.g. OSM's amenity=restaurant excludes fast food,
# which is its own amenity=fast_food tag - so the Overture side excludes
# fast_food_restaurant from the restaurant group too).
GROUPS = {
    "cafe": {
        "osm_filter": "amenity=cafe",
        "overture_categories": CAFE,
    },
    "restaurant": {
        "osm_filter": "amenity=restaurant",
        "overture_categories": RESTAURANT - {"fast_food_restaurant"},
    },
    "pharmacy": {
        "osm_filter": "amenity=pharmacy",
        "overture_categories": PHARMACY,
    },
    "supermarket_convenience": {
        "osm_filter": "shop=supermarket or shop=convenience",
        "overture_categories": {"supermarket", "convenience_store"},
    },
    "fast_food": {
        "osm_filter": "amenity=fast_food",
        "overture_categories": {"fast_food_restaurant"},
    },
}


def get_ohsome_max_timestamp() -> str:
    r = requests.get(f"{OHSOME_BASE}/metadata", timeout=20)
    r.raise_for_status()
    to_ts = r.json()["extractRegion"]["temporalExtent"]["toTimestamp"]
    return to_ts[:10]  # YYYY-MM-DD


def ohsome_count(bbox: dict, osm_filter: str, time_param: str) -> list:
    bboxes = f"{bbox['xmin']},{bbox['ymin']},{bbox['xmax']},{bbox['ymax']}"
    resp = requests.post(
        f"{OHSOME_BASE}/elements/count",
        data={"bboxes": bboxes, "filter": osm_filter, "time": time_param},
        timeout=60,
    )
    if resp.status_code != 200:
        return None
    return resp.json()["result"]


def overture_category_counts(con, base: str, bbox: dict) -> dict:
    where = bbox_where(bbox)
    q = f"SELECT categories.primary AS cat, count(*) AS n FROM {base} WHERE {where} GROUP BY 1"
    return dict(con.execute(q).fetchall())


def main():
    max_ts = get_ohsome_max_timestamp()
    print(f"ohsome max data timestamp: {max_ts} (using this as 'now', not today's date)\n")

    con = get_con()
    districts = load_districts()
    base = f"read_parquet('{PLACES_PATH}', hive_partitioning=1)"

    ratio_rows = []
    series_rows = []

    for name, d in districts.items():
        bbox = d["bbox"]
        ov_counts = overture_category_counts(con, base, bbox)

        print(f"\n{'='*70}\n{name}\n{'='*70}")
        print(f"{'group':26s} {'OSM (now)':>10s} {'Overture':>10s} {'ratio OSM/Overture':>20s}")
        for group, spec in GROUPS.items():
            current = ohsome_count(bbox, spec["osm_filter"], max_ts)
            time.sleep(0.3)
            osm_now = current[0]["value"] if current else None

            overture_n = sum(ov_counts.get(c, 0) for c in spec["overture_categories"])
            ratio = (osm_now / overture_n) if overture_n and osm_now is not None else None

            print(f"{group:26s} {str(osm_now):>10s} {overture_n:10d} {str(round(ratio,3)) if ratio is not None else 'n/a':>20s}")
            ratio_rows.append({
                "district": name, "group": group, "osm_now": osm_now,
                "overture_now": overture_n, "ratio_osm_over_overture": ratio,
            })

            annual = ohsome_count(bbox, spec["osm_filter"], f"2015-01-01/{max_ts}/P1Y")
            time.sleep(0.3)
            if annual:
                for point in annual:
                    series_rows.append({
                        "district": name, "group": group,
                        "year": point["timestamp"][:4], "osm_count": point["value"],
                    })

        print("\nAnnual OSM counts (2015 -> now), per group:")
        for group in GROUPS:
            sub = [r for r in series_rows if r["district"] == name and r["group"] == group]
            vals = ", ".join(f"{r['year']}={int(r['osm_count'])}" for r in sub)
            print(f"  {group:26s} {vals}")

    ratio_df = pd.DataFrame(ratio_rows)
    series_df = pd.DataFrame(series_rows)
    ratio_path = ROOT / "output" / "test2b_osm_vs_overture_ratio.csv"
    series_path = ROOT / "output" / "test2b_osm_annual_series.csv"
    ratio_df.to_csv(ratio_path, index=False)
    series_df.to_csv(series_path, index=False)
    print(f"\nWrote {ratio_path}")
    print(f"Wrote {series_path}")

    print("\n" + "=" * 70)
    print("READ: is OSM POI density in Egypt sufficient for YoY trend analysis?")
    print("=" * 70)
    latest_year_vals = series_df[series_df["year"] == series_df["year"].max()]
    low = latest_year_vals[latest_year_vals["osm_count"] < 10]
    print(f"Groups/districts with fewer than 10 OSM elements in the latest year: {len(low)} of {len(latest_year_vals)}")
    if len(low) > 0:
        print("At counts this low, a single new/deleted OSM tag changes the")
        print("year-over-year percentage by tens of points - the Test 3 kill")
        print("criterion (>40% YoY jump = bulk import) will trigger on ordinary")
        print("noise, not just real import events, in these cells.")


if __name__ == "__main__":
    main()

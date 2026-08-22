"""
Test 1 - Does the data exist here?

For each district bbox: total POI count, count by categories.primary
(top 30), % with non-null primary category, % with a name.

Queries Overture places directly from S3 with bbox predicate pushdown
(no full-planet scan).
"""
import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
OVERTURE_RELEASE = "2026-07-22.0"
PLACES_PATH = f"s3://overturemaps-us-west-2/release/{OVERTURE_RELEASE}/theme=places/type=place/*"


def get_con():
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;")
    con.execute("SET s3_region='us-west-2';")
    return con


def run_district(con, name: str, bbox: dict) -> dict:
    where = (
        f"bbox.xmin <= {bbox['xmax']} AND bbox.xmax >= {bbox['xmin']} "
        f"AND bbox.ymin <= {bbox['ymax']} AND bbox.ymax >= {bbox['ymin']}"
    )
    base = f"read_parquet('{PLACES_PATH}', hive_partitioning=1)"

    total = con.execute(f"SELECT count(*) FROM {base} WHERE {where}").fetchone()[0]

    pct_cat = con.execute(
        f"""SELECT
                round(100.0 * sum(CASE WHEN categories.primary IS NOT NULL THEN 1 ELSE 0 END) / count(*), 2)
            FROM {base} WHERE {where}"""
    ).fetchone()[0] if total else None

    pct_name = con.execute(
        f"""SELECT
                round(100.0 * sum(CASE WHEN names.primary IS NOT NULL AND names.primary != '' THEN 1 ELSE 0 END) / count(*), 2)
            FROM {base} WHERE {where}"""
    ).fetchone()[0] if total else None

    cat_counts = con.execute(
        f"""SELECT categories.primary AS category, count(*) AS n
            FROM {base} WHERE {where}
            GROUP BY categories.primary
            ORDER BY n DESC
            LIMIT 30"""
    ).fetchdf() if total else None

    return {
        "district": name,
        "bbox": bbox,
        "total_pois": total,
        "pct_with_primary_category": pct_cat,
        "pct_with_name": pct_name,
        "top_categories": cat_counts,
    }


def main():
    districts = json.loads((ROOT / "data" / "districts.json").read_text())
    con = get_con()

    results = []
    for name, d in districts.items():
        print(f"Querying {name}...", flush=True)
        r = run_district(con, name, d["bbox"])
        results.append(r)

        if r["top_categories"] is not None:
            out_csv = ROOT / "output" / f"test1_{name.replace(' ', '_').lower()}_categories.csv"
            r["top_categories"].to_csv(out_csv, index=False)

    summary_path = ROOT / "output" / "test1_summary.csv"
    with open(summary_path, "w") as f:
        f.write("district,total_pois,pct_with_primary_category,pct_with_name\n")
        for r in results:
            f.write(
                f"{r['district']},{r['total_pois']},{r['pct_with_primary_category']},{r['pct_with_name']}\n"
            )

    print("\n" + "=" * 70)
    for r in results:
        print(f"\n=== {r['district']} ===")
        print(f"  bbox: {r['bbox']}")
        print(f"  total POIs: {r['total_pois']}")
        print(f"  % with primary category: {r['pct_with_primary_category']}")
        print(f"  % with name: {r['pct_with_name']}")
        if r["top_categories"] is not None:
            print("  top categories:")
            for _, row in r["top_categories"].iterrows():
                print(f"    {row['category']}: {row['n']}")
    print(f"\nWrote {summary_path} and per-district category CSVs to output/")


if __name__ == "__main__":
    main()

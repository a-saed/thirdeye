"""
FSQ Leg A: date_created/date_closed reconstruction, the business-layer
second source test.md calls for.

Uses the pulled local slice (data/fsq_districts.parquet - our 3 district
bboxes only, pulled directly from the Iceberg catalog since country-level
or any other filter gets zero partition pruning on this table; see
scripts/test2c_fsq_1_date_integrity.py for date field integrity, which
already confirmed 0 unparseable dates and one consistent YYYY-MM-DD
format everywhere).

Five things, matching test.md's spec:
  1. FSQ POI count per district vs Overture mapped counts (separate FSQ
     category mapping - scripts/categories.py FSQ_* - not the Overture one)
  2. date_created histogram by year, per district, 2010-2026
  3. % of records with non-null date_closed, per district
  4. "places open as of 1 Jan" reconstruction, 2015-2026, per district
  5. Prose read on realism (Foursquare check-in adoption bias) and on
     whether date_closed is populated enough to matter
"""
import sys
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import ROOT, PLACES_PATH, get_con, load_districts, bbox_where
from scripts.categories import GROUPS as OVERTURE_GROUPS, FSQ_GROUPS, fsq_group_match

FSQ_PARQUET = str(ROOT / "data" / "fsq_districts.parquet")
YEARS = list(range(2015, 2027))


def fsq_bbox_where(bbox: dict) -> str:
    return f"longitude BETWEEN {bbox['xmin']} AND {bbox['xmax']} AND latitude BETWEEN {bbox['ymin']} AND {bbox['ymax']}"


def load_fsq_district(con, district_bbox) -> pd.DataFrame:
    where = fsq_bbox_where(district_bbox)
    return con.execute(f"SELECT * FROM read_parquet('{FSQ_PARQUET}') WHERE {where}").fetchdf()


def main():
    fsq_con = duckdb.connect()
    ov_con = get_con()
    districts = load_districts()
    ov_base = f"read_parquet('{PLACES_PATH}', hive_partitioning=1)"

    fsq_dfs = {name: load_fsq_district(fsq_con, d["bbox"]) for name, d in districts.items()}

    # ------------------------------------------------------------------
    # 1. FSQ count vs Overture mapped count, per group, per district
    # ------------------------------------------------------------------
    print("=" * 100)
    print("1. FSQ vs Overture mapped counts")
    print("=" * 100)
    count_rows = []
    for name, d in districts.items():
        df = fsq_dfs[name]
        ov_where = bbox_where(d["bbox"])
        ov_counts = dict(ov_con.execute(f"SELECT categories.primary AS cat, count(*) AS n FROM {ov_base} WHERE {ov_where} GROUP BY 1").fetchall())

        print(f"\n=== {name} (FSQ total={len(df)}) ===")
        for group in FSQ_GROUPS:
            fsq_n = df["fsq_category_labels"].apply(lambda labels: fsq_group_match(labels, group)).sum()
            ov_n = sum(ov_counts.get(m, 0) for m in OVERTURE_GROUPS[group])
            ratio = round(fsq_n / ov_n, 3) if ov_n else None
            print(f"  {group:10s} FSQ={fsq_n:4d}  Overture={ov_n:4d}  ratio(FSQ/Overture)={ratio}")
            count_rows.append({"district": name, "group": group, "fsq_n": int(fsq_n), "overture_n": ov_n, "ratio": ratio})

    pd.DataFrame(count_rows).to_csv(ROOT / "output" / "test2c_fsq_vs_overture_counts.csv", index=False)

    # ------------------------------------------------------------------
    # 2. date_created histogram by year, 2010-2026
    # ------------------------------------------------------------------
    print("\n" + "=" * 100)
    print("2. date_created histogram by year, 2010-2026")
    print("=" * 100)
    hist_rows = []
    for name, df in fsq_dfs.items():
        years = pd.to_datetime(df["date_created"]).dt.year
        years_clipped = years[(years >= 2010) & (years <= 2026)]
        counts = years_clipped.value_counts().sort_index()
        print(f"\n=== {name} ===")
        for y in range(2010, 2027):
            n = int(counts.get(y, 0))
            print(f"  {y}: {'#' * n} ({n})")
            hist_rows.append({"district": name, "year": y, "n_created": n})
    pd.DataFrame(hist_rows).to_csv(ROOT / "output" / "test2c_fsq_date_created_histogram.csv", index=False)

    # ------------------------------------------------------------------
    # 3. % non-null date_closed
    # ------------------------------------------------------------------
    print("\n" + "=" * 100)
    print("3. date_closed population rate")
    print("=" * 100)
    closed_rows = []
    for name, df in fsq_dfs.items():
        total = len(df)
        n_closed = df["date_closed"].notna().sum()
        pct = round(100 * n_closed / total, 2)
        print(f"  {name:14s} {n_closed}/{total} closed-dated  ({pct}%)")
        closed_rows.append({"district": name, "total": total, "n_date_closed": int(n_closed), "pct_date_closed": pct})
    pd.DataFrame(closed_rows).to_csv(ROOT / "output" / "test2c_fsq_date_closed_rate.csv", index=False)

    # ------------------------------------------------------------------
    # 4. "open as of 1 Jan" reconstruction, 2015-2026
    # ------------------------------------------------------------------
    print("\n" + "=" * 100)
    print("4. Reconstructed 'open as of 1 Jan', 2015-2026")
    print("=" * 100)
    recon_rows = []
    for name, df in fsq_dfs.items():
        created = pd.to_datetime(df["date_created"])
        closed = pd.to_datetime(df["date_closed"])
        print(f"\n=== {name} ===")
        series = {}
        for year in YEARS:
            cutoff = pd.Timestamp(f"{year}-01-01")
            open_asof = ((created <= cutoff) & (closed.isna() | (closed > cutoff))).sum()
            series[year] = int(open_asof)
            recon_rows.append({"district": name, "year": year, "open_as_of_jan1": int(open_asof)})
        print("  " + ", ".join(f"{y}={n}" for y, n in series.items()))
    recon_df = pd.DataFrame(recon_rows)
    recon_df.to_csv(ROOT / "output" / "test2c_fsq_reconstruction.csv", index=False)

    print("\nWrote all test2c_fsq_*.csv outputs to output/")


if __name__ == "__main__":
    main()

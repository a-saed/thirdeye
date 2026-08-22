"""
FSQ Leg A, step 0: date field integrity check - run BEFORE any casting.

A silent cast failure on date_created would silently drop POIs from
early years and manufacture fake growth in the open-as-of-year
reconstruction, so this reports the count of NULL / empty / unparseable
rows explicitly per district, and the distinct string formats actually
present in date_created (not assumed to all be one format).
"""
import re
import sys
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import ROOT, load_districts

FSQ_PARQUET = str(ROOT / "data" / "fsq_districts.parquet")


def bbox_where(bbox: dict) -> str:
    return (
        f"longitude BETWEEN {bbox['xmin']} AND {bbox['xmax']} "
        f"AND latitude BETWEEN {bbox['ymin']} AND {bbox['ymax']}"
    )


def main():
    con = duckdb.connect()
    districts = load_districts()

    print("=" * 90)
    print("DATE FIELD INTEGRITY")
    print("=" * 90)

    rows = []
    all_formats = {"date_created": set(), "date_closed": set(), "date_refreshed": set()}

    for name, d in districts.items():
        where = bbox_where(d["bbox"])
        q = f"""
            SELECT date_created, date_closed, date_refreshed
            FROM read_parquet('{FSQ_PARQUET}')
            WHERE {where}
        """
        df = con.execute(q).fetchdf()
        total = len(df)
        print(f"\n=== {name} (n={total}) ===")

        row = {"district": name, "total": total}
        for col in ["date_created", "date_closed", "date_refreshed"]:
            vals = df[col]
            n_null = vals.isna().sum()
            n_empty = (vals == "").sum()
            non_null_non_empty = vals[vals.notna() & (vals != "")]

            # try strict ISO date/timestamp parse; count failures explicitly
            parsed = pd.to_datetime(non_null_non_empty, errors="coerce", format="ISO8601")
            n_unparseable = parsed.isna().sum()

            print(f"  {col:16s} NULL={n_null:6d}  empty=''={n_empty:6d}  "
                  f"unparseable(non-null/empty)={n_unparseable:6d}  "
                  f"usable={total - n_null - n_empty - n_unparseable:6d}")

            row[f"{col}_null"] = int(n_null)
            row[f"{col}_empty"] = int(n_empty)
            row[f"{col}_unparseable"] = int(n_unparseable)
            row[f"{col}_usable"] = int(total - n_null - n_empty - n_unparseable)

            # collect distinct "shape" of the string (structure, not value) via a regex generalisation
            def shape(s):
                if pd.isna(s) or s == "":
                    return None
                x = re.sub(r"\d", "9", str(s))
                return x
            shapes = non_null_non_empty.apply(shape).dropna().unique().tolist()
            all_formats[col].update(shapes)

        rows.append(row)

    print("\n" + "=" * 90)
    print("Distinct string SHAPES observed per field (digits replaced with 9, so '2019-05-01' -> '9999-99-99'):")
    for col, shapes in all_formats.items():
        print(f"  {col}: {sorted(shapes)}")

    out = pd.DataFrame(rows)
    out_path = ROOT / "output" / "test2c_fsq_date_integrity.csv"
    out.to_csv(out_path, index=False)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()

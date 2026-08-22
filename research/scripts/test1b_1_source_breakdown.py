"""
Test 1b.1 - Source breakdown per district.

Overture places carry a `sources` array. Each place has one entry with
property="" giving the record-level contributing dataset (e.g. "meta",
"Microsoft", "PinMeTo", "OpenStreetMap"). A separate entry with
property="/properties/confidence" and dataset="Overture" just records
where the confidence score was computed - it is not a content source and
is excluded here.

Purpose: check whether the ~3x POI density gap between Imbaba and Maadi
(Test 1) is a real difference or a contribution-coverage artifact (e.g.
Maadi getting heavy Meta/Microsoft coverage that Imbaba doesn't).

Note: fetches with a plain bbox WHERE (no SQL-side unnest/join) then
unnests `sources` in pandas. A CROSS JOIN unnest(sources) directly against
the S3 scan defeats DuckDB's row-group pruning on this dataset - it turns
a ~10s bbox-filtered read into a 10+ minute near-full-dataset scan. Do not
"simplify" this back to SQL-side unnest.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import ROOT, PLACES_PATH, get_con, load_districts, bbox_where


def record_dataset(sources) -> str:
    if sources is None:
        return "unknown"
    for s in sources:
        if s.get("property", "") == "":
            return s.get("dataset") or "unknown"
    return "unknown"


def main():
    con = get_con()
    districts = load_districts()
    base = f"read_parquet('{PLACES_PATH}', hive_partitioning=1)"

    rows = []
    for name, d in districts.items():
        where = bbox_where(d["bbox"])
        q = f"SELECT id, sources FROM {base} WHERE {where}"
        df = con.execute(q).fetchdf()
        df["dataset"] = df["sources"].apply(record_dataset)

        counts = df["dataset"].value_counts().reset_index()
        counts.columns = ["dataset", "n"]
        total = counts["n"].sum()
        counts["pct"] = (100.0 * counts["n"] / total).round(2)
        counts["district"] = name
        rows.append(counts[["district", "dataset", "n", "pct"]])

        print(f"\n=== {name} (total {total}) ===")
        for _, r in counts.iterrows():
            print(f"  {r['dataset']:20s} {r['n']:5d}  ({r['pct']}%)")

    out = pd.concat(rows, ignore_index=True)
    out_path = ROOT / "output" / "test1b_source_breakdown.csv"
    out.to_csv(out_path, index=False)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()

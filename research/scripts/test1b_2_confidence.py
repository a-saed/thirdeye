"""
Test 1b.2 - Confidence distribution per district.

This Overture release exposes a top-level `confidence` DOUBLE field per
place. Report min, p25, median, p75, max, and % below 0.5, per district,
to check whether low-confidence entries cluster in any one district
(which would suggest that district's data is less trustworthy, not just
sparser).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import ROOT, PLACES_PATH, get_con, load_districts, bbox_where


def main():
    con = get_con()
    districts = load_districts()
    base = f"read_parquet('{PLACES_PATH}', hive_partitioning=1)"

    results = []
    for name, d in districts.items():
        where = bbox_where(d["bbox"])
        q = f"""
            SELECT
                count(*) AS n,
                count(confidence) AS n_with_confidence,
                min(confidence) AS min_c,
                quantile_cont(confidence, 0.25) AS p25,
                quantile_cont(confidence, 0.50) AS median,
                quantile_cont(confidence, 0.75) AS p75,
                max(confidence) AS max_c,
                round(100.0 * sum(CASE WHEN confidence < 0.5 THEN 1 ELSE 0 END) / count(confidence), 2) AS pct_below_0_5
            FROM {base}
            WHERE {where}
        """
        row = con.execute(q).fetchdf().iloc[0]
        row["district"] = name
        results.append(row)

        print(f"\n=== {name} ===")
        print(f"  n total:            {row['n']}")
        print(f"  n with confidence:  {row['n_with_confidence']}")
        print(f"  min:                {row['min_c']:.4f}")
        print(f"  p25:                {row['p25']:.4f}")
        print(f"  median:             {row['median']:.4f}")
        print(f"  p75:                {row['p75']:.4f}")
        print(f"  max:                {row['max_c']:.4f}")
        print(f"  % below 0.5:        {row['pct_below_0_5']}%")

    import pandas as pd
    out = pd.DataFrame(results)[
        ["district", "n", "n_with_confidence", "min_c", "p25", "median", "p75", "max_c", "pct_below_0_5"]
    ]
    out_path = ROOT / "output" / "test1b_confidence.csv"
    out.to_csv(out_path, index=False)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()

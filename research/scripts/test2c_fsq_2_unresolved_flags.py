"""
FSQ Leg A, step 0b: inspect unresolved_flags (not documented in the
older public docs seen during research - inspected directly here rather
than assumed).

Reports distinct values and frequency per district, and specifically
checks whether flagged records cluster in Imbaba - Overture's
low-confidence records did (Test 1b), and if unresolved_flags turns out
to be a similar quality signal, filtering on it would penalise the
poorest/least-formal district the same way. Reports counts both filtered
and unfiltered either way, not a silent filter.
"""
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
    print("unresolved_flags inspection")
    print("=" * 90)

    rows = []
    for name, d in districts.items():
        where = bbox_where(d["bbox"])
        q = f"""
            SELECT unresolved_flags, count(*) AS n
            FROM read_parquet('{FSQ_PARQUET}')
            WHERE {where}
            GROUP BY 1
            ORDER BY n DESC
        """
        df = con.execute(q).fetchdf()
        total = df["n"].sum()
        def has_flag(x):
            if isinstance(x, (list, tuple)) or hasattr(x, "__len__") and not isinstance(x, str):
                try:
                    return len(x) > 0
                except TypeError:
                    return False
            return False
        n_any_flag = df[df["unresolved_flags"].apply(has_flag)]["n"].sum()
        n_no_flag = total - n_any_flag

        print(f"\n=== {name} (total {total}) ===")
        print(f"  no flags (NULL or empty array): {n_no_flag}  ({100*n_no_flag/total:.1f}%)")
        print(f"  any flag present:                {n_any_flag}  ({100*n_any_flag/total:.1f}%)")
        for _, r in df.iterrows():
            flags = r["unresolved_flags"]
            label = str(flags) if has_flag(flags) else "(none)"
            print(f"    {label:50s} {r['n']:5d}  ({100*r['n']/total:.1f}%)")

        rows.append({
            "district": name, "total": int(total),
            "n_no_flag": int(n_no_flag), "n_any_flag": int(n_any_flag),
            "pct_any_flag": round(100 * n_any_flag / total, 2),
        })

    out = pd.DataFrame(rows)
    out_path = ROOT / "output" / "test2c_fsq_unresolved_flags.csv"
    out.to_csv(out_path, index=False)
    print(f"\nWrote {out_path}")

    print("\n" + "=" * 90)
    print("Clustering check (does the flagged rate track the same low-confidence-in-Imbaba")
    print("pattern Test 1b found for Overture?):")
    for _, r in out.iterrows():
        print(f"  {r['district']:14s} {r['pct_any_flag']:.2f}% flagged")


if __name__ == "__main__":
    main()

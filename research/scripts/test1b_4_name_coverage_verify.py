"""
Test 1b.4 - Verify the 100% name-coverage figure from Test 1.

Test 1 computed % with name over the same bbox-filtered base query (no
extra WHERE narrowing), so 100% shouldn't be a filter artifact - but
"looks too clean" is a fair thing to double check independently. This
re-runs with three separate checks per district, with no name predicate
anywhere in the query:
  - count where names.primary IS NULL
  - count where names.primary = '' (empty string, non-null)
  - count where trim(names.primary) = '' (whitespace-only)
and cross-checks the raw total against Test 1's total.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import ROOT, PLACES_PATH, get_con, load_districts, bbox_where


def main():
    con = get_con()
    districts = load_districts()
    base = f"read_parquet('{PLACES_PATH}', hive_partitioning=1)"

    rows = []
    for name, d in districts.items():
        where = bbox_where(d["bbox"])
        q = f"""
            SELECT
                count(*) AS total,
                sum(CASE WHEN names.primary IS NULL THEN 1 ELSE 0 END) AS n_null,
                sum(CASE WHEN names.primary = '' THEN 1 ELSE 0 END) AS n_empty_string,
                sum(CASE WHEN names.primary IS NOT NULL AND trim(names.primary) = '' THEN 1 ELSE 0 END) AS n_whitespace_only
            FROM {base}
            WHERE {where}
        """
        r = con.execute(q).fetchdf().iloc[0]
        n_missing = r["n_null"] + r["n_empty_string"]
        pct_missing = round(100.0 * n_missing / r["total"], 4) if r["total"] else None
        rows.append({
            "district": name,
            "total": int(r["total"]),
            "n_null": int(r["n_null"]),
            "n_empty_string": int(r["n_empty_string"]),
            "n_whitespace_only": int(r["n_whitespace_only"]),
            "pct_missing_name": pct_missing,
        })

        print(f"\n=== {name} ===")
        print(f"  total records:            {int(r['total'])}")
        print(f"  names.primary IS NULL:    {int(r['n_null'])}")
        print(f"  names.primary = '':       {int(r['n_empty_string'])}")
        print(f"  trim(name) = '' (non-null but blank): {int(r['n_whitespace_only'])}")
        print(f"  => % missing a usable name: {pct_missing}%")

    import pandas as pd
    out = pd.DataFrame(rows)
    out_path = ROOT / "output" / "test1b_name_coverage_verify.csv"
    out.to_csv(out_path, index=False)

    all_zero = all(r["n_null"] == 0 and r["n_empty_string"] == 0 for r in rows)
    print("\n" + "=" * 60)
    if all_zero:
        print("CONFIRMED: name coverage is genuinely 100% in all three districts.")
        print("This is very likely a schema property of Overture's `place` type")
        print("(a place record without any name probably isn't emitted as a place),")
        print("not a query artifact. As a metric it carries no discriminating signal")
        print("across these three districts and should be dropped from further")
        print("comparisons.")
    else:
        print("NOT confirmed as 100% - see per-district breakdown above.")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()

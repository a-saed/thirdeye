"""
Splits Road 9's 103 remaining-to-verify records (after excluding
collapsed_coord and likely_not_storefront) into four verification-method
groups, so the user can batch-check FOOD on Talabat/Elmenus and do
everything else individually on Google Maps, rather than working through
103 records with one method.

Category-based classification (Overture's flat category string, FSQ's
hierarchical label) - built from the actual category vocabulary present
in the remaining 103 rows (see output/gt-maadi-road9.csv), not guessed.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import ROOT

FOOD_OVERTURE = {
    "restaurant", "coffee_shop", "cafe", "chicken_restaurant", "burger_restaurant",
    "desserts", "fast_food_restaurant", "pancake_house", "chocolatier",
    "theme_restaurant", "syrian_restaurant",
}
FOOD_FSQ_PREFIX = "Dining and Drinking"

MEDICAL_OVERTURE = {"doctor", "pharmacy", "ear_nose_and_throat", "hospital", "dentist", "cosmetic_dentist"}
MEDICAL_FSQ_PREFIX = "Health and Medicine"


def classify(row) -> str:
    cat = row["category"]
    if pd.isna(cat) or cat == "":
        return "UNCLEAR/NO CATEGORY"
    if row["source"] == "overture":
        if cat in FOOD_OVERTURE:
            return "FOOD"
        if cat in MEDICAL_OVERTURE:
            return "MEDICAL/CLINIC"
        return "RETAIL/SERVICE"
    else:  # fsq - category column here is the LEAF label; need the full label for prefix check
        full = row.get("_full_label", cat)
        if str(full).startswith(FOOD_FSQ_PREFIX):
            return "FOOD"
        if str(full).startswith(MEDICAL_FSQ_PREFIX):
            return "MEDICAL/CLINIC"
        return "RETAIL/SERVICE"


def main():
    path = ROOT / "output" / "gt-maadi-road9.csv"
    df = pd.read_csv(path, comment="#")
    remaining = df[(df["collapsed_coord"] == "n") & (df["likely_not_storefront"] == "n")].copy()

    # Need FSQ's full hierarchical label, not just the leaf, for prefix matching -
    # re-pull it fresh since the main file only stores the leaf category.
    fsq_parquet = ROOT / "data" / "fsq_road9.parquet"
    if fsq_parquet.exists():
        import duckdb
        con = duckdb.connect()
        fsq_full = con.execute(f"SELECT name, latitude AS lat, longitude AS lon, fsq_category_labels FROM read_parquet('{fsq_parquet}')").fetchdf()

        def full_label(l):
            try:
                return l[-1] if l is not None and len(l) > 0 else ""
            except TypeError:
                return ""
        fsq_full["_full_label"] = fsq_full["fsq_category_labels"].apply(full_label)
        label_map = {(r["name"], round(r["lat"], 6), round(r["lon"], 6)): r["_full_label"] for _, r in fsq_full.iterrows()}
        remaining["_full_label"] = remaining.apply(
            lambda r: label_map.get((r["name"], round(r["lat"], 6), round(r["lon"], 6)), r["category"]) if r["source"] == "fsq" else "", axis=1)

    remaining["verify_group"] = remaining.apply(classify, axis=1)
    remaining = remaining.drop(columns=["_full_label"], errors="ignore")

    counts = remaining["verify_group"].value_counts()
    print("Verification groups (row counts):")
    for g, n in counts.items():
        print(f"  {g:20s} {n}")

    # distinct-business count: matched pairs count once, unmatched rows count once
    matched = remaining[remaining["match_group"] >= 0]
    unmatched = remaining[remaining["match_group"] < 0]
    n_distinct = matched["match_group"].nunique() + len(unmatched)
    print(f"\nTotal rows: {len(remaining)}  |  Distinct businesses to verify: {n_distinct} "
          f"({matched['match_group'].nunique()} matched pairs count once each + {len(unmatched)} single-source records)")

    out_full = ROOT / "output" / "gt-maadi-road9-verification-groups.csv"
    remaining.sort_values(["verify_group", "source", "name"]).to_csv(out_full, index=False)
    print(f"\nWrote {out_full} (all groups, sorted, with verify_group column)")

    for group in ["FOOD", "RETAIL/SERVICE", "MEDICAL/CLINIC", "UNCLEAR/NO CATEGORY"]:
        sub = remaining[remaining["verify_group"] == group].sort_values(["source", "name"])
        fname = group.replace("/", "-").replace(" ", "_").lower()
        out_path = ROOT / "output" / f"gt-maadi-road9-{fname}.csv"
        sub.to_csv(out_path, index=False)
        print(f"Wrote {out_path} ({len(sub)} rows)")


if __name__ == "__main__":
    main()

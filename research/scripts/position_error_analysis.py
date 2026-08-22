"""
Cross-source positional disagreement, across all three street extractions
(Road 9, El Shabab, 90th Street). Requested after German Beauty Center
turned out to be 381.7m apart despite an exact name match (7.6x the 50m
buffer half-width) - if positions can be off by that much, "competitors
within 500m" is a much softer number than it looks, and the product needs
a stated uncertainty band, not an assumed-precise one.

Method: name-only one-to-one greedy matching (same bipartite assignment
as scripts/test2a_road9_extract.py, but with NO distance gate - distance
is exactly what we're measuring here, not filtering on it), restricted to
pairs with normalised name similarity > 0.9 so this measures position
error conditional on high match confidence, not match error.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import ROOT
from scripts.test2a_road9_extract import name_similarity, dist_m

SIM_THRESHOLD = 0.9

# Manually-verified false positive, excluded: matched only because both names
# carry "الشيخ زايد" (the district name) as a trailing location qualifier -
# "Syriana palace" is a restaurant, "Sheikh Zayed Downtown Mall" is a mall,
# clearly different business types, not a position-error pair. Root cause:
# the matcher's script-run variant splitting treats a shared locality suffix
# as if it were a matching distinctive-name variant. Same failure mode as the
# "- Maadi Branch" false positive noted during the Road 9 review. Not fixed
# at the matcher level (would need locality-suffix stripping, risking
# side effects on already-verified Road 9 results under time pressure) -
# excluded by name here instead, found 2026-08-18.
EXCLUDE_PAIRS = {("Syriana palace الشيخ زايد", "Sheikh Zayed Downtown Mall | داون تاون مول الشيخ زايد")}

FILES = {
    "Road 9 (Maadi)": ROOT / "output" / "gt-maadi-road9.csv",
    "El Shabab St (Sheikh Zayed)": ROOT / "output" / "gcheck-elshabab.csv",
    "90th Street (New Cairo)": ROOT / "output" / "gcheck-90thstreet.csv",
}


def match_by_name_only(df: pd.DataFrame):
    ov = df[df["source"] == "overture"].reset_index()
    fsq = df[df["source"] == "fsq"].reset_index()
    candidates = []
    for oi, orow in ov.iterrows():
        for fi, frow in fsq.iterrows():
            sim = name_similarity(orow["name"], frow["name"])
            if sim > SIM_THRESHOLD:
                d = dist_m(orow["lat"], orow["lon"], frow["lat"], frow["lon"])
                candidates.append((sim, -d, oi, fi, d, orow["name"], frow["name"]))
    candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)
    claimed_ov, claimed_fsq = set(), set()
    results = []
    for sim, _, oi, fi, d, name_ov, name_fsq in candidates:
        if oi in claimed_ov or fi in claimed_fsq:
            continue
        if (name_ov, name_fsq) in EXCLUDE_PAIRS or (name_fsq, name_ov) in EXCLUDE_PAIRS:
            continue
        claimed_ov.add(oi)
        claimed_fsq.add(fi)
        results.append({"name_overture": name_ov, "name_fsq": name_fsq, "sim": round(sim, 3), "distance_m": round(d, 1)})
    return results


def main():
    all_rows = []
    print("=" * 90)
    for street, path in FILES.items():
        df = pd.read_csv(path, comment="#")
        results = match_by_name_only(df)
        for r in results:
            r["street"] = street
        all_rows.extend(results)

        dists = [r["distance_m"] for r in results]
        if dists:
            print(f"\n=== {street} (n={len(dists)} high-confidence name matches, sim>{SIM_THRESHOLD}) ===")
            print(f"  median: {np.median(dists):.1f}m  p75: {np.percentile(dists,75):.1f}m  "
                  f"p90: {np.percentile(dists,90):.1f}m  max: {np.max(dists):.1f}m")
            worst = sorted(results, key=lambda r: -r["distance_m"])[:3]
            for w in worst:
                print(f"    worst: {w['name_overture']!r} <-> {w['name_fsq']!r}  {w['distance_m']}m  (sim={w['sim']})")

    out = pd.DataFrame(all_rows)
    out_path = ROOT / "output" / "position_error_distribution.csv"
    out.to_csv(out_path, index=False)

    all_dists = out["distance_m"].tolist()
    print("\n" + "=" * 90)
    print(f"POOLED across all 3 streets (n={len(all_dists)}):")
    print(f"  median: {np.median(all_dists):.1f}m")
    print(f"  p75:    {np.percentile(all_dists,75):.1f}m")
    print(f"  p90:    {np.percentile(all_dists,90):.1f}m")
    print(f"  max:    {np.max(all_dists):.1f}m")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()

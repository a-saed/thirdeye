"""
Produce the FULL citywide duplicate-candidate pair list, intra-source AND
cross-source, with scores - so precision can be measured out-of-sample.

WHY THIS EXISTS / IMPORTANT CORRECTION:
The citywide QA report's "19.7% of Cairo rows in a duplicate pair" figure came
from qa.check_intra_source_duplicates, which SKIPS any pair whose two records
come from different sources. So that number is INTRA-SOURCE ONLY - one
provider listing the same place twice - and no cross-source figure existed at
all. The two cases mean different things:
  cross-source (Overture vs FSQ) - expected, and exactly what entity
      resolution is supposed to merge.
  intra-source (Overture vs Overture) - a single provider double-listing,
      which inflates competitor counts even after a perfect cross-source merge.
This script computes both, keeps them labelled, and writes every pair so the
sample can be drawn across the whole score range rather than the top of it.

Writes per governorate incrementally (earlier citywide passes were killed
mid-run and lost everything).
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import ROOT
from scripts.name_matching import name_similarity, skeleton
from scripts.qa import DUP_DIST_M, DUP_NAME_SIM, _dist_m
from scripts.qa_report_citywide import (assign_governorate, fsq_clipped,
                                        latest_overture, load_governorates)

OUT = ROOT / "output" / "dup_pairs_citywide.parquet"


def grams(n):
    sk = skeleton(str(n)) if n is not None else ""
    return {sk[i:i + 2] for i in range(len(sk) - 1)} or {sk}


def pairs_for(df: pd.DataFrame, gov: str) -> pd.DataFrame:
    import h3
    d = df.reset_index(drop=True)
    cells = [h3.latlng_to_cell(la, lo, 9) for la, lo in zip(d["lat"], d["lon"])]
    buckets = {}
    for i, c in enumerate(cells):
        buckets.setdefault(c, []).append(i)
    gs = [grams(n) for n in d["name"]]

    seen, rows = set(), []
    for cell, idxs in buckets.items():
        neigh = []
        for nb in h3.grid_disk(cell, 1):
            neigh.extend(buckets.get(nb, []))
        for i in idxs:
            for j in neigh:
                if j <= i or (i, j) in seen:
                    continue
                if not (gs[i] & gs[j]):
                    continue
                dist = _dist_m(d.at[i, "lat"], d.at[i, "lon"], d.at[j, "lat"], d.at[j, "lon"])
                if dist > DUP_DIST_M:
                    continue
                sim = name_similarity(d.at[i, "name"], d.at[j, "name"])
                if sim < DUP_NAME_SIM:
                    continue
                seen.add((i, j))
                rows.append({
                    "governorate": gov,
                    "source_a": d.at[i, "source"], "source_b": d.at[j, "source"],
                    "pair_type": "intra_source" if d.at[i, "source"] == d.at[j, "source"] else "cross_source",
                    "name_a": d.at[i, "name"], "name_b": d.at[j, "name"],
                    "category_a": d.at[i, "category"], "category_b": d.at[j, "category"],
                    "lat_a": d.at[i, "lat"], "lon_a": d.at[i, "lon"],
                    "lat_b": d.at[j, "lat"], "lon_b": d.at[j, "lon"],
                    "distance_m": round(dist, 1), "name_sim": round(sim, 3),
                })
    return pd.DataFrame(rows)


def main():
    govs = load_governorates()
    ov, _ = latest_overture()
    fsq, _ = fsq_clipped(govs)
    ov["governorate"] = assign_governorate(ov, govs)
    fsq["governorate"] = assign_governorate(fsq, govs)
    cols = ["source", "name", "category", "lat", "lon", "governorate"]
    combined = pd.concat([ov[cols], fsq[cols]], ignore_index=True)

    all_parts = []
    for gov in ["Qalyubiya", "Alexandria", "Giza", "Cairo"]:   # cheapest first
        sub = combined[combined["governorate"] == gov]
        part = pairs_for(sub, gov)
        all_parts.append(part)
        pd.concat(all_parts, ignore_index=True).to_parquet(OUT, index=False)
        n_intra = int((part["pair_type"] == "intra_source").sum()) if len(part) else 0
        n_cross = int((part["pair_type"] == "cross_source").sum()) if len(part) else 0
        print(f"  {gov}: {len(part):,} pairs  (intra {n_intra:,} / cross {n_cross:,})", flush=True)

    final = pd.concat(all_parts, ignore_index=True)
    final.to_parquet(OUT, index=False)
    print(f"\nTOTAL {len(final):,} pairs -> {OUT}")
    print(final.groupby(["governorate", "pair_type"]).size().unstack(fill_value=0).to_string())


if __name__ == "__main__":
    main()

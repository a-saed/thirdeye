"""
Draw a targeted 100-pair sample from PATH A ONLY:
   exact normalised-name match  AND  distance <= 50m  AND  cross_source.

Why a second, separate sample: the first citywide triage put only 9 pairs in
this slice, and they scored 8/9 = 88.9% - a number whose 95% CI floor is 56%.
That is far too wide to justify auto-merging 11,504 pairs. This sample tests
the slice on its own terms.

Stratified across the four governorates with a floor, because Path A is
heavily Cairo-weighted (6,765 of 11,504) and a purely proportional draw would
give Qalyubiya ~2 pairs. Also stratified across distance bands: median
distance here is 0.0m, so a naive draw would be almost entirely
zero-distance pairs and would not test the 10-50m tail at all.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import ROOT
from scripts.name_matching import normalize

PAIRS = ROOT / "output" / "dup_pairs_citywide.parquet"
OUT = ROOT / "output" / "pathA-sample.csv"
N = 100
SEED = 20260821


def main():
    P = pd.read_parquet(PAIRS)
    na = P.name_a.astype(str).map(normalize)
    nb = P.name_b.astype(str).map(normalize)
    P["exact"] = (na == nb) & (na.str.len() > 0)
    A = P[P.exact & (P.distance_m <= 50) & (P.pair_type == "cross_source")].copy()
    print(f"Path A population: {len(A):,}")

    A["dband"] = pd.cut(A.distance_m, bins=[-0.01, 0.5, 10, 25, 50.01],
                        labels=["0m", "0-10m", "10-25m", "25-50m"])

    rng = np.random.default_rng(SEED)
    picks = []
    # governorate floor of 15 (or all, if fewer), then distance-stratify within
    for gov, g in A.groupby("governorate"):
        take = min(len(g), max(15, int(round(N * len(g) / len(A)))))
        sub = []
        for db, gg in g.groupby("dband", observed=True):
            k = max(1, int(round(take * len(gg) / len(g))))
            sub.append(gg.sample(min(k, len(gg)), random_state=int(rng.integers(1e9))))
        picks.append(pd.concat(sub).head(take))
    sample = pd.concat(picks, ignore_index=True)

    if len(sample) > N:
        sample = sample.sample(N, random_state=SEED)
    elif len(sample) < N:
        rest = A.drop(index=pd.concat(picks).index, errors="ignore")
        if len(rest):
            sample = pd.concat([sample, rest.sample(min(N - len(sample), len(rest)),
                                                    random_state=SEED)], ignore_index=True)

    # interleave by distance band so the harder (non-zero distance) cases are
    # spread through the file rather than sitting together at the end
    sample = sample.sample(frac=1.0, random_state=SEED).reset_index(drop=True)
    sample["_ord"] = sample.groupby("dband", observed=True).cumcount()
    sample = sample.sort_values(["_ord", "dband"]).drop(columns=["_ord"]).reset_index(drop=True)

    sample.insert(0, "pair_id", range(1, len(sample) + 1))
    sample["verdict"] = ""       # SAME / DIFFERENT / UNSURE
    sample["notes"] = ""
    cols = ["pair_id", "verdict", "notes", "governorate", "pair_type",
            "source_a", "name_a", "category_a", "source_b", "name_b", "category_b",
            "distance_m", "name_sim", "dband", "lat_a", "lon_a", "lat_b", "lon_b"]
    sample[cols].to_csv(OUT, index=False)

    print(f"sampled {len(sample)} -> {OUT}")
    print("\nby governorate:"); print(sample.governorate.value_counts().to_string())
    print("\nby distance band:"); print(sample.dband.value_counts().sort_index().to_string())


if __name__ == "__main__":
    main()

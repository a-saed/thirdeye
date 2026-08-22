"""
Draw a RANDOM, STRATIFIED sample of flagged duplicate pairs for manual
verdicts, so matcher precision can be measured OUT-OF-SAMPLE.

Why stratified and random, not top-scoring:
The existing 38-pair labelled set is Cairo study-district data that the
thresholds were tuned ON - in-sample twice over. Any precision measured from
it is optimistic. This sample is drawn:
  - across all four governorates (not just Cairo),
  - across the whole similarity range in bands (not only high-confidence
    pairs, which would flatter precision),
  - across both pair types (cross_source vs intra_source), which mean
    different things: cross-source is what entity resolution SHOULD merge;
    intra-source is one provider double-listing, which inflates competitor
    counts even after a perfect merge.

Output is deliberately INTERLEAVED so the hard cases are spread through the
file rather than all sitting at the bottom where attention fades.

The verdict column is empty for the reviewer: SAME / DIFFERENT / UNSURE.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import ROOT

PAIRS = ROOT / "output" / "dup_pairs_citywide.parquet"
OUT = ROOT / "output" / "dup-triage-sample.csv"
N = 100
SEED = 20260820

BANDS = [(0.72, 0.80), (0.80, 0.90), (0.90, 0.99), (0.99, 1.01)]


def main():
    df = pd.read_parquet(PAIRS)
    print(f"population: {len(df):,} flagged pairs")
    print(df.groupby(["governorate", "pair_type"]).size().unstack(fill_value=0).to_string())

    df["band"] = pd.cut(df["name_sim"], bins=[b[0] for b in BANDS] + [BANDS[-1][1]],
                        labels=[f"{a:.2f}-{b:.2f}" for a, b in BANDS], right=False)

    # Proportional-ish allocation across (governorate x pair_type x band), but
    # with a floor so small strata (e.g. Qalyubiya cross-source at high sim)
    # are still represented - precision could differ sharply there and a purely
    # proportional draw would miss them entirely.
    rng = np.random.default_rng(SEED)
    strata = [g for g, _ in df.groupby(["governorate", "pair_type", "band"], observed=True)]
    per = max(1, N // max(1, len(strata)))
    picks = []
    for key, grp in df.groupby(["governorate", "pair_type", "band"], observed=True):
        take = min(len(grp), per)
        picks.append(grp.sample(take, random_state=int(rng.integers(1e9))))
    sample = pd.concat(picks, ignore_index=True)

    # top up to N with a random draw from whatever is left
    if len(sample) < N:
        rest = df.drop(index=pd.concat(picks).index, errors="ignore")
        if len(rest):
            sample = pd.concat([sample, rest.sample(min(N - len(sample), len(rest)),
                                                    random_state=SEED)], ignore_index=True)
    sample = sample.sample(frac=1.0, random_state=SEED).head(N).reset_index(drop=True)

    # Interleave by band so hard (low-sim) cases are spread through the file,
    # not clustered at the end.
    sample["_ord"] = sample.groupby("band", observed=True).cumcount()
    sample = sample.sort_values(["_ord", "band"]).drop(columns=["_ord"]).reset_index(drop=True)

    sample.insert(0, "pair_id", range(1, len(sample) + 1))
    sample["verdict"] = ""            # SAME / DIFFERENT / UNSURE
    sample["notes"] = ""

    cols = ["pair_id", "verdict", "notes", "governorate", "pair_type",
            "source_a", "name_a", "category_a", "source_b", "name_b", "category_b",
            "distance_m", "name_sim", "band", "lat_a", "lon_a", "lat_b", "lon_b"]
    sample[cols].to_csv(OUT, index=False)

    print(f"\nsampled {len(sample)} pairs -> {OUT}")
    print("\nsample composition:")
    print(sample.groupby(["pair_type", "band"], observed=True).size().unstack(fill_value=0).to_string())
    print("\nby governorate:")
    print(sample["governorate"].value_counts().to_string())


if __name__ == "__main__":
    main()

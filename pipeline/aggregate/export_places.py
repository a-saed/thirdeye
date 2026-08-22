"""Persist the individual places behind every business count.

WHY THIS EXISTS. "65 cafes" is a claim nobody can check. "Here are the 65"
is a claim anyone who knows the street can falsify in ten seconds, which is
the only real quality control this dataset will ever get - the study never
obtained ground truth, and the duplicate matcher scored 100% in-sample against
25% out-of-sample. Publishing the underlying records turns an assertion into
something a local can audit.

It also makes duplicate inflation VISIBLE rather than merely disclosed. The
3.2-6.3% figure in limitations.json is abstract; two adjacent rows with the
same name from two sources are not.

NOTHING IS MERGED HERE. Pairs are flagged as suspected and both rows are kept,
exactly as the aggregate counts keep them. See research/VERDICT.md.
"""
import json
import sys
from pathlib import Path

import h3
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.config._common import ROOT, threshold
from pipeline.aggregate.h3_pipeline import (
    OV_GROUPS, fsq_group_match, load_places, PIPELINE_VERSION,
)
from pipeline.resolve.name_matching import name_similarity

OUT = ROOT / "data" / "derived" / "h3_tables" / "places.parquet"

# Duplicate flagging is deliberately CONSERVATIVE. The fuzzy matcher's
# out-of-sample precision was 25%, so this only flags what the study found
# defensible: cross-source pairs that are close in space AND similar in name.
DUP_MAX_M = threshold("duplicates", "max_distance_m")
DUP_MIN_SIM = threshold("duplicates", "min_name_similarity")
# Blocking resolution for candidate generation. res-10 edge is ~66m, so a
# cell plus its ring comfortably contains any pair within 40m.
BLOCK_RES = 10


def _groups_of(row) -> str:
    """EVERY group a place belongs to, pipe-delimited.

    Not the first match. business_metrics() evaluates each category group
    independently, so a place tagged both restaurant and cafe is counted in
    BOTH counts. Storing a single winning group here made the list disagree
    with the number it was supposed to explain - restaurant read 74 in the
    metric and 72 in the list, which is exactly the "two numbers for the same
    thing" failure this list exists to prevent.

    Delimited with a leading and trailing pipe so a filter can match "|cafe|"
    without "|cafe|" also matching a hypothetical "|cafeteria|".
    """
    out = []
    if row.source == "overture":
        c = str(row.category)
        out = [g for g, cats in OV_GROUPS.items() if c in cats]
    else:
        labels = row.fsq_category_labels
        if labels is not None and len(labels):
            out = [g for g in OV_GROUPS if fsq_group_match(labels, g)]
    return "|" + "|".join(out) + "|" if out else ""


def _haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


def flag_duplicates(df: pd.DataFrame) -> pd.Series:
    """Suspected cross-source duplicate pairs, blocked spatially.

    Cross-source only. Two Overture records at the same spot are an
    intra-source problem the QA gate already reports; what inflates a
    catchment count is the same shop arriving once from each feed.
    """
    flag = np.zeros(len(df), dtype=bool)
    blocks = {}
    for i, (lat, lon) in enumerate(zip(df.lat.values, df.lon.values)):
        blocks.setdefault(h3.latlng_to_cell(lat, lon, BLOCK_RES), []).append(i)

    lat, lon = df.lat.values, df.lon.values
    src, name = df.source.values, df.name.values
    seen = set()
    for cell, idxs in blocks.items():
        # candidates: this block plus its ring, deduplicated by pair
        cand = list(idxs)
        for nb in h3.grid_disk(cell, 1):
            if nb != cell and nb in blocks:
                cand.extend(blocks[nb])
        ov = [i for i in cand if src[i] == "overture"]
        fq = [i for i in cand if src[i] == "fsq"]
        for a in ov:
            for b in fq:
                key = (a, b) if a < b else (b, a)
                if key in seen:
                    continue
                seen.add(key)
                if _haversine_m(lat[a], lon[a], lat[b], lon[b]) > DUP_MAX_M:
                    continue
                if name_similarity(name[a], name[b]) >= DUP_MIN_SIM:
                    flag[a] = True
                    flag[b] = True
    return pd.Series(flag, index=df.index)


def main():
    places, ov_snap, fsq_snap, n_ns = load_places({})
    print(f"places after non-storefront filter: {len(places):,} (excluded {n_ns:,})")

    places = places.reset_index(drop=True)
    places["groups"] = [_groups_of(r) for r in places.itertuples()]
    places["h3_res9"] = [h3.latlng_to_cell(a, b, 9) for a, b in zip(places.lat, places.lon)]
    places["h3_res8"] = [h3.cell_to_parent(c, 8) for c in places.h3_res9]

    print("flagging suspected cross-source duplicates…")
    places["dup_suspected"] = flag_duplicates(places)

    places["snapshot"] = np.where(places.source == "overture", ov_snap, fsq_snap)
    places["pipeline_version"] = PIPELINE_VERSION

    out = places[["source", "name", "category", "groups", "lat", "lon",
                  "h3_res9", "h3_res8", "dup_suspected", "snapshot",
                  "pipeline_version"]].copy()
    out["groups"] = out.groups.fillna("").astype(str)
    out["name"] = out.name.fillna("").astype(str)
    out["category"] = out.category.astype(str)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT, index=False)

    print(f"wrote {OUT} — {len(out):,} rows, {OUT.stat().st_size/1048576:.1f} MB")
    print(f"  by source: {out.source.value_counts().to_dict()}")
    has = out.groups != ""
    print(f"  with a category group: {int(has.sum()):,} ({100*has.mean():.1f}%)")
    print(f"  suspected duplicates: {int(out.dup_suspected.sum()):,} "
          f"({100*out.dup_suspected.mean():.2f}% of rows)")
    print("  NOTHING MERGED — flags are advisory, both rows are kept.")


if __name__ == "__main__":
    main()

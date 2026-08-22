"""
Test 1b.3 - Duplicate detection per district.

Overture merges multiple source datasets (OSM, Meta, Microsoft, PinMeTo,
...) and dedup across them isn't perfect. This finds points within 20m of
each other with similar normalised names and unions them into a single
"real-world entity" via connected components, so we can report e.g.
"11 hospital records in Imbaba collapse to 4 distinct hospitals."

No fuzzy-matching library dependency: uses stdlib difflib.SequenceMatcher
on a normalised name string, plus a plain equirectangular-projection
distance (fine at 20m / neighborhood scale) and a hand-rolled union-find.
"""
import re
import unicodedata
from itertools import combinations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import ROOT, PLACES_PATH, get_con, load_districts, bbox_where

DIST_THRESHOLD_M = 20.0
NAME_SIM_THRESHOLD = 0.82


def normalize_name(name: str) -> str:
    if not name:
        return ""
    name = unicodedata.normalize("NFKC", name)
    name = name.lower().strip()
    name = re.sub(r"[^\w\s]", "", name, flags=re.UNICODE)
    name = re.sub(r"\s+", " ", name)
    return name


def name_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b).ratio()


def equirect_xy(lat, lon, lat0, lon0):
    R = 6371000.0
    x = np.radians(lon - lon0) * np.cos(np.radians(lat0)) * R
    y = np.radians(lat - lat0) * R
    return x, y


class UnionFind:
    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, i):
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, i, j):
        ri, rj = self.find(i), self.find(j)
        if ri != rj:
            self.parent[ri] = rj


def main():
    con = get_con()
    districts = load_districts()
    base = f"read_parquet('{PLACES_PATH}', hive_partitioning=1)"

    all_rows = []
    for name, d in districts.items():
        where = bbox_where(d["bbox"])
        q = f"""
            SELECT id, names.primary AS place_name, categories.primary AS category,
                   ST_X(geometry) AS lon, ST_Y(geometry) AS lat
            FROM {base}
            WHERE {where}
        """
        df = con.execute(q).fetchdf()
        n = len(df)

        lat0, lon0 = df["lat"].mean(), df["lon"].mean()
        x, y = equirect_xy(df["lat"].values, df["lon"].values, lat0, lon0)
        df["x"], df["y"] = x, y
        df["norm_name"] = df["place_name"].apply(normalize_name)

        uf = UnionFind(n)
        # bucket by rounded coords to avoid full O(n^2) on larger districts
        cell = 25.0  # meters, > threshold so neighboring cells cover adjacency
        df["_cx"] = (df["x"] // cell).astype(int)
        df["_cy"] = (df["y"] // cell).astype(int)
        buckets = {}
        for i, (cx, cy) in enumerate(zip(df["_cx"], df["_cy"])):
            buckets.setdefault((cx, cy), []).append(i)

        candidate_pairs = set()
        for (cx, cy), idxs in buckets.items():
            neighbor_idxs = []
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    neighbor_idxs.extend(buckets.get((cx + dx, cy + dy), []))
            for i in idxs:
                for j in neighbor_idxs:
                    if i < j:
                        candidate_pairs.add((i, j))

        dup_pairs = []
        for i, j in candidate_pairs:
            dist = ((df["x"].iloc[i] - df["x"].iloc[j]) ** 2 + (df["y"].iloc[i] - df["y"].iloc[j]) ** 2) ** 0.5
            if dist > DIST_THRESHOLD_M:
                continue
            sim = name_similarity(df["norm_name"].iloc[i], df["norm_name"].iloc[j])
            if sim >= NAME_SIM_THRESHOLD:
                uf.union(i, j)
                dup_pairs.append((df["id"].iloc[i], df["id"].iloc[j], round(dist, 1), round(sim, 2)))

        clusters = {}
        for i in range(n):
            clusters.setdefault(uf.find(i), []).append(i)

        n_clusters = len(clusters)
        n_dupe_records = n - n_clusters
        dup_rate = round(100.0 * n_dupe_records / n, 2) if n else 0.0

        print(f"\n=== {name} ===")
        print(f"  raw records:          {n}")
        print(f"  distinct entities:    {n_clusters}")
        print(f"  duplicate records:    {n_dupe_records}  ({dup_rate}% of raw count)")
        print(f"  merge threshold:      <= {DIST_THRESHOLD_M}m and name similarity >= {NAME_SIM_THRESHOLD}")

        multi = [(idxs, len(idxs)) for idxs in clusters.values() if len(idxs) > 1]
        multi.sort(key=lambda t: -t[1])
        if multi:
            print("  largest duplicate clusters:")
            for idxs, size in multi[:10]:
                sample_names = df["place_name"].iloc[idxs].tolist()
                sample_cat = df["category"].iloc[idxs[0]]
                print(f"    x{size}  [{sample_cat}]  {sample_names}")

        cluster_rows = []
        for cid, idxs in clusters.items():
            for i in idxs:
                cluster_rows.append({
                    "district": name,
                    "cluster_id": cid,
                    "cluster_size": len(idxs),
                    "id": df["id"].iloc[i],
                    "name": df["place_name"].iloc[i],
                    "category": df["category"].iloc[i],
                    "lat": df["lat"].iloc[i],
                    "lon": df["lon"].iloc[i],
                })
        all_rows.extend(cluster_rows)

    out = pd.DataFrame(all_rows)
    out_path = ROOT / "output" / "test1b_duplicate_clusters.csv"
    out.to_csv(out_path, index=False)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()

"""
QA GATE — run before and after any ingest.

NOTE ON PROVENANCE: this script did not previously exist. It was requested
on 2026-08-20 as "run qa.py", but no qa.py had ever been written or
specified in test.md or any earlier plan. It is new work, built to the
stated requirement: catch automatically every defect class that was found
BY HAND during the Cairo 3-district study, because at city scale
(250k+ rows) nothing can be eyeballed.

The four defect classes it must catch, each with a known ground-truth case
from the study that serves as its regression test:

  C1 COORDINATE COLLAPSE
      Known case: 90th Street, New Cairo - 170 of 270 Overture places in one
      100m cell, 159 of them within 5m of four tiny (20-25 m^2) building
      fragments. Dozens of distinct businesses sharing one imprecise
      coordinate. Inflates competitor counts and fakes density.

  C2 INTRA-SOURCE DUPLICATES  (the class we originally MISSED)
      Known case: Road 9, Maadi - "Hara 9" and "حارة 9", both Overture,
      both category=cafe, 126.6m apart. The same real cafe, transliterated
      two ways, counted twice. Our earlier matcher only compared
      Overture<->FSQ, so it structurally could not see this. Distance
      threshold must exceed 126.6m to catch it.

  C3 NON-STOREFRONT RECORDS
      Known cases: Egypreonics HQ, Smartology Head Office, Cloudberry
      Solutions, Bekka, Lavender House, شركة نقل عفش, الصفحة الرسمية...
      Offices/residential/freight/government pages are not street-level
      businesses and must not count as competitors.

  C4 BULK-IMPORT ARTIFACTS (temporal, runs on release history not places)
      Known case: Imbaba, 2024-09-18 release - 173 -> 329 (+90.2%) in one
      release, then flat for five releases. Not real-world change.

Exit code is non-zero if any check fails its regression case, so this can
gate a pipeline.
"""
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

import h3
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.config._common import ROOT
from pipeline.resolve.name_matching import name_similarity

# ---------------------------------------------------------------- thresholds
COLLAPSE_MIN_GROUP = 3          # >=3 records on one coordinate = collapse
COLLAPSE_PRECISION = 5          # decimal places (~1m) for "same coordinate"
DUP_DIST_M = 150                # must exceed the 126.6m Hara 9 case
DUP_NAME_SIM = 0.72             # same threshold as the entity matcher
BULK_JUMP_PCT = 40.0
BULK_FLAT_TOL_PCT = 15.0
BULK_MIN_FLAT = 3

NOT_STOREFRONT_FSQ_PREFIXES = (
    "Business and Professional Services > Office",
    "Community and Government > Residential Building",
    "Community and Government > Housing Development",
)

# CAMPUS-INTERIOR spaces: rooms, halls and buildings INSIDE an institution
# (AUC Core C121, MIU Main Building, Room 227, R/N Building...). They are not
# independently visitable businesses and must not count as competitors.
# 2,986 such records citywide (0.89%), concentrated enough to distort local
# density badly - the worst single res-9 cell holds 58 of them.
# CATEGORY-BASED ONLY, deliberately no name regex: a name-pattern pass over
# these was tried on 2026-08-20 and over-matched severely, sweeping in real
# businesses (medical labs, dental labs, even "Block cafe").
CAMPUS_INTERIOR_FSQ_SUFFIXES = (
    "College Classroom", "College Lab", "College Academic Building",
    "College Administrative Building", "College Auditorium",
    "College Science Building", "College Gym", "College Football Field",
    "College Stadium", "Student Center", "College Residence Hall",
    "College Bookstore", "College Quad", "College Theater",
    "College Library", "College Cafeteria", "Fraternity House",
    "Sorority House",
)
CAMPUS_INTERIOR_CATEGORIES = {"campus_building"}
NOT_STOREFRONT_CATEGORIES = {
    "freight_and_cargo_service", "public_and_government_association",
    "real_estate", "real_estate_agent", "real_estate_service",
    "real_estate_investment", "professional_services", "corporate_office",
    "shipping_center", "home_developer", "architectural_designer",
}
NOT_STOREFRONT_NAME_KEYWORDS = (
    r"\bhq\b", r"head office", r"\boffice\b", r"holding", r"consultants?\b",
    r"شركة نقل", r"الصفحة الرسمية",
)


# C5 thresholds. A parent whose value sits >=99% in one child is "carried".
CARRIER_SHARE = 0.99
# Sparse point data hits this sometimes; a carrier bug hits it essentially
# always. Population measured 100.0% before the fix; business counts 35-50%.
CARRIER_FAIL = 0.90
CARRIER_WARN = 0.60
MIN_PARENTS_TO_JUDGE = 50


def _dist_m(lat1, lon1, lat2, lon2):
    return (((lat1 - lat2) * 111320) ** 2 + ((lon1 - lon2) * 111320 * 0.868) ** 2) ** 0.5


# ---------------------------------------------------------------- C1
def check_coordinate_collapse(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["_lat_r"] = d["lat"].round(COLLAPSE_PRECISION)
    d["_lon_r"] = d["lon"].round(COLLAPSE_PRECISION)
    g = d.groupby(["_lat_r", "_lon_r"])
    size = g["name"].transform("size")
    n_names = g["name"].transform("nunique")
    # collapse = many records, many DISTINCT names, one coordinate
    flag = (size >= COLLAPSE_MIN_GROUP) & (n_names >= COLLAPSE_MIN_GROUP)
    out = d[flag].copy()
    out["group_size"] = size[flag]
    return out[["source", "name", "category", "lat", "lon", "group_size"]]


# ---------------------------------------------------------------- C2
def check_intra_source_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """Same source, similar name, close together. Spatially bucketed so this
    stays tractable at city scale instead of O(n^2)."""
    import h3
    d = df.reset_index(drop=True).copy()
    d["_cell"] = [h3.latlng_to_cell(la, lo, 9) for la, lo in zip(d["lat"], d["lon"])]

    buckets = {}
    for i, c in enumerate(d["_cell"]):
        buckets.setdefault(c, []).append(i)

    # Cheap prefilter: candidate pairs must share a 2-gram of their name
    # skeleton. Without this the citywide run calls the full (expensive)
    # matcher on every pair within 150m, which in dense Cairo is thousands of
    # comparisons per record. 2-grams not 3-grams: short transliterated names
    # ("Hara 9" -> "hr9" vs "حارة 9" -> "hrh9") share no 3-gram but do share
    # "hr", so 3-grams would silently lose real duplicates.
    from pipeline.resolve.name_matching import skeleton as _skel

    def grams(n):
        sk = _skel(str(n)) if n is not None else ""
        return {sk[i:i + 2] for i in range(len(sk) - 1)} or {sk}

    gram_sets = [grams(n) for n in d["name"]]

    seen, rows = set(), []
    for cell, idxs in buckets.items():
        neigh = []
        for nb in h3.grid_disk(cell, 1):
            neigh.extend(buckets.get(nb, []))
        for i in idxs:
            for j in neigh:
                if j <= i:
                    continue
                if d.at[i, "source"] != d.at[j, "source"]:
                    continue
                key = (i, j)
                if key in seen:
                    continue
                if not (gram_sets[i] & gram_sets[j]):
                    continue
                dist = _dist_m(d.at[i, "lat"], d.at[i, "lon"], d.at[j, "lat"], d.at[j, "lon"])
                if dist > DUP_DIST_M:
                    continue
                sim = name_similarity(d.at[i, "name"], d.at[j, "name"])
                if sim < DUP_NAME_SIM:
                    continue
                seen.add(key)
                rows.append({
                    "source": d.at[i, "source"], "name_a": d.at[i, "name"], "name_b": d.at[j, "name"],
                    "category_a": d.at[i, "category"], "category_b": d.at[j, "category"],
                    "distance_m": round(dist, 1), "name_sim": round(sim, 3),
                })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- C3
def check_non_storefront(df: pd.DataFrame, fsq_full_labels: dict | None = None) -> pd.DataFrame:
    fsq_full_labels = fsq_full_labels or {}

    def is_flag(r):
        cat = r["category"]
        if r["source"] == "fsq":
            full = fsq_full_labels.get((r["name"], r["lat"], r["lon"]), str(cat))
            if str(full).startswith(NOT_STOREFRONT_FSQ_PREFIXES):
                return True
        if pd.notna(cat) and str(cat) in NOT_STOREFRONT_CATEGORIES:
            return True
        if pd.notna(cat) and str(cat) in CAMPUS_INTERIOR_CATEGORIES:
            return True
        c = str(cat)
        if any(c.endswith("> " + x) or c == x for x in CAMPUS_INTERIOR_FSQ_SUFFIXES):
            return True
        nm = str(r["name"]) if pd.notna(r["name"]) else ""
        return any(re.search(k, nm, re.IGNORECASE) for k in NOT_STOREFRONT_NAME_KEYWORDS)

    m = df.apply(is_flag, axis=1)
    return df[m][["source", "name", "category", "lat", "lon"]].copy()


# ---------------------------------------------------------------- C3b
DENSITY_DISTORTION_MIN = 20


def check_density_distortion(df: pd.DataFrame, res: int = 9) -> pd.DataFrame:
    """Res-9 cells holding DENSITY_DISTORTION_MIN+ non-storefront records.

    Filtering these records out fixes the competitor COUNT, but a cell that
    contained 58 campus rooms was never a normal cell - its remaining density,
    catchment and comparability are all suspect. Flag the cell, not just the
    rows."""
    import h3
    ns = check_non_storefront(df)
    if not len(ns):
        return pd.DataFrame(columns=["h3_index", "n_non_storefront"])
    cells = [h3.latlng_to_cell(la, lo, res) for la, lo in zip(ns["lat"], ns["lon"])]
    vc = pd.Series(cells).value_counts()
    vc = vc[vc >= DENSITY_DISTORTION_MIN]
    return pd.DataFrame({"h3_index": vc.index, "n_non_storefront": vc.values})


# ---------------------------------------------------------------- C4
def check_bulk_import(history: pd.DataFrame, value_cols) -> pd.DataFrame:
    rows = []
    for col in value_cols:
        vals = history[col].tolist()
        rels = history["release"].tolist()
        for i in range(1, len(vals)):
            if not vals[i - 1]:
                continue
            pct = 100.0 * (vals[i] - vals[i - 1]) / vals[i - 1]
            if abs(pct) < BULK_JUMP_PCT:
                continue
            window = vals[i:i + BULK_MIN_FLAT]
            if len(window) < BULK_MIN_FLAT:
                continue
            if all(abs(100.0 * (w - vals[i]) / vals[i]) <= BULK_FLAT_TOL_PCT for w in window):
                rows.append({"series": col, "release": rels[i], "prev": vals[i - 1],
                             "value": vals[i], "jump_pct": round(pct, 1)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- runner

def check_resolution_carrier(metrics: pd.DataFrame, cells: pd.DataFrame,
                             res: int = 9) -> pd.DataFrame:
    """C5 - a coarse value carried by ONE child instead of distributed.

    THE FAILURE MODE THIS EXISTS FOR, because it defeats every check we had.
    Population was ingested from Kontur, which is natively h3 res-8. Building
    the res-9 table indexed each source hexagon by the cell containing its
    CENTROID, so at res-9 the parent's whole population landed in exactly one
    of its seven children and the other six got nothing.

    A sum check passes this cleanly: the city total reconciled to 34.0M at both
    resolutions. A row-count check passes it: rows existed. A null check passes
    it: values were present and positive. Every individual cell was wrong and
    every aggregate was right, which is the worst shape a data bug can take,
    because it only surfaces when someone queries a small area - exactly what a
    500 m catchment does.

    The signature is distributional: for a metric measured at a coarser
    resolution and stored at a finer one, look at how many parents have their
    entire value sitting in a single child. Sparse point data (a parent with
    three cafes may legitimately have all three in one child) produces this
    sometimes; a carrier bug produces it ALWAYS.
    """
    rows = []
    for metric, g in metrics.groupby("metric"):
        g = g[["h3_index", "value"]].copy()
        g["parent"] = [h3.cell_to_parent(c, res - 1) for c in g.h3_index]
        tot = g.groupby("parent")["value"].sum()
        top = g.groupby("parent")["value"].max()
        parents = len(tot)
        if parents < MIN_PARENTS_TO_JUDGE:
            continue
        # Share of parents where a single child holds essentially all of it.
        lone = float(((top / tot.replace(0, np.nan)) >= CARRIER_SHARE).mean())
        rows.append({"metric": metric, "parents": parents,
                     "single_child_share": round(lone, 4),
                     "verdict": "CARRIER BUG" if lone >= CARRIER_FAIL
                     else ("suspect" if lone >= CARRIER_WARN else "ok")})
    return pd.DataFrame(rows).sort_values("single_child_share", ascending=False)


def main():
    print("=" * 78)
    print("QA GATE — regression run against the 3 known Cairo districts")
    print("=" * 78)

    road9 = pd.read_csv(ROOT / "research" / "output" / "gt-maadi-road9.csv", comment="#")
    n90 = pd.read_csv(ROOT / "research" / "output" / "gcheck-90thstreet.csv", comment="#")
    shabab = pd.read_csv(ROOT / "research" / "output" / "gcheck-elshabab.csv", comment="#")
    hist = pd.read_csv(ROOT / "research" / "output" / "overture_release_history_places_count.csv")

    failures = []

    # ---- C1 : must catch the 90th Street collapse
    c1 = check_coordinate_collapse(n90)
    biggest = int(c1["group_size"].max()) if len(c1) else 0
    print(f"\nC1 coordinate collapse (90th Street): {len(c1)} records flagged, "
          f"largest group {biggest}")
    if biggest >= 3:
        print("   PASS — collapse detected")
    else:
        print("   FAIL — did not detect the known 90th Street collapse")
        failures.append("C1")

    # ---- C2 : must catch Hara 9 / حارة 9
    c2 = check_intra_source_duplicates(road9)
    hara = c2[c2.apply(lambda r: "9" in str(r["name_a"]) and "9" in str(r["name_b"])
                       and ("Hara" in f"{r['name_a']}{r['name_b']}" or "حارة" in f"{r['name_a']}{r['name_b']}"), axis=1)] if len(c2) else c2
    print(f"\nC2 intra-source duplicates (Road 9): {len(c2)} pairs flagged")
    for _, r in c2.iterrows():
        print(f"   [{r['source']}] {r['name_a']!r} <-> {r['name_b']!r}  {r['distance_m']}m sim={r['name_sim']}")
    if len(hara):
        print("   PASS — Hara 9 / حارة 9 detected")
    else:
        print("   FAIL — did not detect the known Hara 9 / حارة 9 duplicate")
        failures.append("C2")

    # ---- C3 : must catch the known non-storefront records
    c3 = check_non_storefront(road9)
    known = ["Egypreonics", "Smartology", "Cloudberry", "Bekka", "Lavender House",
             "شركة نقل", "الصفحة الرسمية"]
    got = {k: any(k in str(n) for n in c3["name"]) for k in known}
    print(f"\nC3 non-storefront (Road 9): {len(c3)} records flagged")
    missed = [k for k, v in got.items() if not v]
    if not missed:
        print("   PASS — all known non-storefront records caught")
    else:
        print(f"   FAIL — missed: {missed}")
        failures.append("C3")

    # ---- C4 : must catch the Sept-2024 Imbaba bulk import
    c4 = check_bulk_import(hist, ["Sheikh Zayed", "Maadi", "Imbaba"])
    print(f"\nC4 bulk-import artifacts (release history): {len(c4)} flagged")
    for _, r in c4.iterrows():
        print(f"   {r['series']}: {r['release']}  {r['prev']} -> {r['value']}  ({r['jump_pct']:+.1f}%)")
    sept = c4[(c4["series"] == "Imbaba") & (c4["release"] == "2024-09-18-0")]
    if len(sept):
        print("   PASS — Sept-2024 Imbaba bulk import detected")
    else:
        print("   FAIL — did not detect the known Sept-2024 Imbaba bulk import")
        failures.append("C4")

    # ---- C5: resolution carrier bug, across every stored metric
    print("\n" + "-" * 78)
    print("C5  coarse value carried by a single child (see check_resolution_carrier)")
    tables = ROOT / "data" / "derived" / "h3_tables"
    c5_ran = False
    for res in (9,):
        mp, cp = tables / f"h3_metric_res{res}.parquet", tables / f"h3_cell_res{res}.parquet"
        if not (mp.exists() and cp.exists()):
            print(f"   res-{res}: tables not built, skipped")
            continue
        c5_ran = True
        rep = check_resolution_carrier(pd.read_parquet(mp), pd.read_parquet(cp), res)
        for r in rep.itertuples():
            print(f"   res-{res} {r.metric:26s} parents {r.parents:6,}  "
                  f"single-child {100*r.single_child_share:5.1f}%  {r.verdict}")
        bad = rep[rep.verdict == "CARRIER BUG"]
        if len(bad):
            failures.append("C5:" + ",".join(bad.metric))
    if not c5_ran:
        print("   skipped - no h3 tables on disk")

    # ---- extra coverage: run C1/C2 across the other streets for signal
    print("\n" + "-" * 78)
    print("Additional signal (not regression-gated):")
    for label, d in (("Road 9", road9), ("El Shabab", shabab), ("90th St", n90)):
        a = check_coordinate_collapse(d)
        b = check_intra_source_duplicates(d)
        print(f"   {label:10s} collapse-flagged {len(a):4d} | intra-source dup pairs {len(b):3d}")

    print("\n" + "=" * 78)
    if failures:
        print(f"QA GATE FAILED — checks not catching their known case: {failures}")
        sys.exit(1)
    print("QA GATE PASSED — all four checks caught their known Cairo cases")
    sys.exit(0)


if __name__ == "__main__":
    main()

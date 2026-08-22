"""
Citywide QA report: run the QA gate checks over the ingested raw layer and
break flag counts down BY GOVERNORATE.

ADVISORY ONLY. Nothing here merges, deletes or rewrites a record. Every
output is a flag for human review. The duplicate matcher has a measured
in-sample precision of 1.0 on a 38-pair labelled set, which is a regression
suite - NOT evidence it generalises to 250k+ unseen rows in a city it was
never tuned on. Auto-merging on that basis would delete real businesses.

The per-governorate breakdown is the point: if flag rates differ sharply
between Cairo/Giza/Qalyubiya and Alexandria, that is an early read on the
Alexandria generalisation question (are the Part I coverage findings
structural, or specific to Cairo?) - before the full Step 4 analysis runs.
"""
import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point
from shapely.prepared import prep

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import ROOT
from scripts.qa import (check_coordinate_collapse, check_intra_source_duplicates,
                        check_non_storefront, check_bulk_import)

RAW = ROOT / "data" / "raw"
GOV_RELATIONS = {"Cairo": 4103336, "Giza": 3824206, "Alexandria": 3061846, "Qalyubiya": 4103337}
GEOM_FILES = [Path("/tmp/gov_geom.json"), Path("/tmp/alex_qal_geom.json")]


def load_governorates() -> dict:
    from shapely.geometry import LineString, MultiLineString
    from shapely.ops import linemerge, polygonize, unary_union
    by_id = {}
    for f in GEOM_FILES:
        if not f.exists():
            continue
        for el in json.loads(f.read_text())["elements"]:
            lines = []
            for m in el.get("members", []):
                if m.get("role") != "outer":
                    continue
                g = m.get("geometry")
                if not g or len(g) < 2:
                    continue
                lines.append(LineString([(p["lon"], p["lat"]) for p in g]))
            if lines:
                built = list(polygonize(linemerge(MultiLineString(lines))))
                if built:
                    by_id[el["id"]] = unary_union(built)
    return {lab: by_id[rid] for lab, rid in GOV_RELATIONS.items() if rid in by_id}


def assign_governorate(df: pd.DataFrame, govs: dict) -> pd.Series:
    prepared = {k: prep(v) for k, v in govs.items()}
    out = []
    for lat, lon in zip(df["lat"], df["lon"]):
        p = Point(lon, lat)
        hit = next((k for k, pg in prepared.items() if pg.contains(p)), "outside")
        out.append(hit)
    return pd.Series(out, index=df.index)


def latest_overture() -> pd.DataFrame:
    snaps = sorted((RAW / "overture").glob("snapshot=*"))
    if not snaps:
        raise SystemExit("no overture snapshots ingested")
    latest = snaps[-1]
    df = pd.read_parquet(latest / "places.parquet")
    df["source"] = "overture"
    return df, latest.name.split("=", 1)[1]


def fsq_clipped(govs: dict) -> pd.DataFrame:
    snaps = sorted((RAW / "fsq").glob("snapshot=*"))
    if not snaps:
        return pd.DataFrame(), None
    latest = snaps[-1]
    df = pd.read_parquet(latest / "places_egypt.parquet")
    df = df.rename(columns={"latitude": "lat", "longitude": "lon"})
    df["source"] = "fsq"
    df["category"] = df["fsq_category_labels"].apply(
        lambda l: l[-1] if l is not None and len(l) else None)
    # clip to the 4-governorate bbox first (cheap), polygon test happens later
    df = df[(df["lon"].between(29.5803, 31.8979)) & (df["lat"].between(29.1717, 31.352))]
    return df, latest.name.split("=", 1)[1]


def main():
    govs = load_governorates()
    ov, ov_snap = latest_overture()
    fsq, fsq_snap = fsq_clipped(govs)
    print(f"Overture snapshot {ov_snap}: {len(ov):,} rows")
    print(f"FSQ snapshot {fsq_snap}: {len(fsq):,} rows in coverage bbox")

    ov["governorate"] = assign_governorate(ov, govs)
    if len(fsq):
        fsq["governorate"] = assign_governorate(fsq, govs)

    combined = pd.concat([ov[["source", "name", "category", "lat", "lon", "governorate"]],
                          fsq[["source", "name", "category", "lat", "lon", "governorate"]]
                          if len(fsq) else pd.DataFrame()], ignore_index=True)

    print("\nrows per governorate:")
    print(combined.groupby(["governorate", "source"]).size().unstack(fill_value=0).to_string())

    out = ROOT / "output" / "qa_citywide_report.csv"
    rows = []
    # Written incrementally: two earlier citywide runs were killed mid-pass and
    # lost everything. Each governorate's result is flushed as soon as it is
    # computed, so a kill costs one governorate, not the whole report.
    for gov in sorted(combined["governorate"].unique()):
        if gov == "outside":
            continue
        sub = combined[combined["governorate"] == gov].reset_index(drop=True)
        c1 = check_coordinate_collapse(sub)
        c2 = check_intra_source_duplicates(sub)
        c3 = check_non_storefront(sub)
        rows.append({
            "governorate": gov, "rows": len(sub),
            "c1_collapse_records": len(c1),
            "c1_pct": round(100 * len(c1) / len(sub), 2) if len(sub) else 0,
            "c2_dup_pairs": len(c2),
            "c2_pct_rows_involved": round(100 * (2 * len(c2)) / len(sub), 2) if len(sub) else 0,
            "c3_non_storefront": len(c3),
            "c3_pct": round(100 * len(c3) / len(sub), 2) if len(sub) else 0,
        })
        pd.DataFrame(rows).to_csv(out, index=False)
        r = rows[-1]
        print(f"  {gov}: rows={r['rows']:,} c1={r['c1_collapse_records']} "
              f"c2_pairs={r['c2_dup_pairs']} c3={r['c3_non_storefront']}", flush=True)

    rep = pd.DataFrame(rows)
    rep.to_csv(out, index=False)
    print("\n" + "=" * 90)
    print(rep.to_string(index=False))
    print(f"\nWrote {out}")
    print("\nADVISORY ONLY — flags are for review. No record has been merged or removed.")


if __name__ == "__main__":
    main()

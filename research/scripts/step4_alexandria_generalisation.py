"""
STEP 4 — ALEXANDRIA GENERALISATION TEST.

Repeats the Part I Cairo analysis on three Alexandria districts of differing
income level, to answer one question:

  Are the Part I coverage findings STRUCTURAL to free geodata in Egypt, or
  SPECIFIC TO CAIRO?

The Cairo finding under test: business-layer coverage degrades sharply in
poorer districts. Imbaba (low income) was 96.5% single-source (Meta), had zero
OSM contribution, the worst confidence distribution (median 0.56, 36% below
0.5), and FSQ held only 84 records against Overture's 316 (27%).

If Alexandria reproduces that gradient, the finding is structural and Part I's
conclusions carry. If it does not, they are Cairo-specific and every
coverage-bias claim must be restated with that scope limit.

DISTRICTS (config/alexandria_test_areas.json), 1.5km boxes:
  Smouha      HIGH    - option A, the mosque<->Green Plaza commercial corridor
                        midpoint. NOT the Nominatim match, which was Smouha
                        Club mosque, a landmark whose box is club grounds.
  Sidi Gaber  MIDDLE
  Karmouz     LOW

RELEASE PINNING: queries the PINNED analysis release (_common.OVERTURE_RELEASE
= 2026-07-22.0), NOT the latest ingest snapshot. The Cairo baseline numbers
were computed against that release; using a different one would confound a
release difference with a city difference.

Note the raw ingest layer cannot serve this: archive_release.py stores
id/name/category/confidence/lat/lon only, and the source-breakdown needs the
`sources` array, so this queries S3 directly.
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import ROOT, OVERTURE_RELEASE, PLACES_PATH, get_con

AREAS = ROOT / "config" / "alexandria_test_areas.json"
FSQ_GLOB = ROOT / "data" / "raw" / "fsq"

# Cairo baseline, from Part I (same pinned release), for side-by-side reading.
CAIRO_BASELINE = {
    "Sheikh Zayed (high)": dict(overture=491, meta_pct=77.6, conf_median=0.770,
                                conf_below_05=15.9, fsq=490, fsq_ratio=1.00),
    "Maadi (mid)":         dict(overture=991, meta_pct=86.1, conf_median=0.676,
                                conf_below_05=23.7, fsq=1025, fsq_ratio=1.03),
    "Imbaba (low)":        dict(overture=316, meta_pct=96.5, conf_median=0.562,
                                conf_below_05=36.4, fsq=84, fsq_ratio=0.27),
}


def record_dataset(sources):
    """The record-level contributing dataset: the sources entry with
    property == "" . The '/properties/confidence' entry (dataset='Overture')
    records where the confidence score was computed and is NOT a content
    source - counting it would show every record as Overture-sourced."""
    if sources is None:
        return "unknown"
    for s in sources:
        if s.get("property", "") == "":
            return s.get("dataset") or "unknown"
    return "unknown"


def latest_fsq() -> Path:
    snaps = sorted(FSQ_GLOB.glob("snapshot=*"))
    return snaps[-1] / "places_egypt.parquet"


def main():
    areas = json.loads(AREAS.read_text())
    con = get_con()
    base = f"read_parquet('{PLACES_PATH}', hive_partitioning=1)"
    fsq_all = pd.read_parquet(latest_fsq())

    print("=" * 84)
    print(f"STEP 4 — Alexandria generalisation (Overture release {OVERTURE_RELEASE}, pinned)")
    print("=" * 84)

    rows = []
    for name, a in areas.items():
        b = a["bbox"]
        where = (f"bbox.xmin <= {b['xmax']} AND bbox.xmax >= {b['xmin']} "
                 f"AND bbox.ymin <= {b['ymax']} AND bbox.ymax >= {b['ymin']}")
        ov = con.execute(f"""
            SELECT names.primary AS name, categories.primary AS category,
                   confidence, sources
            FROM {base} WHERE {where}
        """).fetchdf()

        fsq = fsq_all[(fsq_all.longitude.between(b["xmin"], b["xmax"])) &
                      (fsq_all.latitude.between(b["ymin"], b["ymax"]))]

        print(f"\n{'='*84}\n{name}   centre {a['center']['lat']:.6f}, {a['center']['lon']:.6f}")
        print(f"{'='*84}")
        print(f"  Overture places: {len(ov):,}   |   FSQ places: {len(fsq):,}   "
              f"|   FSQ/Overture ratio: {len(fsq)/len(ov):.2f}" if len(ov) else "  Overture: 0")

        if not len(ov):
            continue

        ds = ov["sources"].apply(record_dataset)
        vc = ds.value_counts()
        print("\n  source contribution:")
        for k, v in vc.items():
            print(f"    {k:16s} {v:5,}  ({100*v/len(ov):5.1f}%)")
        meta_pct = 100 * vc.get("meta", 0) / len(ov)
        osm_pct = 100 * vc.get("OpenStreetMap", 0) / len(ov)
        top_pct = 100 * vc.iloc[0] / len(ov)

        c = ov["confidence"].dropna()
        print(f"\n  confidence: median {c.median():.3f} | p25 {c.quantile(.25):.3f} | "
              f"% below 0.5: {100*(c < 0.5).mean():.1f}%")

        # FSQ date_created histogram
        if len(fsq):
            yrs = pd.to_datetime(fsq["date_created"], errors="coerce").dt.year
            hist = yrs.value_counts().sort_index()
            span = hist.loc[2011:2013].sum() if len(hist) else 0
            print(f"\n  FSQ date_created 2010-2026 (2011-13 share: {100*span/len(fsq):.1f}%):")
            for y in range(2010, 2027):
                n = int(hist.get(y, 0))
                print(f"    {y}: {'#'*min(n, 60)} ({n})")
        else:
            span = 0

        rows.append({
            "district": name, "overture": len(ov), "fsq": len(fsq),
            "fsq_ratio": round(len(fsq)/len(ov), 2),
            "top_source": vc.index[0], "top_source_pct": round(top_pct, 1),
            "meta_pct": round(meta_pct, 1), "osm_pct": round(osm_pct, 1),
            "conf_median": round(float(c.median()), 3),
            "conf_below_05_pct": round(100*float((c < 0.5).mean()), 1),
            "fsq_2011_13_pct": round(100*span/len(fsq), 1) if len(fsq) else None,
        })

    out = pd.DataFrame(rows)
    out.to_csv(ROOT / "output" / "step4_alexandria_generalisation.csv", index=False)

    print("\n" + "=" * 84)
    print("ALEXANDRIA SUMMARY")
    print("=" * 84)
    print(out.to_string(index=False))
    print("\nCAIRO BASELINE (Part I, same pinned release):")
    cb = pd.DataFrame(CAIRO_BASELINE).T.reset_index().rename(columns={"index": "district"})
    print(cb.to_string(index=False))
    print(f"\nWrote {ROOT/'output'/'step4_alexandria_generalisation.csv'}")


if __name__ == "__main__":
    main()

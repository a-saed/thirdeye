"""
Corroboration matrix, v2 (restructured 2026-08-18): two INDEPENDENT
tracks, never mixed.

Overture/Foursquare measure BUSINESSES (places opening/closing/being
mapped). Open Buildings/GHSL/WSF measure BUILDINGS (physical
construction). A fully-built, business-churning district can legitimately
show flat buildings and active businesses at the same time - that is not
a contradiction, so v1's single combined vote (which flagged Maadi as
"DIVERGE" for exactly this reason) was comparing two different physical
quantities and calling the difference a disagreement. Fixed here:
corroboration is only computed WITHIN a track.

  BUILT ENVIRONMENT track: Open Buildings (presence-based), GHSL,
    WSF Evolution (context - its 1985-2015 window barely overlaps the
    other two, and its "flat" reading for already-saturated districts is
    partly a ceiling effect - can't grow much past ~100% - not fully
    independent confirmation of "no change." Flagged inline, not hidden.)
  BUSINESS LAYER track: Overture release history (artifact-corrected),
    Foursquare reconstruction (pending - not live yet).

Where a track currently has only one live source, it is reported as
UNCORROBORATED - SINGLE SOURCE, not given an AGREE/DIVERGE verdict. As of
this revision that is the business layer's status in all three
districts - Overture is not yet cross-checked by anything, so its
"growth" readings (corrected or not) should not be presented as
confirmed findings.

Also reports each district's saturation status (GREENFIELD / DEVELOPING
/ SATURATED) from GHSL's most recent built-up %, as a standing attribute
- not a metric that changes, a classification of what kind of area this
is, so that a flat building signal in a SATURATED district reads as
"expected", not "nothing is happening here."
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import ROOT
from scripts.artifact_detection import corrected_trend

FLAT_THRESHOLD_PCT = 10.0

SATURATED_PCT = 40.0
GREENFIELD_PCT = 10.0


def classify_direction(pct_change) -> str:
    if pct_change is None:
        return "n/a"
    if abs(pct_change) < FLAT_THRESHOLD_PCT:
        return "flat"
    return "growing" if pct_change > 0 else "declining"


def classify_saturation(built_up_pct: float) -> str:
    if built_up_pct >= SATURATED_PCT:
        return "SATURATED"
    if built_up_pct < GREENFIELD_PCT:
        return "GREENFIELD"
    return "DEVELOPING"


def track_verdict(signal_results: dict) -> str:
    live = {k: v for k, v in signal_results.items() if v is not None}
    if len(live) == 0:
        return "NO DATA"
    if len(live) == 1:
        return "UNCORROBORATED - SINGLE SOURCE"
    directions = {v["direction"] for v in live.values() if v["direction"] != "n/a"}
    if len(directions) == 1:
        return f"AGREE ({directions.pop()})"
    return f"DIVERGE ({' vs '.join(sorted(directions))})"


OPEN_BUILDINGS_BASELINE_YEAR = 2018  # 2016-2017 excluded: Sentinel-2B launched March 2017,
# so the 2016 composite came from a single satellite at half revisit rate - degraded worst
# in dense complex fabric (Imbaba's entire "decline" was 2016->2018, then flat for 5 years -
# a sensor-transition artifact, not a real change). Confirmed 2026-08-18.


def open_buildings_signal(district: str) -> dict:
    df = pd.read_csv(ROOT / "output" / "test2c_open_buildings_annual.csv")
    sub = df[(df["district"] == district) & (df["year"] >= OPEN_BUILDINGS_BASELINE_YEAR)].sort_values("year")
    first, last = sub.iloc[0], sub.iloc[-1]
    pct = round(100.0 * (last["presence_area_m2"] - first["presence_area_m2"]) / first["presence_area_m2"], 1)
    return {
        "signal": "Open Buildings (presence area, 2018 baseline)",
        "period": f"{int(first['year'])} -> {int(last['year'])}",
        "first_value": round(first["presence_area_m2"], 0), "last_value": round(last["presence_area_m2"], 0),
        "pct_change": pct, "direction": classify_direction(pct),
    }


def ghsl_signal(district: str) -> dict:
    df = pd.read_csv(ROOT / "output" / "test2c_ghsl_annual.csv")
    sub = df[df["district"] == district].sort_values("epoch")
    first, last = sub.iloc[0], sub.iloc[-1]
    pct = round(100.0 * (last["built_up_m2"] - first["built_up_m2"]) / first["built_up_m2"], 1) if first["built_up_m2"] else None
    return {
        "signal": "GHSL built-up surface",
        "period": f"{int(first['epoch'])} -> {int(last['epoch'])}",
        "first_value": first["built_up_m2"], "last_value": last["built_up_m2"],
        "pct_change": pct, "direction": classify_direction(pct),
    }


def wsf_signal(district: str) -> dict:
    path = ROOT / "output" / "test2c_wsf_evolution_annual.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    sub = df[df["district"] == district].sort_values("year")
    if sub.empty:
        return None
    first, last = sub.iloc[0], sub.iloc[-1]
    pct = round(100.0 * (last["pct_settled"] - first["pct_settled"]) / first["pct_settled"], 1) if first["pct_settled"] else None
    ceiling_note = " [near-saturation ceiling effect - weak evidence of 'no change']" if last["pct_settled"] > 90 else ""
    return {
        "signal": "WSF Evolution" + ceiling_note,
        "period": f"{int(first['year'])} -> {int(last['year'])}",
        "first_value": first["pct_settled"], "last_value": last["pct_settled"],
        "pct_change": pct, "direction": classify_direction(pct),
    }


def foursquare_signal(district: str) -> dict:
    path = ROOT / "output" / "test2c_fsq_reconstruction.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    sub = df[df["district"] == district].sort_values("year")
    if sub.empty:
        return None
    first, last = sub.iloc[0], sub.iloc[-1]
    pct = round(100.0 * (last["open_as_of_jan1"] - first["open_as_of_jan1"]) / first["open_as_of_jan1"], 1) if first["open_as_of_jan1"] else None
    return {
        "signal": "Foursquare reconstruction (date_created/date_closed)",
        "period": f"{int(first['year'])} -> {int(last['year'])}",
        "first_value": int(first["open_as_of_jan1"]), "last_value": int(last["open_as_of_jan1"]),
        "pct_change": pct, "direction": classify_direction(pct),
    }


def overture_signal(district: str) -> dict:
    df = pd.read_csv(ROOT / "output" / "overture_release_history_places_count.csv")
    r = corrected_trend(df["release"].tolist(), df[district].tolist())
    note = f"  [artifact excluded: raw range was {r['raw_pct_change']:+.1f}%]" if r["artifact_indices"] else ""
    return {
        "signal": "Overture release history (artifact-corrected)" + note,
        "period": f"{r['corrected_baseline_date']} -> {df['release'].iloc[-1]}",
        "first_value": r["corrected_baseline_value"], "last_value": r["corrected_last_value"],
        "pct_change": r["corrected_pct_change"], "direction": classify_direction(r["corrected_pct_change"]),
    }


def coverage_ratio_signal(district: str, ghsl_latest: pd.DataFrame) -> dict:
    """Open Buildings presence % / GHSL built-up % - separates villa/garden
    fabric (ratio well below 1, presence undercounts relative to GHSL's
    coarser built-up-surface measure) from wall-to-wall dense fabric
    (ratio at or above 1). Neither source alone reports this - it's a
    standing derived attribute, not a growth metric."""
    ob = pd.read_csv(ROOT / "output" / "test2c_open_buildings_annual.csv")
    ob_latest = ob[ob["district"] == district].sort_values("year").iloc[-1]
    ghsl_row = ghsl_latest[(ghsl_latest["district"] == district) & (ghsl_latest["epoch"] == ghsl_latest["epoch"].max())].iloc[0]
    ratio = round(ob_latest["presence_pct_of_bbox"] / ghsl_row["pct_of_bbox"], 2)
    return {"open_buildings_pct": ob_latest["presence_pct_of_bbox"], "ghsl_pct": ghsl_row["pct_of_bbox"], "ratio": ratio}


def main():
    districts = ["Sheikh Zayed", "Maadi", "Imbaba"]
    ghsl_latest = pd.read_csv(ROOT / "output" / "test2c_ghsl_annual.csv")

    all_rows = []
    coverage_rows = []
    print("=" * 100)
    for district in districts:
        sat_pct = ghsl_latest[(ghsl_latest["district"] == district) & (ghsl_latest["epoch"] == ghsl_latest["epoch"].max())]["pct_of_bbox"].iloc[0]
        sat_label = classify_saturation(sat_pct)
        cov = coverage_ratio_signal(district, ghsl_latest)
        coverage_rows.append({"district": district, "saturation": sat_label, **cov})

        print(f"\n=== {district} ===")
        print(f"  SATURATION: {sat_label} (GHSL {int(ghsl_latest['epoch'].max())}: {sat_pct:.1f}% of bbox built up)")
        if sat_label == "SATURATED":
            print(f"    -> a flat building signal here is EXPECTED, not a finding of stagnation.")
        print(f"  BUILDING COVERAGE RATIO: {cov['ratio']}  (Open Buildings presence {cov['open_buildings_pct']:.1f}% / GHSL {cov['ghsl_pct']:.1f}%)")
        print(f"    -> {'wall-to-wall dense fabric' if cov['ratio'] >= 0.9 else 'villa/garden or lower-density fabric'} "
              f"(neither source alone reports this distinction)")

        print("\n  --- BUILT ENVIRONMENT track ---")
        built_signals = {"open_buildings": open_buildings_signal(district), "ghsl": ghsl_signal(district), "wsf": wsf_signal(district)}
        for key, r in built_signals.items():
            if r is None:
                continue
            print(f"    {r['signal']:65s} {r['period']:18s} {r['first_value']:>12} -> {r['last_value']:<12} ({r['pct_change']:+.1f}%, {r['direction']})")
            all_rows.append({"district": district, "track": "built_environment", **r})
        built_verdict = track_verdict(built_signals)
        print(f"    -> BUILT ENVIRONMENT verdict: {built_verdict}")

        print("\n  --- BUSINESS LAYER track ---")
        business_signals = {"overture": overture_signal(district), "foursquare": foursquare_signal(district)}
        for key, r in business_signals.items():
            if r is None:
                continue
            print(f"    {r['signal']:65s} {r['period']:18s} {r['first_value']:>12} -> {r['last_value']:<12} ({r['pct_change']:+.1f}%, {r['direction']})")
            all_rows.append({"district": district, "track": "business_layer", **r})
        business_verdict = track_verdict(business_signals)
        print(f"    -> BUSINESS LAYER verdict: {business_verdict}")

    out = pd.DataFrame(all_rows)
    out_path = ROOT / "output" / "corroboration_matrix.csv"
    out.to_csv(out_path, index=False)
    print(f"\nWrote {out_path}")

    cov_out = pd.DataFrame(coverage_rows)
    cov_path = ROOT / "output" / "building_coverage_ratio.csv"
    cov_out.to_csv(cov_path, index=False)
    print(f"Wrote {cov_path}")


if __name__ == "__main__":
    main()

"""
Bulk-import artifact detection for release-over-release series (e.g. the
Overture release-history place counts). A "40% YoY/release jump = bulk
import, not real change" is already this study's kill criterion for Test
3's ohsome check - reused here for consistency, not invented fresh.

Detection: a release-over-release jump >= JUMP_THRESHOLD_PCT counts as a
CANDIDATE artifact only if the level then holds flat (within
FLAT_TOLERANCE_PCT of the post-jump value) for at least MIN_FLAT_RELEASES
consecutive releases afterward - a genuine bulk import lands all at once
and then sits still, which is what separates it from noisy-but-real
growth. Calibration check against this dataset: the largest jump ANYWHERE
outside the one confirmed artifact is 28.3% (Sheikh Zayed) - a threshold
of 40% is not a post-hoc fit to get one specific district's answer, it
sits in the natural gap between "biggest ordinary jump" and "the outlier."

Correction: growth is recomputed from the value immediately AFTER the
last confirmed artifact (not from the original first value) to the
latest value - i.e. the artifact and everything before it is excluded
from the trend calculation, not smoothed or interpolated.
"""
import pandas as pd

JUMP_THRESHOLD_PCT = 40.0
FLAT_TOLERANCE_PCT = 15.0
MIN_FLAT_RELEASES = 3


def detect_artifacts(dates: list, values: list) -> list:
    """Returns list of confirmed artifact indices (index of the jump, i.e.
    the transition FROM values[i-1] TO values[i])."""
    artifacts = []
    for i in range(1, len(values)):
        if values[i - 1] == 0:
            continue
        pct = 100.0 * (values[i] - values[i - 1]) / values[i - 1]
        if abs(pct) < JUMP_THRESHOLD_PCT:
            continue
        # does it hold flat for the next MIN_FLAT_RELEASES releases?
        window = values[i : i + MIN_FLAT_RELEASES]
        if len(window) < MIN_FLAT_RELEASES:
            continue  # not enough subsequent data to confirm - don't flag near the series end
        holds_flat = all(abs(100.0 * (w - values[i]) / values[i]) <= FLAT_TOLERANCE_PCT for w in window)
        if holds_flat:
            artifacts.append(i)
    return artifacts


def corrected_trend(dates: list, values: list) -> dict:
    artifacts = detect_artifacts(dates, values)
    raw_pct = round(100.0 * (values[-1] - values[0]) / values[0], 1) if values[0] else None

    if artifacts:
        baseline_idx = artifacts[-1]
        baseline_value = values[baseline_idx]
        baseline_date = dates[baseline_idx]
        corrected_pct = round(100.0 * (values[-1] - baseline_value) / baseline_value, 1) if baseline_value else None
    else:
        baseline_idx = 0
        baseline_value = values[0]
        baseline_date = dates[0]
        corrected_pct = raw_pct

    return {
        "artifact_indices": artifacts,
        "artifact_dates": [dates[i] for i in artifacts],
        "raw_first_value": values[0],
        "raw_last_value": values[-1],
        "raw_pct_change": raw_pct,
        "corrected_baseline_date": baseline_date,
        "corrected_baseline_value": baseline_value,
        "corrected_last_value": values[-1],
        "corrected_pct_change": corrected_pct,
    }


def main():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts._common import ROOT

    df = pd.read_csv(ROOT / "output" / "overture_release_history_places_count.csv")
    print(f"Jump threshold: {JUMP_THRESHOLD_PCT}%, flat tolerance: {FLAT_TOLERANCE_PCT}%, "
          f"min flat releases to confirm: {MIN_FLAT_RELEASES}\n")
    for d in ["Sheikh Zayed", "Maadi", "Imbaba"]:
        r = corrected_trend(df["release"].tolist(), df[d].tolist())
        print(f"=== {d} ===")
        print(f"  BEFORE (raw full range):  {r['raw_first_value']} -> {r['raw_last_value']}  ({r['raw_pct_change']:+.1f}%)")
        if r["artifact_indices"]:
            print(f"  Artifact(s) detected at: {r['artifact_dates']}")
            print(f"  AFTER (corrected):        {r['corrected_baseline_date']}: {r['corrected_baseline_value']} "
                  f"-> {r['corrected_last_value']}  ({r['corrected_pct_change']:+.1f}%)")
        else:
            print("  No artifact detected - before/after are the same.")
        print()


if __name__ == "__main__":
    main()

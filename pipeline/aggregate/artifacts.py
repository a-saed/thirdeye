"""
Bulk-import artifact detection, applied PER CELL PER METRIC.

Ported from research/scripts/artifact_detection.py, which ran on
DISTRICT-level counts (hundreds of places). The rule is unchanged:

    a release-over-release jump of >= JUMP_PCT that then holds flat
    (within FLAT_TOL_PCT) for >= MIN_FLAT subsequent releases

Calibration from the study: the largest ordinary jump anywhere in the
district series was 28.3%, the one confirmed artifact was 90.2%. 40% sits in
that gap.

ONE ADDITION FOR CELL-LEVEL USE — MIN_BASE.
At district level the counts were in the hundreds, so a 40% jump meant dozens
of records appearing at once. At res-9 a cell often holds 1-5 businesses, and
there 40% is a single record: 2 -> 3 is +50%, followed by "flat" simply
because nothing else changed. Without a floor, ordinary small-cell noise gets
labelled an import and the flag becomes meaningless. MIN_BASE requires the
pre-jump value to be large enough that the jump means something. Sensitivity
to this choice is reported by the build script rather than hidden.
"""
JUMP_PCT = 40.0
FLAT_TOL_PCT = 15.0
MIN_FLAT = 3
MIN_BASE = 5           # pre-jump value must be >= this for a jump to count
MIN_ABS_JUMP = 3       # and the jump must move at least this many records


def detect_artifact_indices(values) -> list:
    """Return indices i where values[i-1] -> values[i] looks like a bulk import.

    Index i is the FIRST point at the new level, i.e. the first point that
    should be treated as a new baseline."""
    out = []
    n = len(values)
    for i in range(1, n):
        prev, cur = values[i - 1], values[i]
        if prev < MIN_BASE:
            continue
        if (cur - prev) < MIN_ABS_JUMP:
            continue
        if prev == 0:
            continue
        pct = 100.0 * (cur - prev) / prev
        if abs(pct) < JUMP_PCT:
            continue
        window = values[i:i + MIN_FLAT]
        if len(window) < MIN_FLAT:
            # Not enough subsequent points to confirm the level holds. Do not
            # flag near the series end - an unconfirmed jump is just a jump.
            continue
        if all(abs(100.0 * (w - cur) / cur) <= FLAT_TOL_PCT for w in window if cur):
            out.append(i)
    return out

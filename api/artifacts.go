package main

import "math"

// ARTIFACT DETECTION RUNS ON THE SERIES BEING DISPLAYED.
//
// Port of pipeline/aggregate/artifacts.py. Parameters are read from the
// history manifest at startup rather than duplicated here, so the Python
// build and the Go API cannot drift apart.
//
// WHY THIS IS NOT WEAKEST-LINK, UNLIKE CONFIDENCE.
// Confidence propagates weakest-link: one single-source member cell makes the
// whole catchment's number uncertain, because the uncertainty is genuinely
// inherited by the total.
// Artifact correction does NOT propagate. It operates on the series actually
// being shown. An import step in 1 of 37 member cells may be invisible in the
// aggregate — the Road 9 catchment went 687 -> 724 -> 712 -> 732 -> 696 around
// a propagated 2026-03-18 flag, which has no step in it, and truncating there
// discarded 18 real points to correct an artifact that was not present in the
// displayed number.
// Different rules, different reasons: confidence is about how much to trust a
// value, artifacts are about whether a movement in THIS line is real.
//
// Member-cell flags are still surfaced, as an advisory count.

type detectorParams struct {
	JumpPct    float64 `json:"jump_pct"`
	FlatTolPct float64 `json:"flat_tol_pct"`
	MinFlat    int     `json:"min_flat_releases"`
	MinBase    float64 `json:"min_base"`
	MinAbsJump float64 `json:"min_abs_jump"`
}

// The floor below which a corrected series is withheld now comes from
// config/thresholds.json (series.min_corrected_points). A 3-point line renders
// as a trend and is not one.

// detectArtifacts returns indices i where values[i-1] -> values[i] shows the
// bulk-import signature: a large jump that then holds flat. Index i is the
// first point at the new level, i.e. the first valid post-import baseline.
func (p detectorParams) detectArtifacts(values []float64) []int {
	var out []int
	n := len(values)
	for i := 1; i < n; i++ {
		prev, cur := values[i-1], values[i]
		if prev < p.MinBase || prev == 0 {
			continue
		}
		if (cur - prev) < p.MinAbsJump {
			continue
		}
		pct := 100.0 * (cur - prev) / prev
		if math.Abs(pct) < p.JumpPct {
			continue
		}
		if i+p.MinFlat > n {
			// Not enough subsequent points to confirm the level holds. An
			// unconfirmed jump is just a jump.
			continue
		}
		flat := true
		for _, w := range values[i : i+p.MinFlat] {
			if cur == 0 || math.Abs(100.0*(w-cur)/cur) > p.FlatTolPct {
				flat = false
				break
			}
		}
		if flat {
			out = append(out, i)
		}
	}
	return out
}

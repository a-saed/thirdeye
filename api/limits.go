package main

import (
	"encoding/json"
	"fmt"
	"os"
)

// LIMITATIONS COME FROM CONFIG, NOT FROM CODE.
//
// These are measured values from the feasibility study. Keeping them in
// api/limitations.json rather than as Go string literals means updating a
// measurement is a data change with a visible diff, and means the API refuses
// to start if the file is missing rather than silently shipping stale or
// absent caveats.
type limitationsFile struct {
	DuplicateInflationPctRange [2]float64 `json:"duplicate_inflation_pct_range"`
	PositionErrorMedianM       float64    `json:"position_error_median_m"`
	PositionErrorP90M          float64    `json:"position_error_p90_m"`
	PositionErrorMaxM          float64    `json:"position_error_max_m"`
	IndependenceCaveat         string     `json:"independence_caveat"`
}

func LoadLimitations(path string) (Limitations, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return Limitations{}, fmt.Errorf("read %s: %w", path, err)
	}
	var f limitationsFile
	if err := json.Unmarshal(b, &f); err != nil {
		return Limitations{}, fmt.Errorf("parse %s: %w", path, err)
	}
	if f.IndependenceCaveat == "" || f.PositionErrorP90M == 0 {
		// A half-populated file would ship responses that look caveated but
		// are not. Refuse rather than degrade.
		return Limitations{}, fmt.Errorf("%s is missing required fields", path)
	}
	return Limitations{
		DuplicateInflationPctRange: f.DuplicateInflationPctRange,
		PositionErrorMedianM:       f.PositionErrorMedianM,
		PositionErrorP90M:          f.PositionErrorP90M,
		PositionErrorMaxM:          f.PositionErrorMaxM,
		IndependenceCaveat:         f.IndependenceCaveat,
	}, nil
}

package main

import (
	"encoding/json"
	"fmt"
	"os"
)

// THRESHOLDS COME FROM config/thresholds.json AND ARE NEVER REDECLARED HERE.
//
// A constant copied into two languages is a rule with two places to get it
// wrong. This project has already shipped that failure: saturation boundaries
// existed in Python and Go, the land-fraction floor in both, and the report
// resolution in Go and TypeScript. They happened to agree — which is luck, not
// design, and luck does not survive the next edit.
//
// LOADING IS STRICT. A missing value is a startup failure, not a default.
// Falling back to a built-in would let the API aggregate on one rule while the
// pipeline aggregated on another, and the resulting numbers would look
// perfectly reasonable. The artifact detector already works this way, refusing
// to start without its parameters from the history manifest.

type Thresholds struct {
	Resolutions struct {
		Report   int `json:"report"`
		Coverage int `json:"coverage"`
	} `json:"resolutions"`

	Catchment struct {
		DefaultK       int `json:"default_k"`
		MaxK           int `json:"max_k"`
		DefaultRadiusM int `json:"default_radius_m"`
	} `json:"catchment"`

	LandFractionFloor struct {
		Value float64 `json:"value"`
	} `json:"land_fraction_floor"`

	Saturation struct {
		SaturatedPct      float64 `json:"saturated_pct"`
		GreenfieldPct     float64 `json:"greenfield_pct"`
		GrowthMaterialPct float64 `json:"growth_material_pct"`
	} `json:"saturation"`

	Corroboration struct {
		MinRatio float64 `json:"min_ratio"`
	} `json:"corroboration"`

	Percentages struct {
		MinBase float64 `json:"min_base"`
	} `json:"percentages"`

	Inhabited struct {
		PopulationMin float64 `json:"population_min"`
		BuiltupPctMin float64 `json:"builtup_pct_min"`
	} `json:"inhabited"`

	Duplicates struct {
		MaxDistanceM      float64 `json:"max_distance_m"`
		MinNameSimilarity float64 `json:"min_name_similarity"`
	} `json:"duplicates"`

	Series struct {
		MinCorrectedPoints int `json:"min_corrected_points"`
	} `json:"series"`
}

func LoadThresholds(path string) (*Thresholds, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("thresholds config: %w", err)
	}
	var t Thresholds
	if err := json.Unmarshal(b, &t); err != nil {
		return nil, fmt.Errorf("thresholds config parse: %w", err)
	}

	// Every field the API actually uses. Listed explicitly rather than checked
	// reflectively, so the failure names the missing key.
	missing := []string{}
	req := []struct {
		name string
		ok   bool
	}{
		{"resolutions.report", t.Resolutions.Report > 0},
		{"resolutions.coverage", t.Resolutions.Coverage > 0},
		{"catchment.default_k", t.Catchment.DefaultK >= 0},
		{"catchment.max_k", t.Catchment.MaxK > 0},
		{"catchment.default_radius_m", t.Catchment.DefaultRadiusM > 0},
		{"land_fraction_floor.value", t.LandFractionFloor.Value > 0},
		{"saturation.saturated_pct", t.Saturation.SaturatedPct > 0},
		{"saturation.greenfield_pct", t.Saturation.GreenfieldPct > 0},
		{"saturation.growth_material_pct", t.Saturation.GrowthMaterialPct > 0},
		{"percentages.min_base", t.Percentages.MinBase > 0},
		{"series.min_corrected_points", t.Series.MinCorrectedPoints > 0},
	}
	for _, r := range req {
		if !r.ok {
			missing = append(missing, r.name)
		}
	}
	if len(missing) > 0 {
		return nil, fmt.Errorf(
			"thresholds config %s is missing or zero for: %v — refusing to start rather "+
				"than aggregate on a default that may not match the pipeline", path, missing)
	}
	return &t, nil
}

// classifySaturation is the ONLY implementation of this rule. It was previously
// written twice, once in the pipeline and once here, and a third time as a
// branch in the frontend.
func (t *Thresholds) classifySaturation(builtUpPct float64) string {
	switch {
	case builtUpPct >= t.Saturation.SaturatedPct:
		return "SATURATED"
	case builtUpPct < t.Saturation.GreenfieldPct:
		return "GREENFIELD"
	default:
		return "DEVELOPING"
	}
}

// confidenceRank exposes the WEAKEST-LINK ordering as a number so a client can
// compare two confidences without redeclaring which is weaker. The frontend had
// its own CONF_RANK map; ordering is a rule, and rules live here.
func confidenceRank(c Confidence) int {
	switch c {
	case Corroborated:
		return 2
	case SingleSource:
		return 1
	default:
		return 0
	}
}

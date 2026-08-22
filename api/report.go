package main

import (
	"fmt"
	"math"
	"sort"
	"strings"

	"github.com/uber/h3-go/v4"
)

// Resolution comes from config/thresholds.json — see thresholds.go for why no
// constant is declared here.

// weakest returns the WEAKEST confidence among the inputs.
//
// THIS IS DELIBERATE AND MUST NOT BECOME AN AVERAGE OR A MAJORITY VOTE.
// A catchment spanning one corroborated cell and five single-source cells is
// single_source. Aggregating confidence upward would launder exactly the
// uncertainty the study spent two weeks measuring — 84-86% of cells are
// single-source, so any upward-averaging rule would report most of the city
// as better-evidenced than it is.
func weakest(cs []Confidence) Confidence {
	if len(cs) == 0 {
		return Unavailable
	}
	rank := map[Confidence]int{Corroborated: 2, SingleSource: 1, Unavailable: 0}
	worst := Corroborated
	for _, c := range cs {
		if rank[c] < rank[worst] {
			worst = c
		}
	}
	return worst
}

// kForRadius picks the k-ring size whose AREA best matches the requested
// circle, measured against the origin cell's own area.
//
// THE BUG THIS REPLACES, because it is easy to reintroduce: k was computed as
// round(radius / edgeLength) using the res-9 edge of ~174 m. Edge length is
// the distance from a cell's centre to its VERTEX. Stepping one cell across
// the grid moves centre-to-centre, which is edge * sqrt(3) ~= 301 m — so the
// old formula overstated k by about 1.7x, and because ring cell count grows
// as 3k^2+3k+1, a 500 m request returned k=3 and 37 cells covering 4.59 km²
// against a true circle of 0.79 km². Every metric on the screen inherited the
// error: ~6x the cafes and ~7x the population.
//
// Area-matching rather than a distance formula, because the k-ring is a
// hexagon and the request is a circle: there is no k that is simply "right",
// only the one whose area lands closest. The chosen ring's actual area is
// always reported alongside, so the approximation is visible rather than
// implied.
func kForRadius(origin h3.Cell, radius int) (int, error) {
	cellArea, err := h3.CellAreaKm2(origin)
	if err != nil {
		return 0, fmt.Errorf("cell area: %w", err)
	}
	target := math.Pi * float64(radius) * float64(radius) / 1e6
	best, bestDiff := 0, math.Abs(cellArea-target)
	for k := 1; k <= 60; k++ {
		cells := float64(3*k*k + 3*k + 1)
		if d := math.Abs(cells*cellArea - target); d < bestDiff {
			best, bestDiff = k, d
		} else if cells*cellArea > target {
			// Ring area only grows from here; nothing further can be closer.
			break
		}
	}
	return best, nil
}

// BuildReport assembles a catchment report: lat/lon -> h3 cell -> k-ring ->
// aggregate member cells.
// BuildReport takes an OPTIONAL explicit k (kOverride >= 0). The grid only
// supports discrete ring sizes, so a caller that wants "the next ring out"
// should say so rather than guessing a radius that happens to round to it.
func (a *App) BuildReport(lat, lon float64, radius int, category string, kOverride int) (*ReportResponse, error) {
	origin, err := h3.LatLngToCell(h3.NewLatLng(lat, lon), a.th.Resolutions.Report)
	if err != nil {
		return nil, fmt.Errorf("h3 index for %.6f,%.6f: %w", lat, lon, err)
	}
	k := kOverride
	if k < 0 {
		var err error
		if k, err = kForRadius(origin, radius); err != nil {
			return nil, err
		}
	}
	ring, err := origin.GridDisk(k)
	if err != nil {
		return nil, fmt.Errorf("k-ring k=%d: %w", k, err)
	}

	var (
		landAreaM2, rawAreaM2, landFracSum, builtUpSum float64
		covRatioSum                                    float64
		covRatioN                                      int
		inCoverage                                     int
		distorted                                      bool
		anyStale                                       bool
		growthSum                                      float64
		notes                                          []string
		cellsInRing                                    []uint64
	)
	// Which cells hold ANY business-track row, so "no cafes here" can be told
	// apart from "no business data here". They are different facts.
	cellsWithBusiness := map[uint64]bool{}
	satCells := map[string]int{}
	cellDetail := map[uint64]*CatchmentCell{}
	// metric name -> accumulator
	type acc struct {
		value   float64
		confs   []Confidence
		sources map[string]bool
		snaps   map[string]string
		asOf    string
		track   Track
		ratios  []float64
		srcVals map[string]float64
		stale   bool
		cells   map[uint64]bool
		// nativeRes: the resolution the value was MEASURED at, which for
		// population is coarser than the table it is stored in.
		nativeRes int
	}
	accs := map[string]*acc{}

	for _, cIdx := range ring {
		idx := uint64(cIdx)
		cell := a.store.Cell(a.th.Resolutions.Report, idx)
		if cell == nil {
			// Outside coverage. NOT the same as zero — recorded, not silently
			// treated as an empty cell.
			continue
		}
		inCoverage++
		cellsInRing = append(cellsInRing, idx)
		cellDetail[idx] = &CatchmentCell{
			H3: cIdx.String(), Confidence: Unavailable,
			LandFraction: round2(cell.LandFraction), InCoverage: true,
		}
		landAreaM2 += cell.LandAreaM2
		rawAreaM2 += cell.CellAreaM2
		landFracSum += cell.LandFraction
		builtUpSum += cell.BuiltUpPct
		if !math.IsNaN(cell.CoverageRatio) && cell.CoverageRatio != 0 {
			covRatioSum += cell.CoverageRatio
			covRatioN++
		}
		if cell.DensityDistort {
			distorted = true
		}
		if cell.PopulationStale {
			anyStale = true
		}
		satCells[cell.SaturationClass]++
		growthSum += cell.GrowthPct

		for _, m := range a.store.MetricsFor(a.th.Resolutions.Report, idx) {
			if category != "" && m.Track == TrackBusiness &&
				m.Metric != "business_count."+category {
				continue
			}
			e, ok := accs[m.Metric]
			if !ok {
				e = &acc{sources: map[string]bool{}, snaps: map[string]string{},
					track: m.Track, cells: map[uint64]bool{},
					srcVals: map[string]float64{}}
				accs[m.Metric] = e
			}
			e.value += m.Value
			e.confs = append(e.confs, m.Confidence)
			e.cells[idx] = true
			if d := cellDetail[idx]; d != nil && m.Track == TrackBusiness {
				if category == "" || m.Metric == "business_count."+category {
					d.Confidence = m.Confidence
					d.BusinessCount = m.Value
				}
			}
			if m.NativeRes > 0 {
				e.nativeRes = m.NativeRes
			}
			if m.Track == TrackBusiness {
				cellsWithBusiness[idx] = true
			}
			if m.OvertureCount > 0 {
				e.sources["overture"] = true
				e.srcVals["overture"] += float64(m.OvertureCount)
			}
			if m.FSQCount > 0 {
				e.sources["fsq"] = true
				e.srcVals["fsq"] += float64(m.FSQCount)
			}
			for k2, v := range m.SourceSnapshots {
				e.snaps[k2] = v
				e.sources[k2] = true
			}
			if e.asOf == "" || m.AsOf < e.asOf {
				// Report the OLDEST vintage in the catchment, not the newest —
				// the freshest figure would overstate how current the answer is.
				e.asOf = m.AsOf
			}
			if !math.IsNaN(m.AgreementRatio) {
				e.ratios = append(e.ratios, m.AgreementRatio)
			}
			if m.Track == TrackPopulation && cell.PopulationStale {
				e.stale = true
			}
		}
	}

	if inCoverage == 0 {
		return nil, fmt.Errorf("no cells in coverage for %.6f,%.6f (radius %dm)", lat, lon, radius)
	}
	if landAreaM2 <= 0 {
		return nil, fmt.Errorf("catchment has zero habitable land area (all water)")
	}
	if inCoverage < len(ring) {
		// NOTES ARE PROSE, NOT LOG LINES. They are rendered straight into
		// "what we can't say", beside two written paragraphs, so they have to
		// read in the same voice: sentence case, no operators, no shorthand.
		notes = append(notes, fmt.Sprintf(
			"%d of the %d cells in this catchment fall outside the area we have processed "+
				"and were left out. That is missing coverage, not an absence of businesses.",
			len(ring)-inCoverage, len(ring)))
	}
	if distorted {
		notes = append(notes, "One cell in this catchment is dominated by a campus or office cluster. "+
			"Those records are excluded from the counts, but the cell does not compare cleanly to an "+
			"ordinary one.")
	}
	if anyStale {
		notes = append(notes, "The population figure is from 2023, and this catchment has been built on "+
			"since. Treat it as an undercount.")
	}

	// SATURATION IS CLASSIFIED FROM THE CATCHMENT'S OWN BUILT-UP SHARE.
	//
	// It used to take the WORST class among member cells, while builtup_pct
	// reported the MEAN — so one saturated cell in a seven-cell ring made the
	// headline read "saturated" beside a subtitle saying 33.1% built up and
	// "villa and garden fabric". The card contradicted itself.
	//
	// Same principle as artifact detection: judge the aggregate you are
	// SHOWING, do not inherit a flag from one member. Weakest-link is right for
	// confidence, because uncertainty genuinely propagates upward; saturation
	// is a physical description of the ground, and the ground here is the
	// average, not its densest corner. The per-class spread is still returned
	// so a caller can see how mixed the catchment is.
	builtUpPct := builtUpSum / float64(inCoverage)
	satClass := a.th.classifySaturation(builtUpPct)
	growthPct := growthSum / float64(inCoverage)

	cellList := make([]CatchmentCell, 0, len(cellsInRing))
	for _, idx := range cellsInRing {
		if d := cellDetail[idx]; d != nil {
			cellList = append(cellList, *d)
		}
	}

	landKm2 := landAreaM2 / 1e6
	// FLOOR THE LAND DENOMINATOR.
	// value_per_land_km2 divides by habitable land, which is right, but as the
	// land share approaches zero the quotient explodes: an Alexandria Corniche
	// cell that is 99.9% sea produced 8.26M people/km2. That is not a dense
	// neighbourhood, it is a division artifact, and it would fire the first
	// time anyone compares a waterfront location.
	// The floor is 0.05 of the catchment's area. Chosen from the distribution:
	// land_fraction is above 0.95 for 95% of res-9 cells and the lower tail is
	// tiny - only 0.34% of cells fall under 0.05 - so the floor discards almost
	// nothing while removing every cell where the denominator is doing more
	// work than the numerator. A null with a reason is honest; 8 million is not.
	landFracMean := landFracSum / float64(inCoverage)
	perAreaOK := landFracMean >= a.th.LandFractionFloor.Value
	metrics := make([]Metric, 0, len(accs))
	for name, e := range accs {
		srcs := make([]string, 0, len(e.sources))
		for s := range e.sources {
			srcs = append(srcs, s)
		}
		sort.Strings(srcs)

		// AGREEMENT RATIO ONLY EXISTS WITH SOMETHING TO AGREE WITH.
		// Population comes from Kontur alone, and emitting 0.0 made the UI say
		// "sources agree to 0.00", which reads as total disagreement when the
		// truth is that there is nothing to compare against. One source means
		// no ratio, not a ratio of zero.
		var ratio *float64
		if len(srcs) > 1 && len(e.ratios) > 0 {
			sort.Float64s(e.ratios)
			med := e.ratios[len(e.ratios)/2]
			ratio = &med
		}
		// DENOMINATOR IS THE CATCHMENT, NOT THE ROWS THAT HAPPENED TO EXIST.
		// A cell with no row for this metric was previously dropped from the
		// total, so a 7-cell catchment reported "3 of 6 cells" while the header
		// and population both said 7. Same ring, two different denominators.
		// Every cell is now accounted for, and the reason it holds no row is
		// stated rather than hidden by shrinking the total.
		byConf := map[string]int{}
		for _, c := range e.confs {
			byConf[string(c)]++
		}
		var perKm2 *float64
		perKm2Reason := ""
		if perAreaOK && landKm2 > 0 {
			v := round2(e.value / landKm2)
			perKm2 = &v
		} else {
			perKm2Reason = fmt.Sprintf(
				"withheld: this catchment is %.1f%% land, below the %.0f%% floor for a "+
					"per-area figure. Dividing by a near-zero land area produces densities "+
					"that are arithmetic, not geography.",
				100*landFracMean, 100*a.th.LandFractionFloor.Value)
		}
		var noData, noneHere int
		for _, idx := range cellsInRing {
			if e.cells[idx] {
				continue
			}
			// For a category count, a cell that HAS business data but no row
			// for this category genuinely holds none of them - that is a zero,
			// not a gap. A cell with no business data at all is a gap.
			if e.track == TrackBusiness && cellsWithBusiness[idx] {
				noneHere++
			} else {
				noData++
			}
		}

		metrics = append(metrics, Metric{
			Name:  name,
			Value: e.value,
			// RULE 1: land area, never raw cell area.
			// RULE 1: land area, never raw area. Null when mostly water.
			ValuePerLandKm2:   perKm2,
			PerLandKm2Reason:  perKm2Reason,
			Track:             e.track,
			Confidence:        weakest(e.confs),
			Sources:           srcs,
			AsOf:              e.asOf,
			SourceSnapshots:   e.snaps,
			SourceCounts:      e.srcVals,
			AgreementRatio:    ratio,
			Stale:             e.stale,
			CellsByConfidence: byConf,
			CellsTotal:        inCoverage,
			CellsNoData:       noData,
			CellsNonePresent:  noneHere,
			ConfidenceRank:    confidenceRank(weakest(e.confs)),
			DirectionOfGood:   directionOfGood(name),
			NativeRes:         e.nativeRes,
		})
	}

	// PEOPLE PER COMPETITOR - the only value this API derives from others.
	//
	// It is computed HERE, not in the client, because a ratio of two metrics
	// inherits their provenance: confidence is weakest-link across both inputs
	// and as_of is the OLDER of the two vintages. A frontend dividing one
	// number by another would produce a bare float with neither, which is
	// exactly the path Metric exists to make impossible.
	if category != "" {
		var pop, comp *Metric
		for i := range metrics {
			switch metrics[i].Name {
			case "population":
				pop = &metrics[i]
			case "business_count." + category:
				comp = &metrics[i]
			}
		}
		// No competitors is NOT infinite demand per competitor - it is an
		// undefined ratio, and emitting a huge number would read as a
		// spectacular opportunity. Omit the metric instead.
		if pop != nil && comp != nil && comp.Value > 0 {
			srcSet := map[string]bool{}
			snaps := map[string]string{}
			for _, m := range []*Metric{pop, comp} {
				for _, s := range m.Sources {
					srcSet[s] = true
				}
				for k, v := range m.SourceSnapshots {
					snaps[k] = v
				}
			}
			srcs := make([]string, 0, len(srcSet))
			for s := range srcSet {
				srcs = append(srcs, s)
			}
			sort.Strings(srcs)
			asOf := pop.AsOf
			if comp.AsOf < asOf { // ISO dates: lexical order is chronological
				asOf = comp.AsOf
			}
			metrics = append(metrics, Metric{
				Name:  "people_per_competitor." + category,
				Value: round2(pop.Value / comp.Value),
				// A ratio is already normalised; per-km2 would be meaningless.
				ValuePerLandKm2: nil,
				Track:           TrackDerived,
				Confidence:      weakest([]Confidence{pop.Confidence, comp.Confidence}),
				Sources:         srcs,
				AsOf:            asOf,
				SourceSnapshots: snaps,
				AgreementRatio:  nil,
				Stale:           pop.Stale || comp.Stale,
				// A ratio is only as corroborated as its weaker input, cell for
				// cell. Reporting the population split here would overstate it.
				CellsByConfidence: comp.CellsByConfidence,
				CellsTotal:        comp.CellsTotal,
				CellsNoData:       comp.CellsNoData,
				CellsNonePresent:  comp.CellsNonePresent,
				// A ratio is only as finely measured as its coarsest input: population
				// is a res-8 observation, so this is too.
				NativeRes:       minRes(pop.NativeRes, comp.NativeRes),
				ConfidenceRank:  confidenceRank(weakest([]Confidence{pop.Confidence, comp.Confidence})),
				DirectionOfGood: "higher",
			})
		}
	}

	// CONTEXT VALUES ARE METRICS TOO. The compare screen was hardcoding
	// direction_of_good for built-up ("context") and growth ("higher") in
	// TypeScript — the exact duplication this pass exists to remove. Publishing
	// them as metrics means every row on that screen reads its direction from
	// the response.
	ctxMetric := func(name string, v float64, dir string) Metric {
		return Metric{
			Name: name, Value: round2(v), Track: TrackBuiltEnvironment,
			Confidence: Corroborated, ConfidenceRank: confidenceRank(Corroborated),
			Sources: []string{"ghsl"}, AsOf: "2025-01-01",
			SourceSnapshots: map[string]string{"ghsl": "R2023A"},
			CellsTotal:      inCoverage, CellsByConfidence: map[string]int{"corroborated": inCoverage},
			NativeRes: a.th.Resolutions.Report, DirectionOfGood: dir,
		}
	}
	metrics = append(metrics,
		ctxMetric("builtup_pct", builtUpPct, "context"),
		ctxMetric("builtup_growth_pct", growthPct, "higher"))

	sort.Slice(metrics, func(i, j int) bool { return metrics[i].Name < metrics[j].Name })

	var covRatio *float64
	if covRatioN > 0 {
		v := round2(covRatioSum / float64(covRatioN))
		covRatio = &v
	}

	series, err := a.history.SeriesFor(ring, category)
	if err != nil {
		notes = append(notes, "time series unavailable: "+err.Error())
		series = nil
	}

	lim := a.limits
	lim.Notes = notes

	return &ReportResponse{
		Query: QueryEcho{Lat: lat, Lon: lon, RadiusM: radius, Category: category, KRing: k},
		Context: CatchmentContext{
			LandAreaKm2:      round2(landKm2),
			RawAreaKm2:       round2(rawAreaM2 / 1e6),
			NominalAreaKm2:   round2(math.Pi * float64(radius) * float64(radius) / 1e6),
			LandFractionMean: round2(landFracMean),
			SaturationClass:  satClass,
			SaturationCells:  satCells,
			BuiltUpPct:       round2(builtUpPct),
			BuiltUpGrowthPct: round2(growthPct),
			GrowthIsMaterial: growthPct >= a.th.Saturation.GrowthMaterialPct,
			CoverageRatio:    covRatio,
			DensityDistorted: distorted,
			CellCount:        inCoverage,
			H3Res:            a.th.Resolutions.Report,
			KRing:            k,
			Cells:            cellList,
		},
		Metrics:    metrics,
		TimeSeries: series,
		Limits:     lim,
	}, nil
}

// directionOfGood states which way is better for a metric, because getting it
// backwards silently invalidates everything downstream. It travels with the
// number so a client cannot drift from it.
func directionOfGood(name string) string {
	switch {
	case strings.HasPrefix(name, "business_count."):
		// Competitors. More is worse for someone choosing where to open.
		return "lower"
	case name == "population":
		return "higher"
	case strings.HasPrefix(name, "people_per_competitor."):
		return "higher"
	default:
		// Built-up area and similar describe the ground rather than scoring it.
		return "context"
	}
}

func round2(f float64) float64 {
	if math.IsNaN(f) || math.IsInf(f, 0) {
		return 0
	}
	return math.Round(f*100) / 100
}

// minRes returns the COARSER of two h3 resolutions (smaller number = coarser),
// ignoring zeros for metrics that never recorded one.
func minRes(a, b int) int {
	if a == 0 {
		return b
	}
	if b == 0 {
		return a
	}
	if a < b {
		return a
	}
	return b
}

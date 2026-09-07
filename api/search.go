package main

import (
	"fmt"
	"math"
	"net/http"
	"sort"
	"strconv"
	"strings"

	"github.com/uber/h3-go/v4"
)

// GET /api/search — find cells matching criteria, rather than requiring the
// caller to already know where to look.
//
// NO COMPOSITE SCORE. Rows are ranked by ONE stated metric and the other
// filtered metrics travel alongside. Blending population, competition and
// growth into a single "opportunity" number would hide the weighting and
// pretend to know what matters to this user, and the whole product has
// refused to do that from the start. The sort key is named in the response
// and carries its direction_of_good, so a caller can always say what the
// ranking means.
//
// Runs at the COVERAGE resolution (res-8, 9,938 cells). A full linear scan of
// an in-memory slice needs no index; the whole pass is well under the cost of
// the JSON encoding that follows it.
//
// MISSING DATA IS NEVER ZERO. A cell with no business data at all is excluded
// and counted, so the caller can see the search ran over less than the map.
// A cell that HAS business data but no row for the chosen category holds none
// of them — a genuine zero, and a legitimate result. That distinction is not
// invented here: it is the same rule report.go applies via cellsWithBusiness,
// and search must use it or the two screens would describe one cell in two
// different ways.

// rangeFilter is an optional [min,max] bound. Absent is not zero: a filter the
// caller never set must not silently exclude cells whose value is below zero's
// neighbourhood.
type rangeFilter struct {
	min, max       float64
	hasMin, hasMax bool
}

func (f rangeFilter) active() bool { return f.hasMin || f.hasMax }

func (f rangeFilter) admits(v float64) bool {
	if f.hasMin && v < f.min {
		return false
	}
	if f.hasMax && v > f.max {
		return false
	}
	return true
}

func parseRange(q map[string][]string, base string) (rangeFilter, error) {
	var f rangeFilter
	get := func(k string) string {
		if v, ok := q[k]; ok && len(v) > 0 {
			return strings.TrimSpace(v[0])
		}
		return ""
	}
	if s := get(base + "_min"); s != "" {
		v, err := strconv.ParseFloat(s, 64)
		if err != nil {
			return f, fmt.Errorf("%s_min must be a number", base)
		}
		f.min, f.hasMin = v, true
	}
	if s := get(base + "_max"); s != "" {
		v, err := strconv.ParseFloat(s, 64)
		if err != nil {
			return f, fmt.Errorf("%s_max must be a number", base)
		}
		f.max, f.hasMax = v, true
	}
	if f.hasMin && f.hasMax && f.min > f.max {
		return f, fmt.Errorf("%s_min (%g) is above %s_max (%g)", base, f.min, base, f.max)
	}
	return f, nil
}

// SearchQuery is the parsed request. Every filter is optional and combinable.
type SearchQuery struct {
	Category    string `json:"category,omitempty"`
	Governorate string `json:"governorate,omitempty"`
	Saturation  string `json:"saturation_class,omitempty"`

	Population  rangeFilter `json:"-"`
	Competitors rangeFilter `json:"-"`
	PeoplePer   rangeFilter `json:"-"`
	BuiltUp     rangeFilter `json:"-"`
	Growth      rangeFilter `json:"-"`

	MinConfidence      Confidence `json:"min_confidence,omitempty"`
	ExcludeUninhabited bool       `json:"exclude_uninhabited"`
	ExcludeDistorted   bool       `json:"exclude_density_distorted"`

	Sort  string `json:"sort"`
	Order string `json:"order"`
	Limit int    `json:"limit"`
}

// sortKeys maps a sort name to the metric that carries its value. Sorting is
// only ever by a metric the response actually returns, so the ranking can be
// checked against the column beside it.
var sortKeys = map[string]string{
	"population":               "population",
	"population_per_land_km2":  "population",
	"competitors":              "business_count",
	"competitors_per_land_km2": "business_count",
	"people_per_competitor":    "people_per_competitor",
	"builtup_pct":              "builtup_pct",
	"builtup_growth_pct":       "builtup_growth_pct",
}

var searchCategories = map[string]bool{
	"cafe": true, "restaurant": true, "pharmacy": true, "grocery": true, "gym": true,
}

// SearchRow is one matching cell.
type SearchRow struct {
	H3          string  `json:"h3"`
	Lat         float64 `json:"lat"`
	Lon         float64 `json:"lon"`
	PlaceName   string  `json:"place_name,omitempty"`
	Governorate string  `json:"governorate"`

	SaturationClass string  `json:"saturation_class"`
	LandAreaKm2     float64 `json:"land_area_km2"`
	LandFraction    float64 `json:"land_fraction"`
	DensityDistort  bool    `json:"density_distorted"`
	PopulationStale bool    `json:"population_stale"`

	// Confidence is the WEAKEST-LINK across the metrics that were filtered on,
	// matching how a report describes a catchment.
	Confidence     Confidence `json:"confidence"`
	ConfidenceRank int        `json:"confidence_rank"`

	// Metrics carries every value as a full Metric. There is deliberately no
	// bare float here and no duplicated "sort_value" field: the client reads
	// the ranked number from the metric named in sort.metric, so the ranking
	// and the column can never disagree.
	Metrics []Metric `json:"metrics"`

	sortVal float64
	sortOK  bool
}

// SearchResponse is the whole answer, counts first.
type SearchResponse struct {
	Query  map[string]any `json:"query"`
	Sort   map[string]any `json:"sort"`
	Counts SearchCounts   `json:"counts"`
	Notes  []string       `json:"notes"`
	// EmptyReason is set ONLY when nothing matched. An empty list is a real
	// state with a cause, never a blank panel.
	EmptyReason string      `json:"empty_reason,omitempty"`
	Results     []SearchRow `json:"results"`
	// MatchedH3 is EVERY matching cell id, not just the returned page. The map
	// is the primary view and the shape of the answer is spatial, so painting
	// only the top 100 would draw a different, smaller answer than the one the
	// counts describe. Ids alone are cheap; the full rows are not.
	MatchedH3 []string `json:"matched_h3"`
	AsOf      string   `json:"as_of"`
}

type SearchCounts struct {
	CellsInCoverage int            `json:"cells_in_coverage"`
	Searchable      int            `json:"cells_searchable"`
	Excluded        map[string]int `json:"excluded_for_missing_data"`
	Gated           map[string]int `json:"excluded_by_scope"`
	Matched         int            `json:"matched"`
	Returned        int            `json:"returned"`
	Capped          bool           `json:"capped"`
}

func (a *App) handleAreaSearch(w http.ResponseWriter, r *http.Request) {
	q, err := parseSearchQuery(r, a.th)
	if err != nil {
		httpErr(w, http.StatusBadRequest, err.Error())
		return
	}
	resp, err := a.SearchCells(q)
	if err != nil {
		httpErr(w, http.StatusInternalServerError, err.Error())
		return
	}
	writeJSON(w, resp)
}

func parseSearchQuery(r *http.Request, th *Thresholds) (SearchQuery, error) {
	raw := r.URL.Query()
	var q SearchQuery

	q.Category = strings.ToLower(strings.TrimSpace(raw.Get("category")))
	if q.Category != "" && !searchCategories[q.Category] {
		return q, fmt.Errorf("unknown category %q; known: cafe, restaurant, pharmacy, grocery, gym", q.Category)
	}
	q.Governorate = strings.TrimSpace(raw.Get("governorate"))
	q.Saturation = strings.ToUpper(strings.TrimSpace(raw.Get("saturation")))
	if q.Saturation != "" &&
		q.Saturation != "GREENFIELD" && q.Saturation != "DEVELOPING" && q.Saturation != "SATURATED" {
		return q, fmt.Errorf("saturation must be one of greenfield, developing, saturated")
	}

	var err error
	if q.Population, err = parseRange(raw, "population"); err != nil {
		return q, err
	}
	if q.Competitors, err = parseRange(raw, "competitors"); err != nil {
		return q, err
	}
	if q.PeoplePer, err = parseRange(raw, "people_per_competitor"); err != nil {
		return q, err
	}
	if q.BuiltUp, err = parseRange(raw, "builtup_pct"); err != nil {
		return q, err
	}
	if q.Growth, err = parseRange(raw, "growth_pct"); err != nil {
		return q, err
	}

	switch strings.ToLower(strings.TrimSpace(raw.Get("confidence"))) {
	case "", "any":
		q.MinConfidence = ""
	case "single_source":
		q.MinConfidence = SingleSource
	case "corroborated":
		q.MinConfidence = Corroborated
	default:
		return q, fmt.Errorf("confidence must be any, single_source or corroborated")
	}

	// Both default ON. A campus or barracks cluster makes a cell's density
	// non-comparable, and the coverage polygon includes desert and farmland.
	q.ExcludeUninhabited = raw.Get("include_uninhabited") != "1"
	q.ExcludeDistorted = raw.Get("include_distorted") != "1"

	q.Sort = strings.ToLower(strings.TrimSpace(raw.Get("sort")))
	if q.Sort == "" {
		q.Sort = "population"
	}
	if _, ok := sortKeys[q.Sort]; !ok {
		return q, fmt.Errorf("unknown sort %q", q.Sort)
	}
	// Competitor and people-per-competitor sorts need a category to be about
	// anything. Failing here beats ranking every cell by a metric that does
	// not exist for it.
	if (q.Sort == "competitors" || q.Sort == "competitors_per_land_km2" ||
		q.Sort == "people_per_competitor") && q.Category == "" {
		return q, fmt.Errorf("sort=%s requires a category", q.Sort)
	}
	q.Order = strings.ToLower(strings.TrimSpace(raw.Get("order")))
	if q.Order == "" {
		// Default to the direction that puts the BETTER cell first, read from
		// the metric's own direction_of_good rather than a guess per sort key.
		if directionOfGood(sortMetricName(q.Sort, q.Category)) == "lower" {
			q.Order = "asc"
		} else {
			q.Order = "desc"
		}
	}
	if q.Order != "asc" && q.Order != "desc" {
		return q, fmt.Errorf("order must be asc or desc")
	}

	q.Limit = 100
	if s := raw.Get("limit"); s != "" {
		n, err := strconv.Atoi(s)
		if err != nil || n < 1 {
			return q, fmt.Errorf("limit must be a positive integer")
		}
		// CLAMP, do not ignore — the same rule /places follows. A caller asking
		// for 5000 gets 500 and is told so by counts.capped.
		if n > 500 {
			n = 500
		}
		q.Limit = n
	}
	return q, nil
}

// sortMetricName resolves a sort key to the metric name it ranks by.
func sortMetricName(sortKey, category string) string {
	base := sortKeys[sortKey]
	switch base {
	case "business_count", "people_per_competitor":
		if category == "" {
			return base
		}
		return base + "." + category
	default:
		return base
	}
}

// SearchCells scans the coverage grid and returns matching cells.
func (a *App) SearchCells(q SearchQuery) (*SearchResponse, error) {
	res := a.th.Resolutions.Coverage
	cells := a.store.CellsAt(res)
	if len(cells) == 0 {
		return nil, fmt.Errorf("no cells loaded at res-%d", res)
	}

	catMetric := ""
	if q.Category != "" {
		catMetric = "business_count." + q.Category
	}
	sortMetric := sortMetricName(q.Sort, q.Category)
	perArea := strings.HasSuffix(q.Sort, "_per_land_km2")

	gated := map[string]int{}
	excluded := map[string]int{}
	rows := make([]SearchRow, 0, 256)

	// Measured during the scan rather than hardcoded: what share of observed
	// businesses carry ANY category. It decides how much weight a "0 cafes
	// here" reading can bear, and a constant would drift from the data.
	var sumTotal, sumCategorised float64
	searchable := 0

	for _, c := range cells {
		// ---- scope gates. These narrow WHERE we looked, not what we know.
		if q.Governorate != "" && !strings.EqualFold(c.Governorate, q.Governorate) {
			gated["outside_region"]++
			continue
		}
		if q.ExcludeDistorted && c.DensityDistort {
			gated["density_distorted"]++
			continue
		}
		if q.Saturation != "" && c.SaturationClass != q.Saturation {
			gated["other_saturation_class"]++
			continue
		}

		recs := a.store.MetricsFor(res, c.H3Index)
		byName := make(map[string]*MetricRecord, len(recs))
		hasBusiness := false
		for _, m := range recs {
			byName[m.Metric] = m
			if m.Track == TrackBusiness {
				hasBusiness = true
				if m.Metric == "business_count.total" {
					sumTotal += m.Value
				} else {
					sumCategorised += m.Value
				}
			}
		}
		pop := byName["population"]

		// INHABITED REQUIRES BOTH. Population alone admits Delta farmland;
		// built-up alone admits airports and industrial land. The rule and its
		// reason live in config/thresholds.json.
		if q.ExcludeUninhabited {
			popV := 0.0
			if pop != nil {
				popV = pop.Value
			}
			if popV < a.th.Inhabited.PopulationMin || c.BuiltUpPct < a.th.Inhabited.BuiltupPctMin {
				gated["uninhabited"]++
				continue
			}
		}

		// ---- data gates. These are gaps in what we KNOW and are reported.
		if q.Category != "" {
			if _, ok := byName[catMetric]; !ok && !hasBusiness {
				excluded["no_business_data"]++
				continue
			}
		}
		if pop == nil && (q.Population.active() || q.PeoplePer.active() ||
			q.Sort == "population" || q.Sort == "population_per_land_km2" ||
			q.Sort == "people_per_competitor") {
			excluded["no_population_data"]++
			continue
		}
		searchable++

		landKm2 := c.LandAreaM2 / 1e6
		perAreaOK := c.LandFraction >= a.th.LandFractionFloor.Value && landKm2 > 0

		var metrics []Metric
		var confs []Confidence

		if pop != nil {
			m := a.searchMetric(pop, landKm2, perAreaOK, c)
			metrics = append(metrics, m)
			if q.Population.active() {
				v := pop.Value
				if perArea && q.Sort == "population_per_land_km2" && m.ValuePerLandKm2 != nil {
					v = *m.ValuePerLandKm2
				}
				if !q.Population.admits(v) {
					continue
				}
				confs = append(confs, pop.Confidence)
			}
		}

		// ---- competitors
		var compVal float64
		compKnown := false
		var compConf Confidence
		if q.Category != "" {
			if rec, ok := byName[catMetric]; ok {
				m := a.searchMetric(rec, landKm2, perAreaOK, c)
				metrics = append(metrics, m)
				compVal, compKnown, compConf = rec.Value, true, rec.Confidence
			} else {
				// GENUINE ZERO: business data exists for this cell, none of it
				// in this category. Same rule report.go uses. Confidence rests
				// on the business observation that establishes the zero.
				zc := SingleSource
				if t, ok := byName["business_count.total"]; ok {
					zc = t.Confidence
				}
				metrics = append(metrics, a.zeroMetric(catMetric, zc, byName, c, perAreaOK))
				compVal, compKnown, compConf = 0, true, zc
			}
			if q.Competitors.active() && !q.Competitors.admits(compVal) {
				continue
			}
			confs = append(confs, compConf)
		}

		// ---- people per competitor. Derived, and UNDEFINED at zero supply.
		if q.Category != "" && pop != nil && compKnown {
			if compVal > 0 {
				ppc := pop.Value / compVal
				metrics = append(metrics, Metric{
					Name: "people_per_competitor." + q.Category, Value: round2(ppc),
					Track: TrackDerived, Confidence: weakest([]Confidence{pop.Confidence, compConf}),
					ConfidenceRank:  confidenceRank(weakest([]Confidence{pop.Confidence, compConf})),
					Sources:         []string{"kontur", "overture", "fsq"},
					AsOf:            olderOf(pop.AsOf, asOfOr(byName[catMetric], pop.AsOf)),
					SourceSnapshots: map[string]string{},
					CellsTotal:      1,
					CellsByConfidence: map[string]int{
						string(weakest([]Confidence{pop.Confidence, compConf})): 1},
					NativeRes: minRes(pop.NativeRes, 8), DirectionOfGood: "higher",
					Stale: c.PopulationStale,
				})
				if q.PeoplePer.active() && !q.PeoplePer.admits(ppc) {
					continue
				}
			} else if q.PeoplePer.active() || q.Sort == "people_per_competitor" {
				// No supply means the ratio has no denominator. Reporting it as
				// a huge number would rank empty desert above a real gap.
				excluded["people_per_competitor_undefined_no_competitors"]++
				continue
			}
		}

		// ---- built environment context
		metrics = append(metrics, ctxSearchMetric("builtup_pct", c.BuiltUpPct, "context", a.th))
		if !math.IsNaN(c.GrowthPct) {
			metrics = append(metrics, ctxSearchMetric("builtup_growth_pct", c.GrowthPct, "higher", a.th))
			// THE BASE TRAVELS WITH THE PERCENTAGE. A cell that went from 1% to
			// 8.6% built reads as +769%, and ranked on that alone near-empty
			// desert outranks real development. Publishing the 2015 share lets
			// the reader see what the growth grew FROM, which is the whole
			// difference between a boom and a rounding artifact.
			if base, ok := builtUp2015Pct(c); ok {
				metrics = append(metrics, ctxSearchMetric("builtup_pct_2015", base, "context", a.th))
			}
		}
		if q.BuiltUp.active() && !q.BuiltUp.admits(c.BuiltUpPct) {
			continue
		}
		if q.Growth.active() {
			if math.IsNaN(c.GrowthPct) || !q.Growth.admits(c.GrowthPct) {
				continue
			}
		}

		// ---- confidence gate, on the metric the caller is actually asking about
		rowConf := weakest(confs)
		if len(confs) == 0 {
			rowConf = Corroborated
			if pop != nil {
				rowConf = pop.Confidence
			}
		}
		if q.MinConfidence != "" && confidenceRank(rowConf) < confidenceRank(q.MinConfidence) {
			continue
		}

		// ---- sort value, read from the metric that will be displayed
		var sv float64
		svOK := false
		for i := range metrics {
			if metrics[i].Name != sortMetric {
				continue
			}
			if perArea {
				if metrics[i].ValuePerLandKm2 != nil {
					sv, svOK = *metrics[i].ValuePerLandKm2, true
				}
			} else {
				sv, svOK = metrics[i].Value, true
			}
			break
		}
		if !svOK {
			// Cannot rank a row by a number it does not have. Withheld, not
			// defaulted to zero, which would bury it at one end of the list.
			excluded["no_value_for_sort_metric"]++
			continue
		}

		ll, err := h3.Cell(c.H3Index).LatLng()
		if err != nil {
			return nil, fmt.Errorf("h3 cell %x: %w", c.H3Index, err)
		}
		rows = append(rows, SearchRow{
			H3: h3.Cell(c.H3Index).String(), Lat: round5(ll.Lat), Lon: round5(ll.Lng),
			PlaceName:   a.geo.CachedName(ll.Lat, ll.Lng),
			Governorate: c.Governorate, SaturationClass: c.SaturationClass,
			LandAreaKm2: round2(landKm2), LandFraction: round2(c.LandFraction),
			DensityDistort: c.DensityDistort, PopulationStale: c.PopulationStale,
			Confidence: rowConf, ConfidenceRank: confidenceRank(rowConf),
			Metrics: metrics,
			sortVal: sv, sortOK: true,
		})
	}

	sort.SliceStable(rows, func(i, j int) bool {
		if q.Order == "asc" {
			return rows[i].sortVal < rows[j].sortVal
		}
		return rows[i].sortVal > rows[j].sortVal
	})

	// POPULATION SATURATES UPSTREAM. Kontur's own data has a ceiling: hundreds
	// of cells across Egypt pile up within a whisker of a single maximum value,
	// while the median cell holds two orders of magnitude fewer people. The
	// pipeline carries that through faithfully, which means the top of a
	// population sort is a TIE, not a sequence — the one-person decrements
	// between those cells are quantisation noise and ranking on them invents an
	// order the data does not contain. Measured here rather than hardcoded, so
	// it self-corrects when the vintage changes.
	plateauN, plateauAt := populationPlateau(rows)
	// Counted over the FULL matched set, before the cap. Counting the returned
	// page instead would report "2 of 272" from a sample of three.
	tinyBase := tinyBaseGrowth(rows)

	matched := len(rows)
	allH3 := make([]string, 0, matched)
	for _, r := range rows {
		allH3 = append(allH3, r.H3)
	}
	capped := matched > q.Limit
	if capped {
		rows = rows[:q.Limit]
	}

	resp := &SearchResponse{
		Query: map[string]any{
			"category": q.Category, "governorate": q.Governorate,
			"saturation": q.Saturation, "confidence": string(q.MinConfidence),
			"exclude_uninhabited":       q.ExcludeUninhabited,
			"exclude_density_distorted": q.ExcludeDistorted,
			"h3_res":                    res,
		},
		Sort: map[string]any{
			"key": q.Sort, "metric": sortMetric, "order": q.Order,
			"direction_of_good": directionOfGood(sortMetric),
		},
		Counts: SearchCounts{
			CellsInCoverage: len(cells), Searchable: searchable,
			Excluded: excluded, Gated: gated,
			Matched: matched, Returned: len(rows), Capped: capped,
		},
		Results:   rows,
		MatchedH3: allH3,
		AsOf:      a.store.PipelineVersion(),
	}
	resp.Notes = searchNotes(q, resp.Counts, len(cells), sumTotal, sumCategorised)
	if q.Sort == "builtup_growth_pct" {
		if n := tinyBase; n > 0 {
			resp.Notes = append(resp.Notes, fmt.Sprintf(
				"%d of the %d matched cells grew from a 2015 footprint smaller than 1%% of the "+
					"cell, so their growth percentage is large because the base was near zero. "+
					"builtup_pct_2015 is published beside it — read the two together, and "+
					"prefer sorting by built-up %% if you want places that are already built.",
				n, matched))
		}
	}
	if plateauN >= 10 && (q.Sort == "population" || q.Sort == "population_per_land_km2" ||
		q.Sort == "people_per_competitor") {
		resp.Notes = append(resp.Notes, fmt.Sprintf(
			"%d matched cells sit within 0.5%% of the highest population value in the data "+
				"(%.0f). That ceiling is in the upstream Kontur figures, not in this pipeline, "+
				"so the ordering among those cells is quantisation noise rather than a real "+
				"ranking — read the top of this list as a tie.", plateauN, plateauAt))
	}
	if matched == 0 {
		resp.EmptyReason = emptyReason(q, resp.Counts)
	}
	return resp, nil
}

// searchMetric wraps one stored record as a full Metric for a single cell.
func (a *App) searchMetric(m *MetricRecord, landKm2 float64, perAreaOK bool, c *CellRecord) Metric {
	var perKm2 *float64
	reason := ""
	if perAreaOK {
		v := round2(m.Value / landKm2)
		perKm2 = &v
	} else {
		reason = fmt.Sprintf(
			"withheld: this cell is %.0f%% land, below the %.0f%% floor for a per-area "+
				"figure. Dividing by a near-zero land area produces densities that are "+
				"arithmetic, not geography.",
			100*c.LandFraction, 100*a.th.LandFractionFloor.Value)
	}
	srcs, counts := recordSources(m)
	var ratio *float64
	if !math.IsNaN(m.AgreementRatio) {
		r := round2(m.AgreementRatio)
		ratio = &r
	}
	return Metric{
		Name: m.Metric, Value: m.Value,
		ValuePerLandKm2: perKm2, PerLandKm2Reason: reason,
		Track: m.Track, Confidence: m.Confidence,
		ConfidenceRank: confidenceRank(m.Confidence),
		Sources:        srcs, SourceCounts: counts,
		AsOf: m.AsOf, SourceSnapshots: m.SourceSnapshots,
		AgreementRatio: ratio,
		Stale:          m.Metric == "population" && c.PopulationStale,
		CellsTotal:     1, CellsByConfidence: map[string]int{string(m.Confidence): 1},
		NativeRes: m.NativeRes, DirectionOfGood: directionOfGood(m.Metric),
	}
}

// zeroMetric is a MEASURED zero: the cell carries business data and none of it
// falls in this category. CellsNonePresent distinguishes it from a gap.
func (a *App) zeroMetric(name string, conf Confidence, byName map[string]*MetricRecord,
	c *CellRecord, perAreaOK bool) Metric {
	asOf := ""
	snaps := map[string]string{}
	var srcs []string
	if t, ok := byName["business_count.total"]; ok {
		asOf, snaps = t.AsOf, t.SourceSnapshots
		srcs, _ = recordSources(t)
	}
	zero := 0.0
	var perKm2 *float64
	if perAreaOK {
		perKm2 = &zero
	}
	return Metric{
		Name: name, Value: 0, ValuePerLandKm2: perKm2,
		Track: TrackBusiness, Confidence: conf, ConfidenceRank: confidenceRank(conf),
		Sources: srcs, AsOf: asOf, SourceSnapshots: snaps,
		CellsTotal: 1, CellsByConfidence: map[string]int{string(conf): 1},
		CellsNonePresent: 1,
		NativeRes:        8, DirectionOfGood: directionOfGood(name),
	}
}

func ctxSearchMetric(name string, v float64, dir string, th *Thresholds) Metric {
	return Metric{
		Name: name, Value: round2(v), Track: TrackBuiltEnvironment,
		Confidence: Corroborated, ConfidenceRank: confidenceRank(Corroborated),
		Sources: []string{"ghsl"}, AsOf: "2025-01-01",
		SourceSnapshots: map[string]string{"ghsl": "R2023A"},
		CellsTotal:      1, CellsByConfidence: map[string]int{"corroborated": 1},
		NativeRes: th.Resolutions.Coverage, DirectionOfGood: dir,
	}
}

func recordSources(m *MetricRecord) ([]string, map[string]float64) {
	srcs := []string{}
	counts := map[string]float64{}
	if m.OvertureCount > 0 {
		srcs = append(srcs, "overture")
		counts["overture"] = float64(m.OvertureCount)
	}
	if m.FSQCount > 0 {
		srcs = append(srcs, "fsq")
		counts["fsq"] = float64(m.FSQCount)
	}
	for k := range m.SourceSnapshots {
		found := false
		for _, s := range srcs {
			if s == k {
				found = true
			}
		}
		if !found {
			srcs = append(srcs, k)
		}
	}
	sort.Strings(srcs)
	if len(counts) == 0 {
		counts = nil
	}
	return srcs, counts
}

func asOfOr(m *MetricRecord, fallback string) string {
	if m == nil {
		return fallback
	}
	return m.AsOf
}

// olderOf returns the EARLIER vintage. A ratio is only as current as its
// stalest input.
func olderOf(a, b string) string {
	if a == "" {
		return b
	}
	if b == "" {
		return a
	}
	if a < b {
		return a
	}
	return b
}

func round5(f float64) float64 {
	if math.IsNaN(f) || math.IsInf(f, 0) {
		return 0
	}
	return math.Round(f*1e5) / 1e5
}

// searchNotes states what the search could NOT see. A result list that looks
// complete while resting on a fifth of the map is the failure mode here.
func searchNotes(q SearchQuery, c SearchCounts, total int, sumTotal, sumCat float64) []string {
	var notes []string
	if n := c.Excluded["no_business_data"]; n > 0 && q.Category != "" {
		notes = append(notes, fmt.Sprintf(
			"%d of %d cells hold no business data at all and were excluded — not counted as "+
				"zero %s. The search ran over %.0f%% of the coverage grid.",
			n, total, q.Category, 100*float64(c.Searchable)/float64(total)))
	}
	if n := c.Excluded["no_population_data"]; n > 0 {
		notes = append(notes, fmt.Sprintf(
			"%d cells were excluded for having no population figure.", n))
	}
	if n := c.Excluded["people_per_competitor_undefined_no_competitors"]; n > 0 {
		notes = append(notes, fmt.Sprintf(
			"%d cells have zero %s, so people-per-outlet has no denominator there and they "+
				"cannot be ranked by it. Sort by competitors to see them.", n, q.Category))
	}
	if q.Category != "" && sumTotal > 0 {
		pct := 100 * sumCat / sumTotal
		notes = append(notes, fmt.Sprintf(
			"%.1f%% of observed businesses carry a category. A cell reading zero %s may hold "+
				"uncategorised businesses, so treat a zero as 'none recorded', not 'none there'.",
			pct, q.Category))
	}
	if q.MinConfidence == Corroborated {
		notes = append(notes,
			"Corroborated requires two sources to agree within tolerance, and the sources are "+
				"not independent — Foursquare feeds Overture. Few cells qualify, so a short "+
				"list here is expected rather than a fault.")
	}
	if c.Capped {
		notes = append(notes, fmt.Sprintf(
			"%d cells matched; showing the top %d by %s.", c.Matched, c.Returned, q.Sort))
	}
	if q.ExcludeDistorted && c.Gated["density_distorted"] > 0 {
		notes = append(notes, fmt.Sprintf(
			"%d cells were set aside as density-distorted (a campus or barracks cluster makes "+
				"per-person figures non-comparable).", c.Gated["density_distorted"]))
	}
	return notes
}

func emptyReason(q SearchQuery, c SearchCounts) string {
	if c.Searchable == 0 {
		if q.Category != "" && c.Excluded["no_business_data"] > 0 {
			return fmt.Sprintf(
				"No cell in this scope has business data for %s. Try a wider region, or clear "+
					"the category to search on population and built-up area alone.", q.Category)
		}
		return "Nothing was left to search after the scope filters. Try a wider region or " +
			"include uninhabited cells."
	}
	var active []string
	if q.Population.active() {
		active = append(active, "population")
	}
	if q.Competitors.active() {
		active = append(active, "competitors")
	}
	if q.PeoplePer.active() {
		active = append(active, "people per outlet")
	}
	if q.BuiltUp.active() {
		active = append(active, "built-up %")
	}
	if q.Growth.active() {
		active = append(active, "growth")
	}
	if q.MinConfidence == Corroborated {
		active = append(active, "corroborated only")
	}
	if len(active) == 0 {
		return fmt.Sprintf("%d cells were searchable but none matched.", c.Searchable)
	}
	return fmt.Sprintf(
		"%d cells were searchable but none satisfy all of: %s. Try widening one range — "+
			"the ranges combine, so a narrow population band and a narrow competitor band "+
			"can exclude everything between them.",
		c.Searchable, strings.Join(active, ", "))
}

// populationPlateau counts matched cells bunched at the top of the population
// range. It returns the count and the maximum it clusters around. Deriving the
// maximum from the data rather than naming a constant means this keeps working
// when the population vintage is replaced.
func populationPlateau(rows []SearchRow) (int, float64) {
	max := 0.0
	for _, r := range rows {
		for _, m := range r.Metrics {
			if m.Name == "population" && m.Value > max {
				max = m.Value
			}
		}
	}
	if max <= 0 {
		return 0, 0
	}
	n := 0
	for _, r := range rows {
		for _, m := range r.Metrics {
			if m.Name == "population" && m.Value >= max*0.995 {
				n++
				break
			}
		}
	}
	return n, max
}

// builtUp2015Pct recovers the 2015 built-up share of the cell from the two
// figures already loaded: today's share and the growth since. It is exact
// arithmetic on the same GHSL measurements, not a new estimate.
func builtUp2015Pct(c *CellRecord) (float64, bool) {
	if math.IsNaN(c.GrowthPct) || math.IsNaN(c.BuiltUpPct) {
		return 0, false
	}
	denom := 1 + c.GrowthPct/100
	if denom <= 0 {
		return 0, false
	}
	return c.BuiltUpPct / denom, true
}

// tinyBaseGrowth counts rows whose 2015 footprint was under 1% of the cell.
// The cutoff is stated in the note it feeds rather than hidden here, because a
// threshold that shapes a ranking and is never shown is a rule the reader
// cannot check.
func tinyBaseGrowth(rows []SearchRow) int {
	n := 0
	for _, r := range rows {
		for _, m := range r.Metrics {
			if m.Name == "builtup_pct_2015" && m.Value < 1.0 {
				n++
				break
			}
		}
	}
	return n
}

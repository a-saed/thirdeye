package main

// PROVENANCE IS STRUCTURALLY REQUIRED.
//
// Every number this API returns is wrapped in Metric, which cannot be
// constructed without Confidence, Sources and AsOf. There is deliberately no
// path that returns a bare float64: the study that produced this data found
// that 84-86% of cells have business data from a single source, that the two
// "independent" sources are not actually independent (Foursquare feeds
// Overture), and that population is a 2023 vintage served as present-day.
// A caller who receives 12.0 without that context will misread it. So the
// type system makes the context non-optional rather than relying on
// discipline.
//
// See research/VERDICT.md for the measurements behind each field.

// Confidence is the per-metric, per-cell confidence level. It is never a
// property of a cell alone: one cell legitimately carries corroborated
// population, corroborated built-environment and single-source business at
// the same time.
type Confidence string

const (
	// Corroborated: 2+ sources WITHIN THE SAME TRACK agree, counts within the
	// configured tolerance (1.5x). NOT proof of independence - see
	// IndependenceCaveat.
	Corroborated Confidence = "corroborated"
	// SingleSource: only one source covers this metric in this cell.
	SingleSource Confidence = "single_source"
	// Unavailable: no source covers it. Distinct from a value of zero.
	Unavailable Confidence = "unavailable"
)

// Track groups metrics that may be compared with each other. Cross-track
// agreement is meaningless and must never be used as corroboration: a
// built-out district can have flat construction and active business churn
// simultaneously.
type Track string

const (
	TrackBusiness         Track = "business"
	TrackBuiltEnvironment Track = "built_environment"
	TrackPopulation       Track = "population"
	// TrackDerived is for values computed FROM other tracks, such as
	// people-per-competitor. Combining tracks is legitimate for a RATIO and
	// never for corroboration: dividing population by competitor count is a
	// demand-per-supply figure, not a claim that two sources agree.
	TrackDerived Track = "derived"
)

// Metric is the only way a number leaves this API. All fields are required.
type Metric struct {
	Name string `json:"metric"`
	// Value is the raw catchment total (sum over cells in the k-ring).
	Value float64 `json:"value"`
	// ValuePerLandKm2 is the number callers should actually use. Normalised by
	// LAND area, not cell area: Alexandria's Corniche cells are ~half sea
	// (land_fraction 0.52 measured at Stanley), so a raw-area denominator
	// scores prime waterfront as "low competition".
	// NULL when the catchment is mostly water: see MinLandFractionForDensity.
	ValuePerLandKm2 *float64 `json:"value_per_land_km2"`
	// PerLandKm2Reason explains a null ValuePerLandKm2.
	PerLandKm2Reason string `json:"value_per_land_km2_unavailable_reason,omitempty"`
	Track            Track  `json:"track"`

	Confidence Confidence `json:"confidence"`
	// Sources contributing to this metric in this catchment.
	Sources []string `json:"contributing_sources"`
	// AsOf is what point in time the value DESCRIBES, not when it was fetched.
	// Population is 2023-11-01 even when served in 2026.
	AsOf string `json:"as_of"`
	// SourceSnapshots maps source -> upstream immutable snapshot id.
	SourceSnapshots map[string]string `json:"source_snapshots"`

	// SourceCounts is each source's own contribution to Value. Published so a
	// client can show "4 of 12 listed by Overture" instead of printing 12 in
	// one place and 4 in another and leaving the reader to work out that one is
	// a subset of the other.
	SourceCounts map[string]float64 `json:"source_counts,omitempty"`

	// AgreementRatio is min/max of the two source counts where both exist
	// (nil when only one source). The median across the city is ~0.50, i.e.
	// the two sources typically disagree by 2x. Exposed so callers can see
	// how weak "corroborated" actually is.
	AgreementRatio *float64 `json:"agreement_ratio"`

	// Stale marks values whose vintage is materially older than now in a cell
	// with measured construction since. Set for population in cells with
	// >=50% GHSL built-up growth 2015->2025 covering >=5% of cell land.
	Stale bool `json:"stale"`

	// CellsByConfidence is how many member cells fall in each confidence class,
	// and CellsTotal how many contributed at all. Confidence above is the
	// WEAKEST of these (one single-source cell makes the total single-source),
	// which is correct but reads as a contradiction next to a two-source list:
	// "single source" beside "fsq, overture" looks like a bug unless the split
	// is shown. It is not a bug; it is the weakest-link rule, and this field
	// makes it legible.
	CellsByConfidence map[string]int `json:"cells_by_confidence"`
	// CellsTotal is the CATCHMENT's cell count, not the number of cells that
	// happened to carry a row. Those differ, and reporting the latter made a
	// 7-cell catchment say "3 of 6 cells" beside a header saying 7.
	CellsTotal int `json:"cells_total"`
	// CellsNoData: in the catchment, but no source covers this metric there.
	CellsNoData int `json:"cells_no_data"`
	// CellsNonePresent: covered by a source, but holding none of this thing.
	// A genuine zero, which is NOT the same as no data and must not be shown
	// as a gap.
	CellsNonePresent int `json:"cells_none_present"`

	// NativeRes is the h3 resolution the value was MEASURED at. When it is
	// coarser than the report's own resolution the number was apportioned, not
	// observed: Kontur population is native res-8, spread across res-9 children
	// by land area. A caller must be able to say "estimated for this area from
	// a coarser measurement" rather than implying a reading at this scale.
	NativeRes int `json:"native_res"`

	// ConfidenceRank is the weakest-link ORDERING as a number (2 corroborated,
	// 1 single source, 0 none). Published so a client can tell which of two
	// metrics rests on weaker evidence without redeclaring the ordering — the
	// frontend had its own copy of that map, and an ordering is a rule.
	ConfidenceRank int `json:"confidence_rank"`

	// DirectionOfGood states which way is better: "higher", "lower", or
	// "context" for a value that is neither. Getting this backwards silently
	// invalidates everything downstream - more population is good, more
	// competitors is bad - so it travels WITH the number rather than living in
	// a UI lookup table that can drift from the API.
	DirectionOfGood string `json:"direction_of_good"`
}

// PointStatus marks how a history point should be read.
type PointStatus string

const (
	// PointOK: an ordinary observation.
	PointOK PointStatus = "ok"
	// PointArtifactSuspected: a >=40% release-over-release jump that then held
	// flat for >=3 releases - the bulk-import signature. The value is NOT
	// removed or smoothed; it is flagged so the caller decides.
	PointArtifactSuspected PointStatus = "artifact_suspected"
	// PointGap: a snapshot known to be missing. Value is meaningless and must
	// not be plotted as zero or as a decline.
	PointGap PointStatus = "gap"
)

// TimeSeriesPoint is one observation in a metric's history.
type TimeSeriesPoint struct {
	AsOf       string      `json:"as_of"`
	SnapshotID string      `json:"snapshot_id"`
	Value      float64     `json:"value"`
	Confidence Confidence  `json:"confidence"`
	Status     PointStatus `json:"status"`
}

// CorrectionStatus is a REQUIRED field on every series. It is never inferred
// from whether SeriesCorrected is null: null previously meant both "no
// correction needed, raw is fine" and "correction withheld as unplottable",
// which a caller doing `if (series_corrected)` would read identically — even
// though in one case raw is trustworthy and in the other it contains a known
// artifact.
type CorrectionStatus string

const (
	// CorrectionNotNeeded: no artifact detected in the aggregated series.
	// series_raw is trustworthy as-is.
	CorrectionNotNeeded CorrectionStatus = "not_needed"
	// CorrectionApplied: an artifact was detected and series_corrected holds
	// the post-artifact baseline.
	CorrectionApplied CorrectionStatus = "applied"
	// CorrectionWithheldTooShort: an artifact WAS detected, but correcting
	// would leave too few points to plot honestly. series_raw therefore
	// CONTAINS AN UNCORRECTED ARTIFACT. The reason string is mandatory here.
	CorrectionWithheldTooShort CorrectionStatus = "withheld_too_short"
)

// ExcludedPoint records a point dropped from the corrected series and why.
type ExcludedPoint struct {
	SnapshotID string  `json:"snapshot_id"`
	AsOf       string  `json:"as_of"`
	Value      float64 `json:"value"`
	Reason     string  `json:"reason"`
}

// TimeSeries is returned WHOLE, never one point per request. The UI scrubber
// must not need a round trip per year.
//
// BOTH SERIES ARE RETURNED. Raw is every point as measured. Corrected drops
// everything up to and including the last artifact and restarts from the
// post-artifact baseline - the method that turned Imbaba's headline +78.5%
// into -4.0%. Neither is authoritative on its own: raw overstates growth
// where an import happened, corrected discards real history where the
// detector fired on noise. The API returns both and names them, rather than
// picking for the caller.
type TimeSeries struct {
	Metric string `json:"metric"`
	Track  Track  `json:"track"`

	SeriesRaw []TimeSeriesPoint `json:"series_raw"`
	// SeriesCorrected is NULL when no correction was needed, or when the
	// correction would leave too few points to plot honestly (see
	// CorrectedUnavailable).
	SeriesCorrected []TimeSeriesPoint `json:"series_corrected"`
	Excluded        []ExcludedPoint   `json:"excluded_from_corrected"`
	// CorrectionStatus is REQUIRED and always set. See CorrectionStatus docs.
	CorrectionStatus CorrectionStatus `json:"correction_status"`
	// CorrectedUnavailable explains a null SeriesCorrected. MANDATORY when
	// CorrectionStatus is withheld_too_short, and must state that the raw
	// series contains an uncorrected artifact.
	CorrectedUnavailable string `json:"series_corrected_unavailable_reason,omitempty"`

	// ArtifactCount is how many points in THIS aggregated series carry
	// artifact_suspected.
	ArtifactCount int `json:"artifact_suspected_count"`
	// MemberCellsWithArtifacts / MemberCellsTotal are ADVISORY ONLY. A member
	// cell's import step may be invisible in the aggregate; it does not trigger
	// truncation. Surfaced so a caller can see underlying churn the aggregate
	// smooths over.
	MemberCellsWithArtifacts int `json:"member_cells_with_artifacts"`
	MemberCellsTotal         int `json:"member_cells_total"`
	// DivergenceNote is set when raw and corrected imply materially different
	// growth for this catchment, so a consumer cannot miss it.
	DivergenceNote string `json:"divergence_note,omitempty"`
	// GrowthPctRaw / GrowthPctCorrected are first-to-last percent change for
	// each series, for direct comparison.
	GrowthPctRaw       *float64 `json:"growth_pct_raw"`
	GrowthPctCorrected *float64 `json:"growth_pct_corrected"`

	// GapNote documents known discontinuities so a gap is not read as a real
	// decline. Overture release 2026-06-17.0 is permanently lost.
	GapNote string `json:"gap_note,omitempty"`

	// Sources is which sources this SERIES is built from. It is frequently a
	// SUBSET of the sources behind the headline Metric of the same name, and
	// that difference is not cosmetic: the archive holds Overture snapshots
	// only, because Foursquare publishes no historical releases. So a
	// catchment can legitimately report 65 cafes today and a series whose
	// latest point is 32 - the first counts two sources, the second counts
	// one. Publishing both under a bare metric name made them look like the
	// same quantity disagreeing with itself.
	Sources []string `json:"series_sources"`
	// ComparableToLatest is false when Sources is narrower than the metric's,
	// i.e. the series' last point must NOT be read as the headline value.
	ComparableToLatest bool `json:"comparable_to_latest_metric"`
	// ScopeNote spells that out in words, for direct display.
	ScopeNote string `json:"scope_note,omitempty"`
}

// CatchmentContext describes the ground the catchment sits on. Without it the
// metrics above are uninterpretable.
type CatchmentContext struct {
	// LandAreaKm2 is the habitable land in the catchment, after removing sea
	// and water. The denominator for every per-area figure.
	LandAreaKm2 float64 `json:"land_area_km2"`
	// RawAreaKm2 is the geometric catchment area. Shown only so callers can
	// see how much was water.
	RawAreaKm2 float64 `json:"raw_area_km2"`
	// NominalAreaKm2 is the area of the circle the caller ASKED for. The
	// catchment is a hexagon ring, so it can never match exactly; publishing
	// both makes the approximation visible instead of implied.
	NominalAreaKm2   float64 `json:"nominal_area_km2"`
	LandFractionMean float64 `json:"land_fraction_mean"`

	// SaturationClass: GREENFIELD <10% built-up, DEVELOPING 10-40%,
	// SATURATED >=40%. In a SATURATED catchment a flat built-environment
	// signal is EXPECTED and means "no new construction", NOT "no commercial
	// change".
	SaturationClass string `json:"saturation_class"`
	// SaturationCells is the per-class spread across member cells. The headline
	// class is computed from the catchment's own built-up share, NOT from the
	// worst cell — this shows how mixed the ground actually is.
	SaturationCells map[string]int `json:"saturation_cells"`
	BuiltUpPct      float64        `json:"builtup_pct"`
	// GrowthIsMaterial applies the threshold so the client does not. The
	// frontend compared builtup_growth_pct against a hardcoded 5, which is a
	// rule living in two languages.
	GrowthIsMaterial bool `json:"growth_is_material"`
	// BuiltUpGrowthPct is measured GHSL built-up growth 2015->2025. The study
	// found the growth signal fires ONLY where there is room to build: a
	// saturated district reads flat because it is built out, which means "no
	// new construction", never "no commercial change".
	BuiltUpGrowthPct float64 `json:"builtup_growth_pct"`
	// CoverageRatio = Open Buildings presence / GHSL built-up. Below ~0.9
	// indicates villa/garden fabric; at or above ~1.0 wall-to-wall density.
	CoverageRatio *float64 `json:"coverage_ratio"`

	// DensityDistorted is set when any cell in the catchment holds >=20
	// non-storefront records (campus buildings, offices). Those records are
	// excluded from counts, but such a cell was never comparable to a normal
	// one.
	DensityDistorted bool `json:"density_distorted"`

	CellCount int `json:"cell_count"`
	H3Res     int `json:"h3_res"`
	// KRing is the ring size actually used. Exposed so a client can offer the
	// DISCRETE steps the grid supports instead of a continuous radius: cells
	// are ~0.105 km2, so a slider moves nothing for 200 m and then jumps from
	// 7 cells to 19. Honest controls match the resolution of the data.
	KRing int `json:"k_ring"`
	// Cells is the member cells with their own confidence, so a map can shade
	// them individually. A catchment reading "3 corroborated, 3 single-source,
	// 1 no data" is far more legible as a picture than as a sentence.
	Cells []CatchmentCell `json:"cells"`
}

// CatchmentCell is one member cell of the catchment.
type CatchmentCell struct {
	H3            string     `json:"h3"`
	Confidence    Confidence `json:"confidence"`
	BusinessCount float64    `json:"business_count"`
	LandFraction  float64    `json:"land_fraction"`
	InCoverage    bool       `json:"in_coverage"`
}

// Limitations travels with every response. These are measured, not
// hypothetical, and the product must not present numbers without them.
type Limitations struct {
	// DuplicateInflationPctRange is [3.2, 6.3] - the 95% CI on record
	// inflation from unmerged duplicates. Nothing is auto-merged: the
	// matcher's out-of-sample precision was 25% against an in-sample suite
	// that claimed 100%.
	DuplicateInflationPctRange [2]float64 `json:"duplicate_inflation_pct_range"`
	// PositionErrorMeters: median / p90 / max cross-source disagreement.
	// Safe for 500m catchments; unsafe for any address-level claim.
	PositionErrorMedianM float64 `json:"position_error_median_m"`
	PositionErrorP90M    float64 `json:"position_error_p90_m"`
	PositionErrorMaxM    float64 `json:"position_error_max_m"`
	// IndependenceCaveat: Overture and Foursquare are NOT independent -
	// Foursquare is itself an Overture contributor (17.1% / 10.6% / 1.3% of
	// Overture records in the three Cairo study districts). "Corroborated"
	// means partially-overlapping feeds agree, not that two independent
	// observers agree.
	IndependenceCaveat string `json:"independence_caveat"`
	// Notes carries any catchment-specific warnings raised at request time.
	Notes []string `json:"notes,omitempty"`
}

// ReportResponse is what GET /report returns.
type ReportResponse struct {
	Query      QueryEcho        `json:"query"`
	Context    CatchmentContext `json:"context"`
	Metrics    []Metric         `json:"metrics"`
	TimeSeries []TimeSeries     `json:"time_series"`
	Limits     Limitations      `json:"limitations"`
}

type QueryEcho struct {
	Lat      float64 `json:"lat"`
	Lon      float64 `json:"lon"`
	RadiusM  int     `json:"radius_m"`
	Category string  `json:"category,omitempty"`
	KRing    int     `json:"k_ring"`
}

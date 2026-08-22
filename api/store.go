package main

import (
	"fmt"
	"strings"
	"sync"
)

// NO DATABASE.
//
// res-8 + res-9 is 79,041 cells and h3_metric is 109,996 rows. On disk the
// four parquet files total 6.11 MB compressed; in Go structs the whole set is
// tens of MB. That fits in RAM with room to spare, so the API loads
// everything at startup into maps keyed by h3 index and serves every request
// as a hash lookup plus an h3 k-ring. No PostGIS, no DB server, no hosting
// cost, no query planner to fight.
//
// THE ONE EXCEPTION is h3_metric_history. It is not loaded and must never be:
// 23 archived Overture snapshots across the business metrics is millions of
// rows. It stays on disk and is queried lazily via DuckDB (see history.go).

// CellRecord is the static per-cell context. One per (h3_index, res).
type CellRecord struct {
	H3Index         uint64
	Res             int
	LandFraction    float64
	LandAreaM2      float64
	CellAreaM2      float64
	Governorate     string
	BuiltUpPct      float64
	SaturationClass string
	CoverageRatio   float64 // NaN when GHSL built-up is zero
	GrowthPct       float64 // GHSL built-up growth 2015->2025, percent
	DensityDistort  bool
	PopulationStale bool
}

// MetricRecord is one (cell, metric) fact.
type MetricRecord struct {
	H3Index         uint64
	Metric          string
	NativeRes       int
	Track           Track
	Value           float64
	Confidence      Confidence
	NSources        int
	AgreementRatio  float64 // NaN when only one source
	AsOf            string
	SourceSnapshots map[string]string
	OvertureCount   int
	FSQCount        int
}

// Store holds everything served from memory.
type Store struct {
	mu sync.RWMutex

	// cells[res][h3index]
	cells map[int]map[uint64]*CellRecord
	// metrics[res][h3index] -> the facts for that cell
	metrics map[int]map[uint64][]*MetricRecord

	// Immutable provenance of what is loaded, echoed in responses so a
	// caller can always tell which snapshot answered them.
	loadedSnapshots map[string]string
	pipelineVersion string
	residentBytes   uint64
}

func NewStore() *Store {
	return &Store{
		cells:           map[int]map[uint64]*CellRecord{},
		metrics:         map[int]map[uint64][]*MetricRecord{},
		loadedSnapshots: map[string]string{},
	}
}

// Lookup returns the cell context, or nil if the cell is outside coverage.
// Outside-coverage is NOT the same as zero and callers must distinguish it.
func (s *Store) Cell(res int, idx uint64) *CellRecord {
	s.mu.RLock()
	defer s.mu.RUnlock()
	if m, ok := s.cells[res]; ok {
		return m[idx]
	}
	return nil
}

// MetricsFor returns the facts for one cell. Never nil-panics; an empty slice
// means the cell exists but has no metric of any kind.
func (s *Store) MetricsFor(res int, idx uint64) []*MetricRecord {
	s.mu.RLock()
	defer s.mu.RUnlock()
	if m, ok := s.metrics[res]; ok {
		return m[idx]
	}
	return nil
}

func (s *Store) Stats() string {
	s.mu.RLock()
	defer s.mu.RUnlock()
	var b strings.Builder
	for _, res := range []int{8, 9} {
		fmt.Fprintf(&b, "res-%d: %d cells, %d metric rows\n",
			res, len(s.cells[res]), countMetrics(s.metrics[res]))
	}
	return b.String()
}

func countMetrics(m map[uint64][]*MetricRecord) int {
	n := 0
	for _, v := range m {
		n += len(v)
	}
	return n
}

// Load is implemented in load.go. Called once at startup; the process is
// restarted after a monthly pipeline run rather than hot-reloading, so there
// is no cache invalidation logic to get wrong.

func (s *Store) ResidentBytes() uint64   { return s.residentBytes }
func (s *Store) PipelineVersion() string { return s.pipelineVersion }

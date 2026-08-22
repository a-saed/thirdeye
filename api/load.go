package main

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strconv"

	"github.com/parquet-go/parquet-go"
)

// Parquet row structs. Field tags match the column names written by
// pipeline/aggregate/h3_pipeline.py. h3_index arrives as a hex STRING and is
// parsed to uint64 here — every downstream lookup is then an integer hash,
// not a string compare.

type cellRow struct {
	H3Index         string  `parquet:"h3_index"`
	LandFraction    float64 `parquet:"land_fraction"`
	H3Res           int64   `parquet:"h3_res"`
	CellAreaM2      float64 `parquet:"cell_area_m2"`
	LandAreaM2      float64 `parquet:"land_area_m2"`
	Governorate     string  `parquet:"governorate"`
	BuiltUpPct      float64 `parquet:"builtup_pct"`
	SaturationClass string  `parquet:"saturation_class"`
	CoverageRatio   float64 `parquet:"coverage_ratio"`
	GrowthPct       float64 `parquet:"builtup_growth_pct_2015_2025"`
	PopulationStale bool    `parquet:"population_stale"`
	DensityDistort  bool    `parquet:"density_distorted"`
	PipelineVersion string  `parquet:"pipeline_version"`
}

type metricRow struct {
	H3Index         string  `parquet:"h3_index"`
	Metric          string  `parquet:"metric"`
	NativeRes       int32   `parquet:"native_res"`
	Track           string  `parquet:"track"`
	Value           float64 `parquet:"value"`
	Confidence      string  `parquet:"confidence"`
	NSources        int64   `parquet:"n_sources"`
	AgreementRatio  float64 `parquet:"agreement_ratio"`
	AsOf            string  `parquet:"as_of"`
	SourceSnapshots string  `parquet:"source_snapshots"`
	Overture        int64   `parquet:"overture"`
	FSQ             int64   `parquet:"fsq"`
	LandAreaM2      float64 `parquet:"land_area_m2"`
	PipelineVersion string  `parquet:"pipeline_version"`
}

// interner keeps one copy of each repeated string. Governorate,
// saturation_class, confidence, track, metric and as_of are all low
// cardinality across ~110k rows; interning them turns hundreds of thousands
// of small allocations into a few dozen.
type interner struct{ m map[string]string }

func newInterner() *interner { return &interner{m: make(map[string]string, 256)} }

func (i *interner) do(s string) string {
	if v, ok := i.m[s]; ok {
		return v
	}
	i.m[s] = s
	return s
}

// Load reads the four parquet tables into memory.
//
// FAILS LOUDLY on any missing or malformed file. There is no partial-load
// path: a store missing res-9 metrics would answer "0 cafes here" for half
// the city, which is indistinguishable from a real answer.
func (s *Store) Load(dir string) error {
	var m0 runtime.MemStats
	runtime.ReadMemStats(&m0)

	in := newInterner()
	pipelineVersions := map[string]bool{}

	for _, res := range []int{8, 9} {
		cellPath := filepath.Join(dir, fmt.Sprintf("h3_cell_res%d.parquet", res))
		cells, err := readRows[cellRow](cellPath)
		if err != nil {
			return fmt.Errorf("load cells res-%d: %w", res, err)
		}
		if len(cells) == 0 {
			return fmt.Errorf("load cells res-%d: file %s contained zero rows", res, cellPath)
		}
		cm := make(map[uint64]*CellRecord, len(cells))
		for _, c := range cells {
			idx, err := strconv.ParseUint(c.H3Index, 16, 64)
			if err != nil {
				return fmt.Errorf("load cells res-%d: bad h3 index %q: %w", res, c.H3Index, err)
			}
			cm[idx] = &CellRecord{
				H3Index:         idx,
				Res:             int(c.H3Res),
				LandFraction:    c.LandFraction,
				LandAreaM2:      c.LandAreaM2,
				CellAreaM2:      c.CellAreaM2,
				Governorate:     in.do(c.Governorate),
				BuiltUpPct:      c.BuiltUpPct,
				SaturationClass: in.do(c.SaturationClass),
				CoverageRatio:   c.CoverageRatio,
				GrowthPct:       c.GrowthPct,
				DensityDistort:  c.DensityDistort,
				PopulationStale: c.PopulationStale,
			}
			pipelineVersions[c.PipelineVersion] = true
		}
		s.cells[res] = cm

		metricPath := filepath.Join(dir, fmt.Sprintf("h3_metric_res%d.parquet", res))
		mrows, err := readRows[metricRow](metricPath)
		if err != nil {
			return fmt.Errorf("load metrics res-%d: %w", res, err)
		}
		if len(mrows) == 0 {
			return fmt.Errorf("load metrics res-%d: file %s contained zero rows", res, metricPath)
		}
		mm := make(map[uint64][]*MetricRecord, len(cm))
		for _, r := range mrows {
			idx, err := strconv.ParseUint(r.H3Index, 16, 64)
			if err != nil {
				return fmt.Errorf("load metrics res-%d: bad h3 index %q: %w", res, r.H3Index, err)
			}
			mm[idx] = append(mm[idx], &MetricRecord{
				H3Index:         idx,
				Metric:          in.do(r.Metric),
				NativeRes:       int(r.NativeRes),
				Track:           Track(in.do(r.Track)),
				Value:           r.Value,
				Confidence:      Confidence(in.do(r.Confidence)),
				NSources:        int(r.NSources),
				AgreementRatio:  r.AgreementRatio,
				AsOf:            in.do(r.AsOf),
				SourceSnapshots: parseSnapshots(r.SourceSnapshots),
				OvertureCount:   int(r.Overture),
				FSQCount:        int(r.FSQ),
			})
			pipelineVersions[r.PipelineVersion] = true
		}
		s.metrics[res] = mm
	}

	if len(pipelineVersions) != 1 {
		// Mixed pipeline versions mean the tables were built by different code
		// and may not be mutually consistent.
		return fmt.Errorf("inconsistent pipeline_version across tables: %v", keys(pipelineVersions))
	}
	for v := range pipelineVersions {
		s.pipelineVersion = v
	}

	var m1 runtime.MemStats
	runtime.ReadMemStats(&m1)
	s.residentBytes = m1.HeapAlloc - m0.HeapAlloc
	return nil
}

func readRows[T any](path string) ([]T, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("open %s: %w", path, err)
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		return nil, fmt.Errorf("stat %s: %w", path, err)
	}
	rows, err := parquet.Read[T](f, st.Size())
	if err != nil {
		return nil, fmt.Errorf("read %s: %w", path, err)
	}
	return rows, nil
}

// parseSnapshots decodes the JSON map the pipeline stores as a string. A
// malformed value yields an empty map rather than a nil one, so the response
// always carries the field even if empty — provenance is never dropped
// silently.
func parseSnapshots(s string) map[string]string {
	out := map[string]string{}
	if s == "" {
		return out
	}
	if err := jsonUnmarshalLoose(s, &out); err != nil {
		return map[string]string{}
	}
	return out
}

func keys(m map[string]bool) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	return out
}

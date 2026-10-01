package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"github.com/parquet-go/parquet-go"
	"github.com/uber/h3-go/v4"
)

// WHY THESE TESTS EXIST. SeriesFor used to decode every row of the history
// table on every report — 823k rows at res 9, ~1.4 s of a ~1.3 s request
// (measured 2026-10-01). It now seeks to the catchment's rows through an index
// built at startup. The index must select exactly the rows the full scan did,
// whatever order the pipeline writes them in.

// fullScanRows is the reference: the old behaviour, every row decoded and
// filtered. Kept here only to check the index against.
func fullScanRows(t *testing.T, path string, want map[uint64]bool) []historyRow {
	t.Helper()
	f, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	r := parquet.NewGenericReader[historyRow](f, parquet.SchemaOf(historyRow{}))
	defer r.Close()
	var out []historyRow
	buf := make([]historyRow, 4096)
	for {
		n, err := r.Read(buf)
		for _, row := range buf[:n] {
			if idx, perr := parseCell(row.H3Index); perr == nil && want[idx] {
				out = append(out, row)
			}
		}
		if err != nil {
			break
		}
	}
	return out
}

func wantSet(ring []h3.Cell) map[uint64]bool {
	w := map[uint64]bool{}
	for _, c := range ring {
		w[uint64(c)] = true
	}
	return w
}

func sameRows(a, b []historyRow) bool {
	count := func(rs []historyRow) map[historyRow]int {
		m := map[historyRow]int{}
		for _, r := range rs {
			m[r]++
		}
		return m
	}
	return reflect.DeepEqual(count(a), count(b))
}

// A small table whose rows are NOT grouped by cell: the index must not
// assume the pipeline sorts its output.
func TestHistoryIndexSelectsSameRowsAsFullScan_Unsorted(t *testing.T) {
	a, _ := h3.LatLngToCell(h3.LatLng{Lat: 30.0444, Lng: 31.2357}, 9)
	b, _ := h3.LatLngToCell(h3.LatLng{Lat: 31.2001, Lng: 29.9187}, 9)
	c, _ := h3.LatLngToCell(h3.LatLng{Lat: 29.9513, Lng: 31.2664}, 9)
	row := func(cell h3.Cell, snap string, v float64) historyRow {
		return historyRow{H3Index: cell.String(), Metric: "business_count.cafe", Value: v,
			SnapshotID: snap, AsOf: snap, Confidence: "single_source", Track: "business", PointStatus: "ok"}
	}
	rows := []historyRow{
		row(a, "2026-07-01", 1), row(b, "2026-07-01", 2), row(a, "2026-08-01", 3),
		row(c, "2026-07-01", 4), row(b, "2026-08-01", 5), row(a, "2026-09-01", 6),
	}
	path := filepath.Join(t.TempDir(), "h.parquet")
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	w := parquet.NewGenericWriter[historyRow](f, parquet.PageBufferSize(64))
	if _, err := w.Write(rows); err != nil {
		t.Fatal(err)
	}
	if err := w.Close(); err != nil {
		t.Fatal(err)
	}
	f.Close()

	idx, err := buildHistoryIndex(path)
	if err != nil {
		t.Fatal(err)
	}
	for _, ring := range [][]h3.Cell{{a}, {b}, {c}, {a, c}, {a, b, c}, {}} {
		want := wantSet(ring)
		got, err := readIndexedRows(path, idx, ring)
		if err != nil {
			t.Fatal(err)
		}
		if ref := fullScanRows(t, path, want); !sameRows(got, ref) {
			t.Fatalf("ring %v: index selected %d rows, full scan %d", ring, len(got), len(ref))
		}
	}
}

// Against the real tables, when they are present (CI tests run before the
// data is downloaded, so this skips there). The whole SeriesFor output — not
// just the rows — must be unchanged for a spread of catchments.
func TestHistoryIndexMatchesFullScan_RealData(t *testing.T) {
	dir := "../data/derived/h3_tables"
	for _, res := range []int{8, 9} {
		h, err := NewHistory(dir, res, 3)
		if err != nil {
			t.Skipf("history tables not present (%v); run locally after the pipeline", err)
		}
		points := []h3.LatLng{
			{Lat: 29.9513, Lng: 31.2664}, {Lat: 30.0877, Lng: 31.3263}, {Lat: 30.0444, Lng: 31.2357},
			{Lat: 31.2001, Lng: 29.9187}, {Lat: 30.0131, Lng: 31.2089}, {Lat: 0, Lng: 0},
		}
		for _, p := range points {
			cell, _ := h3.LatLngToCell(p, res)
			for _, k := range []int{0, 1, 2} {
				ring, _ := cell.GridDisk(k)
				for _, cat := range []string{"", "cafe", "pharmacy"} {
					got, err := h.SeriesFor(ring, cat)
					if err != nil {
						t.Fatal(err)
					}
					ref := h.aggregate(fullScanRows(t, h.path, wantSet(ring)), cat)
					gj, _ := json.Marshal(got)
					rj, _ := json.Marshal(ref)
					if string(gj) != string(rj) {
						t.Fatalf("res%d %v k=%d cat=%q: indexed SeriesFor differs from full scan", res, p, k, cat)
					}
				}
			}
		}
	}
}

func BenchmarkSeriesForRes9(b *testing.B) {
	dir := "../data/derived/h3_tables"
	h, err := NewHistory(dir, 9, 3)
	if err != nil {
		b.Skip("history tables not present")
	}
	cell, _ := h3.LatLngToCell(h3.LatLng{Lat: 29.9513, Lng: 31.2664}, 9)
	ring, _ := cell.GridDisk(2)
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		if _, err := h.SeriesFor(ring, "cafe"); err != nil {
			b.Fatal(err)
		}
	}
}

package main

import (
	"fmt"
	"math"
	"os"
	"sort"
	"strconv"
	"strings"

	"github.com/parquet-go/parquet-go"
	"github.com/uber/h3-go/v4"
)

// THE RECORDS BEHIND THE COUNT.
//
// "65 cafes" is a claim nobody can check. "Here are the 65" is a claim anyone
// who knows the street can falsify in ten seconds, and that is the only real
// quality control this dataset will ever get: the study never obtained ground
// truth, and the duplicate matcher scored 100% in-sample against 25%
// out-of-sample. Publishing the underlying rows turns an assertion into
// something a local can audit.
//
// It also makes duplicate inflation VISIBLE rather than merely disclosed. The
// 3.2-6.3% range in limitations.json is abstract; two adjacent rows with the
// same name from two different feeds are not.
//
// NOTHING IS MERGED. A flagged pair is returned as two rows, exactly as the
// aggregate counts hold it.

type placeRow struct {
	Source       string  `parquet:"source"`
	Name         string  `parquet:"name"`
	Category     string  `parquet:"category"`
	Groups       string  `parquet:"groups"`
	Lat          float64 `parquet:"lat"`
	Lon          float64 `parquet:"lon"`
	H3Res9       string  `parquet:"h3_res9"`
	H3Res8       string  `parquet:"h3_res8"`
	DupSuspected bool    `parquet:"dup_suspected"`
	Snapshot     string  `parquet:"snapshot"`
}

// Place is one record as returned to a caller.
type Place struct {
	Name     string  `json:"name"`
	Source   string  `json:"source"`
	Category string  `json:"category"`
	Groups   string  `json:"groups,omitempty"`
	Lat      float64 `json:"lat"`
	Lon      float64 `json:"lon"`
	// DistanceM is from the query pin. Rounded to whole metres deliberately:
	// cross-source position disagreement is 10.2 m median and 58.5 m at p90,
	// so a decimal place here would be invented precision.
	DistanceM int `json:"distance_m"`
	// DupSuspected marks a record that a conservative cross-source rule paired
	// with another. ADVISORY. Both rows are counted, and the pairing itself is
	// unreliable enough that nothing is merged on it.
	DupSuspected bool `json:"duplicate_suspected"`
	// SamePoint is how many records in this catchment share this exact
	// coordinate, including this one. Anything above 1 is COORDINATE COLLAPSE:
	// a source geocoding several businesses to one building or plaza centroid.
	// It is why four different cafes can all sit at exactly 90 m, and it is a
	// different defect from duplication — these are distinct businesses with
	// one shared position, not one business counted twice.
	SamePoint int    `json:"same_point"`
	Snapshot  string `json:"snapshot"`
}

type PlacesResponse struct {
	Query QueryEcho `json:"query"`
	// Total is the number of rows matching the CURRENT filter; TotalAll is the
	// number before the flagged filter, so a caller can always show both.
	Total      int     `json:"total"`
	TotalAll   int     `json:"total_unfiltered"`
	Returned   int     `json:"returned"`
	Offset     int     `json:"offset"`
	DupFlagged int     `json:"duplicate_flagged"`
	Places     []Place `json:"places"`
	Note       string  `json:"note"`
}

// PlaceStore keeps every record in RAM, bucketed by res-9 cell, so a catchment
// lookup is a k-ring of map hits with no scan. 310k rows is ~12 MB on disk.
type PlaceStore struct {
	byCell map[uint64][]placeRow
	total  int
}

func LoadPlaces(path string) (*PlaceStore, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("places table: %w", err)
	}
	defer f.Close()

	r := parquet.NewGenericReader[placeRow](f, parquet.SchemaOf(placeRow{}))
	defer r.Close()

	ps := &PlaceStore{byCell: map[uint64][]placeRow{}}
	buf := make([]placeRow, 4096)
	for {
		n, err := r.Read(buf)
		for i := 0; i < n; i++ {
			row := buf[i]
			idx, perr := strconv.ParseUint(row.H3Res9, 16, 64)
			if perr != nil {
				continue
			}
			ps.byCell[idx] = append(ps.byCell[idx], row)
			ps.total++
		}
		if err != nil {
			break
		}
	}
	return ps, nil
}

// haversineM is the same formula the export uses, so the distance a user sees
// matches the distance the duplicate rule was applied at.
func haversineM(lat1, lon1, lat2, lon2 float64) float64 {
	const R = 6371000.0
	p1, p2 := lat1*math.Pi/180, lat2*math.Pi/180
	dp := p2 - p1
	dl := (lon2 - lon1) * math.Pi / 180
	a := math.Sin(dp/2)*math.Sin(dp/2) + math.Cos(p1)*math.Cos(p2)*math.Sin(dl/2)*math.Sin(dl/2)
	return 2 * R * math.Asin(math.Sqrt(a))
}

// InCatchment returns every record in the ring, sorted by distance from the
// pin. The SAME ring the report is built from, so the list and the count can
// never describe different areas.
func (ps *PlaceStore) InCatchment(ring []h3.Cell, lat, lon float64, group string) []Place {
	out := []Place{}
	for _, c := range ring {
		for _, row := range ps.byCell[uint64(c)] {
			// A place can belong to several groups - business_metrics counts
			// it in each - so membership, not equality. The pipe delimiters
			// stop "cafe" matching a longer name that contains it.
			if group != "" && !strings.Contains(row.Groups, "|"+group+"|") {
				continue
			}
			out = append(out, Place{
				Name:         row.Name,
				Source:       row.Source,
				Category:     row.Category,
				Groups:       row.Groups,
				Lat:          row.Lat,
				Lon:          row.Lon,
				DistanceM:    int(math.Round(haversineM(lat, lon, row.Lat, row.Lon))),
				DupSuspected: row.DupSuspected,
				Snapshot:     row.Snapshot,
			})
		}
	}
	// Coordinate collapse, counted over the catchment actually returned.
	at := map[string]int{}
	for _, p := range out {
		at[coordKey(p.Lat, p.Lon)]++
	}
	for i := range out {
		out[i].SamePoint = at[coordKey(out[i].Lat, out[i].Lon)]
	}

	sort.Slice(out, func(i, j int) bool {
		if out[i].DistanceM != out[j].DistanceM {
			return out[i].DistanceM < out[j].DistanceM
		}
		return out[i].Name < out[j].Name
	})
	return out
}

// coordKey identifies an exact shared position. 6 dp is ~0.11 m: fine enough
// that only genuinely identical coordinates collide, not merely close ones.
func coordKey(lat, lon float64) string {
	return strconv.FormatFloat(lat, 'f', 6, 64) + "," + strconv.FormatFloat(lon, 'f', 6, 64)
}

// SearchByName finds our OWN records by name.
//
// WHY THIS EXISTS ALONGSIDE NOMINATIM. Nominatim indexes addresses and place
// names; it does not know the 310k business records this product is built on.
// A user searching a venue in Sheikh Zayed got nothing back, which read as a
// broken search when it was really a search pointed at the wrong corpus. The
// business names ARE the data — searching them is both faster (in RAM, no
// network, no rate limit) and honest: a hit means we actually hold a record
// there, and a miss means we do not.
//
// Substring match, case-folded, no fuzzy matching. The fuzzy matcher in this
// project scored 25% precision out-of-sample, and quietly guessing at what
// someone meant is exactly the behaviour that produced that number.
func (ps *PlaceStore) SearchByName(term string, limit int) []Place {
	needle := strings.ToLower(strings.TrimSpace(term))
	if needle == "" {
		return nil
	}
	type scored struct {
		p     Place
		exact bool
		start bool
	}
	var hits []scored
	seen := map[string]bool{}
	for _, rows := range ps.byCell {
		for _, row := range rows {
			if row.Name == "" {
				continue
			}
			low := strings.ToLower(row.Name)
			if !strings.Contains(low, needle) {
				continue
			}
			// One entry per name+coordinate: the same shop from two feeds is
			// two records, but it is one thing to navigate to.
			key := row.Name + "|" + strconv.FormatFloat(row.Lat, 'f', 4, 64) +
				"|" + strconv.FormatFloat(row.Lon, 'f', 4, 64)
			if seen[key] {
				continue
			}
			seen[key] = true
			hits = append(hits, scored{
				p: Place{
					Name: row.Name, Source: row.Source, Category: row.Category,
					Groups: row.Groups, Lat: row.Lat, Lon: row.Lon,
					DupSuspected: row.DupSuspected, Snapshot: row.Snapshot,
				},
				exact: low == needle,
				start: strings.HasPrefix(low, needle),
			})
			if len(hits) > 4000 {
				break
			}
		}
	}
	// Exact name, then prefix, then shortest — a short name containing the term
	// is usually the thing itself rather than something that mentions it.
	sort.Slice(hits, func(i, j int) bool {
		a, b := hits[i], hits[j]
		if a.exact != b.exact {
			return a.exact
		}
		if a.start != b.start {
			return a.start
		}
		if len(a.p.Name) != len(b.p.Name) {
			return len(a.p.Name) < len(b.p.Name)
		}
		return a.p.Name < b.p.Name
	})
	out := make([]Place, 0, limit)
	for i := 0; i < len(hits) && i < limit; i++ {
		out = append(out, hits[i].p)
	}
	return out
}

package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"

	"github.com/uber/h3-go/v4"
)

// GET /report?lat=&lon=&radius=&category=
//
// Returns catchment metrics normalised by LAND area, per-metric confidence
// with contributing sources and as_of, saturation class, coverage ratio, and
// the FULL time series in one round trip (the UI scrubber must not fetch per
// year).
//
// Radius is resolved at READ TIME via an h3 k-ring rather than precomputed,
// so radii stay flexible. The k for a given radius is chosen in report.go,
// against the ORIGIN CELL'S MEASURED AREA — see kForRadius.

func (a *App) handleReport(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	lat, err1 := strconv.ParseFloat(q.Get("lat"), 64)
	lon, err2 := strconv.ParseFloat(q.Get("lon"), 64)
	if err1 != nil || err2 != nil {
		httpErr(w, http.StatusBadRequest, "lat and lon are required floats")
		return
	}
	radius := a.th.Catchment.DefaultRadiusM
	if v := q.Get("radius"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			radius = n
		} else {
			httpErr(w, http.StatusBadRequest, "radius must be a positive integer (metres)")
			return
		}
	}
	category := q.Get("category")
	// Explicit ring size wins over the radius. -1 means "derive it".
	kOverride := -1
	if v := q.Get("k"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n >= 0 && n <= a.th.Catchment.MaxK {
			kOverride = n
		} else {
			httpErr(w, http.StatusBadRequest, fmt.Sprintf("k must be an integer between 0 and %d", a.th.Catchment.MaxK))
			return
		}
	}

	resp, err := a.BuildReport(lat, lon, radius, category, kOverride)
	if err != nil {
		httpErr(w, http.StatusInternalServerError, err.Error())
		return
	}
	w.Header().Set("Content-Type", "application/json")
	enc := json.NewEncoder(w)
	enc.SetIndent("", "  ")
	_ = enc.Encode(resp)
}

func httpErr(w http.ResponseWriter, code int, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": msg})
}

// GET /places?lat=&lon=&radius=&category=&limit=&offset=
//
// The individual records behind a catchment's business count, nearest first.
// Uses the SAME k-ring the report uses, so the list can never describe a
// different area than the number it explains.
func (a *App) handlePlaces(w http.ResponseWriter, r *http.Request) {
	if a.places == nil {
		httpErr(w, http.StatusServiceUnavailable,
			"place-level table not built; run pipeline/aggregate/export_places.py")
		return
	}
	q := r.URL.Query()
	lat, err1 := strconv.ParseFloat(q.Get("lat"), 64)
	lon, err2 := strconv.ParseFloat(q.Get("lon"), 64)
	if err1 != nil || err2 != nil {
		httpErr(w, http.StatusBadRequest, "lat and lon are required floats")
		return
	}
	radius := a.th.Catchment.DefaultRadiusM
	if v := q.Get("radius"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			radius = n
		}
	}
	// CLAMP, do not ignore. The previous version silently fell through to the
	// default of 50 when limit exceeded its cap, so a client asking for 1000
	// got 50 back and no indication that it had been overruled — the map would
	// have plotted 50 of 80 records and looked complete.
	limit, offset := 200, 0
	if v, err := strconv.Atoi(q.Get("limit")); err == nil && v > 0 {
		limit = v
		if limit > maxPlaceLimit {
			limit = maxPlaceLimit
		}
	}
	if v, err := strconv.Atoi(q.Get("offset")); err == nil && v >= 0 {
		offset = v
	}

	origin, err := h3.LatLngToCell(h3.NewLatLng(lat, lon), a.th.Resolutions.Report)
	if err != nil {
		httpErr(w, http.StatusInternalServerError, err.Error())
		return
	}
	k := -1
	if v := q.Get("k"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n >= 0 && n <= a.th.Catchment.MaxK {
			k = n
		}
	}
	if k < 0 {
		var err error
		if k, err = kForRadius(origin, radius); err != nil {
			httpErr(w, http.StatusInternalServerError, err.Error())
			return
		}
	}
	ring, err := origin.GridDisk(k)
	if err != nil {
		httpErr(w, http.StatusInternalServerError, err.Error())
		return
	}

	all := a.places.InCatchment(ring, lat, lon, q.Get("category"))
	flagged := 0
	for _, p := range all {
		if p.DupSuspected {
			flagged++
		}
	}
	// flagged=1 narrows to the suspected duplicates. Filtering server-side
	// rather than in the browser, because a client filtering only the rows it
	// happens to be holding would report a page count as a total.
	total := len(all)
	if q.Get("flagged") == "1" {
		only := make([]Place, 0, flagged)
		for _, p := range all {
			if p.DupSuspected {
				only = append(only, p)
			}
		}
		all = only
	}
	_ = total
	lo := offset
	if lo > len(all) {
		lo = len(all)
	}
	hi := lo + limit
	if hi > len(all) {
		hi = len(all)
	}

	resp := PlacesResponse{
		Query:      QueryEcho{Lat: lat, Lon: lon, RadiusM: radius, Category: q.Get("category"), KRing: k},
		Total:      len(all),
		TotalAll:   total,
		Returned:   hi - lo,
		Offset:     lo,
		DupFlagged: flagged,
		Places:     all[lo:hi],
		Note: "Every record as the sources publish it. Nothing is merged: a suspected " +
			"duplicate pair appears as two rows and is counted twice, which is where the " +
			"3.2-6.3% record inflation comes from. Flags are advisory — the matcher behind " +
			"them scored 25% precision out-of-sample.",
	}
	w.Header().Set("Content-Type", "application/json")
	enc := json.NewEncoder(w)
	enc.SetIndent("", "  ")
	_ = enc.Encode(resp)
}

// maxPlaceLimit bounds one response. A 19-cell catchment in central Cairo can
// hold a few thousand records; beyond this the caller should page.
const maxPlaceLimit = 2000

// GET /coverage?lat=&lon=
//
// Whether a point is inside coverage and what is there, resolved from the
// res-8 store. Exists so a picker can show a candidate's status BEFORE it is
// chosen — discovering that a location has no data only after selecting it,
// and seeing four rows read "no data", is the frustrating version.
func (a *App) handleCoverage(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	lat, err1 := strconv.ParseFloat(q.Get("lat"), 64)
	lon, err2 := strconv.ParseFloat(q.Get("lon"), 64)
	if err1 != nil || err2 != nil {
		httpErr(w, http.StatusBadRequest, "lat and lon are required floats")
		return
	}
	cell, err := h3.LatLngToCell(h3.NewLatLng(lat, lon), a.th.Resolutions.Coverage)
	if err != nil {
		httpErr(w, http.StatusInternalServerError, err.Error())
		return
	}
	idx := uint64(cell)
	c := a.store.Cell(a.th.Resolutions.Coverage, idx)
	if c == nil {
		writeJSON(w, map[string]any{"in_coverage": false})
		return
	}
	out := map[string]any{
		"in_coverage": true,
		"governorate": c.Governorate,
		"confidence":  string(Unavailable),
		"businesses":  0.0,
	}
	for _, m := range a.store.MetricsFor(a.th.Resolutions.Coverage, idx) {
		if m.Metric == "business_count.total" {
			out["confidence"] = string(m.Confidence)
			out["businesses"] = m.Value
		}
	}
	writeJSON(w, out)
}

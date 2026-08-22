package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"
)

// NOMINATIM, PROXIED THROUGH THE API ON PURPOSE.
//
// It could be called from the browser — Nominatim sends CORS headers — but the
// usage policy requires an identifying User-Agent and at most 1 request per
// second, and a browser can enforce neither: User-Agent is a forbidden header
// in fetch(), and per-tab throttling does nothing about ten tabs. Proxying puts
// both under our control, and the cache means panning the map does not turn
// into a request storm.
//
// FREE-DATA RULE: Nominatim is free and keyless. No API key, no card, no paid
// tier. Results are ODbL from OSM and attributed as such in the UI.
//
// THIS IS THE ONE PLACE THE PRODUCT USES OSM. The study measured zero OSM
// contribution to business data in six districts, which is why OSM is not a
// business source. Street and place NAMES are a different dataset with
// different coverage, and are only ever used as a label — never as evidence,
// never counted, never fed into a metric.

const (
	nominatimBase = "https://nominatim.openstreetmap.org"
	// Identifies the caller as the policy requires. A default Go or urllib UA
	// gets 403'd — that already happened once on this project, against the
	// Source Cooperative mirror, and was misreported as "no gaps" for a while.
	nominatimUA = "ThirdEye/1.0 (location intelligence for Greater Cairo; contact via repo)"
	// One request per second, globally. Not per client.
	nominatimMinInterval = 1100 * time.Millisecond
	nominatimTimeout     = 8 * time.Second
	geocodeCacheMax      = 4096
)

type Geocoder struct {
	mu       sync.Mutex
	last     time.Time
	cache    map[string]json.RawMessage
	cacheSeq []string
	client   *http.Client
}

func NewGeocoder() *Geocoder {
	return &Geocoder{
		cache:  map[string]json.RawMessage{},
		client: &http.Client{Timeout: nominatimTimeout},
	}
}

// fetch serialises every upstream call and spaces them, so the 1 req/s policy
// holds no matter how many browsers are pointed at this API.
func (g *Geocoder) fetch(path string, q url.Values) (json.RawMessage, error) {
	key := path + "?" + q.Encode()

	g.mu.Lock()
	if v, ok := g.cache[key]; ok {
		g.mu.Unlock()
		return v, nil
	}
	wait := nominatimMinInterval - time.Since(g.last)
	if wait > 0 {
		time.Sleep(wait)
	}
	g.last = time.Now()
	g.mu.Unlock()

	req, err := http.NewRequest("GET", nominatimBase+path+"?"+q.Encode(), nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", nominatimUA)
	req.Header.Set("Accept", "application/json")

	resp, err := g.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("nominatim unreachable: %w", err)
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("nominatim returned %d", resp.StatusCode)
	}

	g.mu.Lock()
	if len(g.cacheSeq) >= geocodeCacheMax {
		delete(g.cache, g.cacheSeq[0])
		g.cacheSeq = g.cacheSeq[1:]
	}
	g.cache[key] = body
	g.cacheSeq = append(g.cacheSeq, key)
	g.mu.Unlock()
	return body, nil
}

// CachedName returns a previously-resolved place name for a point, or "" if we
// have not looked it up.
//
// CACHE ONLY, NEVER A FETCH. This serves the server-rendered <title> for share
// previews, and Nominatim's policy caps us at one request per second — a
// crawler hitting ten unvisited URLs would serialise into ten seconds of HTML
// latency, or a timeout. A share link is usually pasted after someone has
// looked at the page, so the name is normally already cached; when it is not,
// the metadata falls back to coordinates and still carries the figures, which
// are the part worth sharing.
func (g *Geocoder) CachedName(lat, lon float64) string {
	q := url.Values{}
	q.Set("lat", strconv.FormatFloat(lat, 'f', 5, 64))
	q.Set("lon", strconv.FormatFloat(lon, 'f', 5, 64))
	q.Set("format", "jsonv2")
	q.Set("zoom", "16")
	q.Set("addressdetails", "1")
	q.Set("accept-language", "en")

	g.mu.Lock()
	body, ok := g.cache["/reverse?"+q.Encode()]
	g.mu.Unlock()
	if !ok {
		return ""
	}
	var p nominatimPlace
	if json.Unmarshal(body, &p) != nil {
		return ""
	}
	return p.shortName()
}

// PlaceLabel is the small, boring shape the UI actually wants: a short name to
// put in a heading, and the fuller address underneath.
type PlaceLabel struct {
	Name   string `json:"name"`
	Detail string `json:"detail"`
	// Kind separates "a place OSM knows about" from "a record we actually
	// hold". They are different promises and the UI labels them differently.
	Kind        string  `json:"kind,omitempty"`
	Source      string  `json:"source,omitempty"`
	Lat         float64 `json:"lat"`
	Lon         float64 `json:"lon"`
	Attribution string  `json:"attribution"`
}

type nominatimAddress struct {
	Neighbourhood string `json:"neighbourhood"`
	Suburb        string `json:"suburb"`
	Quarter       string `json:"quarter"`
	CityDistrict  string `json:"city_district"`
	Road          string `json:"road"`
	City          string `json:"city"`
	Town          string `json:"town"`
	State         string `json:"state"`
	Country       string `json:"country"`
}

type nominatimPlace struct {
	DisplayName string           `json:"display_name"`
	Lat         string           `json:"lat"`
	Lon         string           `json:"lon"`
	Address     nominatimAddress `json:"address"`
}

// shortName prefers the NEIGHBOURHOOD, not the street and not the city.
// A report describes a 500 m catchment: "Road 9" is too narrow for it and
// "Cairo" is far too broad. Suburb/quarter is the scale that matches.
func (p nominatimPlace) shortName() string {
	for _, c := range []string{
		p.Address.Neighbourhood, p.Address.Quarter, p.Address.Suburb,
		p.Address.CityDistrict, p.Address.Road, p.Address.City, p.Address.Town,
	} {
		if strings.TrimSpace(c) != "" {
			return c
		}
	}
	if p.DisplayName != "" {
		return strings.SplitN(p.DisplayName, ",", 2)[0]
	}
	return ""
}

func (p nominatimPlace) detail() string {
	parts := []string{}
	seen := map[string]bool{}
	short := p.shortName()
	for _, c := range []string{p.Address.Suburb, p.Address.CityDistrict,
		p.Address.City, p.Address.Town, p.Address.State} {
		c = strings.TrimSpace(c)
		if c == "" || c == short || seen[c] {
			continue
		}
		seen[c] = true
		parts = append(parts, c)
	}
	return strings.Join(parts, ", ")
}

// GET /geocode/reverse?lat=&lon=
func (a *App) handleReverse(w http.ResponseWriter, r *http.Request) {
	lat, err1 := strconv.ParseFloat(r.URL.Query().Get("lat"), 64)
	lon, err2 := strconv.ParseFloat(r.URL.Query().Get("lon"), 64)
	if err1 != nil || err2 != nil {
		httpErr(w, http.StatusBadRequest, "lat and lon are required floats")
		return
	}
	q := url.Values{}
	q.Set("lat", strconv.FormatFloat(lat, 'f', 5, 64))
	q.Set("lon", strconv.FormatFloat(lon, 'f', 5, 64))
	q.Set("format", "jsonv2")
	// 16 is roughly neighbourhood granularity - matching the catchment, not
	// the building.
	q.Set("zoom", "16")
	q.Set("addressdetails", "1")
	q.Set("accept-language", "en")

	body, err := a.geo.fetch("/reverse", q)
	if err != nil {
		// A missing label is cosmetic. Never fail the screen over it.
		httpErr(w, http.StatusBadGateway, err.Error())
		return
	}
	var p nominatimPlace
	if err := json.Unmarshal(body, &p); err != nil {
		httpErr(w, http.StatusBadGateway, "could not parse nominatim response")
		return
	}
	writeJSON(w, PlaceLabel{
		Name: p.shortName(), Detail: p.detail(), Lat: lat, Lon: lon,
		Attribution: "© OpenStreetMap contributors (ODbL), via Nominatim",
	})
}

// GET /geocode/search?q=
//
// Two corpora, ours first: the records this product actually holds, then the
// places OSM knows about. They are different promises — a business hit means
// we have data at that point, an area hit only means the place exists — so
// they are labelled separately rather than blended into one ranked list.
func (a *App) handleSearch(w http.ResponseWriter, r *http.Request) {
	term := strings.TrimSpace(r.URL.Query().Get("q"))
	if len(term) < 3 {
		writeJSON(w, map[string]any{"results": []PlaceLabel{}})
		return
	}

	out := []PlaceLabel{}
	// OUR OWN RECORDS FIRST, and independently of the network. Nominatim being
	// unreachable must not take the local index down with it — searching data
	// that is already resident in RAM has no reason to fail.
	if a.places != nil {
		for _, p := range a.places.SearchByName(term, 5) {
			out = append(out, PlaceLabel{
				Name: p.Name, Detail: shortCategory(p.Category), Lat: p.Lat, Lon: p.Lon,
				Kind: "business", Source: p.Source,
				Attribution: "Overture / Foursquare record",
			})
		}
	}

	q := url.Values{}
	q.Set("q", term)
	q.Set("format", "jsonv2")
	q.Set("addressdetails", "1")
	q.Set("limit", "6")
	q.Set("accept-language", "en")
	// WORLDWIDE. Third Eye is a method, not a Cairo tool — restricting the
	// geocoder to one country bakes today's coverage into the product itself.
	// The viewbox biases results toward where we hold data WITHOUT excluding
	// anywhere: a search for a place we cannot report on still finds it, and
	// the client says plainly that there is no data there. Refusing to look is
	// worse than answering honestly.
	q.Set("viewbox", "29.5803,31.3520,31.8979,29.1717")
	q.Set("limit", "8")

	geoErr := ""
	if body, err := a.geo.fetch("/search", q); err != nil {
		geoErr = err.Error()
	} else {
		var raw []nominatimPlace
		if err := json.Unmarshal(body, &raw); err != nil {
			geoErr = "could not parse nominatim response"
		} else {
			for _, p := range raw {
				lat, e1 := strconv.ParseFloat(p.Lat, 64)
				lon, e2 := strconv.ParseFloat(p.Lon, 64)
				if e1 != nil || e2 != nil {
					continue
				}
				out = append(out, PlaceLabel{
					Name: p.shortName(), Detail: p.detail(), Lat: lat, Lon: lon,
					Kind:        "area",
					Attribution: "© OpenStreetMap contributors (ODbL), via Nominatim",
				})
			}
		}
	}

	resp := map[string]any{"results": out}
	if geoErr != "" {
		// Degraded, not failed — and said so rather than silently returning
		// half the corpus as if it were all of it.
		resp["place_search_unavailable"] = geoErr
	}
	writeJSON(w, resp)
}

// shortCategory turns a source category into something readable: Foursquare
// ships a full path, Overture ships snake_case.
func shortCategory(raw string) string {
	if raw == "" {
		return ""
	}
	parts := strings.Split(raw, ">")
	leaf := strings.TrimSpace(parts[len(parts)-1])
	leaf = strings.ReplaceAll(leaf, "_", " ")
	if leaf == "" {
		return ""
	}
	return strings.ToUpper(leaf[:1]) + strings.ToLower(leaf[1:])
}

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(v)
}

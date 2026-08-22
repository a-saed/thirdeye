package main

import (
	"fmt"
	"html"
	"log"
	"math"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
)

// SERVER-RENDERED METADATA FOR SHARE PREVIEWS.
//
// Titles and descriptions are also set client-side, which covers humans and
// the crawlers that run JavaScript. Facebook, LinkedIn, WhatsApp and Slack do
// not run it, and Twitter is inconsistent — so a shared report link previewed
// as the generic home card no matter what the page said. Since the API is
// already a server holding the whole store in RAM, rendering the tags here
// costs a map lookup.
//
// CONSEQUENCE, RECORDED IN docs/DEPLOYMENT.md: the API is now the HTML origin
// for /report and /compare. Those two paths can no longer be served by a pure
// static host.
//
// Text only. A per-location OG image would need an image library and a render
// path; the text tags carry most of the value.

type HTMLServer struct {
	dir      string
	mu       sync.RWMutex
	template string
}

func NewHTMLServer(dir string) (*HTMLServer, error) {
	h := &HTMLServer{dir: dir}
	if err := h.load(); err != nil {
		return nil, err
	}
	return h, nil
}

func (h *HTMLServer) load() error {
	b, err := os.ReadFile(filepath.Join(h.dir, "index.html"))
	if err != nil {
		return fmt.Errorf("index.html in %s: %w", h.dir, err)
	}
	h.mu.Lock()
	h.template = string(b)
	h.mu.Unlock()
	return nil
}

// meta is the small set of tags worth rewriting per route.
type meta struct {
	title string
	desc  string
}

// render swaps the four tags that carry a preview. String replacement rather
// than an HTML parser: the template is ours, the tags are fixed, and a parser
// would reformat a file that is also read by people.
func (h *HTMLServer) render(m meta) string {
	h.mu.RLock()
	out := h.template
	h.mu.RUnlock()

	t := html.EscapeString(m.title)
	d := html.EscapeString(m.desc)

	replacements := [][2]string{
		{`<title>Third Eye — location intelligence that shows its working</title>`,
			"<title>" + t + "</title>"},
		{`content="Businesses, population and construction for any point on the map. Open data, every figure sourced and dated, with the gaps left visible."`,
			`content="` + d + `"`},
		{`content="Third Eye — location intelligence that shows its working"`,
			`content="` + t + `"`},
	}
	for _, r := range replacements {
		out = strings.ReplaceAll(out, r[0], r[1])
	}
	return out
}

func fmtInt(v float64) string {
	n := int64(math.Round(v))
	s := strconv.FormatInt(n, 10)
	if n < 0 {
		return s
	}
	// Thousands separators, because these land in a preview card read at a
	// glance rather than in a data table.
	var b strings.Builder
	for i, c := range s {
		if i > 0 && (len(s)-i)%3 == 0 {
			b.WriteByte(',')
		}
		b.WriteRune(c)
	}
	return b.String()
}

func (a *App) placeOrCoords(lat, lon float64) string {
	if a.geo != nil {
		if n := a.geo.CachedName(lat, lon); n != "" {
			return n
		}
	}
	return fmt.Sprintf("%.4f, %.4f", lat, lon)
}

// metaForReport builds the preview from the SAME BuildReport the page uses, so
// the shared figure and the rendered figure cannot disagree.
func (a *App) metaForReport(q map[string][]string) meta {
	get := func(k string) string {
		if v, ok := q[k]; ok && len(v) > 0 {
			return v[0]
		}
		return ""
	}
	lat, err1 := strconv.ParseFloat(get("lat"), 64)
	lon, err2 := strconv.ParseFloat(get("lon"), 64)
	if err1 != nil || err2 != nil {
		return meta{
			title: "Third Eye — location intelligence that shows its working",
			desc:  "Businesses, population and construction for any point on the map.",
		}
	}
	category := get("category")
	if category == "" {
		category = "cafe"
	}
	k := -1
	if v, err := strconv.Atoi(get("k")); err == nil && v >= 0 && v <= 12 {
		k = v
	}
	where := a.placeOrCoords(lat, lon)

	rep, err := a.BuildReport(lat, lon, 500, category, k)
	if err != nil {
		// Outside coverage is a real answer and should preview as one.
		return meta{
			title: where + " — Third Eye",
			desc:  "No data for this location yet. Third Eye covers the regions it has processed, and says so where it has not.",
		}
	}
	var biz, pop float64
	var haveBiz bool
	for _, m := range rep.Metrics {
		switch m.Name {
		case "business_count." + category:
			biz, haveBiz = m.Value, true
		case "population":
			pop = m.Value
		}
	}
	d := fmt.Sprintf("%s people within %d m", fmtInt(pop), rep.Query.RadiusM)
	if haveBiz {
		d = fmt.Sprintf("%s %ss and %s", fmtInt(biz), category, d)
	} else {
		d = fmt.Sprintf("No %s records here, and %s", category, d)
	}
	return meta{
		title: where + " — Third Eye",
		desc:  d + ". Every figure sourced and dated, with the gaps left visible.",
	}
}

func (a *App) metaForCompare(q map[string][]string) meta {
	parse := func(k string) (float64, float64, bool) {
		v, ok := q[k]
		if !ok || len(v) == 0 {
			return 0, 0, false
		}
		parts := strings.Split(v[0], ",")
		if len(parts) != 2 {
			return 0, 0, false
		}
		lat, e1 := strconv.ParseFloat(parts[0], 64)
		lon, e2 := strconv.ParseFloat(parts[1], 64)
		return lat, lon, e1 == nil && e2 == nil
	}
	alat, alon, aok := parse("a")
	blat, blon, bok := parse("b")
	if !aok || !bok {
		return meta{
			title: "Compare locations — Third Eye",
			desc:  "Two locations side by side: businesses, population and construction, each figure sourced and dated.",
		}
	}
	an, bn := a.placeOrCoords(alat, alon), a.placeOrCoords(blat, blon)
	return meta{
		title: an + " vs " + bn + " — Third Eye",
		desc: "Two locations side by side: businesses, population and construction. " +
			"Each figure sourced and dated, with no overall score — the comparison does not know your rent.",
	}
}

func (a *App) handleHTML(w http.ResponseWriter, r *http.Request) {
	if a.html == nil {
		http.NotFound(w, r)
		return
	}
	var m meta
	switch strings.TrimSuffix(r.URL.Path, "/") {
	case "/report":
		m = a.metaForReport(r.URL.Query())
	case "/compare":
		m = a.metaForCompare(r.URL.Query())
	default:
		http.NotFound(w, r)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	// Short cache: the figures change only with a monthly pipeline run, but a
	// crawler re-fetching after a run should not see a stale headline.
	w.Header().Set("Cache-Control", "public, max-age=300")
	_, _ = w.Write([]byte(a.html.render(m)))
}

func mountHTML(mux *http.ServeMux, app *App, dir string) {
	if dir == "" {
		return
	}
	h, err := NewHTMLServer(dir)
	if err != nil {
		log.Printf("WARNING: server-rendered meta disabled (%v); share previews will "+
			"fall back to the generic card", err)
		return
	}
	app.html = h
	mux.HandleFunc("/report", app.handleHTML)
	mux.HandleFunc("/compare", app.handleHTML)
	log.Printf("serving /report and /compare HTML from %s with rendered meta", dir)
}

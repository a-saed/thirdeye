package main

import (
	"flag"
	"log"
	"net/http"
	"os"
	"path/filepath"
)

type App struct {
	store   *Store
	history *History
	places  *PlaceStore
	geo     *Geocoder
	html    *HTMLServer
	th      *Thresholds
	limits  Limitations
}

func main() {
	dataDir := flag.String("data", "data/derived/h3_tables", "directory holding the h3 parquet tables")
	addr := flag.String("addr", ":8080", "listen address")
	limitsPath := flag.String("limits", "api/limitations.json", "measured limitations config")
	webDir := flag.String("web", "", "built SPA directory; when set, /report and /compare are "+
		"served from here with server-rendered meta tags for share previews")
	thresholdsPath := flag.String("thresholds", "config/thresholds.json",
		"shared threshold config, also read by the pipeline")
	flag.Parse()

	// Strict: a missing threshold is a startup failure, never a default. The
	// API must not aggregate on a rule the pipeline did not use.
	th, err := LoadThresholds(*thresholdsPath)
	if err != nil {
		log.Fatal(err)
	}
	log.Printf("thresholds loaded from %s (res-%d reports, saturation %.0f/%.0f)",
		*thresholdsPath, th.Resolutions.Report,
		th.Saturation.SaturatedPct, th.Saturation.GreenfieldPct)

	store := NewStore()
	if err := store.Load(*dataDir); err != nil {
		// Fail loudly. Serving an empty store would return zeros that look
		// like real "no businesses here" answers.
		log.Printf("FATAL: %v", err)
		log.Printf("scaffold: parquet loading is not implemented yet; refusing to serve")
		os.Exit(1)
	}
	log.Printf("store loaded: pipeline_version=%s", store.PipelineVersion())
	log.Print(store.Stats())
	log.Printf("store resident: %.1f MB", float64(store.ResidentBytes())/1048576)

	hist, err := NewHistory(*dataDir, th.Resolutions.Report, th.Series.MinCorrectedPoints)
	if err != nil {
		log.Printf("FATAL: history: %v", err)
		os.Exit(1)
	}

	limits, err := LoadLimitations(*limitsPath)
	if err != nil {
		log.Printf("FATAL: limitations config: %v", err)
		os.Exit(1)
	}

	// Places are optional: the report still stands without them, it just
	// cannot be audited. Warn rather than refuse to start.
	places, perr := LoadPlaces(filepath.Join(*dataDir, "places.parquet"))
	if perr != nil {
		log.Printf("WARNING: place-level table unavailable (%v) — /places will 503", perr)
	} else {
		log.Printf("places loaded: %d records", places.total)
	}

	app := &App{store: store, history: hist, places: places, geo: NewGeocoder(), th: th, limits: limits}
	mux := http.NewServeMux()
	// JSON lives under /api. It used to sit at the root, which collided the
	// moment /report also had to serve HTML for share previews — one path
	// cannot be both a document and an endpoint. The frontend already called
	// it /api/... through a proxy rewrite, so this only removes the rewrite.
	mux.HandleFunc("/api/report", app.handleReport)
	mux.HandleFunc("/api/places", app.handlePlaces)
	mux.HandleFunc("/api/geocode/reverse", app.handleReverse)
	mux.HandleFunc("/api/geocode/search", app.handleSearch)
	mux.HandleFunc("/api/coverage", app.handleCoverage)
	mountHTML(mux, app, *webDir)
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})

	log.Printf("thirdeye api listening on %s", *addr)
	log.Fatal(http.ListenAndServe(*addr, mux))
}

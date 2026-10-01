package main

import (
	"bytes"
	"compress/gzip"
	"io/fs"
	"mime"
	"net/http"
	"os"
	"path"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

// COMPRESSION. Nothing used to be compressed: a first visit moved 6.17 MB
// that gzip brings to 1.09 MB (measured 2026-09-30). Two shapes, because the
// costs differ:
//
//   - Static files never change while a container runs (the image is the
//     deploy), so each is gzipped ONCE, on first request, and kept. Doing it
//     per request would cost 50-170 ms of CPU for the geojson alone.
//   - API responses are per request and small (2-325 KB raw), so they are
//     compressed as they are written.

// acceptsGzip reports whether the client takes gzip ("gzip;q=0" refuses it).
func acceptsGzip(r *http.Request) bool {
	for _, part := range strings.Split(r.Header.Get("Accept-Encoding"), ",") {
		fields := strings.Split(part, ";")
		if strings.TrimSpace(fields[0]) != "gzip" {
			continue
		}
		for _, f := range fields[1:] {
			if q := strings.TrimSpace(f); q == "q=0" || q == "q=0.0" || q == "q=0.00" || q == "q=0.000" {
				return false
			}
		}
		return true
	}
	return false
}

// compressible lists the static formats worth gzipping. Images and fonts are
// already compressed; gzipping them again costs CPU and saves nothing.
var compressible = map[string]string{
	".js":          "text/javascript; charset=utf-8",
	".css":         "text/css; charset=utf-8",
	".json":        "application/json",
	".geojson":     "application/geo+json",
	".svg":         "image/svg+xml",
	".txt":         "text/plain; charset=utf-8",
	".webmanifest": "application/manifest+json",
	".html":        "text/html; charset=utf-8",
}

type gzEntry struct {
	once sync.Once
	gz   []byte
	mod  time.Time
	err  error
}

type gzCache struct{ m sync.Map } // file path -> *gzEntry

func (c *gzCache) get(file string) ([]byte, time.Time, error) {
	v, _ := c.m.LoadOrStore(file, &gzEntry{})
	e := v.(*gzEntry)
	e.once.Do(func() {
		st, err := os.Stat(file)
		if err != nil {
			e.err = err
			return
		}
		b, err := os.ReadFile(file)
		if err != nil {
			e.err = err
			return
		}
		var buf bytes.Buffer
		zw, _ := gzip.NewWriterLevel(&buf, gzip.BestCompression)
		_, _ = zw.Write(b)
		_ = zw.Close()
		e.gz, e.mod = buf.Bytes(), st.ModTime()
	})
	return e.gz, e.mod, e.err
}

// warm compresses every compressible file under dir in the background at
// startup, so no visitor waits for the first compression (~0.3 s for the
// geojson at BestCompression, measured locally).
func (c *gzCache) warm(dir string) {
	_ = filepath.WalkDir(dir, func(p string, d fs.DirEntry, err error) error {
		if err == nil && !d.IsDir() {
			if _, ok := compressible[path.Ext(p)]; ok {
				_, _, _ = c.get(p)
			}
		}
		return nil
	})
}

// serveGzipped answers from the cached gzip copy when the client accepts it.
// It returns false to let the caller serve the plain file instead: no gzip in
// Accept-Encoding, a Range request (ranges are served from the plain file),
// or a format not worth compressing.
func (c *gzCache) serveGzipped(w http.ResponseWriter, r *http.Request, file, urlPath string) bool {
	ctype, ok := compressible[path.Ext(urlPath)]
	if !ok || !acceptsGzip(r) || r.Header.Get("Range") != "" {
		return false
	}
	gz, mod, err := c.get(file)
	if err != nil {
		return false
	}
	h := w.Header()
	h.Set("Content-Type", ctype)
	h.Set("Content-Encoding", "gzip")
	h.Add("Vary", "Accept-Encoding")
	http.ServeContent(w, r, "", mod, bytes.NewReader(gz))
	return true
}

// staticCacheControl: Vite content-hashes everything under /assets/, so a
// changed file gets a new name and the old one can be cached forever. The
// rest (the coverage geojson, summaries, icons) keeps its name across data
// rebuilds, so it gets an hour: long enough for repeat visits, short enough
// that a monthly data deploy shows up the same day.
func staticCacheControl(urlPath string) string {
	if strings.HasPrefix(urlPath, "/assets/") {
		return "public, max-age=31536000, immutable"
	}
	return "public, max-age=3600"
}

// gzipResponses compresses an API handler's output for clients that accept
// gzip. Every /api route goes through it.
func gzipResponses(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !acceptsGzip(r) || r.Method == http.MethodHead {
			next(w, r)
			return
		}
		w.Header().Add("Vary", "Accept-Encoding")
		gw := &gzipWriter{ResponseWriter: w}
		defer gw.close()
		next(gw, r)
	}
}

type gzipWriter struct {
	http.ResponseWriter
	zw          *gzip.Writer
	wroteHeader bool
	plain       bool // status has no body (204, 304): pass through untouched
}

func (g *gzipWriter) WriteHeader(code int) {
	if g.wroteHeader {
		return
	}
	g.wroteHeader = true
	if code == http.StatusNoContent || code == http.StatusNotModified {
		g.plain = true
	} else {
		h := g.Header()
		h.Del("Content-Length")
		h.Set("Content-Encoding", "gzip")
	}
	g.ResponseWriter.WriteHeader(code)
}

func (g *gzipWriter) Write(b []byte) (int, error) {
	if !g.wroteHeader {
		if g.Header().Get("Content-Type") == "" {
			g.Header().Set("Content-Type", http.DetectContentType(b))
		}
		g.WriteHeader(http.StatusOK)
	}
	if g.plain {
		return g.ResponseWriter.Write(b)
	}
	if g.zw == nil {
		g.zw, _ = gzip.NewWriterLevel(g.ResponseWriter, gzip.DefaultCompression)
	}
	return g.zw.Write(b)
}

func (g *gzipWriter) close() {
	if g.zw != nil {
		_ = g.zw.Close()
	}
}

func init() {
	// The standard table has no entry for .geojson; keep a sniffed
	// text/plain from reaching clients on the plain path.
	_ = mime.AddExtensionType(".geojson", "application/geo+json")
}

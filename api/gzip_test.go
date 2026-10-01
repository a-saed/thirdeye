package main

import (
	"bytes"
	"compress/gzip"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// WHY. Nothing was compressed (measured 2026-09-30): a first visit moved
// 6.17 MB that gzip brings to 1.09 MB, and /api/search answered 325 KB that
// gzips to 20 KB. Static files are compressed once per container and kept;
// API responses are compressed as they are written.

func gunzip(t *testing.T, b []byte) []byte {
	t.Helper()
	zr, err := gzip.NewReader(bytes.NewReader(b))
	if err != nil {
		t.Fatalf("body is not gzip: %v", err)
	}
	out, err := io.ReadAll(zr)
	if err != nil {
		t.Fatal(err)
	}
	return out
}

func staticFixture(t *testing.T) (http.Handler, map[string][]byte) {
	t.Helper()
	dir := t.TempDir()
	files := map[string][]byte{
		"index.html":            []byte("<!doctype html><title>t</title>"),
		"coverage-res8.geojson": bytes.Repeat([]byte(`{"type":"Feature","properties":{"h3":"881f1d4887fffff"}},`), 2000),
		"assets/index-abc.js":   bytes.Repeat([]byte("console.log('third eye');"), 2000),
		"icon-192.png":          bytes.Repeat([]byte{0x89, 'P', 'N', 'G'}, 500),
	}
	for name, b := range files {
		p := filepath.Join(dir, filepath.FromSlash(name))
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, b, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	h, err := newSPAHandler(dir)
	if err != nil {
		t.Fatal(err)
	}
	return h, files
}

func fetch(h http.Handler, path string, hdr map[string]string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(http.MethodGet, path, nil)
	for k, v := range hdr {
		req.Header.Set(k, v)
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func TestStaticFilesGzippedWhenAccepted(t *testing.T) {
	h, files := staticFixture(t)
	for _, name := range []string{"coverage-res8.geojson", "assets/index-abc.js"} {
		rec := fetch(h, "/"+name, map[string]string{"Accept-Encoding": "gzip, deflate, br"})
		if rec.Code != 200 {
			t.Fatalf("%s: status %d", name, rec.Code)
		}
		if rec.Header().Get("Content-Encoding") != "gzip" {
			t.Fatalf("%s: not gzipped", name)
		}
		if !strings.Contains(rec.Header().Get("Vary"), "Accept-Encoding") {
			t.Fatalf("%s: missing Vary: Accept-Encoding", name)
		}
		if got := gunzip(t, rec.Body.Bytes()); !bytes.Equal(got, files[name]) {
			t.Fatalf("%s: decompressed body differs from the file", name)
		}
		if rec.Body.Len() >= len(files[name]) {
			t.Fatalf("%s: gzip did not shrink it", name)
		}
	}
}

func TestStaticFilesPlainWhenNotAcceptedOrRanged(t *testing.T) {
	h, files := staticFixture(t)
	rec := fetch(h, "/coverage-res8.geojson", nil)
	if rec.Header().Get("Content-Encoding") != "" || !bytes.Equal(rec.Body.Bytes(), files["coverage-res8.geojson"]) {
		t.Fatal("client without gzip must get the plain file")
	}
	rec = fetch(h, "/coverage-res8.geojson", map[string]string{"Accept-Encoding": "gzip", "Range": "bytes=0-9"})
	if rec.Header().Get("Content-Encoding") != "" || rec.Code != http.StatusPartialContent {
		t.Fatalf("a range request must be served from the plain file, got %d %q", rec.Code, rec.Header().Get("Content-Encoding"))
	}
	rec = fetch(h, "/icon-192.png", map[string]string{"Accept-Encoding": "gzip"})
	if rec.Header().Get("Content-Encoding") != "" {
		t.Fatal("already-compressed formats must not be gzipped")
	}
}

func TestStaticCacheHeaders(t *testing.T) {
	h, _ := staticFixture(t)
	if cc := fetch(h, "/assets/index-abc.js", nil).Header().Get("Cache-Control"); cc != "public, max-age=31536000, immutable" {
		t.Fatalf("hashed asset Cache-Control = %q", cc)
	}
	if cc := fetch(h, "/coverage-res8.geojson", map[string]string{"Accept-Encoding": "gzip"}).Header().Get("Cache-Control"); cc != "public, max-age=3600" {
		t.Fatalf("geojson Cache-Control = %q", cc)
	}
}

func TestSPAShellStillServedWithGzip(t *testing.T) {
	h, _ := staticFixture(t)
	rec := fetch(h, "/nope", map[string]string{"Accept-Encoding": "gzip"})
	if rec.Code != http.StatusNotFound {
		t.Fatalf("unknown path status %d, want 404", rec.Code)
	}
}

func TestAPIResponsesGzipped(t *testing.T) {
	body := strings.Repeat(`{"metric":"business_count.cafe","value":37},`, 300)
	h := gzipResponses(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, body)
	})
	rec := fetch(h, "/api/report", map[string]string{"Accept-Encoding": "gzip"})
	if rec.Header().Get("Content-Encoding") != "gzip" || string(gunzip(t, rec.Body.Bytes())) != body {
		t.Fatal("API JSON must be gzipped and decompress to the original")
	}
	if rec.Header().Get("Content-Length") != "" {
		t.Fatal("Content-Length of the plain body must not survive compression")
	}
	rec = fetch(h, "/api/report", nil)
	if rec.Header().Get("Content-Encoding") != "" || rec.Body.String() != body {
		t.Fatal("client without gzip must get plain JSON")
	}
}

package main

import (
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// THE STATUS IS PART OF THE ANSWER.
//
// A single-page app's history fallback serves index.html for every path, so
// the server reports 200 for an address that does not exist. For a product
// whose argument is that it says what it does not have, a success status on a
// missing page is the wrong default — and it lets a crawler index every
// typo'd URL as a real page. docs/DEPLOYMENT.md records this; these tests are
// what stop it coming back.

const indexMarker = `<div id="root"></div>`

func newTestSPADir(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "index.html"),
		[]byte("<!doctype html><html><body>"+indexMarker+"</body></html>"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(dir, "assets"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "assets", "app.js"),
		[]byte("console.log('real asset')"), 0o644); err != nil {
		t.Fatal(err)
	}
	return dir
}

func get(t *testing.T, h http.Handler, path string) *httptest.ResponseRecorder {
	t.Helper()
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
	return rec
}

func TestUnknownPathReturns404ButStillRendersTheApp(t *testing.T) {
	h, err := newSPAHandler(newTestSPADir(t))
	if err != nil {
		t.Fatal(err)
	}
	rec := get(t, h, "/no-such-page")

	if rec.Code != http.StatusNotFound {
		t.Errorf("status = %d, want 404 — a missing address must not report success", rec.Code)
	}
	// The body is still the app, so the SPA renders its own 404 screen rather
	// than the browser's. Status and body carry different jobs here.
	if !strings.Contains(rec.Body.String(), indexMarker) {
		t.Errorf("body did not contain the app shell; got %q", rec.Body.String())
	}
}

func TestRootIsServedWith200(t *testing.T) {
	h, err := newSPAHandler(newTestSPADir(t))
	if err != nil {
		t.Fatal(err)
	}
	rec := get(t, h, "/")

	if rec.Code != http.StatusOK {
		t.Errorf("status = %d, want 200", rec.Code)
	}
	if !strings.Contains(rec.Body.String(), indexMarker) {
		t.Error("root did not serve the app shell")
	}
}

func TestKnownAppRouteIsServedWith200(t *testing.T) {
	h, err := newSPAHandler(newTestSPADir(t))
	if err != nil {
		t.Fatal(err)
	}
	// /tokens is a real screen in main.jsx's route table but has no file on
	// disk — the classic case a history fallback exists for.
	rec := get(t, h, "/tokens")

	if rec.Code != http.StatusOK {
		t.Errorf("status = %d, want 200 for a known app route", rec.Code)
	}
}

func TestExistingAssetIsServedVerbatim(t *testing.T) {
	h, err := newSPAHandler(newTestSPADir(t))
	if err != nil {
		t.Fatal(err)
	}
	rec := get(t, h, "/assets/app.js")

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if got := rec.Body.String(); got != "console.log('real asset')" {
		t.Errorf("asset body = %q, want the file's contents", got)
	}
}

func TestMissingAssetIs404AndNotTheAppShell(t *testing.T) {
	h, err := newSPAHandler(newTestSPADir(t))
	if err != nil {
		t.Fatal(err)
	}
	// A missing script must fail as a script. Returning HTML with a 200 here
	// is how a broken deploy looks like a working one: the browser fetches
	// index.html, tries to execute it as JavaScript, and reports a syntax
	// error instead of a missing file.
	rec := get(t, h, "/assets/does-not-exist.js")

	if rec.Code != http.StatusNotFound {
		t.Errorf("status = %d, want 404", rec.Code)
	}
	if strings.Contains(rec.Body.String(), indexMarker) {
		t.Error("a missing asset was answered with the app shell")
	}
}

func TestDirectoryTraversalIsRefused(t *testing.T) {
	dir := newTestSPADir(t)
	secret := filepath.Join(filepath.Dir(dir), "secret.txt")
	if err := os.WriteFile(secret, []byte("do not serve me"), 0o644); err != nil {
		t.Fatal(err)
	}
	h, err := newSPAHandler(dir)
	if err != nil {
		t.Fatal(err)
	}
	rec := get(t, h, "/../secret.txt")

	if strings.Contains(rec.Body.String(), "do not serve me") {
		t.Fatal("served a file from outside the SPA directory")
	}
}

func TestMissingIndexIsAStartupError(t *testing.T) {
	// Refuse to start rather than serve 404s for every path — a container
	// built without the SPA should fail loudly, not quietly serve nothing.
	if _, err := newSPAHandler(t.TempDir()); err == nil {
		t.Error("expected an error when index.html is absent")
	}
}

// The mount order matters as much as the handler. A catch-all registered for
// "/" must not shadow the JSON API or the meta-rendered document routes.
func TestMountSPADoesNotShadowTheAPI(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/ping", func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("pong"))
	})
	if err := mountSPA(mux, newTestSPADir(t)); err != nil {
		t.Fatal(err)
	}

	if rec := get(t, mux, "/api/ping"); rec.Body.String() != "pong" {
		t.Errorf("/api/ping = %q, want \"pong\" — the SPA catch-all shadowed the API",
			rec.Body.String())
	}
	if rec := get(t, mux, "/"); rec.Code != http.StatusOK {
		t.Errorf("/ status = %d, want 200", rec.Code)
	}
	if rec := get(t, mux, "/nope"); rec.Code != http.StatusNotFound {
		t.Errorf("/nope status = %d, want 404", rec.Code)
	}
}

// Cloud Run's frontend swallows exactly /healthz — it never reaches the
// container, while /health, /healthz/ and /healthzz all do. Verified against
// the deployed service on 2026-09-07. Nothing depended on it (the startup
// probe is TCP), but a health endpoint that answers locally and 404s in
// production is a trap for whoever configures monitoring next. So the app
// answers on both paths, and /api/healthz is the one to point anything at.
func TestHealthAnswersOnAPathCloudRunDoesNotIntercept(t *testing.T) {
	mux := http.NewServeMux()
	mountHealth(mux)

	for _, path := range []string{"/healthz", "/api/healthz"} {
		rec := get(t, mux, path)
		if rec.Code != http.StatusOK {
			t.Errorf("%s status = %d, want 200", path, rec.Code)
		}
		if got := strings.TrimSpace(rec.Body.String()); got != "ok" {
			t.Errorf("%s body = %q, want \"ok\"", path, got)
		}
	}
}

package main

import (
	"fmt"
	"net/http"
	"os"
	"path"
	"path/filepath"
	"strings"
)

// SERVING THE BUILT SPA, WITH HONEST STATUS CODES.
//
// A history fallback serves index.html for every path, so the server reports
// 200 for an address that does not exist. docs/DEPLOYMENT.md records this as
// a bug and puts the fix in nginx — which was right when a static host sat in
// front. It is not right for a single container on Cloud Run, where this
// binary is the only thing answering. So the rule moves here.
//
// Three answers, not two:
//   - a real file            -> 200, the file
//   - a known app route      -> 200, the app shell
//   - anything else          -> 404, AND the app shell
//
// The last one is the point. Status and body do different jobs: the status
// tells a crawler the address is not real, the body still renders the app's
// own "we don't have that" screen rather than the browser's default. Getting
// only one of those right is what the bug was.

// spaRoutes must match the PAGES table in web/src/main.jsx. A path listed
// here that the bundle does not know would render the app's own 404 under a
// 200 status — exactly the defect this file removes, reintroduced by drift.
var spaRoutes = map[string]bool{
	"/report":  true,
	"/compare": true,
	"/search":  true,
	"/tokens":  true,
}

type spaHandler struct {
	dir   string
	files http.Handler
	index []byte
}

// newSPAHandler fails when index.html is absent rather than starting and
// answering 404 for every path: a container built without the bundle should
// be loud, not quietly empty.
func newSPAHandler(dir string) (http.Handler, error) {
	index, err := os.ReadFile(filepath.Join(dir, "index.html"))
	if err != nil {
		return nil, fmt.Errorf("index.html in %s: %w", dir, err)
	}
	return &spaHandler{
		dir:   dir,
		files: http.FileServer(http.Dir(dir)),
		index: index,
	}, nil
}

func (s *spaHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	// Clean before touching the filesystem: "/../secret" becomes "/secret",
	// so a traversal cannot escape dir even before http.Dir's own check.
	clean := path.Clean("/" + strings.TrimPrefix(r.URL.Path, "/"))

	if clean != "/" {
		if st, err := os.Stat(filepath.Join(s.dir, filepath.FromSlash(clean))); err == nil && !st.IsDir() {
			r2 := *r
			u := *r.URL
			u.Path = clean
			r2.URL = &u
			s.files.ServeHTTP(w, &r2)
			return
		}
	}

	// A missing asset must fail AS AN ASSET. Answering a missing .js with
	// index.html is how a broken deploy imitates a working one: the browser
	// executes HTML as JavaScript and reports a syntax error rather than a
	// missing file, which sends you looking in entirely the wrong place.
	if path.Ext(clean) != "" {
		http.NotFound(w, r)
		return
	}

	status := http.StatusNotFound
	if clean == "/" || spaRoutes[strings.TrimSuffix(clean, "/")] {
		status = http.StatusOK
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.WriteHeader(status)
	_, _ = w.Write(s.index)
}

// mountSPA registers the catch-all. Call it AFTER the /api handlers and the
// meta-rendered document routes: Go's ServeMux prefers the longest matching
// pattern, so "/" only answers what nothing else claimed.
func mountSPA(mux *http.ServeMux, dir string) error {
	h, err := newSPAHandler(dir)
	if err != nil {
		return err
	}
	mux.Handle("/", h)
	return nil
}

// mountHealth answers on two paths for one reason: Cloud Run's frontend
// intercepts exactly "/healthz" and never forwards it to the container, so
// the obvious name is unusable in production while working perfectly in
// development. "/healthz" stays because scripts/_common.sh polls it locally;
// "/api/healthz" is the one to point a monitor at.
func mountHealth(mux *http.ServeMux) {
	ok := func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	}
	mux.HandleFunc("/healthz", ok)
	mux.HandleFunc("/api/healthz", ok)
}

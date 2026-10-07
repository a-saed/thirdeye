package main

import (
	"encoding/json"
	"net/http"
	"sort"
)

// TEMPORARY (2026-10-07): shows how a request arrives through each entrance
// (run.app directly vs the Firebase Hosting rewrite), so clientIP can be
// fixed from evidence rather than from documentation. Echoes only the
// caller's own forwarding headers and the NAMES of the rest. Remove once read.
func handleDebugIP(w http.ResponseWriter, r *http.Request) {
	fwd := map[string]string{}
	for _, h := range []string{"X-Forwarded-For", "Forwarded", "X-Forwarded-Host", "X-Forwarded-Proto",
		"Fastly-Client-Ip", "X-Real-Ip", "X-Client-Ip", "X-Appengine-User-Ip", "Via", "X-Firebase-Hosting", "Cdn-Loop"} {
		if v := r.Header.Get(h); v != "" {
			fwd[h] = v
		}
	}
	names := make([]string, 0, len(r.Header))
	for k := range r.Header {
		names = append(names, k)
	}
	sort.Strings(names)
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	_ = json.NewEncoder(w).Encode(map[string]any{
		"remote_addr": r.RemoteAddr, "host": r.Host, "client_ip_today": clientIP(r),
		"forwarding": fwd, "header_names": names,
	})
}

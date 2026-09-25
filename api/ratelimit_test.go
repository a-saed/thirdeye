package main

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

// WHY THE SECOND-TO-LAST X-Forwarded-For ENTRY.
//
// Cloud Run appends TWO addresses: the client it actually observed, then the
// load balancer. It does NOT validate entries already present, so anything to
// the left of those two is attacker-supplied. Taking XFF[0] - the usual
// shortcut - means a forged header buys an unlimited quota, and taking the
// last entry buckets every visitor under one load-balancer address. Neither
// is a rate limiter.

func TestClientIPUsesTheAddressCloudRunObserved(t *testing.T) {
	r := httptest.NewRequest("GET", "/api/report", nil)
	r.Header.Set("X-Forwarded-For", "203.0.113.7, 130.211.0.1")
	if got := clientIP(r); got != "203.0.113.7" {
		t.Fatalf("clientIP = %q, want 203.0.113.7", got)
	}
}

func TestClientIPIgnoresSpoofedLeadingEntries(t *testing.T) {
	r := httptest.NewRequest("GET", "/api/report", nil)
	// The caller forged the first two entries to dodge their bucket.
	r.Header.Set("X-Forwarded-For", "1.1.1.1, 2.2.2.2, 203.0.113.7, 130.211.0.1")
	if got := clientIP(r); got != "203.0.113.7" {
		t.Fatalf("clientIP = %q, want 203.0.113.7 (spoofed prefix must be ignored)", got)
	}
}

func TestClientIPFallsBackToRemoteAddrOffCloudRun(t *testing.T) {
	r := httptest.NewRequest("GET", "/api/report", nil)
	r.RemoteAddr = "198.51.100.4:51234"
	if got := clientIP(r); got != "198.51.100.4" {
		t.Fatalf("clientIP = %q, want 198.51.100.4", got)
	}
}

func TestLimiterAllowsBurstThenDenies(t *testing.T) {
	clock := time.Unix(0, 0)
	l := newLimiter(60, 3, 100, func() time.Time { return clock })
	for i := 0; i < 3; i++ {
		if !l.allow("ip") {
			t.Fatalf("request %d denied inside burst of 3", i+1)
		}
	}
	if l.allow("ip") {
		t.Fatal("4th request allowed; burst of 3 not enforced")
	}
}

func TestLimiterRefillsOverTime(t *testing.T) {
	clock := time.Unix(0, 0)
	l := newLimiter(60, 1, 100, func() time.Time { return clock }) // 60/min = 1/s
	if !l.allow("ip") {
		t.Fatal("first request denied")
	}
	if l.allow("ip") {
		t.Fatal("second request allowed with an empty bucket")
	}
	clock = clock.Add(time.Second)
	if !l.allow("ip") {
		t.Fatal("request denied after a full second of refill")
	}
}

func TestLimiterNeverRefillsBeyondBurst(t *testing.T) {
	clock := time.Unix(0, 0)
	l := newLimiter(60, 2, 100, func() time.Time { return clock })
	clock = clock.Add(time.Hour) // idle for an hour
	if !l.allow("ip") || !l.allow("ip") {
		t.Fatal("burst not available after idling")
	}
	if l.allow("ip") {
		t.Fatal("an hour of idling banked more than the burst")
	}
}

func TestLimiterBucketsEachClientSeparately(t *testing.T) {
	clock := time.Unix(0, 0)
	l := newLimiter(60, 1, 100, func() time.Time { return clock })
	if !l.allow("a") {
		t.Fatal("first client denied")
	}
	if !l.allow("b") {
		t.Fatal("second client denied because the first spent its own quota")
	}
}

func TestLimiterBoundsMemoryUnderSpoofedKeys(t *testing.T) {
	// A limiter that allocates per key without a ceiling is itself the
	// amplification vector: forged addresses become unbounded memory on a
	// 1 GiB instance.
	clock := time.Unix(0, 0)
	l := newLimiter(60, 1, 8, func() time.Time { return clock })
	for i := 0; i < 500; i++ {
		l.allow(string(rune('a'+i%26)) + string(rune('0'+i/26)))
	}
	if n := l.size(); n > 8 {
		t.Fatalf("limiter holds %d buckets, cap is 8", n)
	}
}

func TestMiddlewarePassesRequestsUnderTheLimit(t *testing.T) {
	clock := time.Unix(0, 0)
	l := newLimiter(60, 2, 100, func() time.Time { return clock })
	h := rateLimited(l, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	r := httptest.NewRequest("GET", "/api/report", nil)
	r.Header.Set("X-Forwarded-For", "203.0.113.7, 130.211.0.1")
	w := httptest.NewRecorder()
	h(w, r)
	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", w.Code)
	}
}

func TestMiddlewareReturns429WithRetryAfter(t *testing.T) {
	clock := time.Unix(0, 0)
	l := newLimiter(60, 1, 100, func() time.Time { return clock })
	called := 0
	h := rateLimited(l, func(w http.ResponseWriter, r *http.Request) { called++ })
	newReq := func() *http.Request {
		r := httptest.NewRequest("GET", "/api/report", nil)
		r.Header.Set("X-Forwarded-For", "203.0.113.7, 130.211.0.1")
		return r
	}
	h(httptest.NewRecorder(), newReq()) // spends the bucket

	w := httptest.NewRecorder()
	h(w, newReq())
	if w.Code != http.StatusTooManyRequests {
		t.Fatalf("status = %d, want 429", w.Code)
	}
	if w.Header().Get("Retry-After") == "" {
		t.Error("429 without Retry-After leaves a caller no way to back off politely")
	}
	if called != 1 {
		t.Errorf("handler ran %d times; the limited request must not reach it", called)
	}
}

// The two limits exist because the two risks differ: /api/geocode leaves our
// name on someone else's server, everything else only costs egress.

func TestGeocodeRoutesGetTheTighterLimit(t *testing.T) {
	gen := newLimiter(60, 20, 10, nil)
	geo := newLimiter(6, 3, 10, nil)
	for _, p := range []string{"/api/geocode/search", "/api/geocode/reverse"} {
		if limiterFor(p, gen, geo) != geo {
			t.Errorf("%s did not get the geocode limiter", p)
		}
	}
	for _, p := range []string{"/api/report", "/api/places", "/api/search", "/api/coverage"} {
		if limiterFor(p, gen, geo) != gen {
			t.Errorf("%s did not get the general limiter", p)
		}
	}
}

func TestProductionGeocodeLimitIsStricterThanGeneral(t *testing.T) {
	gen, geo := newAPILimiters()
	if geo.perSec >= gen.perSec {
		t.Fatalf("geocode rate %.3f/s is not stricter than general %.3f/s", geo.perSec, gen.perSec)
	}
}

func TestProductionGeocodeLimitStaysUnderNominatimPolicy(t *testing.T) {
	// Nominatim's policy is 1 request/second, enforced by banning the caller.
	// One client must not be able to spend that budget alone.
	_, geo := newAPILimiters()
	if geo.perSec > 1.0 {
		t.Fatalf("a single client may send %.2f geocodes/s; Nominatim allows 1/s in total", geo.perSec)
	}
}

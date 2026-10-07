package main

import (
	"math"
	"net"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"
)

// PER-CLIENT RATE LIMITING, IN MEMORY.
//
// No store, no Redis — the same reasoning as the rest of the API. One Cloud
// Run instance is the process and nothing else, and at this traffic a limit
// that resets when an instance recycles is not a weakness worth a dependency.
//
// WHAT THIS DEFENDS. Not a distributed attack — that never reaches Go code,
// and stopping it needs something in front (see docs/DEPLOYMENT.md). It
// defends the two things that actually break at one visitor's hands: our
// standing with Nominatim, whose usage policy is enforced by banning the
// caller, and the egress bill, since /api/places answers up to 215 KB.

// clientIP returns the address Google's infrastructure observed, NOT the one
// the caller claims. Measured 2026-10-07 (ratelimit_test.go has the shapes):
// Cloud Run appends exactly ONE entry to X-Forwarded-For, the peer it saw, and
// keeps whatever the caller sent to the left of it. Directly on run.app that
// peer is the client. Through Firebase Hosting the peer is a Google front end,
// and the entry before it is the client as Hosting saw it; Hosting discards a
// caller-supplied X-Forwarded-For, so that entry is trustworthy too.
//
// Anything else to the left is caller-controlled. The previous rule (always
// second-to-last) assumed Cloud Run appended two entries, and let anyone send
// "X-Forwarded-For: <anything>" to get a fresh quota on run.app.
func clientIP(r *http.Request) string {
	if xff := r.Header.Get("X-Forwarded-For"); xff != "" {
		parts := strings.Split(xff, ",")
		for i := range parts {
			parts[i] = strings.TrimSpace(parts[i])
		}
		last := parts[len(parts)-1]
		if len(parts) >= 2 && isGoogleFrontEnd(last) {
			return parts[len(parts)-2]
		}
		return last
	}
	if host, _, err := net.SplitHostPort(r.RemoteAddr); err == nil {
		return host
	}
	return r.RemoteAddr
}

// GOOGLE FRONT ENDS: addresses Firebase Hosting reaches Cloud Run from.
// Every range is in Google's own list (gstatic.com/ipranges/goog.json) and
// in NONE of the customer-rentable ranges (cloud.json), checked 2026-10-07 -
// so a caller on a cloud VM cannot pass as Hosting. Observed peers 142.250.32.4
// and 66.249.93.x fall inside. If Hosting ever arrives from outside these, the
// symptom is the old one (Hosting visitors share one bucket), not a bypass.
var googleFrontEnds = func() []*net.IPNet {
	var out []*net.IPNet
	for _, c := range []string{
		"142.250.0.0/15", "66.249.64.0/19", "74.125.0.0/16", "172.217.0.0/16",
		"172.253.0.0/16", "64.233.160.0/19", "209.85.128.0/17", "108.177.0.0/17",
		"173.194.0.0/16", "216.58.192.0/19", "216.239.32.0/19",
		"130.211.0.0/22", "35.191.0.0/16", // Google load balancer front ends
	} {
		_, n, err := net.ParseCIDR(c)
		if err != nil {
			panic(err)
		}
		out = append(out, n)
	}
	return out
}()

func isGoogleFrontEnd(ip string) bool {
	a := net.ParseIP(ip)
	if a == nil {
		return false
	}
	for _, n := range googleFrontEnds {
		if n.Contains(a) {
			return true
		}
	}
	return false
}

type bucket struct {
	tokens float64
	last   time.Time
}

type limiter struct {
	mu       sync.Mutex
	buckets  map[string]*bucket
	perSec   float64
	burst    float64
	maxKeys  int
	now      func() time.Time
	fullSpan time.Duration // how long an empty bucket takes to refill completely
}

func newLimiter(perMinute float64, burst, maxKeys int, now func() time.Time) *limiter {
	if now == nil {
		now = time.Now
	}
	perSec := perMinute / 60
	return &limiter{
		buckets:  make(map[string]*bucket),
		perSec:   perSec,
		burst:    float64(burst),
		maxKeys:  maxKeys,
		now:      now,
		fullSpan: time.Duration(float64(burst) / perSec * float64(time.Second)),
	}
}

func (l *limiter) allow(key string) bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	t := l.now()
	b, ok := l.buckets[key]
	if !ok {
		if len(l.buckets) >= l.maxKeys {
			l.evictLocked(t)
		}
		b = &bucket{tokens: l.burst, last: t}
		l.buckets[key] = b
	}
	b.tokens = math.Min(l.burst, b.tokens+t.Sub(b.last).Seconds()*l.perSec)
	b.last = t
	if b.tokens < 1 {
		return false
	}
	b.tokens--
	return true
}

// evictLocked frees at least one slot. A bucket that has had time to refill
// completely is indistinguishable from one we have never seen, so dropping it
// costs nothing; only if none qualify do we evict the least recently used.
func (l *limiter) evictLocked(t time.Time) {
	for k, b := range l.buckets {
		if t.Sub(b.last) >= l.fullSpan {
			delete(l.buckets, k)
		}
		if len(l.buckets) < l.maxKeys {
			return
		}
	}
	var oldestKey string
	var oldest time.Time
	first := true
	for k, b := range l.buckets {
		if first || b.last.Before(oldest) {
			oldestKey, oldest, first = k, b.last, false
		}
	}
	if !first {
		delete(l.buckets, oldestKey)
	}
}

func (l *limiter) size() int {
	l.mu.Lock()
	defer l.mu.Unlock()
	return len(l.buckets)
}

// retryAfter is how long until one token exists, rounded up to whole seconds
// because that is the unit the header takes. Never below 1.
func (l *limiter) retryAfter() int {
	s := int(math.Ceil(1 / l.perSec))
	if s < 1 {
		return 1
	}
	return s
}

func rateLimited(l *limiter, next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !l.allow(clientIP(r)) {
			w.Header().Set("Retry-After", strconv.Itoa(l.retryAfter()))
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusTooManyRequests)
			// Say what happened and that it is a limit, not an outage —
			// the same standard the rest of the API holds itself to.
			_, _ = w.Write([]byte(`{"error":"rate limited","detail":"too many requests from this address; this is a per-client limit, not an outage","retry_after_s":` +
				strconv.Itoa(l.retryAfter()) + `}`))
			return
		}
		next(w, r)
	}
}

// PRODUCTION LIMITS.
//
// Generous enough that a person reading the map never sees a 429, tight
// enough that a script does immediately. Sized for the traffic this service
// actually has; raise them when there is evidence of real users hitting one,
// not in anticipation.
const (
	// A report view fires several calls (report, places, reverse geocode) and
	// panning refires them, so the general budget is per-second-ish.
	generalPerMinute = 60
	generalBurst     = 20

	// Nominatim allows 1 req/s IN TOTAL and enforces it by banning the
	// caller, so no single client may approach that alone. Six a minute is
	// more than anyone types and a tenth of the policy ceiling.
	geocodePerMinute = 6
	geocodeBurst     = 3

	// Bucket ceiling. Each is a few dozen bytes, so this is well under a
	// megabyte even when full, and it caps what forged addresses can cost.
	maxTrackedClients = 10000
)

func newAPILimiters() (general, geocode *limiter) {
	return newLimiter(generalPerMinute, generalBurst, maxTrackedClients, nil),
		newLimiter(geocodePerMinute, geocodeBurst, maxTrackedClients, nil)
}

// limiterFor picks the budget a path spends from. Geocoding is separate
// because the cost of abusing it is someone else's ban list, not our bill.
func limiterFor(path string, general, geocode *limiter) *limiter {
	if strings.HasPrefix(path, "/api/geocode/") {
		return geocode
	}
	return general
}

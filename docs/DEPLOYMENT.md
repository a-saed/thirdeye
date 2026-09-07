# Deployment

**Live: https://thirdeye-466032735471.us-central1.run.app**
Cloud Run, `us-central1`, 1 GiB, cpu 1, min-instances 0, max-instances 3.
Project `thirdeye-demo-260906`, image
`us-central1-docker.pkg.dev/thirdeye-demo-260906/thirdeye/api`.
First deployed 2026-09-07.

Deploying a new revision:

```
gcloud builds submit --tag us-central1-docker.pkg.dev/thirdeye-demo-260906/thirdeye/api:vN .
gcloud run deploy thirdeye --image us-central1-docker.pkg.dev/thirdeye-demo-260906/thirdeye/api:vN --region us-central1
```

`gcloud` runs under a separate configuration named `thirdeye` so the work
account and its project are never the active target. `gcloud config
configurations activate thirdeye` before deploying.

## Four things that cost real time to discover

**1. `gcloud builds submit` falls back to `.gitignore`.** With no
`.gcloudignore`, gcloud synthesises the upload-exclusion list from
`.gitignore` — which correctly excludes `data/` and `web/dist/` as derived
artefacts, and those are exactly the two directories the image bakes in. The
upload silently omits them and the build fails minutes later at `COPY
data/derived/h3_tables`, with an error that points at the Dockerfile rather
than at the upload. `.gcloudignore` exists to stop that fallback; keep it in
step with `.dockerignore`. The two answer different questions — what is
uploaded, versus what the daemon may read.

**2. `CGO_ENABLED=0` cannot build this.** `h3-go/v4` is a cgo binding to the C
H3 library with no pure-Go fallback; it fails with `build constraints exclude
all Go files`. The Dockerfile previously set `CGO_ENABLED=0` and asserted
h3-go was pure Go — meaning that image had never been built. It now builds
with cgo and static-links against musl (`-tags osusergo,netgo`,
`-extldflags=-static`) so the runtime stays a bare alpine. The same constraint
is why compiling this API to WebAssembly is not possible without replacing the
H3 dependency.

**3. Cloud Run's frontend intercepts exactly `/healthz`.** It never reaches
the container — verified against the live service: `/health`, `/healthz/` and
`/healthzz` all arrive, `/healthz` returns Google's own error page. Nothing
depended on it (the startup probe is TCP), but a health endpoint that works
locally and 404s in production is a monitoring trap. The app answers on
`/api/healthz` as well; point monitors at that one.

**4. The data is baked into the image, not mounted.** Cloud Run has no volume:
an instance is the image. A monthly pipeline run therefore needs a rebuild and
redeploy rather than a file copy — and a bad data build rolls back by routing
traffic to the previous revision.

## Still open

- **A budget kill-switch.** GCP budget alerts *notify*; they do not stop
  spending. A real cap needs budget → Pub/Sub → a function that detaches the
  billing account. The $300 trial pauses rather than bills, so this becomes
  urgent only when the trial ends.
- **The trial ends after 90 days** (~2026-12-06). The current configuration is
  deliberately the Always Free shape (`us-central1`, scale-to-zero, 1 GiB), so
  that date is a billing decision, not a migration.
- **Egress is not in the free tier**: 1 GB/month free, then ~$0.12/GB. At
  ~1.05 MB per first visit that is ~950 visitors/month. Moving the SPA and
  `coverage-res8.geojson` to Cloudflare Pages removes the ceiling entirely.
- A scheduler for `pipeline/sources/archive_release.py`.
- TLS and a domain: Cloud Run supplies both on `*.run.app`; a custom domain is
  still unregistered, and the contact link points at the GitHub repo.

## 404 must return a 404 status — FIXED 2026-09-06

`web/src/routes/notfound.tsx` renders a real "that page does not exist" page,
but **the HTTP status used to be 200**. A single-page app's history fallback
serves `index.html` for every path, so the server reported success for an
address that does not exist.

For a product whose argument is that it says what it does not have, a 200 on a
missing page is the wrong default. It also let search engines index every
typo'd URL as a real page.

**Where the fix lives: `api/spa.go`, not the host.**

This was originally written up as an nginx/Netlify/Vercel concern, which was
right while a static host sat in front. It is not right for a single container
on Cloud Run, where the Go binary is the only thing answering — so the rule
moved into the binary. `mountSPA` registers a catch-all *after* the `/api`
handlers and the meta-rendered document routes, and answers three ways:

| Request | Status | Body |
| --- | --- | --- |
| a real file (`/assets/app.js`) | 200 | the file |
| a known app route (`/`, `/tokens`, `/report`, `/compare`, `/search`) | 200 | the app shell |
| anything else (`/nope`) | **404** | the app shell |
| a missing asset (`/assets/gone.js`) | **404** | *not* the app shell |

The last two rows are the point. Status and body do different jobs: the status
tells a crawler the address is not real, while the body still renders the app's
own screen rather than the browser's default. And a missing asset must fail as
an asset — answering a missing `.js` with HTML is how a broken deploy imitates
a working one, since the browser then reports a syntax error rather than a
missing file.

`spaRoutes` in `api/spa.go` must stay in step with the `PAGES` table in
`web/src/main.jsx`. A route listed there that the bundle does not know would
reintroduce exactly this bug by drift.

Guarded by `api/spa_test.go` (8 tests). Verified against a running binary:

```
/nope                     404
/                         200
/tokens                   200
/report?lat=..&lon=..     200
/assets/missing.js        404
/api/coverage             200
```

If a static host (Cloudflare Pages, Netlify) is ever put in front of the API,
it needs the equivalent rule of its own — `_redirects` with a `404` on the
catch-all — because the Go handler will not see those requests.

## The API is the HTML origin for /report and /compare

Server-rendered meta tags landed for share previews, so those two paths are
**served by the Go API, not by a static host**. Facebook, LinkedIn, WhatsApp
and Slack do not execute JavaScript, so client-side `document.title` never
reached them and every shared report previewed as the generic home card.

Consequences for whatever hosting is chosen:

- `/report` and `/compare` must proxy to the API, which needs `-web` pointing
  at the built SPA directory (`web/dist`).
- Everything else — `/`, `/tokens`, `/assets/*`, the GeoJSON — can still be
  static.
- **JSON moved under `/api`.** It used to sit at the root, which collided the
  moment `/report` had to be a document as well as an endpoint. The dev proxy
  no longer rewrites the prefix.

```nginx
location /api/    { proxy_pass http://127.0.0.1:8080; }
location = /report  { proxy_pass http://127.0.0.1:8080; }
location = /compare { proxy_pass http://127.0.0.1:8080; }
location /         { try_files $uri $uri/ /index.html; }
```

Check: `curl -s 'https://HOST/report?lat=29.96&lon=31.26' | grep -o '<title>[^<]*'`
must show the place and figures, not the generic title.

Not built: a per-location OG **image** endpoint. The text tags carry most of
the value; an image needs a rendering library in Go.

## Other deployment work not yet started

- Hosting for the static bundle and the Go API; the API loads ~142 MB of
  parquet into RAM at startup and must be restarted after each monthly
  pipeline run.
- A scheduler for `pipeline/sources/archive_release.py`. It **must** run
  monthly: Overture's S3 keeps roughly two releases, the community mirror
  lags, and a release missing from both is gone permanently. 2026-06-17.0
  already is.
- TLS, and a domain. The contact link currently points at the GitHub repo's
  issues rather than an address.

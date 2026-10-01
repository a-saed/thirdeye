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

## CI/CD

`.github/workflows/deploy.yml` — **push to `main` deploys.** It runs the Go
tests and `go vet`, typechecks the web app, builds the SPA (which runs the
MapLibre style validator), builds the image on Cloud Build, deploys, and then
re-runs the acceptance checks below against the revision that just went live.
A red test never reaches the demo.

**No service-account key exists.** Auth is Workload Identity Federation: the
GitHub OIDC token is exchanged for a short-lived credential, and the provider
carries `assertion.repository=='a-saed/thirdeye'`, so no other repository can
use it. Nothing to leak and nothing to rotate.

```
pool      projects/466032735471/locations/global/workloadIdentityPools/github
provider  .../providers/github-provider
identity  github-deployer@thirdeye-demo-260906.iam.gserviceaccount.com
roles     run.admin, artifactregistry.writer, cloudbuild.builds.editor,
          storage.objectViewer, iam.serviceAccountUser
```

### Where the data comes from in CI

`data/` is gitignored — derived, and carrying source licences that should not
be redistributed from this repo — but the image bakes the tables in, because a
Cloud Run instance is the image and nothing else. So CI cannot build from a
git checkout alone. The tables live in **`gs://thirdeye-demo-260906-data/h3_tables`**
and the workflow pulls them before the build.

There are **two** sets of gitignored derived inputs, and both must be in
place before the build:

| What | Where in GCS | Consumed by |
| --- | --- | --- |
| `h3_tables/*.parquet` | `.../h3_tables` | the Go API, loaded into RAM at startup |
| `coverage-res8.geojson`, `coverage-summary.json`, `regions.json` | `.../web-public` | the SPA, fetched at runtime |

Missing the second set is quiet: every route still returns 200, the app still
renders, and the map is simply empty with "coverage layer: HTTP 404" in the
corner. It shipped exactly that way once, because the deployment checks
verified routes and not the assets the map cannot work without. They now
check the assets too.

**A monthly pipeline run is therefore two steps:**

```
gcloud storage cp -r data/derived/h3_tables gs://thirdeye-demo-260906-data/
gcloud storage cp web/public/coverage-res8.geojson \
                  web/public/coverage-summary.json \
                  web/public/regions.json \
                  gs://thirdeye-demo-260906-data/web-public/
gh workflow run "Deploy to Cloud Run"      # or push anything to main
```

The workflow has `workflow_dispatch`, so refreshing data needs no commit.

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

## Options that were evaluated and rejected

Recorded so the decision is not re-litigated from scratch. `fly.toml`,
`api/Dockerfile` and `deploy/nginx.conf` were deleted on 2026-09-07 — all
three described deployments we are not doing, and two of them were broken in
ways that would have wasted someone's afternoon.

| Option | Why not |
| --- | --- |
| **Fly.io** | $5.70/month for the 1 GB machine this needs. Not free. The `$1.24` figure on third-party sites is wrong. `fly.toml` also pointed at `api/Dockerfile`, sized the machine from a stale "~142 MB resident" figure (measured: 346 MB idle, 458 MB peak), and set `min_machines_running = 1`, which bills continuously. |
| **nginx on a VPS** | Superseded. `deploy/nginx.conf` split static files from the API and carried the 404 rule in the server config; the single Cloud Run container now serves both, and the 404 rule lives in `api/spa.go` where it is covered by tests. |
| **Render / Railway free** | 512 MB against a 458 MB measured peak — 54 MB of headroom — plus a 15-minute spin-down and ~1 minute cold start. |
| **Hugging Face Spaces** | Free CPU Basic has 16 GB, but Docker Spaces have required a paid PRO plan since July 2026. |
| **Oracle Cloud Always Free** | 12 GB ARM, genuinely free, but Ampere A1 capacity is rarely available, the tier was halved in June 2026 with no announcement, and it still requires a card. |
| **Fully static + client-side** | Genuinely free with no card: the whole res-9 dataset is 6.55 MB gzipped, and `h3-js` is already a frontend dependency. Blocked on `BuildReport` — porting it to TypeScript would put the threshold, land-fraction and confidence rules in two places, and compiling the Go to wasm is impossible because `h3-go` is a cgo binding. Still the best permanent answer if the free tier ever stops being enough. |

## Rate limiting

Every `/api` route is rate limited per client, in memory, in `api/ratelimit.go`.
Health checks are exempt — a limited health check reads as an outage.

| Scope | Budget | Why that number |
|---|---|---|
| `/api/geocode/*` | 6/min, burst 3 | Nominatim's policy is **1 req/s in total**, enforced by banning the caller. No single client may approach that alone. |
| every other `/api/*` | 60/min, burst 20 | A person reading the map never reaches it; a script reaches it at once. `/api/places` answers up to 215 KB, and egress is 1 GB/month free. |

**The client address is the SECOND-TO-LAST `X-Forwarded-For` entry.** Cloud Run
appends two — the client it observed, then the load balancer — and does not
validate whatever the caller already put there. Reading `XFF[0]`, the usual
shortcut, means a forged header buys an unlimited quota; reading the last entry
buckets every visitor on earth together. Verified against a running instance:
30 plain requests mixed with 30 carrying a forged prefix, all naming one victim
IP, yielded 20x200 and 40x429 — one shared bucket.

**THIS BREAKS BEHIND THE FIREBASE HOSTING FRONT DOOR — 2026-09-25.** A request
that arrives via `thirdeye-app.web.app` reaches Cloud Run from a Hosting
frontend, not from the visitor. Two marked probes, one through each entrance,
seconds apart:

| entrance | `httpRequest.remoteIp` in the Cloud Run request log |
|---|---|
| `thirdeye-app.web.app` | `66.249.93.230` — a Google frontend |
| `thirdeye-hiecbobtpa-uc.a.run.app` | `196.157.42.147` — the real caller |

Cloud Run appends *the client it observed*, and what it observed is the Hosting
frontend. So the second-to-last entry is a Google frontend address for every
visitor arriving through the front door — and that holds whether or not Hosting
also passes the original client in `XFF[0]`, because either chain shape puts the
frontend in that position. The effect is exactly what this rule exists to
prevent: one shared bucket. At 6/min burst 3, the fourth stranger to type a
search gets a 429.

**Not fixed yet.** The header Hosting actually sends has not been read — the API
echoes no headers and adding an endpoint that does is a production deploy — and
that reading is what decides the fix: whether `XFF[0]` is trustworthy when it
arrives through Hosting, or whether the client is only recoverable by stripping
known Google frontend ranges from the right. Until then the run.app URL remains
the entrance with correct per-client limiting, and both entrances stay open.

**WHAT THIS DOES NOT DO: stop a DDoS.** A distributed attack never reaches Go
code, and Cloud Run bills for requests it rejects. What bounds the damage is
`--max-instances 3` (already set), and what would bound it absolutely is a
billing kill-switch, which is still open below. Putting Cloudflare in front
would absorb volumetric traffic and serve the static payloads for free; that is
the real answer if this ever gets popular.

## The Firebase Hosting front door — thirdeye-app.web.app, 2026-09-25

`*.run.app` URLs are unreadable, so Firebase Hosting sits in front purely as a
name. `firebase.json` holds one rewrite — `"**"` to the Cloud Run service — and
`firebase-public/` is deliberately empty: nothing is served by Hosting, every
path falls through to the container. That shape was chosen over serving the SPA
from Hosting for one reason: `api/spa.go` gives unknown paths a 404 *status*
with the app shell as the body, and Hosting's SPA rewrite returns 200 for
everything. Moving static files to Hosting would mean reimplementing the
`spaRoutes` table in `firebase.json`, where `api/spa_test.go` cannot guard it.
Verified after deploy: `/nope` still answers 404, and `/missing.js` still fails
as an asset rather than as HTML.

The cost of this shape is that it buys the name and nothing else — every byte
still leaves Cloud Run, so the egress ceiling in "Still open" is untouched. Only
`api/html.go` sets a `Cache-Control`, so Hosting's CDN caches almost nothing.

Four things cost time here and will cost it again:

- **`thirdeye` and `third-eye` are taken.** Site IDs are one global namespace
  across all of Firebase. The API says so plainly — `is reserved by another
  project` — so check with `?validateOnly=true` before planning around a name.
- **`addFirebase` returns a bare 403 when the Firebase ToS has never been
  accepted.** Not a permissions problem: `testIamPermissions` confirmed
  `firebase.projects.update` was granted the whole time, the account was Owner,
  and the project has no org parent. It started working immediately after a
  visit to the Firebase console. The error names none of this.
- **A raw API call adds a second, unrelated 403.** Without
  `x-goog-user-project`, the request is quota-attributed to gcloud's shared
  client project `32555940559`, where the API is disabled. That masks the real
  error with `SERVICE_DISABLED` against a project number that is not yours.
- **Do not type the project name in the Firebase console — pick it from the
  dropdown.** Typing created a whole new GCP project, `thirdeye-demo-26090`,
  one character short of the real one. It has no billing attached and is inert,
  but it is still there.

Redeploy after a config change is `firebase deploy --only hosting`; it is
independent of the Cloud Run deploy, and the hosting config changes only when
someone edits it, so CI does not run it.

## The Overture archive — weekly, 2026-10-01

`.github/workflows/archive.yml` runs every Monday (and on demand from the
Actions tab). It finds the latest Overture release, skips it if
`raw/overture/snapshot=<release>/_manifest.json` is already in the data bucket,
otherwise runs `pipeline/sources/archive_release.py` and uploads the snapshot
with `--no-clobber`, manifest last. It refuses to upload a snapshot under
100,000 rows (real ones are 219k–251k). A failure is a red run, and GitHub
emails it. Each run also warns if the mirror holds releases the bucket lacks.

The bucket is the archive of record. The 24 snapshots that existed only on one
laptop (343 MB) were uploaded on 2026-10-01.

**The repo is public, so GitHub disables the schedule after 60 days without a
push.** Re-enable it under Actions → *Archive Overture release* if it lapses.

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
- **Narrow the deployer's storage role.** `github-deployer` still holds
  project-wide `roles/storage.objectAdmin` from the abandoned Cloud Build
  attempts, so it can overwrite or delete any object, including the tables
  every deploy bakes in. The deploy only reads; the archive only adds. The
  swap (run by a human; Claude Code's auto mode refuses IAM grants):

  ```
  SA=serviceAccount:github-deployer@thirdeye-demo-260906.iam.gserviceaccount.com
  gcloud storage buckets add-iam-policy-binding gs://thirdeye-demo-260906-data \
    --member=$SA --role=roles/storage.objectCreator
  gcloud projects remove-iam-policy-binding thirdeye-demo-260906 \
    --member=$SA --role=roles/storage.objectAdmin
  ```

  Reads keep working through the project-level `roles/storage.objectViewer`.
  Also unused since the runner build: `roles/cloudbuild.builds.editor` on the
  project and `roles/storage.admin` on `gs://thirdeye-demo-260906_cloudbuild`.
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
- ~~A scheduler for `pipeline/sources/archive_release.py`~~ — built
  2026-10-01; see *The Overture archive* above.
- TLS, and a domain. The contact link currently points at the GitHub repo's
  issues rather than an address.

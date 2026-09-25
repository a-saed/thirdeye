# Roadmap — where Third Eye is and what comes next

Status: written 2026-09-10 from a state-of-the-project review. This is a
working document, not a spec. Anything here that turns into a build gets its
own design under `docs/superpowers/specs/` first.

## Where we are

The feasibility study closed 2026-08-21 with a qualified yes: the data supports
a **descriptive** product; the **predictive** thesis is unproven because the
tests that would have measured it needed ground truth nobody has. Since then the
work has been supply-side: pipeline, Go API, React SPA, Cloud Run deployment,
CI/CD. The demo is live and the tree is clean.

What has *not* happened: nobody with a real location decision has used it. There
is no demand-side evidence at all. Every priority below follows from that.

## What is actually stale — measured, not guessed

"The data is legacy" is true for one layer and false for the other.

| Layer | Served today | Newest free version that exists | Verdict |
|---|---|---|---|
| Businesses — Overture | `2026-08-19.0` — verified in the served table and in the live API's `as_of` | `2026-08-19.0`; S3 lists no newer release as of 2026-09-21 | **already current.** Nothing to bump |
| Businesses — Foursquare | snapshot pulled 2026-08-20 | current snapshot; Iceberg keeps no history | fresh |
| Population — Kontur | 2023-11-01 | **2023-11-01. Kontur v5 (Nov 2023) is still their latest release** | 3 years old, and nothing newer exists at any price |
| Built-up — GHSL | epochs 2015 / 2020 / 2025 | same | the 2025 epoch is modelled, not observed |
| Buildings — Open Buildings | 2023 | 2023 is the last temporal epoch | stale; multi-year not ingested |

Egypt's last census was 2017; the next is 2027. Every population product for
Egypt, free or paid, is that census plus modelling. The app already flags
population stale per cell where construction has been measured since. That is
more disclosure than any competitor offers.

### Sources that would be "better", and why they are out

- **Google Places** — freshest POI data in Egypt by far. Paid (hard rule 2),
  and its terms forbid storing results, so the history table could not be built
  from it even if we paid.
- **Footfall / mobility** (Placer-style, telco) — the signal that would actually
  predict sales. Not reachable for Egypt by a solo project.
- **OSM live** — free and current, and measured at zero contribution in six
  districts across two cities. Current and empty.
- **WorldPop / GHS-POP 2025** — free, modelled from the same 2017 base. A
  different guess, not newer facts.
- **Users' own data** — the only genuinely fresh, genuinely proprietary source.
  See "User-contributed data" below.

### Freshness actions

**Corrected 2026-09-21.** An earlier draft of this file said the business layer
was seven weeks stale and needed a release bump. It does not. The served
`h3_metric` tables carry `as_of = 2026-08-19` for every `business_count.*`
metric, and so does the live API. The `OVERTURE_RELEASE = "2026-07-22.0"` pin in
`pipeline/config/_common.py` is not the served vintage — it is the deliberately
fixed analysis pin described in `archive_release.py` ("do not 'fix' the pin to
match"). Do not read the pin as the data's age.

1. ~~Bump the release.~~ Already current. `2026-08-19.0` is the newest release
   Overture has published; S3 listed nothing newer on 2026-09-21.
2. Schedule `pipeline/sources/archive_release.py` (below) so this never lapses.
3. Make `as_of` prominent on the report screen. A visible "businesses as of
   19 Aug 2026" reads as fresh; a hidden vintage reads as suspicious.

## Engineering backlog, ranked by the cost of not doing it

1. **Monthly archive scheduler** — the only item where delay is irreversible.
   **2026-09-25: this stopped being hypothetical.** The September release
   (`2026-09-23.1`) failed to archive — Overture removed the `categories`
   column and the job died, leaving an empty directory. It was caught two days
   later only because the state of the project happened to be reviewed. The
   scheduler's value is that a red workflow *emails you*; running on time is
   secondary. Fixed and archived (243,013 rows, 24 snapshots) — see the
   findings in `CLAUDE.md`.
   Overture's S3 keeps ~2 releases, the mirror lags and has already missed one
   (`2026-06-17.0`, gone forever). Checked 2026-09-21: the archive is complete —
   every release on S3 and on the mirror is already on disk, and no September
   release has shipped yet. Nothing is currently at risk; the job is to keep it
   that way. Shape: a
   second GitHub Actions workflow on a monthly `cron` + `workflow_dispatch`,
   reusing the WIF auth from `deploy.yml`, running `archive_release.py` and
   syncing `data/raw/overture/snapshot=<release>/` to the existing data bucket.
   Idempotent; archive only, no pipeline rerun, no redeploy; failure is a red
   workflow and an email. ~18 MB per snapshot, 324 MB total — inside GCS free
   tier.
2. **Egress ceiling** — 1 GB/month free, then ~$0.12/GB; ~950 first visits a
   month at ~1.05 MB each. Moving the SPA and `coverage-res8.geojson` to
   Cloudflare Pages removes it. Matters only once there is traffic.
3. **Budget kill-switch** — the trial ends ~2026-12-06 and pauses rather than
   bills. Needs budget → Pub/Sub → function that detaches billing. Do in
   November.
4. **Custom domain and contact link** — cosmetic.

Correction recorded here and in `CLAUDE.md`: `h3_metric_history` **is** built
(`data/derived/h3_tables/h3_metric_history_res{8,9}.parquet`, 23 snapshots,
~1.2M rows) and served lazily by `api/history.go`. The "not built" note was
stale.

## Business direction

### The next step is discovery, not a feature

Run a customer-discovery sprint with the demo as it stands. Target 8–10
conversations, in rough order of willingness to pay:

1. Franchise / chain expansion managers — F&B, pharmacies, supermarkets. They
   open locations monthly and decide with a car ride and gut feel.
2. Commercial real-estate brokers and developers leasing retail units.
3. Banks / fintech placing branches and ATMs.
4. Quick-commerce and delivery — dark-store placement is a pure catchment
   problem.
5. Single-shop owners — cheapest to reach, least likely to pay, loudest signal
   on whether the report is understandable.

Show them the live report for a location *they* recently decided on. Watch,
don't pitch. Learn:

- How they made their last location decision and what it cost to get wrong.
- What they look at first on the report and what they ignore.
- **The disclosure test.** The product's defining choice is that it says
  "single source", "stale", "no coverage". To a sophisticated buyer that is
  credibility; to a casual one it may read as "this tool knows nothing". Which
  reaction comes from which segment is the single most important unknown.
- What they would pay, per report or per month, and what they pay today.

Do not chase the predictive thesis until someone has paid for the descriptive
product. Do not add features from intuition — the study showed intuition about
this data is often measurably wrong; intuition about customers will be no
better.

### Without contacts: the LinkedIn route, and what makes people try

Nobody on LinkedIn knows what vintage Kontur is. A visitor decides in thirty
seconds on three things: *does it know my street*, *did it tell me something I
didn't know*, *how hard was it to get there*. That is a hook problem, not a
data problem.

- **Zero-effort first action.** Landing → "use my location" → report. No
  typing. Geolocation exists; make it the primary button.
- **Lead with findings, not a launch.** Post one surprising, checkable finding
  per post with a link to the live cell: the district with the most cafés per
  resident, the Corniche cells that are half sea, the areas that grew 40%
  built-up since 2015. Findings get shared; "I built a tool" does not.
- **Make the first result about them.** "Bring your branches" for chains,
  "use my location" for everyone else.

## Feature candidates

### Site Finder — bounded, pre-launch

Reframe from *we decide the best location* (a claim the data cannot support: 85%
of cells single-source, sources disagree by 2×, growth fires only on greenfield)
to *you tell us what matters, we do the legwork*:

> Tell us what you're opening and what matters to you. We rank every cell in
> Greater Cairo and Alexandria by *your* criteria, show the top candidates, and
> tell you exactly what we don't know about each.

Route `/find`, three steps: what are you opening (categories from
`pipeline/config`) → where (governorate/district or anywhere in coverage) →
what matters most (one primary sort: fewest competitors / most people / growing
area, plus optional hard limits). Translates into `/api/search` filters and
**one named sort key — no composite score**, which `api/search.go` already
refuses on principle. Top 5–10 cells as cards: ranking metric with direction of
good, confidence badge, a "what we don't know here" line. "Compare these" hands
off to the existing compare route.

### Bring Your Branches — bounded, pre-launch

Paste addresses or `lat,lon` lines, or upload a CSV. Geocode with the existing
`/api/geocode`, plot pins, one `/report` per branch, a table of branch →
population, competitors, confidence. **Nothing persisted, no backend change.**
An email field — "want this as a PDF?" — is the lead list. For a chain manager
this is the most interesting thirty seconds of the demo because it is about
their stores.

### User-contributed data — architectural, post-launch

The best long-term idea and the only path to two things the project lacks:
proprietary data a competitor with the same free feeds cannot copy, and ground
truth that could ever validate the predictive thesis.

It is architectural because the product deliberately has no database, no
accounts, no persistence. Doing it properly needs storage, identity, terms that
license the contribution to us, and — non-negotiable — user data as a
**separate source** in provenance (`source: user`, `confidence:
self_reported`), never blended silently into the public counts.

Build only when someone from discovery asks for it. That ask is the evidence.

### Paid API with credits for contributions — architectural, later

The idea: a keyed API for people who want to consume the data, paid; and
credits toward that API for users whose contributed data is accepted.

Assessment: right direction, wrong order, wrong unit.

**Order.** A paid API is a B2B product sold to proptech, banks, q-commerce.
Nobody has yet paid for the app. Sequence it: (1) a **free keyed API** with a
rate limit — the key is the lead magnet, the sign-up tells us who wants data
and for what; (2) a paid tier only when someone hits the limit and asks.

**Unit.** Credits for *adding points* is the wrong contribution to reward.
Overture already has the points, with 2× disagreement; more unverified points
make that worse, and a credit with monetary value invites junk submissions.
Automated acceptance is not trustworthy either — the duplicate matcher scored
25% out-of-sample (hard rule 4). Reward **verifications** instead: "this
business is closed", "these two are the same", "this category is wrong", "my
store's monthly sales band". Verdicts are cheap to accept by agreement (N
independent users concur → accepted) and they are exactly the out-of-sample
truth the study never had.

**Constraints to respect from day one:**

- Credits are a liability. Non-cash, capped, expiring.
- Contribution terms must license the data to us and state how it is shown.
- **Licensing.** Overture's places theme is ODbL, and share-alike may follow a
  derived *database*. A per-location *report* API is a produced work; a bulk
  cell-export API is a derived database. `docs/LICENSING.md` avoids the question
  by not redistributing; a paid data API stops avoiding it. Get this checked
  before selling bulk access. Reports first, bulk later or never.
- Metering, keys and credits all need persistence — the same architectural
  decision as user-contributed data. Design them together.

## The order

1. Archive scheduler. (The release bump that used to sit here was never
   needed — see the correction above.)
2. Site Finder, then Bring Your Branches.
3. Post findings. Collect emails. Talk to whoever replies.
4. Decide from what they said — not before — whether the next thing is
   user-contributed data, a keyed API, or something nobody here predicted.

# Third Eye — Data Feasibility Verdict

**Market:** Greater Cairo + Giza + Qalyubiya + Alexandria, Egypt
**Question:** can a location-intelligence product be built on free and open geodata here?
**Study period:** 2026-08-18 → 2026-08-21
**Verdict date:** 2026-08-21

---

## Bottom line

**Qualified yes — but not for the product originally described.**

The free data supports a *descriptive* product: where things are now, how dense
the built environment is, how many people live in a cell, and which districts
are physically growing. That layer is real, cross-corroborated by three
independent sources, and citywide.

It does **not** currently support the *predictive* product — "which location
will succeed" — and the study never got far enough to say whether it could.
Test 5, the only test that would have measured predictive validity, never ran.
The temporal signal that the original thesis rested on turned out to fire only
on greenfield development, and the business layer is single-source in exactly
the dense, poor, high-footfall districts where the commercial question is most
interesting.

Two of five kill criteria were evaluated and passed. **Three were never
tested** — including the accuracy check (Test 2) and the predictive check
(Test 5). Anyone reading this as "the data is good" is over-reading it. The
correct reading is: *the data is good enough to describe this city, and
unproven for predicting anything in it.*

---

## The honest shape of the product — state this in the UI

**Three quarters of cells have business data from one source only, and where
both sources exist they typically disagree by about 2x.** That is the headline,
not a footnote.

| | res-8 | res-9 |
|---|---|---|
| Cells with any storefront record | 4,391 | 14,125 |
| **Both sources present at all** | **54.0%** | **47.2%** |
| One source only | 46.0% | 52.8% |
| **Corroborated (counts within 1.5x)** | **15.8%** | **13.8%** |
| **single_source for business** | **84.2%** | **86.2%** |

Among cells where both sources *are* present, the min/max count-agreement ratio
distributes like this (res-9): p05 0.08, p10 0.12, p25 0.24, **p50 0.50**,
p75 0.75, p90 1.00. Only 15.1% agree exactly. **The median pair of sources
disagrees by 2x on how many businesses are in the same cell.**

Corroboration is sensitive to where the bar is set, so the bar is stated
openly rather than chosen to flatter:

| Tolerance | res-8 corroborated | res-9 corroborated |
|---|---|---|
| 0.50 (within 2.0x) | 26.3% | 23.8% |
| **0.667 (within 1.5x) — production default** | **14.2%** | **13.0%** |
| 0.80 (within 1.25x) | 11.0% | 10.4% |

The first pipeline build used 0.5, which was the *observed median disagreement*
— making "corroborated" mean "disagrees by the typical amount". That is
circular and was rejected. 0.667 roughly halves the corroborated set. It is the
honest number, not a worse one.

**single_source share by governorate (res-9, tol 0.667):**
Qalyubiya 92.2% · Alexandria 89.0% · Giza 86.1% · Cairo 84.5%.
No governorate is below 84%.

### Why business corroboration is weak *by construction*

Overture and Foursquare are **not independent sources**. Foursquare is itself a
contributing dataset to Overture — measured in this study at **17.1% of
Sheikh Zayed's Overture records, 10.6% of Maadi's, 1.3% of Imbaba's**, and
2.8% / 1.4% / 0.0% across the three Alexandria districts. Meta supplies
77–99% of the rest.

So when the two "sources" agree, some of that agreement is the same upstream
data arriving twice. Worse, the effect is **strongest exactly where
corroboration is most achievable**: the districts with the highest
Foursquare-inside-Overture share (Sheikh Zayed 17.1%, Maadi 10.6%) are the same
districts with FSQ/Overture coverage ratios near parity (1.00, 1.03), while the
districts where Foursquare contributes least (Imbaba 1.3%, Karmouz 0.0%) have
the thinnest FSQ coverage (0.27, 0.26).

**Consequence:** a `corroborated` business metric is weaker evidence than the
word implies. It means "two partially-overlapping feeds agree", not "two
independent observers agree". Treat it as a *lower bound on doubt*, never as
verification. Genuine independence for the business layer does not exist in
this market — there is no third feed, and OSM contributes nothing.

---

## Test-by-test

### Test 1 — Does the data exist here? **PASS**
Overture Places queried from S3 with bbox pushdown. 491 / 991 / 316 POIs in
2.25 km² boxes (Sheikh Zayed / Maadi / Imbaba). 95–97% carry a primary
category; name coverage is genuinely 100% (verified separately — it is a
property of Overture's `place` type, not a filter artifact, and carries no
signal so it was dropped as a metric).
*Kill criterion (implausibly low density): not triggered.*

### Test 1b — Validation checks **PASS, with findings**
- **Zero OSM contribution** in any district. Sources are Meta / Foursquare /
  Microsoft / PinMeTo / AllThePlaces only.
- **Single-source dependence tracks income**: Imbaba 96.5% Meta-only vs
  Sheikh Zayed 77.6%.
- **Category mapping matters**: naive single-string matching undercounts cafés
  and restaurants by 2–6× and returns **zero** grocery stores citywide, because
  "grocery" is not itself a category value. Fixed with an explicit inclusion-list
  mapping over the real 358-value vocabulary.

### Test 2 — Is it accurate? **NEVER COMPLETED**
Ground-truth files were prepared for Road 9, Maadi (67 Overture + 58 FSQ
records, reduced to 88 distinct businesses after collapse/non-storefront
filtering, split into FOOD / RETAIL / MEDICAL / UNCLEAR review groups) and for
two Google-comparison streets. **No verdicts were ever returned.**
*Kill criterion (recall < 60%): NOT TESTED. Recall, precision and category
accuracy of the place data are unmeasured.* This is the single largest gap in
the study.

### Test 2b — Is there OSM history to carry a temporal feature? **FAIL (decisive)**
ohsome/OSM POI history is unusable in this market. **12 of 15 district ×
category cells have fewer than 10 elements in the latest year**; several are
flat zero for the entire 2015–2026 span. Even the best district (Maadi) is flat
noise apart from two step-jumps in 2024 that look like bulk imports.
This killed the original Test 3 design outright and forced the satellite-based
replacement.

### Test 2C / Test 3 (replaced) — Does satellite-derived growth work? **PASS**
Built-environment track, three independent sources, agreeing across all three
districts:

| District | Open Buildings (2018→2023) | GHSL (2015→2025) | WSF (1985→2015) | Verdict |
|---|---|---|---|---|
| Sheikh Zayed | +13.6% | +12.5% | 0.1% → 63% settled | **growing** |
| Maadi | +0.7% | +0.8% | 95.5% → 99.1% | flat *(saturated)* |
| Imbaba | −0.6% | +0.2% | 99.7% → 99.8% | flat *(saturated)* |

*Kill criterion (flat or contradictory across all three): not triggered.*
Business-layer track (Overture release history + Foursquare reconstruction)
agrees on Sheikh Zayed and Maadi, diverges on Imbaba.

**Two corrections found in this test and worth carrying forward:**
- Open Buildings' `building_fractional_count` band reported Imbaba declining
  −14.4%; the presence band and GHSL both say flat. The count band is
  unreliable in dense informal fabric — **use presence**.
- The 2016 vintage is contaminated (Sentinel-2B launched March 2017, so 2016
  was single-satellite). All growth figures are rebaselined to **2018**.

### Test 4 — Is the population layer sane? **PASS (partial)**
Kontur 400 m H3 hexagons. Density ordering is exactly as independent evidence
predicts: Imbaba 46,045 /km² ≫ Maadi 19,112 ≫ Sheikh Zayed 1,032.
*Kill criterion (empty area returns substantial population; wrong ordering of
three reference points): NOT TESTED — the three reference points were never
supplied.* The district-level ordering is a strong plausibility check, but the
specific empty-area test never ran.

### Test 5 — Does the data separate winners from losers? **NEVER RAN**
Required a CSV of ~20 businesses with known outcomes. Never supplied.
*Kill criterion (no feature separates survivors from closures): NOT TESTED.*
**Predictive validity is entirely unestablished.**

### Step 4 — Alexandria generalisation **PASS — findings are structural**
Three claims reproduce in a second city (zero OSM; single-source dependence
tracking income, 94.6% → 97.4% → 98.9% Meta; FSQ coverage collapsing to 0.26 in
the poor district, matching Imbaba's 0.27). One claim is **refuted**: the
confidence-score gradient does not reproduce (0.643 / 0.595 / 0.597, versus
Cairo's clean 0.770 / 0.676 / 0.562).

---

## The three biggest data problems, ranked

### 1. The business layer is single-source exactly where it matters
Meta supplies 94.6–98.9% of records in Alexandria and 77.6–96.5% in Cairo, and
the dependence worsens as income falls. There is **no OSM contribution at all**
in six districts across two cities. Foursquare, the only alternative provider,
holds 0.26–0.27× Overture's count in poor districts — Karmouz has 23 FSQ places
in 2.25 km² of dense inner-city Alexandria.

*Why it damages the product most:* every commercial claim rests on one
company's data, with no independent check available in the districts where the
tool would be most valuable. If Meta's coverage is wrong somewhere, nothing in
this stack can detect it. It also means any "corroborated" confidence tier is
structurally unreachable for the business layer in poor areas.

### 2. The temporal signal fires only on greenfield
The one district with a corroborated growth signal (Sheikh Zayed) has
**1,032 people/km²**. The district with 45× the residential density (Imbaba,
46,045 /km²) has no growth signal on either track. Saturated districts read
"flat" because they are physically built out — which is correct, and useless.

*Why it damages the product:* the interesting commercial question in a mature
district is business churn, not construction. The built-environment track
cannot see churn, and the business track that could is single-source and, before
February 2024, does not exist at all. A naive score would systematically favour
new desert suburbs and have nothing to say about established neighbourhoods.

### 3. Accuracy is unmeasured, and position is block-level at best
Ground truth was never completed, so recall, precision and category correctness
of the place data are unknown. What *was* measured is position: cross-source
disagreement is **median 10.2 m, p90 58.5 m, max 381.7 m**. Duplicate detection
proved far weaker than it appeared — an in-sample suite reported 100% precision
where the out-of-sample truth was **25%**.

*Why it damages the product:* "competitors within 500 m" is defensible at p90
≈ 60 m, but any storefront-level claim is not. And without ground truth, there
is no basis for stating how many listed places still exist.

---

## What we could not test, and why

| Not tested | Why | Consequence |
|---|---|---|
| **Test 2 recall / precision / category accuracy** (Road 9, Maadi) | Ground-truth files prepared; verdicts never returned | The core accuracy question is open. Kill criterion (recall < 60%) unevaluated. |
| **Test 2B Google comparison** (El Shabab, 90th St) | Files prepared; comparison never performed | Coverage-gap vs Google unknown. *(90th St would have been a poor site anyway — 63% of its Overture records collapse onto four ~20 m² footprints, a geocoding artifact.)* |
| **Test 4 reference-point ordering** | Three points never supplied | The specific "empty area returns population" check never ran. |
| **Test 5 predictive validity** | Outcomes CSV never supplied | **No evidence the data predicts business success.** The central product thesis is unvalidated. |
| **Path A duplicate precision** (n=100) | Deliberately skipped — reviewer would have judged by distance, making the test circular | Auto-merge cannot be justified; nothing is merged. |
| **VIIRS nighttime lights** | EOG's free tier is browser-only; programmatic access requires a paid subscription | Dropped; GHSL covers the same cross-era role for free. |
| **Foursquare pre-2024 archive** | FSQ's Iceberg catalog exposes only the current snapshot | No FSQ back-catalogue exists to archive. |

---

## Explicit product limitations

These must be stated in the product, not buried:

1. **Growth signal is greenfield-only.** Corroborated growth detection works in
   developing districts (Sheikh Zayed: +13.6% Open Buildings / +12.5% GHSL). In
   saturated districts (≥40% built-up: Maadi 40.0%, Imbaba 43.6%) a flat signal
   is expected and means "no new construction", **not** "no commercial change".

2. **Business layer is single-source in poor districts.** Confidence must be
   reported per metric per cell as `single_source`, never as corroborated, in
   any cell where Meta is the only contributor. This affects the majority of
   cells in low-income areas of both cities.

3. **Position accuracy is block-level, not storefront-level.** Median 10.2 m,
   p90 58.5 m, max 381.7 m. Safe for 500 m catchment features; unsafe for any
   "next door to" or address-level claim. Large venues and chains are worst.

4. **Business corroboration is not independence.** See the headline section:
   Foursquare feeds Overture, so "corroborated" means partially-overlapping
   feeds agree. Never present it as verification.

5. **Duplicate inflation of 3.2–6.3%** (95% CI) is present and unmerged. State
   the range, not a point estimate, and never the raw 18.5% flag rate — that
   figure is wrong by 3–6× because the matcher's out-of-sample precision is 25%.

6. **Confidence score is withdrawn as a quality proxy.** Overture's confidence
   field tracked coverage quality in Cairo and does **not** in Alexandria
   (0.643 / 0.595 / 0.597 vs Cairo's 0.770 / 0.676 / 0.562). Use source-share
   and FSQ-ratio instead; both travel across cities.

7. **Business-layer history begins February 2024** and exists only because
   releases were archived. Overture's own S3 retains ~2 releases; one release
   (2026-06-17.0) is permanently lost. Any pre-2024 temporal claim is
   impossible.

8. **Campus and institutional records distort local density.** 2,986
   campus-interior records citywide; 208 res-9 cells hold ≥20 non-storefront
   records, worst 130. Filtering fixes the count but those cells remain
   non-comparable.

---

## If prototyping: where to start

**Sheikh Zayed**, on the built-environment track only.

It is the one district where two independent satellite sources agree on
direction *and* magnitude (+13.6% / +12.5%), where the business track also
agrees, and where WSF confirms the area was built from nothing since 1985. It
is the cleanest available demonstration that the pipeline detects real change.

**But do not read that as the best commercial opportunity** — it has the lowest
population density of the six districts studied (1,032 /km²). It is the best
place to prove the machinery works, not the best place to open a shop. Those
are different questions, and this study only answers the first.

# Third Eye — Interim Verdict (2026-08-18)

This is a checkpoint, not the final verdict. Test 2 (ground truth), Test 4 (population layer), and Test 5 (survivor/closure features) have not run yet — they come after the Foursquare business-layer source lands. What follows is what the data has told us so far, stated as bluntly as the ground rules ask for.

## Bottom line (interim, will change)

The **built environment** in this market is well-covered by free data and cross-corroborated across three independent sources — that part of the study is solid. The **business layer** — the part of Third Eye that actually matters for "should I open a shop here" — currently rests on a single, partially-artifact-contaminated source (Overture) with no independent confirmation. Until Foursquare lands, nothing about business growth or decline in this market can be reported with confidence. The one thing we can say plainly right now: **the temporal engine, as currently built, only produces a trustworthy growth signal in the one district that's still under active construction. It goes silent — correctly, not usefully — everywhere the district is already built out.** For a product meant to help someone pick a location in dense, mature Cairo neighborhoods, that's a real problem, not a footnote.

## What works

**Test 1 — data exists.** Pass. 491 / 991 / 316 POIs in Sheikh Zayed / Maadi / Imbaba (1.5km² boxes) — well above the "one busy commercial street" floor.

**Test 1b — validation.** Zero OpenStreetMap contribution anywhere in this market (100% Meta/Foursquare/Microsoft/PinMeTo/AllThePlaces). Imbaba is 96.5% single-source (Meta), with the lowest confidence scores (36% below 0.5) and the lowest cross-contributor diversity — a real, confirmed data-quality gradient correlating with the district's informal, lower-income character. Duplicate rate near-zero everywhere (not the explanation for category anomalies like "11 hospitals in Imbaba" — that needs Test 2 ground truth). Naive category-string matching undercounts cafe/restaurant by 2–6x and misses "grocery" entirely; fixed with an explicit mapping (`scripts/categories.py`).

**Test 2b — OSM has no usable history here.** Confirmed dead: multiple category/district cells show flat zero OSM edits for the entire 2015–2026 span. This killed the original ohsome-based Test 3 design outright, not as a soft caveat.

**Test 2C, built-environment track — AGREE across all three districts, cross-corroborated.** Three independent sources (Open Buildings presence-based area, GHSL built-up surface, WSF Evolution as long-run context) all agree:
- Sheikh Zayed: growing (+45.5% / +12.5% / built from near-zero since 1985) — **DEVELOPING** (23.1% built-up)
- Maadi: flat (+1.6% / +0.8% / near-ceiling) — **SATURATED** (40.0% built-up)
- Imbaba: flat (+2.6% / +0.2% / near-ceiling) — **SATURATED** (43.6% built-up)

Flat readings in the two saturated districts are the expected physical result of them already being built out, not evidence that "nothing is happening" there commercially.

**Archiving is live.** Current Overture release archived; 21 historical releases backfilled from Source Cooperative (2024-02 through 2026-05, the only real historical Overture archive found — official S3/Azure retain only the current release). `scripts/archive_release.py` must be re-run monthly by the user going forward — it does not self-schedule.

## What's dead

- **OSM edit history** (Test 3 as originally designed) — confirmed too sparse in this market, not a workaround-able gap.
- **VIIRS via EOG** — deprioritized by user direction; EOG's free tier is browser-only, programmatic access needs a paid subscription, which conflicts with the no-payment rule. GHSL fills the role VIIRS was meant to play, for free.

## What's unverifiable right now

- **Every business-layer growth number.** Overture (artifact-corrected) reads Sheikh Zayed +79.9%, Maadi +63.8%, Imbaba -4.0% — but this is one source, and this session already found a confirmed 90%-in-one-month bulk-import artifact in Imbaba's raw history, plus strong circumstantial evidence (via cross-track disagreement with the buildings signal) that Maadi's reading is *also* contaminated, just below the single-source detection threshold. **No number from Overture alone should be presented to an end user as a real finding.**
- **Category accuracy** (is "11 hospitals in Imbaba" real, or mistagged clinics/pharmacies?) — needs Test 2 ground truth, not yet run.
- **Population trend features for Test 5** — GHSL vs WorldPop vintage availability not yet checked.

## Three biggest data problems, ranked

1. **The business layer has no independent second source yet.** This is the single biggest risk to the product concept: everything Third Eye would actually tell a user about commercial dynamics currently depends on one platform's (Overture's) release cadence, which this session proved contains real bulk-import noise indistinguishable from signal without a second source. Foursquare is the only currently-known fix.
2. **The temporal engine's blind spot is exactly backwards from what the product needs.** It works precisely where construction is happening (Sheikh Zayed) and goes quiet exactly where business churn — the actually interesting signal for site selection — would occur (mature, saturated Maadi/Imbaba). A product built naively on today's built-environment signal alone would systematically favor new suburbs and have nothing useful to say about established neighborhoods.
3. **Coverage quality correlates with income/formality.** Imbaba's near-total dependence on a single contributing dataset (Meta, 96.5%) plus its markedly lower confidence scores is a specific, measured bias, not a vague worry — and it's exactly the kind of gap that would make the product systematically worse for the market segment (lower-income, informal-economy areas) where accurate free data would arguably matter most.

## Next

Foursquare token lands → complete Leg A (business-layer second source) → re-run the business-layer corroboration → Test 2 ground truth (both Maadi and Imbaba, mandatory per the earlier revision). This document gets superseded by the real `VERDICT.md` once all five original tests plus the revised temporal work are complete.

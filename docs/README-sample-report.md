# Sample report — GET /report

`sample-report.json` is a real, unmodified response from the Go API.

Query: Road 9, Maadi — `lat=29.9513&lon=31.2664&radius=500`

Reproduce it with:

```bash
cd api && go build -o /tmp/te-api . && cd ..
/tmp/te-api -data data/derived/h3_tables -limits api/limitations.json -addr :8099 &
curl -sS "http://localhost:8099/report?lat=29.9513&lon=31.2664&radius=500" | jq .
```

## What to look at before designing UI around it

- **`context.land_area_km2` (3.75) vs `raw_area_km2` (4.59).** 18% of this
  catchment is not habitable land, in Maadi — not even a waterfront case.
  Every per-area figure uses the land denominator.
- **Every metric is `single_source`.** Catchment confidence is the WEAKEST of
  its member cells, not the average. `business_count.total` has both sources
  contributing with a median agreement ratio of 0.682, yet one single-source
  member cell makes the whole catchment single-source. This is intended.
- **`population.stale = true`**, `as_of` 2023-11-01, with a matching entry in
  `limitations.notes`. Kontur is a 2023 vintage and this catchment has
  measured construction since.
- **`agreement_ratio`** is exposed per metric so the UI can show how weak
  "corroborated" is when it does appear. 0 means only one source had the
  metric; it is not an agreement of zero.
- **23-point time series in one response**, so the scrubber never needs a
  request per year. Each series carries `gap_note` naming the permanently
  missing 2026-06-17.0 snapshot.

## Known trap for the frontend

The `business_count.*` series contain **bulk-import step changes**, e.g.
`2025-01-22: 465 -> 2025-03-19: 673`. That is an artifact of an Overture
release ingesting a new contributor, not real-world growth. The study's
artifact detector (research/scripts/artifact_detection.py, 40% jump followed
by a flat run) identified this class. **The scrubber will render these as
genuine growth unless the UI handles them deliberately.** Decide explicitly:
annotate, smooth, or show raw with a warning — but do not present them
unmarked as business formation.

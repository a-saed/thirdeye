Claude Code prompt — Third Eye data feasibility study

I'm evaluating whether I can build a location-intelligence tool ("Third Eye") on free and open geodata only. Before I write any application code, I need to know whether the underlying data is good enough in my market. Your job is to run a feasibility study and give me an honest verdict — not to build the product.

Ground rules
Free data only. No payment - not "no accounts": free registrations with no card on file and no billing are allowed (amended mid-study). No paid APIs, no cloud services that bill, nothing requiring a credit card or subscription fee ("nominal fee" counts as payment). If something requires payment, skip it and say so - and say so explicitly even for a "free account" whose programmatic/API tier turns out to be paid (this happened with EOG - free registration exists, but their own docs require a paid subscription for the API access a script needs; browser-only free access does not satisfy this study's need for reproducible scripts).
Do not build an app. No frontend, no server, no React. Scripts and outputs only.
Do not fabricate numbers. If a query fails, times out, or returns nothing, report exactly that. A failed test is a useful result; an invented number is worse than useless.
Verify versions before using them. Overture release identifiers and dataset URLs change. Check the current Overture release from https://docs.overturemaps.org (or the OvertureMaps/data GitHub repo) before writing any query — do not assume a release string I gave you is current.
Study area: Cairo/Giza, Egypt. Three districts, each a fixed 1.5km x 1.5km bbox centered on a geocoded landmark point (not the full administrative boundary, which would blend heterogeneous sub-areas into one average):
  1. Sheikh Zayed — centered on Arkan Plaza Mall (30.020223, 31.003295) — "Gate Plaza" was requested first but has no Nominatim match under any spelling tried; Arkan Plaza substituted per user direction.
  2. Maadi — centered on Nominatim's "Maadi, Cairo, Egypt" match (29.960331, 31.263055)
  3. Imbaba — centered on Nominatim's "Imbaba, Giza, Egypt" match (30.075937, 31.207570)
Bboxes and provenance are in data/districts.json (built by scripts/01_geocode_districts.py).

Environment

Local working directory (.venv/), with:

DuckDB (Python), with the spatial and httpfs extensions
Python: pandas, geopandas, matplotlib, requests, duckdb, shapely, pyarrow, rasterio, pyproj
Anonymous S3 access to s3://overturemaps-us-west-2 (no credentials needed)
Anonymous HTTPS access to data.source.coop (Source Cooperative's community Overture mirror), storage.googleapis.com (Google Open Buildings 2.5D Temporal), jeodpp.jrc.ec.europa.eu (JRC GHSL, no login), and download.geoservice.dlr.de (DLR WSF Evolution, no login)

Put every script in scripts/, every raw/archived pull in data/, every chart in output/. Make each test runnable independently.

Current Overture release, verified live against the S3 bucket listing (not assumed): 2026-07-22.0.

Archiving (added mid-study, run monthly going forward)

Overture's official clouds (S3, Azure) only ever hold the CURRENT release — verified directly: S3's release/ prefix has exactly one folder; Azure's one extra folder (2026-06-17.0) contains only 0-byte placeholder blobs in every theme, i.e. no real data. Neither is a usable historical archive. So:

scripts/archive_release.py — pulls the 3 district bboxes from the current Overture release into data/archive/overture/<release-id>/<district>.parquet. Idempotent (keyed by release id, safe to re-run monthly). CONFIRMED SET UP AND WORKING (manifest.json per release, e.g. data/archive/overture/2026-07-22.0/manifest.json). MUST BE RUN MONTHLY GOING FORWARD (e.g. via cron or a scheduled agent) — Overture ships a new release roughly monthly and this script is the only way this study accumulates real go-forward history, since the official S3/Azure clouds only ever hold the single current release. Also attempted the current Foursquare OS Places release for the same bboxes into data/archive/fsq/ — SKIPPED: the public S3 bucket (fsq-os-places-us-east-1) has been emptied (only LICENSE.txt/NOTICE.txt remain); current access requires an account + access token via Foursquare's "Places Portal" (confirmed via Foursquare's own docs, migration completed October 2025). Violates the no-accounts/no-keys rule.

scripts/archive_source_coop_overture.py — Source Cooperative's community mirror (data.source.coop/fused/overture) DOES retain real historical Overture releases: 21 releases found, 2024-02-15-alpha-0 through 2026-05-20-0 (not perfectly monthly — a few gaps). Confirmed non-empty and queryable. Backfills all 21 into the same data/archive/overture/<release-id>/<district>.parquet layout, normalising each release's schema first (bbox field names and category field name both drifted across releases: modern bbox.xmin/xmax/ymin/ymax + categories.primary vs older bbox.minx/maxx/miny/maxy + categories.main — detected per-release, not assumed). These files are not geo-partitioned (flat numbered parts), so pruning is weak and each release pull is close to a full-file scan; slow but tractable in the background.

Test 1 — Does the data exist here?

Query Overture places directly from S3 with DuckDB, filtered by bbox (use the bbox.xmin/xmax/ymin/ymax columns for predicate pushdown so you don't scan the planet).

For each district, output: total POI count; count by categories.primary, top 30; percentage of POIs with a non-null primary category; percentage with a name.

Kill criterion: total POI density is implausibly low for a dense urban district. — PASS for all 3 districts (491 / 991 / 316 POIs in 2.25 km² boxes).

Test 1b — Validation checks that don't need local knowledge (added mid-study)

Before trusting the Test 1 counts:
1. Source breakdown per district (scripts/test1b_1_source_breakdown.py) — which dataset (Meta/Foursquare/Microsoft/PinMeTo/AllThePlaces/OSM) each place record actually came from. Finding: zero OSM contribution in any district; Imbaba is 96.5% Meta-only vs Maadi's 86%/Sheikh Zayed's 78%, with much less Foursquare/Microsoft supplementing it — explains most of the density gap as a contribution-coverage artifact, not reality.
2. Confidence distribution per district (scripts/test1b_2_confidence.py) — Imbaba's median confidence (0.56) and % below 0.5 (36%) are both markedly worse than Sheikh Zayed's (0.77 / 16%), consistent with (1).
3. Duplicate detection, 20m + fuzzy name match (scripts/test1b_3_duplicates.py) — near-zero everywhere (0–0.4%); does NOT explain category-count anomalies like Imbaba's "11 hospitals" — that's more likely a category-accuracy issue than a dedup issue, to be checked in Test 2.
4. Name coverage re-verification (scripts/test1b_4_name_coverage_verify.py) — confirmed genuinely 100% (0 null, 0 empty, 0 whitespace-only), not a filter artifact; dropped as a metric since it carries no discriminating signal.

Category mapping (scripts/categories.py) — naive single-category-string matching undercounts cafe/restaurant by 2–6x and misses "grocery" entirely (0 in all 3 districts, since "grocery" isn't itself a category value — only grocery_store/supermarket/etc. are). Explicit inclusion-list mapping built from the real 358-value category vocabulary (output/category_vocabulary.txt), with exclusions documented per group.

Test 2b — Is there enough OSM history to carry a temporal feature at all? (added mid-study, run BEFORE Test 3)

Checked via scripts/test2b_osm_vs_overture.py before committing to the original ohsome-based Test 3 design:
- Current-count ratio OSM/Overture-mapped, per district/category: mostly 0.0–0.5, i.e. OSM has less than half of what Overture/Meta shows even in the best district.
- Annual OSM counts 2015–2026 (ohsome /elements/count, P1Y): flat zero for the entire span in multiple category/district cells (e.g. Sheikh Zayed restaurant/pharmacy, all of Imbaba's cafe/restaurant/pharmacy). Even Maadi (the best district) is flat noise except for two step-jumps in 2024 (pharmacy +50%, fast_food +225%) that look like bulk imports, not organic growth.

VERDICT: OSM POI density in this market cannot carry a year-over-year trend feature. 12 of 15 (district x category) cells have fewer than 10 elements in the latest year. This kills the original Test 3 design (below) and Test 5's original "competitors at opening year via ohsome" feature.

Also checked in this step: Overture release history on S3/Azure (see Archiving section above — official clouds have no real history; Source Cooperative does).

Test 2 — Is it accurate? SPLIT INTO TWO DISTINCT TESTS (2026-08-18) — do not merge them.

TEST 2A — REAL GROUND TRUTH (scripts/test2a_road9_extract.py). One street: Road 9, Maadi, the stretch running south from Sakanat Al-Maadi metro station, verified from user's own local knowledge - this is the only file that measures both RECALL and PRECISION, since the user will independently list businesses missing from every source.

Geometry: OSM ways 709250206 + 689652353 (confirmed via Overpass, name:en="Street 9"), starting ~38m from the metro and running ~637m south; 50m buffer either side. Sources: Overture (67 places) + Foursquare (58 places, pulled fresh since this stretch falls outside the cached district bboxes - see Archiving note below). 22 places matched across both sources (20m proximity + >=0.82 normalised-name similarity, same method as Test 1b's duplicate detection).

Output: output/gt-maadi-road9.csv (source, name, category, lat, lon, date_created, in_both_sources, + empty exists_today/category_correct/notes for the user to fill) and output/gt-maadi-road9-missing.csv (empty, for businesses in neither source). Buffer width recorded in the file header. Once filled in, compute per test.md's original formulas (recall, precision, category usefulness) - kill criterion unchanged: recall below 60%.

VERIFICATION GROUPING (2026-08-18, scripts/road9_verification_groups.py): the 103 remaining rows split by verification method so the user isn't checking all of them the same way - FOOD (64 rows, batch-checkable on Talabat/Elmenus), RETAIL/SERVICE (30 rows, Google Maps individually), MEDICAL/CLINIC (4 rows, Google Maps individually), UNCLEAR/NO CATEGORY (5 rows, no category tag at all - needs the most attention). Category-based split (Overture flat category / FSQ hierarchical label prefix), built from the actual vocabulary present in the remaining 103 rows. In distinct-business terms (matched pairs counted once, not twice): 88 things to verify, not 103. Separate CSV per group plus one combined file with a verify_group column, all in output/gt-maadi-road9-*.csv.

REVISION 2026-08-18 (user manual review before filling in): original matcher (20m + un-normalised name similarity >=0.82) missed obvious pairs entirely - zero Arabic/Latin handling. Rebuilt scripts/test2a_road9_extract.py with: 40m distance gate; bilingual-name-variant splitting (FSQ's "Name | الاسم" format, Overture's mixed-script concatenations); transliteration (unidecode) + consonant-skeleton + substring-window fuzzy comparison; threshold 0.72. Matched pairs went from 22 (old) to a verified-correct 19 (new) - lower count but higher precision, since the old 22 included false positives the new pipeline doesn't produce. All 19 final pairs manually spot-checked as genuinely correct.

Two bugs caught and fixed during this revision, worth recording: (1) substring-window matching on short skeletons produced a false positive ("Lan Yuan" spuriously matched unrelated text via a coincidental 4-character window) - fixed with a minimum-length guard (skeleton must be >=5 chars before windowing is used). (2) the original matching loop assigned each Overture record to whichever FSQ candidate it evaluated LAST rather than the best one, silently orphaning better matches ("Wafflicious" got overwritten by the weaker "Waffle Shop" candidate) - fixed with proper greedy best-first one-to-one bipartite assignment (sort all valid candidate pairs by name-similarity descending, assign greedily, skip already-claimed records).

New columns added: collapsed_coord (y/n, shares its exact coordinate with >=1 other record) + coord_group_size (2 = usually a legitimate cross-source match; 3+ = likely genuine geocoding artifact - two such 3-record clusters found, both Overture-only, distinct unrelated businesses collapsed onto one point); likely_not_storefront (y/n, category- and keyword-based: offices/tech-startup-HQs/residential-buildings/freight-cargo/government-pages/real-estate); position_outlier_m (distance for any matched pair >20m apart).

Two known name-matches EXCLUDED by the 40m distance gate, not force-matched: 'البحيري'/'El Beheiry' (56.7m apart, sim 0.91) and 'بلال'/'Belal' (113.2m apart, sim 1.00 - a real position error, confirmed via a broader distance-uncapped sweep, not a name-coincidence artifact). 'German Beauty Center'/'German Beauty Center Heidi' is the largest real position error found: 381.7m apart (not ~250m as first eyeballed), sim 1.00. The same uncapped sweep also surfaced 5 more pairs >100m apart that are NOT credible matches - generic shared words ("cafe", "beauty salon", "Maadi Branch") causing coincidental name similarity between actually-different businesses - excluded from the candidate list, not reported as position errors.

Final counts: Overture 67, FSQ 58, 19 matched pairs, collapsed_coord=y for 14 records, likely_not_storefront=y for 10 records, 103/125 total records remain for manual verification after excluding both flagged categories.

POSITION ERROR - STATED UNCERTAINTY BAND (2026-08-18, scripts/position_error_analysis.py): German Beauty Center's 381.7m gap raised the question of how much position disagreement to expect between Overture and FSQ generally, not just in this one case. Measured across all three streets (Road 9, El Shabab, 90th Street) using name-only matching (no distance gate - distance is what's being measured) restricted to pairs with normalised name similarity >0.9, so this reflects position error conditional on high match confidence, not match error:

  POOLED (n=94 high-confidence cross-source pairs): median 10.2m, p75 32.9m, p90 58.5m, max 381.7m.
  Per street: Road 9 median 15.8m/p90 68.0m/max 381.7m; El Shabab median 12.0m/p90 44.2m/max 249.7m; 90th Street median 0.0m/p90 60.9m/max 105.4m.

Two false positives found and excluded during this analysis, both a systematic weakness in the name-variant-splitting matcher, not real position error: (1) a shared locality suffix ("الشيخ زايد"/"Sheikh Zayed") caused "Syriana palace" (a restaurant) to match "Sheikh Zayed Downtown Mall" (a mall) at 226m - completely different business types. (2) bare title fragments like "Dr" (split out of "Dr.karim Abdelmoaty") trivially self-matched against any other "Dr. X" name - caused a false match between two different doctors at 67m. Fixed at the source (MIN_VARIANT_LEN=4 filter on split-out fragments in scripts/test2a_road9_extract.py) rather than just excluded after the fact - Road 9's already-delivered 19 matched pairs were re-verified unaffected by the fix. The pooled figures above are post-fix.

PRODUCT IMPLICATION: p90 position disagreement is ~60m, comfortably inside a 500m "competitors within X" radius - that specific feature is not meaningfully softened by this. But the max (382m) and the shape of the tail (mall/chain entries specifically - Kargo Mall 110m, Medline clinics 250m, both plausibly large-footprint or multi-branch cases rather than pure GPS error) mean position precision should be treated as accurate to roughly one to two city blocks, not to the storefront, especially for large venues. State this as an explicit uncertainty band in any feature or UI that implies precise positioning, rather than presenting Overture/FSQ coordinates as ground-truth-precise.

DISTANCE, NOT NAME MATCHING, IS NOW THE BINDING CONSTRAINT ON MATCH QUALITY: بلال/Belal (confirmed real pair, name similarity 1.0, 113.2m apart) is rejected by the 40m match gate. The name-matching pipeline (transliteration + skeleton + partial-ratio, after the two fixes above) is now good enough that the remaining gap between "matched" and "should be matched" is a distance-threshold choice, not a name-similarity failure - widening the gate would trade precision for recall (risk: more mall/chain-style false positives like the ones just fixed, at longer range). Left at 40m deliberately rather than widened further without stronger evidence per-pair.

TEST 2B — THIRD-SOURCE COMPARISON vs GOOGLE MAPS (scripts/test2b_extract.py) — NOT GROUND TRUTH, labelled as such in every output file's header. Google shows only what's open today: this measures coverage gap vs Google ONLY. It CANNOT detect stale records or businesses missing from every source. DO NOT compute a recall figure from these two files.

Two streets, both far too long to ground-truth in full (El Shabab: 5.4km: 90th Street: 24.4km) - per user direction, the highest-POI-density 500m window on each was picked programmatically (scripts/street_window_selector.py: OSM ways stitched into one ordered path via nearest-endpoint chaining, then a 500m window slid along it in 100m steps, buffered 150m, counting Overture places inside - the window with the most POIs is the street's commercial "heart"), not guessed:
  - El Shabab Street, Sheikh Zayed: chosen window near the street's southern end (159 Overture POIs vs single digits everywhere else along the 5.4km length) - close to Sheikh Zayed's established commercial area near Arkan Plaza. Cross-streets nearby: Streets 2/3/5/6/10/12/22/25/26/27/29/33/36/37, Al Zohour St, Al Mostakbal Rd, Dr. Atef Sedky St, Dr. Ali Lotfi St, Gamal El Din El Afghani St.
  - 90th Street, New Cairo (Tagamoa): chosen window right at El Orouba Axis, a well-known major intersection (270 Overture POIs, the clear density spike across the full 24.4km southern-carriageway length) - strong independent validation that the density-based window-picking method landed somewhere real and recognisable, not an artifact.

Output: output/gcheck-elshabab.csv (Overture 159, FSQ 108, 42 in both) and output/gcheck-90thstreet.csv (Overture 270, FSQ 118, 46 in both) - same column format as Test 2A minus the missing-businesses file (not meaningful for a Google-only comparison). Each file's header states the map link, window endpoints, and nearby landmarks so the user knows exactly where to check on Google.

MONTHLY ARCHIVE RUN, 2026-08-19 (release 2026-08-19.0) - first go-forward archive since the backfill, and it immediately produced a finding:
  Sheikh Zayed 491 -> 482 (-1.8%), Maadi 991 -> 947 (-4.4%), Imbaba 316 -> 285 (-9.8%). All three districts DOWN - the first month-over-month decline observed across the board.
  Effect on the business-layer track: Imbaba's artifact-corrected Overture reading moved from -4.0% (classified "flat") to -13.4% (classified "declining"), crossing the 10% flat/direction threshold. Its verdict changed from DIVERGE (flat vs growing) to DIVERGE (declining vs growing).
  METHOD FRAGILITY FINDING: a single new monthly data point flipped a district's directional classification. The prior "Imbaba flat" reading rested substantially on the 2026-07-22.0 value (316), which in hindsight looks like a transient one-release spike - the series reads 273 -> 316 -> 285 around it. Directional classifications derived from ~2 years of monthly Overture releases are therefore NOT stable to single-release noise, and should carry an explicit stability caveat wherever they are reported. This strengthens, rather than weakens, the core product principle already adopted (only report change when two independent sources within a track agree) - a single-source directional call is demonstrably not durable even after artifact correction.
  Also note: archive_release.py now DISCOVERS the latest release from S3 rather than reusing scripts/_common.py's OVERTURE_RELEASE, which stays pinned at 2026-07-22.0 so every analysis in this study keeps reproducing against one fixed snapshot. Archiving-latest and analysing-pinned are deliberately separate concerns; do not "fix" the pin to match.

Archiving note: the FSQ Iceberg pulls for these three streets (and the combined El Shabab+90th area) were dramatically faster than the original 43.5-minute district pull - 38.9s and 72.8s respectively - most likely because the underlying storage cached manifest/data files touched by that first massive full-table scan. Not guaranteed to stay fast indefinitely.

MATCHING DIAGNOSTIC (2026-08-18, scripts/matching_diagnostic.py) - the original in_both_sources rule (20m + un-normalised name similarity >=0.82) undercounts badly: it never matches Arabic-vs-Latin name pairs at all (SequenceMatcher on disjoint character sets scores ~0 - e.g. "سيلانترو" vs "Cilantro"). Re-ran three ways on all three street files:

  Road 9, Maadi (Overture=67, FSQ=58): A(original)=16.4%/19.0%, B(distance-only 30m)=92.5%/93.1%, C(normalised+skeleton fuzzy)=29.9%/37.9%
  El Shabab St (Overture=159, FSQ=108): A=13.2%/19.4%, B=90.6%/89.8%, C=27.7%/38.0%
  90th Street (Overture=270, FSQ=118): A=8.5%/19.5%, B=31.5%/91.5%, C=12.6%/29.7%

Distance-only jumping to ~90-93% for Road 9 and El Shabab confirms the ORIGINAL low overlap on those two streets was a name-matching artifact, not a real data gap - almost every FSQ record has some Overture record within 30m. Name matching itself remains hard even with Arabic-to-Latin transliteration (unidecode) plus vowel-stripped consonant-skeleton comparison: a genuine same-place pair ("كافيه سيلانترو" / "Cilantro Cafe") only scores 0.44 similarity, below even the loosened 0.5 threshold used for method C - so C undercounts real matches too, just less severely than A. Distance-only (B) is the most reliable of the three for a true overlap estimate on a dense block; category C exists to show directional improvement, not to be trusted as a precise figure.

90th Street is the exception: even distance-only is asymmetric (Overture 31.5% matched vs FSQ 91.5% matched) - most Overture points have NO nearby FSQ point at all, while almost every FSQ point has SOME nearby Overture point. Diagnosed and CONFIRMED, not just suspected:
  - 100m grid-cell clustering: one single cell holds 170/270 (63%) of all Overture points in the window; top 3 cells hold 79.6%.
  - The dominant cluster's category mix is real_estate (27) / real_estate_agent (6) / marketing+advertising / home-based professional services (beauty, dentistry, event planning) - NOT retail. Ruled out "shopping mall" as the explanation on category grounds alone.
  - Checked against actual Overture building polygons for that footprint: only 4 buildings exist there, each TINY (20-25 m^2, ~85 m^2 total, no name/subtype/height metadata) - far too small to be a mall or office tower. Yet 159/170 (93.5%) of the clustered points sit within 5m of one of these 4 tiny footprints.
  - CONCLUSION: this is not "measuring one building's directory" (the original hypothesis) - it's more likely a GEOCODING-COLLAPSE ARTIFACT, where dozens of distinct small businesses (mostly real estate/marketing firms, plausibly sharing a registration or virtual office address) have all been assigned nearly-identical coordinates. This is itself a data-quality finding worth carrying into the final verdict, not just a caveat on this one test.
  - The "270 POIs" figure for 90th Street's chosen window should NOT be read as "270 street-level businesses to ground-truth" - the large majority are collapsed onto one imprecise point. This does not invalidate the window-selection method (it correctly found where Overture has the most raw data); it means the window itself is a poor site for a street-level ground-truth check and the user should treat any Google comparison there as measuring geocoding quality at one address, not street coverage.

Test 2C — Does satellite-derived growth work where OSM doesn't? (decisive test, replaces original Test 3 design)

Legs, access-audited per the no-payment ground rule (amended 2026-08-18: free accounts with no card/billing are fine, only payment is disqualifying):

LEG A — Foursquare date_created/date_closed reconstruction: COMPLETE (2026-08-18). Access via Places Portal Iceberg REST catalog (catalog.h3-hub.foursquare.com/iceberg), free personal token, no card - stored in .env (FSQ_TOKEN), gitignored, loaded via os.environ, never hardcoded.

CRITICAL PERFORMANCE FINDING: this Iceberg table (places.datasets.places_os) has ZERO partition pruning for ANY filter - verified via EXPLAIN, which showed the identical ~21,851,018-row scan estimate whether filtering on country='EG' or a tight 1.5km bbox. A plain count(*) with a filter is fast (~11s, resolved as a streaming aggregate) but SELECT * is not - it must decode all columns (the BLOB geom column especially) across the full global table before any filter reduces the result. Two prior pulls were killed (one after 22min, unbounded RSS growth to 3.7GB with the geom column included; a retry with a narrower column list and memory_limit='2GB' set still exceeded that limit, since the Iceberg/httpfs extension's own buffers aren't fully subject to DuckDB's buffer-manager accounting) before a third attempt, filtering directly to the 3 district bboxes with geom dropped, completed in 2609.5s (~43.5 min), peaking around 3GB RSS. Splitting into per-district queries would NOT be faster - each would pay the same full-scan cost independently. This is a one-time cost per pull, not per-analysis (data cached locally at data/fsq_districts.parquet, 1599 rows, ~120KB).

Date field integrity (scripts/test2c_fsq_1_date_integrity.py), checked BEFORE any casting: 0 NULL, 0 empty, 0 unparseable in date_created across all 3 districts; single consistent format (YYYY-MM-DD) confirmed via string-shape generalisation, not assumed. date_closed is 93.5-96.4% NULL (only 32/490 Sheikh Zayed, 61/1025 Maadi, 3/84 Imbaba have a close date) - the reconstruction below is overwhelmingly openings-only, exactly the weak-signal risk the user flagged in advance.

unresolved_flags (scripts/test2c_fsq_2_unresolved_flags.py, undocumented field, inspected directly): does NOT replicate Overture's poverty-correlated confidence pattern. Imbaba is 0.0% flagged (lowest of the three), Sheikh Zayed highest at 2.04%. Values observed: duplicate, inappropriate+delete, privatevenue - community-moderation flags that require active user engagement to generate, so they cluster where FSQ usage is higher (Sheikh Zayed/Maadi), not where data quality is worse. Filtering on this field would not penalise Imbaba - there's nothing there to filter.

FSQ category mapping (scripts/categories.py FSQ_* sets, SEPARATE from the Overture mapping, built from the real 312-label vocabulary in output/fsq_category_vocabulary.txt): FSQ's fsq_category_labels are genuinely hierarchical ("Dining and Drinking > Restaurant > Italian Restaurant"), so the restaurant group uses safe prefix matching against every subtype nesting under "Dining and Drinking > Restaurant" - unlike Overture's flat strings, where prefix/substring matching was fragile.

FSQ count vs Overture mapped count, per district (output/test2c_fsq_vs_overture_counts.csv): Sheikh Zayed and Maadi totals are close to Overture's (490 vs 491; 1025 vs 991 - FSQ actually higher in Maadi). Imbaba is a striking outlier: FSQ total is 84 vs Overture's 316 (27%) - pharmacy ratio is literally 0 (zero FSQ pharmacies vs 10 in Overture), restaurant 0.17x, grocery 0.13x. This is now the THIRD independent source (after zero OSM coverage and 96.5% single-source Meta reliance) showing severe under-coverage specifically in Imbaba - a consistent, triply-corroborated finding, not a one-off.

date_created histogram by year, 2010-2026 (output/test2c_fsq_date_created_histogram.csv) - answering the realism question directly:
  - Maadi: dominated by an implausible 2011-2013 spike (131, 177, 179 - over 40% of all-time records created in just those 3 years), tapering sharply afterward. This is a textbook Foursquare-check-in-adoption artifact, exactly matching the user's prediction (Egypt FSQ usage peaked ~2012-2016) - NOT evidence of real business formation timing. FLAGGED as implausible.
  - Imbaba: modest early peak (2012-2015: 17,15,12,17) then drops to near-zero for most of 2016-2026 - too thin to read as anything beyond minimal, declining FSQ engagement in this area (consistent with its severe undercoverage above).
  - Sheikh Zayed: the OPPOSITE pattern - its largest peaks are 2021 (70) and 2022 (86), LATER than Egypt's FSQ-adoption peak, and this later peak is independently corroborated by real construction growth in the same window from Open Buildings (Leg B) and GHSL (Leg D). This is evidence Sheikh Zayed's date_created signal reflects real business formation, not platform-adoption noise, unlike Maadi's.

Reconstructed "open as of 1 Jan", 2015-2026 (output/test2c_fsq_reconstruction.csv): Sheikh Zayed 120->445 (+270.8%), Maadi 620->954 (+53.9%), Imbaba 52->81 (+55.8%).

Fed into the corroboration matrix's business layer track (see below) - Maadi and Sheikh Zayed now get a real verdict instead of UNCORROBORATED - SINGLE SOURCE.

LEG B — Google Open Buildings 2.5D Temporal, annual rasters 2016–2023 (scripts/test2c_open_buildings.py). WORKS — confirmed anonymous, keyless read access to storage.googleapis.com/open-buildings-temporal-data. Non-obvious gotcha: tile URLs are built by concatenating the manifest's uriPrefix directly with each tile's uri with NO separator (uriPrefix ends mid-folder-name); adding a "/" 404s. Three bands reported per district per year: built_up_area_index (sum of building_fractional_count, 0.5m-pixel units — per Google's own docs this is "source data for deriving building counts," NOT a calibrated count; useful only for relative year-over-year comparison), mean_height_where_present_m (mean of building_height over pixels where building_presence > 0.5), and presence_area_m2 / presence_pct_of_bbox (area of pixels with building_presence > 0.5 — a real physical area in m²).

IMPORTANT FINDING (2026-08-18): built_up_area_index is unreliable in dense informal fabric. It showed Imbaba declining -14.4% 2016→2023, which does not survive corroboration - both the presence-based metric (+2.6%, flat) and an independent source (GHSL, +0.2%, flat) say Imbaba is flat, not declining. Diagnosis: the fractional-count band is sensitive to the model splitting/merging adjacent structures inconsistently between imagery years in dense abutting-structure fabric; the presence band (binary-ish extent, not fractional count) does not have this problem. DECISION: use presence_area_m2, not built_up_area_index, as Open Buildings' signal in the corroboration matrix and everywhere else in this study. built_up_area_index is retained in the raw output for transparency but should not be trusted alone.

2016 BASELINE CONTAMINATION, FOUND AND FIXED (2026-08-18): looking at the chart directly, Imbaba's entire "-14.4% decline" happens in the single 2016->2018 window, then the series is flat for the remaining five years. Cause: Sentinel-2B (the second Sentinel-2 satellite) only launched March 2017, so the 2016 annual composite was built from Sentinel-2A alone at half the revisit rate - fewer cloud-free frames, worst degradation in dense complex fabric like Imbaba's. This is a sensor-transition artifact in the 2016 vintage, not a real change. FIX: scripts/corroboration.py now uses OPEN_BUILDINGS_BASELINE_YEAR = 2018 for all growth figures, excluding 2016-2017. Corrected numbers (2018->2023, presence-based): Sheikh Zayed +13.6% (was +45.5% from the contaminated 2016 baseline), Maadi +0.7% (was +1.6%), Imbaba -0.6% (was +2.6%, still flat either way). All three districts' directional classification (growing/flat/flat) is UNCHANGED by the rebaseline - only Sheikh Zayed's magnitude moves meaningfully, which matters because it's the one district where the built-environment track fires positively. Raw output (test2c_open_buildings_annual.csv) still contains 2016-2017 for transparency; just excluded from growth calculations.

BUILDING COVERAGE RATIO (new standing district attribute, 2026-08-18): Open Buildings presence % divided by GHSL built-up %, computed in scripts/corroboration.py (coverage_ratio_signal), written to output/building_coverage_ratio.csv. Separates villa/garden fabric (ratio well below 1 - GHSL's coarser 100m built-up-surface measure counts more "built" than Open Buildings' finer presence detection, because a villa plot is mostly garden/setback, not building) from wall-to-wall dense fabric (ratio at or above 1 - the reverse). Neither source alone reports this distinction. Results: Sheikh Zayed 0.57, Maadi 0.58 (both villa/garden-pattern low-density fabric, despite Maadi being SATURATED by built-up %), Imbaba 1.31 (wall-to-wall dense fabric). This is a genuinely new piece of information this study has produced, not present in any single source - it explains WHY Maadi and Imbaba can both be "SATURATED" (40% and 43.6% built-up) yet be completely different physical environments.

HEIGHT: UNRELIABLE, EXCLUDED FROM THE CORROBORATION MATRIX (2026-08-18): mean_height_where_present_m wobbles +/-1m in Maadi across all 8 years with no discernible trend, and Sheikh Zayed's +1.5m rise (12.2m->13.8m) is barely outside that same noise band. Height is reported in the raw output (test2c_open_buildings_annual.csv) and plotted for transparency, but is NOT fed into the corroboration matrix as an independent signal and should not be treated as corroborating evidence for growth or stability in either direction.

LEG C — VIIRS nighttime lights: DEPRIORITISED per user direction (2026-08-18). EOG's own registration page states free accounts cover browser access only; "programmatic access to the global data" needs a paid subscription ("nominal fee") - a real conflict with the no-payment rule that free registration alone doesn't resolve. GHSL (below) fills VIIRS's originally-intended role (a signal spanning both the Open Buildings and Overture eras) for free and without registration, so VIIRS is shelved rather than worked around. Revisit via Google Earth Engine if actually needed later - out of scope for now.

LEG D — JRC Global Human Settlement Layer, GHS-BUILT-S, epochs 2015/2020/2025 (scripts/test2c_ghsl.py). WORKS — plain browsable HTTP index at jeodpp.jrc.ec.europa.eu, no login, no redirect. This is the fix for the no-calendar-overlap problem between Open Buildings (2016-2023) and Overture history (2024-2026): GHSL's 2015/2020/2025 epochs span both eras, so it corroborates across that boundary directly rather than only via trend continuity. Pixel value = built-up surface in m² (confirmed directly). Tiling gotcha: the "row/col" grid is NOT a clean 10°-from-90° grid - actual tile boundaries are offset (e.g. the R6/R7 boundary sits at lat 29.0996, not 30.0) - verified by downloading and checking real tile bounds after an initial wrong guess produced 0.0% built-up for Maadi.

LEG E — DLR World Settlement Footprint Evolution, annual 1985–2015 (scripts/test2c_wsf_evolution.py). WORKS — plain HTTP index at download.geoservice.dlr.de, no login. One file per 2°x2° tile; pixel value = the year first detected as built-up (0 = never by 2015) - the full 30-year annual series comes from a single ~6MB download. Reports structural context (% of bbox settled by year), NOT folded into the direction-agreement vote below since it answers a different question (mature vs newly-developed) over a mostly non-overlapping window. Tiling gotcha: same as GHSL - actual tile bounds don't sit at clean integer degrees; Maadi needed the tile one step further south than its nominal coordinate suggested.

Corroboration matrix (scripts/corroboration.py) — the core cross-source check, now also a standing product concept (see below). RESTRUCTURED 2026-08-18 into two INDEPENDENT tracks that are never mixed:

  BUILT ENVIRONMENT track (measures buildings): Open Buildings presence, GHSL, WSF Evolution (context only - see caveat below).
  BUSINESS LAYER track (measures businesses): Overture release history, Foursquare reconstruction (pending).

Why: a v1 single combined vote flagged Maadi as "DIVERGE" because Overture (business count) said +63.8% growing while Open Buildings/GHSL (buildings) said flat. That is not a contradiction - a fully-built district can have flat construction and active business churn at once. Corroboration only applies WITHIN a track now. A track with only one live source is reported as UNCORROBORATED - SINGLE SOURCE, not given a verdict - that is the business layer's honest status in all three districts right now, since Foursquare (the only other possible business-layer source) is still pending.

Before feeding Overture release history into the business-layer track, artifact detection (scripts/artifact_detection.py) runs first: a release-over-release jump >= 40% that then holds flat for >= 3 releases is treated as a bulk-import artifact, excluded, and growth is recomputed from the post-artifact baseline. 40% sits in the natural gap between the largest ordinary jump anywhere in the dataset (28.3%, Sheikh Zayed) and the one clear outlier (90.2%, Imbaba) - not tuned to force a specific answer. Even after correction, Overture's business-layer reading is NOT a confirmed finding on its own - it needs Foursquare (or another business source) to actually corroborate it. No single threshold on Overture-alone can also catch Maadi's smaller, likely-also-artifactual jumps (23-24%) without also wrongly flagging Sheikh Zayed's real, buildings-corroborated growth (27-28%) - a concrete demonstration that single-source heuristics cannot substitute for cross-source corroboration.

Saturation classification (standing per-district attribute, from GHSL's latest built-up %, NOT a change metric): SATURATED (>=40%), DEVELOPING (10-40%), GREENFIELD (<10%). Sheikh Zayed = DEVELOPING (23.1%), Maadi = SATURATED (40.0%), Imbaba = SATURATED (43.6%). A flat built-environment signal in a SATURATED district is EXPECTED, not a finding of stagnation - the ceiling is real (WSF's "flat" readings for Maadi/Imbaba above 90% settled are partly this same ceiling effect, flagged inline in script output).

Built-environment track result (UPDATED 2026-08-18 with 2018 rebaseline - see below): AGREE across all three districts - Sheikh Zayed growing (Open Buildings presence +13.6% from 2018, GHSL +12.5% from 2015, WSF +62930%-from-near-zero since 1985), Maadi flat (+0.7% / +0.8% / +3.7%-near-ceiling), Imbaba flat (-0.6% / +0.2% / +0.1%-near-ceiling). This is now a solid, cross-corroborated finding, and post-rebaseline Sheikh Zayed's Open Buildings and GHSL rates now agree closely in MAGNITUDE too (13.6% vs 12.5%), not just direction.

Business-layer track result (UPDATED 2026-08-18, Foursquare live): Sheikh Zayed AGREE (growing) - Overture +79.9%, Foursquare +270.8%. Maadi AGREE (growing) - Overture +63.8%, Foursquare +53.9%, BUT flagged with a caveat, not taken at face value: Foursquare's own date_created histogram for Maadi is dominated by an implausible 2011-2013 adoption-artifact spike (see Leg A above), so both business sources may share a correlated confound - "when did this place get digitized on an early-2010s-era platform" rather than "when did this business open." Numeric agreement between two sources does not fully resolve this if both are subject to a similar-shaped historical bias; Maadi's business-layer growth should be read as tentative even with the second source. Imbaba DIVERGE (flat vs growing) - Overture corrected -4.0% flat, Foursquare +55.8% growing, but Foursquare's Imbaba reading rests on only 84 total records (vs 316 in Overture, the severe under-coverage finding above) moving from 52 to 81 - i.e. a 29-record difference over 12 years. Low statistical power; this divergence should not be read as equally weighted against Sheikh Zayed's or Maadi's more robust readings.

Remaining limitation, restated: the built-environment track's flat readings in Maadi/Imbaba are EXPECTED (saturation), not a gap. The business-layer track is now corroborated (2 sources) rather than single-source, which is real progress - but Maadi's agreement may be a shared-artifact illusion rather than confirmed real growth, and Imbaba's divergence is on thin data. Next step (Test 2 ground truth) is exactly what's needed to adjudicate both remaining open questions - it cannot be resolved with more free data sources alone.

PRODUCT PRINCIPLE (elevated from a study finding to a standing design rule, 2026-08-18): Third Eye should only ever report a change to a user when at least two independent sources WITHIN THE SAME TRACK agree on its direction. Cross-track agreement/disagreement is not meaningful and must never be used as a corroboration signal.

Kill criterion: the built-environment track is flat or contradictory across all three districts (NOT triggered - full agreement), OR every district's business layer remains permanently uncorroborated with no path to a second source (NOT YET DETERMINED - Foursquare is pending, not dead).

Test 4 — Is the population layer sane? (RUN 2026-08-18, scripts/test4_kontur_population.py)

Kontur Population, Egypt subset, 400m H3 hexagons, most recent vintage (2023-11-01), direct HDX/S3 download, no key. Clipped to the 3 district bboxes (hexagons straddling the boundary weighted by fraction of area inside the bbox). Choropleth PNG per district in output/test4_kontur_<district>.png.

Population totals (area-weighted) and density per bbox (2.25 km^2):
  Sheikh Zayed: 2,321 people (1,032/km^2) - 7 hexagons
  Maadi: 43,001 people (19,112/km^2) - 8 hexagons
  Imbaba: 103,601 people (46,045/km^2) - 8 hexagons

Ordering (Imbaba >> Maadi >> Sheikh Zayed) is exactly what independent evidence from every other test in this study would predict: Imbaba is the dense, informal, fully-built district (43.6% GHSL built-up, 99.8% WSF-settled since before 1985); Maadi is mature but lower-rise/villa-heavy (40.0% built-up); Sheikh Zayed is the newest, most spread-out development (23.1% built-up, still under construction per Test 2C). This is a strong plausibility check, not a coincidence - it corroborates the built-environment findings from a completely independent dataset/methodology.

Reference-point ordering check (dense residential / commercial / empty) - PENDING, user to supply the three points.

FLAG FOR THE FINAL VERDICT (2026-08-18): the district with the working, cross-corroborated growth signal (Sheikh Zayed, built-environment AGREE-growing and business-layer AGREE-growing) has 1,032 people/km^2. The district with real residential demand and density (Imbaba, 46,045 people/km^2 - 45x Sheikh Zayed's) has NO working growth signal on either track (built-environment flat, business-layer DIVERGE). Maadi sits in between (19,112 people/km^2, built-environment flat/expected, business-layer AGREE-growing but on Overture data with a known artifact-adjacent history - see business-layer notes above). This inverse relationship between "where the data confidently shows something happening" and "where the people actually are" is a structural limitation of what this study's temporal signals can currently support - it directly limits what any single combined score across districts could mean, and should be stated plainly in the final verdict rather than averaged away.

Kill criterion: the empty area returns a substantial population, or the ordering of the three points is wrong - NOT YET TESTABLE, awaiting the three reference points from the user.

Test 5 — Does the data separate winners from losers? (features revised)

Given a CSV of ~20 businesses with known fate (name, lat, lon, year_opened, outcome), compute per business, as of its opening year where possible:

DROPPED: "Competitors of the same category within 500m" and "Transit stops within 500m" as of opening year via ohsome — uncomputable, per the Test 2b finding (no usable OSM history in this market).

REVISED feature set:
- Building count change within 500m over the 3 years before opening (Google Open Buildings, Test 2C leg B)
- VIIRS trend over the same window (Test 2C leg C — pending, see above)
- Population change over the preceding 3 years (GHSL or WorldPop — Kontur is a single-vintage snapshot, not usable for a trend; to be confirmed which of GHSL/WorldPop has the needed vintages)
- Competitors of the same category within 500m — kept, but as a PRESENT-DAY feature only, clearly labelled as such (not "as of opening year")

Then report, plainly: mean/median of each feature split by outcome; whether any feature separates the two groups. Given n≈20, state clearly this is directional evidence only — no significance tests presented as conclusive, no classifier fit on 20 rows.

Kill criterion: no feature meaningfully separates survivors from closures.

Deliverable

A single VERDICT.md at the repo root containing:
A one-paragraph bottom line: is this project viable on free data in this market, yes or no?
Each test: what you ran, the numbers you got, pass or fail against its kill criterion
The three biggest data problems you found, ranked by how much they'd damage the product
What you could not test, and why (Foursquare reconstruction and VIIRS both belong here unless leg C gets unblocked)
If the verdict is positive: which single district has the best data quality, as the place to prototype first

Be blunt. I would rather kill this idea this week than in six months. If the data is bad, say the data is bad — do not soften it or suggest workarounds that require paid data or accounts.

================================================================================
PART II — PRODUCT DATA PLATFORM (Greater Cairo + Giza)
Added 2026-08-20. Everything above this line is the 3-district feasibility
study. Everything below is the production data layer built on its findings.
================================================================================

STEP 1 — SCHEMA DECISIONS (NON-NEGOTIABLE)

These four decisions are locked. They are not defaults to be revisited casually;
each one exists because the feasibility study above produced direct evidence for
it. Any future change to these requires re-deriving the affected history and
should be treated as a migration, not a config tweak.

(a) H3 RESOLUTIONS: res 8 primary (~0.74 km^2/cell), res 9 fine (~0.11 km^2).
    All aggregates are keyed to exactly these two resolutions - no others, no
    ad-hoc radii stored as first-class data. Derived radius queries ("within
    500m") are computed at read time from res-9 cells via k-ring, not stored.
    Rationale: a fixed cell grid is the only way metrics from sources with
    wildly different native geometries (points, 100m rasters, 400m hexagons,
    0.5m rasters) can be compared cell-for-cell at all.

(b) IMMUTABLE VERSIONING: every ingest writes a NEW snapshot tagged with its
    upstream release/snapshot identifier. Nothing is ever overwritten or updated
    in place. No UPSERT, no "latest" table that mutates, no dedup-on-write that
    discards the prior state.
    Rationale, stated plainly because it is the single most important decision
    here: this study has 22 Overture releases of temporal signal ONLY because
    someone archived each release instead of merging it. Overture's own S3 and
    Azure keep exactly one release; the entire historical capability came from a
    third-party mirror that happened to retain them. Merge-on-write would have
    destroyed the product's core differentiator permanently and silently. The
    2026-08-19 archive run proved the point again: a single new release flipped
    Imbaba's directional classification, which is only knowable because the
    prior state still exists.

(c) RAW AND DERIVED STORED SEPARATELY:
      raw     = records exactly as fetched, unmodified, no cleaning, no joins.
      derived = resolved entities + H3 aggregates, always reproducible from raw.
    Re-derivation NEVER re-downloads. Every derived artifact records the
    resolver_version and the source snapshot ids it was built from.
    Rationale: entity resolution produced four distinct bugs across two review
    rounds in this study alone (short-skeleton false positives; bare-title "Dr"
    fragments; greedy-overwrite orphaning better matches; locality-suffix
    collisions). Resolution logic WILL keep changing. If raw and derived are
    entangled, every logic fix costs a full re-download of every source.

(d) CONFIDENCE IS PER METRIC PER CELL, NOT PER LOCATION.
    Levels: corroborated (2+ independent sources within the same track agree)
          / single_source (only one source has it)
          / unavailable (no source covers it).
    Confidence is an attribute of (cell, metric), never of a cell alone, and
    never averaged across tracks.
    Rationale: Imbaba has good population data (Kontur, plausible and
    cross-corroborated by GHSL/WSF), good built-environment data (Open Buildings
    + GHSL + WSF all agree), and BAD single-source business data (96.5% Meta in
    Overture; FSQ has 84 records vs Overture's 316; zero OSM). A single
    location-level confidence badge would be wrong in both directions
    simultaneously - overstating business confidence and understating population
    confidence. Corroboration is computed WITHIN a track only; cross-track
    agreement is meaningless (a fully-built district can have flat construction
    and active business churn at once - this was the Maadi "DIVERGE" error
    already corrected once in this study).

STEP 1 — PROPOSED STORAGE LAYOUT AND SCHEMA

Layout (partition keys in the path, so a snapshot is addressable without a
catalog and an accidental overwrite requires deleting a directory, not a row):

  data/raw/<source>/snapshot=<upstream_id>/...            # immutable
  data/derived/entities/resolver=<ver>/snapshot=<id>/...  # reproducible
  data/derived/h3/res=<8|9>/metric=<name>/resolver=<ver>/snapshot=<id>/...

Three schemas:

1. RAW RECORD (one table per source; columns are whatever the source gives,
   plus the following mandatory provenance columns - never fewer):
     _source              string    # overture | fsq | ghsl | open_buildings | kontur | wsf
     _snapshot_id         string    # upstream release id, e.g. "2026-08-19.0"
     _fetched_at          timestamp
     _fetch_query         string    # exact bbox/filter used, for reproducibility
   Raw is append-only. A re-fetch of the same _snapshot_id is a no-op.

2. ENTITY (derived; a resolved real-world place across sources):
     entity_id            string    # stable surrogate key
     name_primary         string
     name_variants        array<string>
     category_canonical   string    # our taxonomy, not any source's
     lat, lon             double
     position_uncertainty_m double  # from the measured cross-source distribution
     h3_r8, h3_r9         string
     source_refs          array<struct<source string, source_id string, snapshot_id string>>
     n_sources            int
     first_seen_snapshot  string
     last_seen_snapshot   string
     resolver_version     string
   Note position_uncertainty_m is a REQUIRED field, not optional: measured
   cross-source disagreement is median 10.2m / p90 58.5m / max 381.7m. Storing a
   coordinate without its uncertainty would present ~60m-p90 data as exact.

3. H3_METRIC (derived; the product-facing aggregate - this is decision (d)):
     h3_index             string
     h3_res               int       # 8 or 9
     metric               string    # e.g. "business_count.cafe", "population", "builtup_pct"
     track                string    # business | built_environment | population
     value                double
     confidence           string    # corroborated | single_source | unavailable
     n_sources            int
     contributing_sources array<string>
     as_of                date      # what point in time the value describes
     source_snapshots     map<string,string>   # source -> snapshot id used
     resolver_version     string
     computed_at          timestamp
   PRIMARY KEY (h3_index, metric, as_of, resolver_version, source_snapshots).
   Because confidence and track are columns on this row and not on the cell,
   one cell legitimately carries corroborated population, corroborated
   built-environment, and single_source business simultaneously - which is
   exactly the Imbaba case that motivated decision (d).

STEP 2 — COVERAGE AREA (config/coverage_area.gpkg + .json,
built by scripts/build_coverage_area.py)

Source: OSM admin_level=4 relations - Cairo 4103336, Giza 3824206. NOT a bbox.

  admin_full   (legal union)          41,301 km^2   res-8: 47,147   res-9: 330,027
  operational  (admin ∩ built-up)      5,664 km^2   res-8:  6,528   res-9:  45,761

PROBLEM FOUND: Giza governorate legally extends ~450 km west into the Western
Desert (bbox reaches lon 27.31). The raw admin union is 41,301 km^2 of which
~86% is empty Sahara. Under decision (b) - immutable, never deleted - carrying
~284,000 permanently-empty res-9 cells would be a forever cost.

RESOLUTION: both polygons are saved. admin_full is kept as the reference
geometry (answers "is X legally in Cairo/Giza?" and lets the operational
polygon be re-derived if the built-up definition changes). operational is the
ingest target: admin_full intersected with a GHSL-2025 built-up mask
(>=500 m^2 built-up per ~8,500 m^2 pixel) dilated by 2 km so the active growth
frontier is inside coverage rather than clipped at today's edge. This is still
admin-boundary-derived, not a hand-drawn box.
CAVEAT: cached GHSL tile R6_C22 covers lat >= 29.0996N. Giza's southern desert
tail below that is excluded (uninhabited); pull tile R7_C22 if that changes.
OPEN QUESTION for the user: "Greater Cairo" conventionally includes Qalyubiya
(Shubra El Kheima, OSM relation 4103337), which is NOT currently included.
Adding it later is cheap (union + re-derive); it is flagged, not assumed.

STEP 3 — INGEST METHOD AND COST, PER SOURCE (measured, not guessed)

FOURSQUARE - METHOD CHANGED, ~45x FASTER. Use PyIceberg, not DuckDB.
  The DuckDB iceberg extension ignores manifest pruning on this table: it
  reported the same ~21.85M-row scan for every filter, which is why the
  3-district pull took 43.5 minutes for 6.75 km^2.
  PyIceberg plan_files() DOES prune: 28 files / 11.25 GB total -> 4 files /
  1.98 GB. Catalog connection requires warehouse='places' (the /v1/config
  endpoint 400s without it; namespace is 'datasets', table 'places_os').
  CRITICAL PROPERTY: pruning returns the SAME 4 files / 1.98 GB for a single
  300m street, for the whole operational city, and for all of Egypt. The table
  has NO partition spec and NO sort order (verified: t.spec() and
  t.sort_order() are both empty), so pruning is coarse file-level only. The
  marginal cost of taking all of Egypt over one street is therefore ZERO.
  => RECOMMENDED: one Egypt-wide pull per snapshot, stored raw, clipped locally.
     Never pull per-district again.
  MEASURED: full operational-city extent = 72,808 rows, 58 seconds wall time
  with column projection (9 of 27 columns; excluding the BLOB geom column
  matters). This is a measurement of the real scan, not an extrapolation from a
  sample - nothing was written to disk.

OVERTURE - METHOD UNCHANGED, ALREADY GOOD. DuckDB + S3 parquet bbox pushdown.
  MEASURED: 161,489 places in the operational-city bbox, 14.2 seconds.
  Pushdown works properly here (unlike the FSQ path). Keep the existing method.
  Caution already learned: do NOT add SQL-side unnest() or multi-bbox OR to
  these queries - both defeat row-group pruning and turn ~15s into 10+ minutes.

GHSL - ESSENTIALLY FREE, ALREADY CACHED.
  Single tile R6_C22 covers the entire operational polygon; 3 epochs
  (2015/2020/2025) are already in data/ghsl_cache/ at ~19 MB each. Marginal
  ingest cost is seconds. No further download needed for current epochs.

OPEN BUILDINGS - THE EXPENSIVE ONE. Plan for hours, and parallelise.
  MEASURED: 101 tiles intersect the operational polygon per year; a
  representative 2km x 2km 2-band windowed read takes 4.6 s.
  City is 5,664 km^2 = ~1,416 such windows per year:
    ~1.8 hours per year single-threaded
    ~10.9 hours for 2018-2023 (6 usable years; 2016-2017 excluded as
    sensor-transition-contaminated per the Part I finding)
  These are independent HTTP range reads, so this parallelises near-linearly:
  expect ~1-1.5 hours wall time at 8-16 workers. Budget accordingly; this is
  the only source where city-scale ingest is a genuinely long job.

WSF EVOLUTION / KONTUR - trivial. WSF is one ~6 MB tile per 2°x2° (2-3 tiles
  for the city); Kontur Egypt is a single 19 MB gpkg already downloaded. Both
  are one-off, seconds-to-minutes.

TOTAL first full ingest: dominated entirely by Open Buildings. Everything else
combined is ~2 minutes.

NOTED FOR LATER - DO NOT BUILD YET (user instruction 2026-08-20):
  Coverage map per track (business layer / built environment / population) at
  H3 res 8, showing % of cells at each confidence level, broken down by GHSL
  built-up % band. Purpose: test whether business-layer coverage tracks
  affluence across the whole city the way it demonstrably did across the three
  study districts (Imbaba: 96.5% single-source, 27% of Overture's count in FSQ,
  zero OSM). This is the city-scale generalisation of Part I's central bias
  finding and is the highest-value first analysis once ingest lands.

================================================================================
PART II REVISION — 2026-08-20: ALEXANDRIA ADDED TO LAUNCH COVERAGE
Supersedes the Step 2 numbers and Step 3 estimates above. Schema decisions
(a)-(d) are unchanged, plus one new REQUIRED cell field (land_fraction).
================================================================================

LAUNCH COVERAGE IS NOW FOUR GOVERNORATES (OSM admin_level=4):
  Cairo 4103336 | Giza 3824206 | Alexandria 3061846 | Qalyubiya 4103337
Qalyubiya was the open question flagged on 2026-08-20; now agreed and included.
Governorates are matched by OSM RELATION ID, not name - OSM's name:en values
are "Aj Jiza" and "Al Qalyubiya", which silently dropped two governorates on
the first attempt.

  admin_full (legal union)                46,670 km^2
    Cairo 3,006 | Giza 38,295 | Alexandria 4,197 | Qalyubiya 1,171
  operational (admin ∩ built-up + 2km)      8,708 km^2  (18.7% of admin)

  H3 cells in the operational polygon:
    res-8:  10,038 in polygon ->  9,938 with land (100 pure-water dropped)
    res-9:  70,259 in polygon -> 69,103 with land (1,156 pure-water dropped)

Alexandria's admin boundary runs far west along the coast toward Matruh, so
the built-up mask does the same job there it does for Giza's Western Desert:
~81% of the legal area is excluded as unbuilt.

NEW REQUIRED FIELD — land_fraction (CORRECTNESS, NOT AN ENHANCEMENT)

Decision (e), added to the locked schema set: every H3 cell carries
land_fraction (0..1), and ALL catchment metrics normalise by land area, never
by raw radius or raw cell area.

Rationale, and this is a correctness bug not a refinement: Alexandria is a
linear coastal city. A 500m catchment on the Corniche is roughly half sea.
Without land normalisation, competitor counts and population both read low
there, and the product would score a prime waterfront location as "low
competition" when the truth is "half water". The identical failure applies at
desert edges and along the Nile. Every waterfront location in the product
would be systematically mis-scored.

VERIFIED against known points (this is the mechanism working, not a guess):
  Alex Corniche (Stanley)      res-9 land_fraction 0.521   <- the predicted case
  Cairo Nile (Zamalek island)  res-9 0.697 / res-8 0.919
  Maadi Road 9                 res-9 1.000 / res-8 0.681  (res-8 cell reaches the Nile)
  Alex inland (Smouha)         res-9 1.000
  Sheikh Zayed (desert edge)   res-9 1.000
Distribution: mean land_fraction 0.973 (res-8) / 0.979 (res-9); 540 res-8 and
2,721 res-9 cells are below 0.9; 190 res-8 and 1,139 res-9 cells below 0.5.
Those sub-0.5 cells are precisely the waterfront cells that would otherwise be
scored as empty opportunity.

Source: GHSL GHS-LAND R2022A, 100m, Mollweide (ESRI:54009), tile R6_C21.
Stored at config/h3_land_fraction_res{8,9}.csv (h3_index, land_fraction,
n_pixels, n_nodata_pixels).
TWO TRAPS, both verified empirically rather than assumed:
  1. GHS-LAND values are scaled 0..10000 (83% of pixels are exactly 10000 =
     fully land). 65535 is the NODATA sentinel, not a valid high value -
     naive use reads nodata as 6.5x fully-land.
  2. GHS-LAND's Mollweide tiling is a DIFFERENT grid from GHS-BUILT-S's
     4326_3ss tiling. Both have a tile called "R6_C21" and they cover
     different ground. Do not assume tile ids correspond across products.

Implementation note: the built-up mask is dilated in RASTER space (binary
dilation, 2km converted to pixels at local latitude) and vectorised once.
The obvious approach - polygonize every built-up pixel then .buffer(2km) -
OOM-killed on this coverage area, because the Nile Delta and valley produce
millions of disconnected pixel polygons whose unary_union exhausts memory.

STEP 3 REVISED — INGEST COST WITH ALEXANDRIA (all measured 2026-08-20)

FOURSQUARE — UNCHANGED COST, as predicted. Still 4 files / 1.98 GB pruned
  (identical to the 3-district and Cairo-only cases: the table has no
  partition spec, so pruning is coarse and area-independent). The Egypt-wide
  pull already covered Alexandria; marginal cost of adding it is genuinely
  zero.
  MEASURED: 99,048 rows across the 4-governorate extent, 23.1 s.
  (Cairo+Giza only was 72,808 rows / 58 s; the faster wall time here is
  run-to-run variance in streaming the same 1.98 GB, not a real speedup.)

OVERTURE — scales with area, still cheap.
  MEASURED: 250,995 places in the 4-governorate bbox, 18.1 s
  (was 161,489 rows / 14.2 s for Cairo+Giza). Method unchanged.

OPEN BUILDINGS — THE EXPENSIVE ONE, AND ALEXANDRIA CROSSES A UTM ZONE.
  Alexandria sits at lon ~29.2-30.2, straddling UTM 35N and 36N. The existing
  manifest (chunk 15, EPSG:32636) does NOT cover it. Both zones are required:
    chunk 15 / EPSG:32635 :  36 tiles   <- new, Alexandria
    chunk 15 / EPSG:32636 : 116 tiles   (was 101 for Cairo+Giza)
    chunk 17 / either zone:   0 tiles
    TOTAL 152 tiles per year (was 101) = +51 tiles for 2023, +50%
  Revised wall time, from the measured 4.6 s per 2km x 2km 2-band window:
    8,708 km^2 / 4 km^2 = ~2,177 windows per year
    ~2.8 hours per year single-threaded
    ~16.7 hours for 2018-2023 (6 usable years) single-threaded
    ~1-2 hours wall time at 8-16 parallel workers (independent HTTP range
    reads, parallelises near-linearly)
  This remains the only source where city-scale ingest is a long job.

GHSL / GHS-LAND / WSF / KONTUR — still trivial. GHS-BUILT-S needed one extra
  4326 tile (R6_C21) for Alexandria's western extent; GHS-LAND is one 2.7 MB
  tile. All already downloaded.

TOTAL first full ingest: still dominated entirely by Open Buildings
(~1-2 h parallelised). Everything else combined is ~1 minute.

STEP 4 — ALEXANDRIA AS A GENERALISATION TEST (PLAN ONLY, NOT YET RUN)

Runs after ingest. Repeats the Part I analysis on 2-3 Alexandria areas of
differing income level:
  - per-source contribution share (the Test 1b source-breakdown analysis)
  - confidence distribution per district
  - Foursquare date_created histogram by year
THE QUESTION, stated so the result cannot be quietly reinterpreted later:
  Is business-layer coverage single-source in poorer districts in Alexandria
  the way it is in Imbaba (96.5% Meta-only, zero OSM, FSQ at 27% of Overture's
  count)? And does Foursquare's date_created still cluster 2011-2013 (the
  national check-in-adoption artifact) rather than tracking real business
  formation?
  If Alexandria reproduces the pattern, the Part I findings are STRUCTURAL and
  we can claim them as properties of free geodata in Egypt generally.
  If Alexandria does NOT reproduce it, the findings are CITY-SPECIFIC to
  Cairo, and every conclusion in Part I must be restated with that scope
  limit - including the coverage-tracks-affluence claim, which is currently
  the study's most load-bearing bias finding.
Areas to be nominated by the user (needs local knowledge of Alexandria income
geography - not inferable from the data, and inferring it from the data would
be circular given that data coverage is the thing under test).

================================================================================
PART III — CITYWIDE INGEST (2026-08-20)
================================================================================

PERMANENT DATA GAP: OVERTURE RELEASE 2026-06-17.0
This release is LOST at every extent and is not recoverable. Anyone reading
the business-layer history later will see a jump from 2026-05-20-0 to
2026-07-22.0 and must NOT interpret it as a real-world anomaly. Cause:
  - Overture official S3 retains only ~2 releases; 2026-06-17.0 has aged out.
  - Azure held only 0-byte placeholder blobs for it (verified in Part I).
  - The Source Cooperative mirror never received it (its series runs
    2024-02-15-alpha-0 .. 2026-05-20-0, then resumes only via S3).
There is no third source. Treat the June 2026 point as missing data, not as
zero and not as a decline.

NEAR-MISS, same cause: 2026-07-22.0 existed ONLY on S3 (the mirror does not
reach it) and was days from ageing out. It was re-clipped citywide first, on
2026-08-20, specifically to secure it. Had the monthly archiver kept running
at the old 3-district extent, that release would have been permanently
reduced to 6.75 km^2 of history.

MONTHLY ARCHIVER — CHANGED 2026-08-20 (scripts/archive_release.py)
  - Now saves the FULL 4-governorate operational extent, not the 3 study
    districts. Writes to data/raw/overture/snapshot=<release>/.
  - Now checks the Source Cooperative mirror as well as S3 on every run and
    prints any release the mirror offers that we have not archived, so gaps
    surface the month they appear rather than years later.
  - Mirror check distinguishes "unreachable" from "offers nothing" - an
    earlier version 403'd (data.source.coop rejects a default urllib
    User-Agent) and reported "local archive covers everything", which is
    exactly the silent failure this job exists to prevent.
  - MUST RUN MONTHLY. A month archived at the wrong extent, or not archived
    at all, is citywide history that cannot be bought back.

RE-CLIP OF THE ARCHIVE (scripts/reclip_archive.py)
  Re-fetches archived releases at the operational extent into the raw layer.
  Order is deliberate: S3-only releases first (they expire), then the mirror.
  Idempotent - a snapshot directory with a _manifest.json is skipped.
  Handles per-release schema drift (bbox.minx/maxx + categories.main in early
  releases vs bbox.xmin/xmax + categories.primary later) by detection, not
  assumption.

INGEST METHODS AS BUILT
  scripts/ingest_fsq.py             - PyIceberg, Egypt-wide single pull,
                                      snapshot-tagged by Iceberg snapshot id.
  scripts/ingest_static_sources.py  - registers GHSL BUILT-S / GHS-LAND /
                                      WSF / Kontur into the raw layer with
                                      provenance manifests (no re-download).
  scripts/ingest_open_buildings.py  - 2023 only, presence band, parallel.
      NOTE: reads 2km x 2km BLOCKS, not whole tiles. A full Open Buildings
      tile is 25000x25000 px at 0.5m = 625M px ~= 2.5 GB for one band; at any
      useful worker count whole-tile reads OOM the machine. Blocks also match
      the 4.6s/4km^2 figure the cost estimate was derived from.

CITYWIDE INGEST — COMPLETED 2026-08-20

  Overture current    235,066 rows          snapshot 2026-08-19.0
  Overture archive  4,706,730 rows          23 snapshots, 2024-02-15 .. 2026-08-19
  Foursquare          150,023 rows          Egypt-wide, iceberg snapshot 6981762386080966939
  Open Buildings 2023  2,956,555,319 presence px -> 13,195 res-8 / 67,226 res-9 cells, 0 errors
  GHSL BUILT-S / GHS-LAND / WSF / Kontur   registered with provenance manifests

  In-coverage places: 265,445 (Overture 180,509 + FSQ 84,936). ~25% of raw rows
  fall outside the four governorates and are excluded at analysis time, not
  deleted from raw.

QA GATE, CITYWIDE, PER GOVERNORATE (output/qa_citywide_report.csv)
ADVISORY ONLY - no record merged or removed.

  governorate    rows     C1 collapse    C2 dup pairs (% rows)   C3 non-storefront
  Cairo        144,638   10,316 (7.1%)   14,241 (19.7%)          11,390 (7.9%)
  Giza          60,746    3,261 (5.4%)    3,868 (12.7%)           4,367 (7.2%)
  Alexandria    44,120    2,704 (6.1%)    3,431 (15.6%)           2,329 (5.3%)
  Qalyubiya     15,941    1,247 (7.8%)      651 ( 8.2%)             598 (3.8%)

EARLY (TENTATIVE) READ ON THE ALEXANDRIA GENERALISATION QUESTION
Alexandria falls inside the Cairo-area range on all three checks; no
governorate is an outlier. That points toward these defects being STRUCTURAL
to free geodata in Egypt rather than specific to Cairo - which would
strengthen the Part I conclusions rather than limit them.
DO NOT treat this as the answer to Step 4. Two limits:
  - These are volume/density-driven QA rates, NOT the per-source contribution
    share and confidence distribution that Step 4 actually asks for. Coverage
    bias by income is a different measurement from defect rate.
  - The duplicate matcher's precision (1.0) is IN-SAMPLE on a 38-pair labelled
    set built from Cairo cases. The ~15% duplicate figure is a review queue,
    not a count of confirmed duplicates.

MOST ACTIONABLE SINGLE NUMBER: 19.7% of Cairo rows sit in at least one
flagged duplicate pair. If even half survive review, competitor counts
citywide are materially inflated - which directly attacks the core product
metric. This should be triaged before any scoring feature is built on
competitor density.

PERFORMANCE NOTES FROM THE RUN (so they are not rediscovered)
  - name_matching's pure string transforms are now lru_cached; without that,
    the citywide duplicate pass recomputed variants/normalisation/skeletons
    for both sides of every candidate pair.
  - qa.check_intra_source_duplicates applies a 2-gram skeleton prefilter
    before the expensive matcher. 2-grams, not 3-grams: "Hara 9" -> "hr9" and
    "حارة 9" -> "hrh9" share no 3-gram but do share "hr", so 3-grams would
    silently drop real duplicates. Verified the prefilter changes no result on
    the three known street files.
  - qa_report_citywide writes each governorate's row as soon as it is computed;
    two earlier citywide runs were killed mid-pass and lost everything.

DUPLICATE TRIAGE (2026-08-20) — CORRECTION TO THE 19.7% FIGURE

CORRECTION FIRST: the earlier "19.7% of Cairo rows in a duplicate pair" came
from qa.check_intra_source_duplicates, which SKIPS any pair whose two records
come from different sources. That figure was INTRA-SOURCE ONLY and no
cross-source number existed. scripts/dup_pairs_citywide.py now computes both.
All four intra-source counts reproduce the earlier QA report exactly, which
validates the new pipeline against the old.

  governorate   intra-source   cross-source   total    % cross
  Cairo             14,241         16,088     30,329     53%
  Giza               3,868          6,666     10,534     63%
  Alexandria         3,431          3,627      7,058     51%
  Qalyubiya            651            557      1,208     46%
  TOTAL             22,188         26,938     49,129     55%

WHY THE SPLIT MATTERS - the two halves mean different things:
  cross_source (Overture vs FSQ, 26,938) - the expected case; this is exactly
      what entity resolution is meant to merge.
  intra_source (one provider listing a place twice, 22,188) - the worrying
      case. These inflate competitor counts even after a PERFECT cross-source
      merge, because no cross-provider join can collapse them.

SCORE DISTRIBUTION - STRONGLY BIMODAL, WITH A NATURAL CUTOFF
  0.72-0.75   3,373    0.85-0.90   3,340
  0.75-0.80   8,001    0.90-0.95   1,708
  0.80-0.85  10,026    0.95-0.99     339   <- near-empty valley (0.7%)
                        0.99-1.00  22,342   <- 45.5% of all pairs, exact 1.00
The valley at 0.95-0.99 is a natural threshold candidate. The exact-1.00 spike
is 80% cross-source, consistent with genuinely identical names across
providers. Distance: median 40m, p25 8m, p90 127m.

OUT-OF-SAMPLE PRECISION TEST (in progress, awaiting user verdicts)
output/dup-triage-sample.csv - 100 pairs, drawn RANDOMLY and stratified across
all four governorates (~25 each), both pair types (~50/50), and all four
similarity bands (~12-13 each), interleaved so hard cases are not clustered at
the end of the file. Reviewer marks SAME / DIFFERENT / UNSURE.
Rationale: the existing 38-pair labelled set is Cairo study-district data that
the thresholds were tuned ON - in-sample twice over, so any precision from it
is optimistic. Until this returns, the 49,129 figure is a REVIEW QUEUE, not a
count of confirmed duplicates, and NOTHING is merged on the matcher's say-so.

DUPLICATE MATCHER — OUT-OF-SAMPLE RESULTS AND PRODUCTION DECISION (2026-08-21)

100 randomly-sampled flagged pairs, verdicted by the user (100 verdicts,
ids 1-100, no duplicates, none missing, zero UNSURE).

  OVERALL PRECISION 25/100 = 25%   95% CI [17.5%, 34.3%]

*** THE IN-SAMPLE SUITE SAID 100%. THE TRUTH WAS 25%. ***
The 38-pair LABELLED_PAIRS suite in scripts/name_matching.py was built from
Cairo study-district cases AND the thresholds were tuned against it - in-sample
twice over. It reported precision 1.0 / recall 1.0. Out-of-sample precision is
25%. ANY future rebuild of this matcher MUST be validated on a fresh random
sample before it is used for anything. The labelled suite is a regression
guard against re-breaking known cases; it is NOT evidence of accuracy.

  by band:      0.72-0.80 11.5% | 0.80-0.90 12.0% | 0.90-0.99 33.3% | 0.99-1.00 44.0%
  by pair type: cross_source 44.0% [31-58] | intra_source 6.0% [2-16]
  by mechanism: exact 69.2% [42-87] | containment 33.3% [12-65] | fuzzy/skeleton 16.7% [10-26]
  exact + <=50m + cross_source: 8/9 = 88.9% [56-98]  (n=9, hence the Path A retest)

CORRECTED CITYWIDE DUPLICATE RATE (range, not a point estimate):
  flagged 49,129 -> TRUE duplicate pairs 8,620 - 16,854 (point est 12,282)
  cross_source: 26,938 flagged -> 8,394-15,542 true
  intra_source: 22,191 flagged ->   457- 3,599 true
  Record inflation: 3.2% - 6.3% of 265,445 in-coverage records
  (vs 18.5% if every flag had been real).
  Uncertainty is dominated by n=100; ~400 verdicts would be needed to halve
  the interval.

CORRECTION TO AN EARLIER CLAIM: intra-source duplicates were called "the more
worrying problem". They are mostly NOT REAL - 47 of 50 sampled were false, and
fuzzy+intra_source scored 1/45 = 2.2%. The 22,188 intra-source flags are
overwhelmingly the matcher inventing duplicates, not providers double-listing.

PRODUCTION DECISION — FUZZY AND CONTAINMENT MATCHING ARE DISABLED
Fuzzy/skeleton (16.7%) and containment (33.3%) matching are DISABLED for
production use pending a rebuild. Do NOT feed them into any count, any filter,
or any human review queue: at those precisions a reviewer spends most of their
time rejecting noise, and any count built on them is wrong by 3-6x.
Leaving fuzzy duplicates unmerged is cheap - the corrected inflation is only
3.2-6.3%.
Only Path A (exact normalised name + <=50m + cross_source) remains a candidate
for automated merging, and ONLY if output/pathA-sample.csv confirms the rate
on n=100. Nothing is merged until then.

CAMPUS-INTERIOR RECORDS — ADDED TO THE NON-STOREFRONT FILTER
2,986 records citywide (0.89%): Student Center 685, College Classroom 633,
Academic Building 422, College Lab 293, campus_building 155, etc.
FSQ 2,831 / Overture 155. Cairo 1,350, Giza 568, Alexandria 399, Qalyubiya 69.
CATEGORY-BASED ONLY. A name-regex pass was tried first and over-matched badly
(swept in medical labs, dental labs, "Block cafe") - it was discarded, and the
filter deliberately contains no name patterns.
Non-storefront total is now 23,924 records (7.16%).

DENSITY-DISTORTION WARNING (new check, qa.check_density_distortion)
208 res-9 cells hold >=20 non-storefront records, 6,513 records among them;
the worst holds 130. Filtering the records fixes the competitor COUNT, but a
cell that contained 130 institutional records was never a normal cell - its
remaining density and catchment comparability are suspect. The CELL is flagged,
not just the rows. -> output/density_distortion_cells.csv

STEP 4 — ALEXANDRIA GENERALISATION TEST (2026-08-21)
scripts/step4_alexandria_generalisation.py, Overture release 2026-07-22.0
(the PINNED analysis release, so a release difference cannot be confused with
a city difference).

Districts: Smouha (high, option-A corridor midpoint), Sidi Gaber (middle),
Karmouz (low). 1.5km boxes, same treatment as the Cairo three.

  district              overture  fsq  fsq/ov  top source   meta%  OSM%  conf_med  <0.5%  2011-13 FSQ share
  Smouha (high)              612  500   0.82   meta          94.6   0.0     0.643   24.0   51.2%
  Sidi Gaber (middle)      1,449  640   0.44   meta          97.4   0.0     0.595   31.6   43.4%
  Karmouz (low)               90   23   0.26   meta          98.9   0.0     0.597   33.3   56.5%

  CAIRO BASELINE (Part I):
  Sheikh Zayed (high)        491  490   1.00   meta          77.6   0.0     0.770   15.9   -
  Maadi (mid)                991 1025   1.03   meta          86.1   0.0     0.676   23.7   -
  Imbaba (low)               316   84   0.27   meta          96.5   0.0     0.562   36.4   -

VERDICT: THE FINDINGS ARE STRUCTURAL, NOT CAIRO-SPECIFIC. Three of the four
Part I claims reproduce in Alexandria; one is REFUTED and must be restated.

REPRODUCES 1 — zero OSM contribution. 0.0% in all three Alexandria districts,
exactly as in all three Cairo districts. Six districts, two cities, zero OSM.
This is now a firm property of Overture Places in Egypt, not a local quirk.

REPRODUCES 2 — single-source dependence, and it is WORSE in Alexandria.
Meta share by income: Smouha 94.6% -> Sidi Gaber 97.4% -> Karmouz 98.9%. The
poorest district is the most single-source, same direction as Cairo
(77.6 -> 86.1 -> 96.5). But Alexandria's BEST district (94.6%) is more
single-source than Cairo's WORST (96.5% is close, but Cairo's high-income
Sheikh Zayed was only 77.6%). Alexandria has essentially no supplementary
contributor anywhere: Foursquare-as-contributor is 2.8%/1.4%/0.0%.

REPRODUCES 3 — FSQ coverage collapses in the poor district. FSQ/Overture
ratio 0.82 -> 0.44 -> 0.26, monotonic with income, and Karmouz's 0.26 is
almost exactly Imbaba's 0.27. Karmouz has 90 Overture places and 23 FSQ places
in 2.25 km^2 - that is not a data set, it is a rounding error, in a dense
inner-city Alexandria district.

REPRODUCES 4 — FSQ date_created still clusters 2011-2013 (51.2% / 43.4% /
56.5% of each district's records created in just those three years). This is
the Egypt-wide Foursquare check-in adoption artifact, not business formation.
It is now confirmed in a second city, so the earlier decision to treat FSQ
date_created as unusable for temporal analysis holds nationally.

REFUTED — the confidence gradient does NOT reproduce cleanly.
Cairo's confidence median fell monotonically with income (0.770 / 0.676 /
0.562). Alexandria's does not: 0.643 / 0.595 / 0.597 - Sidi Gaber (middle) is
essentially tied with Karmouz (low), and the whole range is compressed
(0.643-0.595 = 0.048 spread, vs Cairo's 0.208). The "% below 0.5" ordering is
directionally right (24.0 / 31.6 / 33.3) but again compressed.
CONSEQUENCE: confidence score is NOT a reliable proxy for coverage quality
across cities. Do not use it as a cross-city quality signal or to rank
districts by data trustworthiness - it worked in Cairo by coincidence of that
city's contributor mix. Source-share and FSQ ratio are the signals that
travel.

SEPARATE OBSERVATION — the density ordering does not follow income.
Sidi Gaber (middle) has 1,449 Overture places, more than double Smouha (612)
and 16x Karmouz (90). Sidi Gaber is a major transport interchange, so this is
plausibly real commercial density rather than a data artifact - but it means
raw POI count cannot be read as an affluence proxy either. Income and POI
density are different axes; only the SOURCE MIX tracks income reliably.

MERGE DECISION — FINAL (2026-08-21): MERGE NOTHING AUTOMATICALLY

The Path A retest (exact name + <=50m + cross-source, n=100) was NOT completed.
Reason, and it is a sound one: the reviewer would have been judging those pairs
largely BY DISTANCE, and distance is part of the rule being tested - the
validation would have been circular and would have produced a falsely
reassuring number. The remaining payoff (3.2-6.3% inflation) does not justify
that risk.

DECISION: no automated merging, at any tier, including Path A. Duplicate
inflation ships as a DISCLOSED KNOWN LIMITATION.
  Measured record inflation: 3.2% - 6.3% (95% CI, from 25/100 out-of-sample
  precision applied to 49,129 flagged pairs over 265,445 in-coverage records).
  State that range in the product. Do not state a point estimate, and do not
  state the raw 18.5% flag rate - it is wrong by 3-6x.

Path A remains the ONLY tier with a plausible case for future automation
(69.2% precision as a mechanism, 88.9% on n=9 when tightened). Any future
attempt must be validated by a reviewer who can judge the pairs on identity
evidence INDEPENDENT of distance - otherwise the test is circular again.

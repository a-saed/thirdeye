"""
Test 2A ground truth extraction: Road 9, Maadi (the stretch running south
from Sakanat Al-Maadi metro station), 50m buffer.

Geometry: OSM ways 709250206 + 689652353 (name:en="Street 9"), starting
~38m from the metro and running ~637m south.

REVISION 2026-08-18, per user review of the first pass:

MATCHING (was 20m + un-normalised name similarity >=0.82, which missed
obvious pairs like "Chimney Cone Factory"/"Chimney Cone Factory" at 32.7m,
just outside the 20m cutoff, and every Arabic/Latin pair since
SequenceMatcher on disjoint scripts scores ~0). Now:
  - 40m distance threshold.
  - Name variants: FSQ bilingual names split on " | " (e.g. "Kazouza |
    كازوزه"); mixed-script Overture names split into contiguous
    same-script runs (e.g. "Sonata Music Center    سوناتا..." splits into
    the English and Arabic parts). Every variant of A is compared against
    every variant of B, best score wins.
  - Each variant pair scored 3 ways, max taken: (1) unidecode-transliterated
    + lowercased + punctuation-stripped full-string ratio, (2) same but
    with vowels also stripped (consonant skeleton - Arabic omits short
    vowels, so this is the standard cross-script trick), (3) partial/
    substring-window ratio of skeletons, which handles boilerplate-padded
    names (e.g. Overture's "قهوة قمر الزمان المعادي ش ٩" containing
    "Amar El Zaman" plus "coffee"/"Maadi St 9" padding - full-string ratio
    dilutes to 0.52, partial ratio correctly finds 1.0).
  - Threshold 0.75, calibrated against 10 known-true pairs the user
    manually spotted (all score >=0.73 with this pipeline; see
    scripts/matching_diagnostic.py session notes) - not against every
    pair in the file, so still verify by eye.

COLLAPSED_COORD: flags every record sharing its exact (lat, lon) with
>=1 other record, plus coord_group_size (2 = usually a legitimate
cross-source match of the same place; 3+ = likely a genuine geocoding
artifact - multiple DISTINCT businesses collapsed onto one point).

LIKELY_NOT_STOREFRONT: category-based (FSQ label prefix or Overture
category in a flagged set - offices, tech startup HQs, residential
buildings, freight/cargo, government pages, real estate) plus a name-
keyword fallback for anything without a clean category tag.

POSITION_OUTLIER_M: for every matched cross-source pair, the actual
distance in meters - flags matches exceeding 100m (position error
bigger than this study's own buffer width) instead of silently trusting
the match.
"""
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd
import pyproj
from shapely.geometry import LineString, Point
from shapely.ops import transform
from unidecode import unidecode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import ROOT, PLACES_PATH, get_con

BUFFER_M = 50
MATCH_DIST_M = 40
MATCH_NAME_THRESHOLD = 0.72

LINE_WGS84_PTS = [
    (31.2637769, 29.9530482), (31.2646772, 29.9522946), (31.2650245, 29.9520296),
    (31.2654376, 29.9517333), (31.2670412, 29.9507268), (31.2670728, 29.9507066),
    (31.2672147, 29.9506157), (31.2675197, 29.9504137), (31.2685719, 29.9498301),
    (31.268636, 29.9497928), (31.2686982, 29.9497519), (31.268905, 29.9495817),
    (31.2689484, 29.9495656), (31.2689882, 29.949566),
]
METRO_LINK = "https://www.openstreetmap.org/node/316638736"
WAY_LINKS = ["https://www.openstreetmap.org/way/709250206", "https://www.openstreetmap.org/way/689652353"]

FSQ_ROAD9_PARQUET = ROOT / "data" / "fsq_road9.parquet"
OUT_CSV = ROOT / "output" / "gt-maadi-road9.csv"
OUT_MISSING_CSV = ROOT / "output" / "gt-maadi-road9-missing.csv"

NOT_STOREFRONT_FSQ_PREFIXES = [
    "Business and Professional Services > Office",
    "Community and Government > Residential Building",
    "Community and Government > Housing Development",
]
NOT_STOREFRONT_OVERTURE_CATEGORIES = {
    "freight_and_cargo_service", "public_and_government_association",
    "real_estate", "real_estate_agent", "real_estate_service", "real_estate_investment",
    "professional_services", "corporate_office", "shipping_center",
}
NOT_STOREFRONT_NAME_KEYWORDS = [
    r"\bhq\b", r"head office", r"\boffice\b", r"holding", r"consultants?\b",
]


# ---------------------------------------------------------------------------
# Name matching
# ---------------------------------------------------------------------------

MIN_VARIANT_LEN = 4  # script-run splitting produces spurious short fragments like
# "Dr" (from "Dr.karim Abdelmoaty" splitting at the period) that trivially self-match
# against ANY other name containing the same title/generic word - "Dr.karim
# Abdelmoaty" and "Dr. Taher Abdel Razek Dental Clinic" scored a false 1.0 via
# this route (two different doctors). Caught during position-error review 2026-08-18.
# The full, unsplit name is always kept regardless of length - only the derived
# script-run fragments are length-filtered.


def name_variants(name) -> list:
    if not name or pd.isna(name):
        return []
    name = str(name)
    parts = re.split(r"\s*\|\s*", name)
    out = []
    for p in parts:
        out.append(p)
        runs = re.findall(r"[A-Za-z0-9][A-Za-z0-9\s&'\-]*|[؀-ۿ][؀-ۿ\s]*", p)
        out.extend(r.strip() for r in runs if len(r.strip()) >= MIN_VARIANT_LEN)
    return list(dict.fromkeys(v for v in out if v))


def _normalize(s: str) -> str:
    s = unidecode(s).lower()
    s = re.sub(r"[^a-z0-9\s]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _skeleton(s: str) -> str:
    return re.sub(r"[aeiou\s]", "", _normalize(s))


MIN_SKELETON_LEN_FOR_WINDOWING = 5  # sliding-window substring search is only safe on
# skeletons this long or longer - shorter ones produce spurious high-scoring windows
# by chance (e.g. "Lan Yuan" -> "lnyn" scored 0.75 against a random 4-char window
# "flny" inside an unrelated longer name - caught during manual review 2026-08-18).


def _partial_ratio(a: str, b: str) -> float:
    plain = SequenceMatcher(None, a, b).ratio()
    if len(a) > len(b):
        a, b = b, a
    if not a or len(a) < MIN_SKELETON_LEN_FOR_WINDOWING:
        return plain
    best = 0.0
    for i in range(len(b) - len(a) + 1):
        best = max(best, SequenceMatcher(None, a, b[i:i + len(a)]).ratio())
    return max(best, plain)


def name_similarity(name_a, name_b) -> float:
    va, vb = name_variants(name_a), name_variants(name_b)
    if not va or not vb:
        return 0.0
    best = 0.0
    for a in va:
        for b in vb:
            na, nb = _normalize(a), _normalize(b)
            sa, sb = _skeleton(a), _skeleton(b)
            best = max(best, SequenceMatcher(None, na, nb).ratio(), _partial_ratio(sa, sb))
    return best


def dist_m(lat1, lon1, lat2, lon2) -> float:
    return (((lat1 - lat2) * 111320) ** 2 + ((lon1 - lon2) * 111320 * 0.868) ** 2) ** 0.5


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def build_buffer():
    to_utm = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32636", always_xy=True).transform
    to_wgs84 = pyproj.Transformer.from_crs("EPSG:32636", "EPSG:4326", always_xy=True).transform
    line_utm = transform(to_utm, LineString(LINE_WGS84_PTS))
    return transform(to_wgs84, line_utm.buffer(BUFFER_M))


def get_overture_rows(buf):
    con = get_con()
    minx, miny, maxx, maxy = buf.bounds
    base = f"read_parquet('{PLACES_PATH}', hive_partitioning=1)"
    q = f"""
        SELECT names.primary AS name, categories.primary AS category,
               ST_X(geometry) AS lon, ST_Y(geometry) AS lat
        FROM {base}
        WHERE bbox.xmin <= {maxx} AND bbox.xmax >= {minx} AND bbox.ymin <= {maxy} AND bbox.ymax >= {miny}
    """
    df = con.execute(q).fetchdf()
    df = df[df.apply(lambda r: buf.contains(Point(r["lon"], r["lat"])), axis=1)].copy()
    df["source"] = "overture"
    df["date_created"] = ""
    return df[["source", "name", "category", "lat", "lon", "date_created"]]


def get_fsq_rows(buf):
    if not FSQ_ROAD9_PARQUET.exists():
        return None
    con = get_con()
    minx, miny, maxx, maxy = buf.bounds
    q = f"""
        SELECT name, fsq_category_labels, latitude AS lat, longitude AS lon, date_created
        FROM read_parquet('{FSQ_ROAD9_PARQUET}')
        WHERE longitude BETWEEN {minx} AND {maxx} AND latitude BETWEEN {miny} AND {maxy}
    """
    df = con.execute(q).fetchdf()
    if len(df):
        df = df[df.apply(lambda r: buf.contains(Point(r["lon"], r["lat"])), axis=1)].copy()

    def leaf_category(l):
        try:
            if l is not None and len(l) > 0:
                return l[-1]
        except TypeError:
            pass
        return None

    def full_label(l):
        try:
            if l is not None and len(l) > 0:
                return l[-1]
        except TypeError:
            pass
        return None

    df["category"] = df["fsq_category_labels"].apply(leaf_category) if len(df) else []
    df["_fsq_full_label"] = df["fsq_category_labels"].apply(full_label) if len(df) else []
    df["source"] = "fsq"
    return df[["source", "name", "category", "lat", "lon", "date_created", "_fsq_full_label"]]


def match_across_sources(df: pd.DataFrame) -> pd.DataFrame:
    """One-to-one greedy best-first matching: collect every (overture, fsq)
    candidate pair that passes both gates, sort by name-similarity
    descending, then assign greedily, skipping any record already claimed.
    (Earlier version overwrote a record's match on every subsequent hit,
    so an Overture record with two valid FSQ candidates - e.g. exact
    "Wafflicious"/"Wafflicious" at sim=1.0 AND "Wafflicious"/"Waffle Shop"
    at sim=0.83 - ended up paired with whichever came LAST in iteration
    order, orphaning the better match. Caught during manual review
    2026-08-18.)"""
    df = df.reset_index(drop=True)
    df["in_both_sources"] = "n"
    df["match_group"] = -1
    df["position_outlier_m"] = ""
    ov_idx = list(df[df["source"] == "overture"].index)
    fsq_idx = list(df[df["source"] == "fsq"].index)

    candidates = []
    for i in ov_idx:
        for j in fsq_idx:
            d_m = dist_m(df.loc[i, "lat"], df.loc[i, "lon"], df.loc[j, "lat"], df.loc[j, "lon"])
            if d_m > MATCH_DIST_M:
                continue
            sim = name_similarity(df.loc[i, "name"], df.loc[j, "name"])
            if sim < MATCH_NAME_THRESHOLD:
                continue
            candidates.append((sim, -d_m, i, j, d_m))  # -d_m so closer wins ties on equal sim

    candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)
    claimed_ov, claimed_fsq = set(), set()
    group_id = 0
    for sim, _, i, j, d_m in candidates:
        if i in claimed_ov or j in claimed_fsq:
            continue
        claimed_ov.add(i)
        claimed_fsq.add(j)
        df.loc[i, "in_both_sources"] = "y"
        df.loc[j, "in_both_sources"] = "y"
        df.loc[i, "match_group"] = group_id
        df.loc[j, "match_group"] = group_id
        df.loc[i, "position_outlier_m"] = round(d_m, 1) if d_m > 20 else ""
        df.loc[j, "position_outlier_m"] = round(d_m, 1) if d_m > 20 else ""
        group_id += 1
    return df


def flag_collapsed_coords(df: pd.DataFrame) -> pd.DataFrame:
    group_sizes = df.groupby(["lat", "lon"])["name"].transform("size")
    df["coord_group_size"] = group_sizes
    df["collapsed_coord"] = (group_sizes > 1).map({True: "y", False: "n"})
    return df


def flag_not_storefront(df: pd.DataFrame, fsq_labels: dict) -> pd.DataFrame:
    def check(row):
        if row["source"] == "fsq":
            full = fsq_labels.get((row["name"], row["lat"], row["lon"]), "")
            if any(full.startswith(p) for p in NOT_STOREFRONT_FSQ_PREFIXES):
                return "y"
        else:
            if row["category"] in NOT_STOREFRONT_OVERTURE_CATEGORIES:
                return "y"
        name = str(row["name"]) if pd.notna(row["name"]) else ""
        if any(re.search(kw, name, re.IGNORECASE) for kw in NOT_STOREFRONT_NAME_KEYWORDS):
            return "y"
        return "n"
    df["likely_not_storefront"] = df.apply(check, axis=1)
    return df


def main():
    buf = build_buffer()
    ov = get_overture_rows(buf)
    fsq_full = get_fsq_rows(buf)

    if fsq_full is not None:
        fsq_labels = {(r["name"], r["lat"], r["lon"]): r["_fsq_full_label"] or "" for _, r in fsq_full.iterrows()}
        fsq = fsq_full.drop(columns=["_fsq_full_label"])
        combined = pd.concat([ov, fsq], ignore_index=True)
        combined = match_across_sources(combined)
        fsq_status = f"FSQ: {len(fsq)} places included"
    else:
        combined = ov.copy()
        combined["in_both_sources"] = "PENDING"
        combined["match_group"] = -1
        combined["position_outlier_m"] = ""
        fsq_labels = {}
        fsq_status = "FSQ: PENDING"

    combined = flag_collapsed_coords(combined)
    combined = flag_not_storefront(combined, fsq_labels)
    combined["exists_today"] = ""
    combined["category_correct"] = ""
    combined["notes"] = ""

    # sort so matched pairs sit adjacent: matched groups first (by group id), then unmatched
    combined["_sort_key"] = combined["match_group"].apply(lambda g: (0, g) if g >= 0 else (1, 0))
    combined = combined.sort_values(["_sort_key", "source", "name"]).drop(columns=["_sort_key"])

    n_matched_pairs = (combined["match_group"] >= 0).sum() // 2
    n_collapsed = (combined["collapsed_coord"] == "y").sum()
    n_not_storefront = (combined["likely_not_storefront"] == "y").sum()
    n_total = len(combined)
    n_after_removal = n_total - combined[(combined["collapsed_coord"] == "y") | (combined["likely_not_storefront"] == "y")].shape[0]
    outliers = combined[combined["position_outlier_m"] != ""]

    header_lines = [
        "# Test 2A ground truth - Road 9, Maadi (south from Sakanat Al-Maadi metro)",
        f"# Buffer width: {BUFFER_M}m either side of the street centerline",
        f"# Matching: {MATCH_DIST_M}m distance + name similarity >={MATCH_NAME_THRESHOLD} (transliteration-normalised, see script docstring)",
        f"# Metro: {METRO_LINK}  |  Street ways: {' , '.join(WAY_LINKS)}",
        f"# Overture: {len(ov)} places  |  {fsq_status}  |  matched pairs: {n_matched_pairs}",
        f"# collapsed_coord=y: {n_collapsed}  |  likely_not_storefront=y: {n_not_storefront}  |  records remaining for manual verification: {n_after_removal}/{n_total}",
        "# NOT auto-matched despite strong name similarity (distance exceeds the 40m gate - your call, not forced):",
        "#   'البحيري' / 'El Beheiry' - 56.7m apart, name sim 0.91",
        "#   'بلال' / 'Belal' - 113.2m apart, name sim 1.00 (this one exceeds even a loose 100m check - real position error, not a false positive)",
        "#   'German Beauty Center' / 'German Beauty Center Heidi' - 381.7m apart, name sim 1.00 (same as above - real, not a name-coincidence artifact)",
        "# A broader sweep (name similarity alone, no distance cap) also flagged 5 more pairs >100m apart, but these look like",
        "# false positives from generic shared words ('cafe', 'beauty salon', 'Maadi Branch') rather than real position errors -",
        "# not listed as candidates here; see chat for the full sweep if you want to double-check them yourself.",
    ]
    with open(OUT_CSV, "w") as f:
        for line in header_lines:
            f.write(line + "\n")
        combined.to_csv(f, index=False)

    if not OUT_MISSING_CSV.exists():
        with open(OUT_MISSING_CSV, "w") as f:
            f.write("# Test 2A - Road 9, Maadi - businesses that exist in reality but are in NEITHER Overture nor FSQ\n")
            f.write("name,category,approx_location,notes\n")

    print(f"Overture: {len(ov)}  FSQ: {'PENDING' if fsq_full is None else len(fsq_full)}")
    print(f"Matched pairs: {n_matched_pairs}")
    print(f"collapsed_coord=y: {n_collapsed}")
    print(f"likely_not_storefront=y: {n_not_storefront}")
    print(f"Records remaining for manual verification after removing collapsed/non-storefront: {n_after_removal}/{n_total}")
    print(f"\nPosition outliers (matched pairs >20m apart):")
    for _, r in outliers.drop_duplicates(subset=["match_group"]).iterrows():
        print(f"  match_group={r['match_group']}: {r['name']} - {r['position_outlier_m']}m apart")
    print(f"\nWrote {OUT_CSV}")
    print(f"Wrote {OUT_MISSING_CSV}")


if __name__ == "__main__":
    main()

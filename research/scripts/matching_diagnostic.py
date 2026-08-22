"""
Diagnostic requested by user (2026-08-18): is the low Overture/FSQ overlap
(17-33%) a real data gap, or an artifact of weak name matching on
Arabic/Latin transliteration pairs (e.g. "Cilantro" vs "سيلانترو")?

Re-runs matching on the three already-extracted street files under THREE
rules, reported side by side:
  A. ORIGINAL: <=20m distance AND normalised-name similarity >= 0.82,
     NO transliteration (Arabic vs Latin names never match here at all -
     SequenceMatcher on disjoint character sets scores ~0).
  B. DISTANCE-ONLY: <=30m, name ignored entirely.
  C. NORMALISED+FUZZY: <=30m AND consonant-skeleton similarity >= 0.5.
     Consonant skeleton = unidecode() to romanise Arabic, lowercase,
     strip punctuation, strip vowels (a/e/i/o/u) - Arabic script omits
     short vowels, so comparing consonant skeletons is the standard trick
     for cross-script fuzzy matching. Even so this is noisy: a real same-
     place pair ("كافيه سيلانترو" / "Cilantro Cafe") only scores 0.44,
     BELOW this threshold - so 0.5 is already a compromise between
     catching real matches and avoiding false positives on a dense block
     where many distinct businesses sit within 30m of each other. Manual
     verification remains the authoritative check, not this script.
"""
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd
from unidecode import unidecode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import ROOT

DIST_THRESHOLD_A = 20
DIST_THRESHOLD_BC = 30
NAME_THRESHOLD_A = 0.82
SKELETON_THRESHOLD_C = 0.5


def normalize_name(name) -> str:
    if not name or pd.isna(name):
        return ""
    name = str(name).lower().strip()
    name = re.sub(r"[^\w\s]", "", name, flags=re.UNICODE)
    return re.sub(r"\s+", " ", name)


def skeleton(name) -> str:
    if not name or pd.isna(name):
        return ""
    s = unidecode(str(name)).lower()
    s = re.sub(r"[^a-z0-9\s]", "", s)
    s = re.sub(r"[aeiou]", "", s)
    return re.sub(r"\s+", "", s)


def dist_m(lat1, lon1, lat2, lon2) -> float:
    return (((lat1 - lat2) * 111320) ** 2 + ((lon1 - lon2) * 111320 * 0.868) ** 2) ** 0.5


def load_places(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, comment="#")
    return df[df["source"].isin(["overture", "fsq"])].reset_index(drop=True)


def match(df: pd.DataFrame, dist_thresh: float, name_fn, name_thresh: float, ignore_name: bool) -> set:
    ov = df[df["source"] == "overture"]
    fsq = df[df["source"] == "fsq"]
    matched_ov, matched_fsq = set(), set()
    for i in ov.index:
        for j in fsq.index:
            d = dist_m(df.loc[i, "lat"], df.loc[i, "lon"], df.loc[j, "lat"], df.loc[j, "lon"])
            if d > dist_thresh:
                continue
            if not ignore_name:
                sim = SequenceMatcher(None, name_fn(df.loc[i, "name"]), name_fn(df.loc[j, "name"])).ratio()
                if sim < name_thresh:
                    continue
            matched_ov.add(i)
            matched_fsq.add(j)
    return matched_ov, matched_fsq


def report(label: str, csv_path: Path):
    df = load_places(csv_path)
    n_ov = (df["source"] == "overture").sum()
    n_fsq = (df["source"] == "fsq").sum()

    a_ov, a_fsq = match(df, DIST_THRESHOLD_A, normalize_name, NAME_THRESHOLD_A, ignore_name=False)
    b_ov, b_fsq = match(df, DIST_THRESHOLD_BC, None, None, ignore_name=True)
    c_ov, c_fsq = match(df, DIST_THRESHOLD_BC, skeleton, SKELETON_THRESHOLD_C, ignore_name=False)

    print(f"\n=== {label} (Overture={n_ov}, FSQ={n_fsq}) ===")
    print(f"  A. original (20m + name>=0.82, no translit):     Overture matched {len(a_ov):3d}/{n_ov} ({100*len(a_ov)/n_ov:.1f}%)  FSQ matched {len(a_fsq):3d}/{n_fsq} ({100*len(a_fsq)/n_fsq:.1f}%)")
    print(f"  B. distance-only (30m, name ignored):             Overture matched {len(b_ov):3d}/{n_ov} ({100*len(b_ov)/n_ov:.1f}%)  FSQ matched {len(b_fsq):3d}/{n_fsq} ({100*len(b_fsq)/n_fsq:.1f}%)")
    print(f"  C. normalised+skeleton fuzzy (30m + skel>=0.5):   Overture matched {len(c_ov):3d}/{n_ov} ({100*len(c_ov)/n_ov:.1f}%)  FSQ matched {len(c_fsq):3d}/{n_fsq} ({100*len(c_fsq)/n_fsq:.1f}%)")

    return {
        "street": label, "overture_n": n_ov, "fsq_n": n_fsq,
        "A_overture_matched": len(a_ov), "A_fsq_matched": len(a_fsq),
        "B_overture_matched": len(b_ov), "B_fsq_matched": len(b_fsq),
        "C_overture_matched": len(c_ov), "C_fsq_matched": len(c_fsq),
    }


def main():
    rows = []
    rows.append(report("Road 9, Maadi", ROOT / "output" / "gt-maadi-road9.csv"))
    rows.append(report("El Shabab Street, Sheikh Zayed", ROOT / "output" / "gcheck-elshabab.csv"))
    rows.append(report("90th Street, New Cairo", ROOT / "output" / "gcheck-90thstreet.csv"))

    out = pd.DataFrame(rows)
    out_path = ROOT / "output" / "matching_diagnostic.csv"
    out.to_csv(out_path, index=False)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()

"""
Name matching for entity resolution and QA duplicate detection.

Extracted into its own module 2026-08-20 after the QA gate exposed a
blocking defect: the previous matcher (in test2a_road9_extract) scored
"AMT - Marketing Agency" vs "MetaGoo Marketing Agency" at 1.00, and
"Noha.Ali.Designs" vs "Nony Designs" at 1.00, because its substring/
partial-ratio path matches on whatever the two names SHARE - and what they
share is the generic part ("marketing agency", "designs"), not the
distinctive part. On 90th Street that produced 113 flagged pairs of which a
large share were distinct businesses. At city scale this is disqualifying:
as a QA alert it is noise, and if ever used to auto-merge it would delete
real businesses.

THE FIX: a name's similarity may not be driven solely by generic tokens.
Similarity is computed twice - once on the full normalised name, once on
the name with generic/locality tokens stripped - and a pair must clear BOTH
a full-name bar and a distinctive-content bar.

The partial/substring path is kept because it is genuinely needed: Overture
stores "قهوة قمر الزمان المعادي ش ٩" for the place FSQ calls "Amar El
Zaman" - the distinctive name is embedded in locality boilerplate. Removing
partial matching entirely would lose that class.

Every threshold here is tuned against the labelled set in
LABELLED_PAIRS below, drawn from cases verified by hand during the Cairo
study. Re-run this module directly to see precision/recall.
"""
import re
from difflib import SequenceMatcher
from functools import lru_cache

from unidecode import unidecode

MIN_VARIANT_LEN = 4
MIN_SKELETON_LEN_FOR_WINDOWING = 5

# Generic business / locality / category tokens. If two names share ONLY
# these, they are not the same business. Skeletonised forms are matched too,
# so Arabic transliterations of the same words are covered.
GENERIC_TOKENS = {
    # business-type words
    "design", "designs", "studio", "studios", "marketing", "agency", "agencies",
    "mall", "store", "stores", "shop", "shops", "boutique", "group", "company",
    "co", "corp", "holding", "holdings", "center", "centre", "services",
    "service", "solutions", "systems", "trading", "international", "intl",
    "restaurant", "cafe", "coffee", "bakery", "pharmacy", "clinic", "clinics",
    "hospital", "school", "academy", "gym", "fitness", "salon", "spa",
    "office", "offices", "branch", "the", "and", "for", "of", "el", "al",
    "new", "grand", "royal", "golden", "city", "plaza", "tower", "towers",
    "dr", "prof", "eng",
    # locality words that recur across distinct businesses
    "egypt", "cairo", "giza", "alexandria", "maadi", "zayed", "sheikh",
    "downtown", "katameya", "tagamoa", "zamalek", "heliopolis", "nasr",
    "smouha", "roushdy", "sporting", "karmouz", "bacos", "imbaba",
    "landscape", "decor", "rent", "car", "parking", "express",
    # arabic equivalents (normalised/transliterated forms)
    "mtm", "qhw", "qhwh", "qhwt", "shrk", "mhl", "mrkz", "msr", "lqhr",
    "lskndry", "lmdy", "lmdyy", "lm", "dy", "sh", "shr", "shrl",
    "dwn", "twn", "mwl",
    "lshykh", "zyd", "zayd",
}


@lru_cache(maxsize=200_000)
def _name_variants_cached(name: str) -> tuple:
    return tuple(_name_variants_impl(name))


def name_variants(name) -> list:
    if name is None or not str(name).strip():
        return []
    return list(_name_variants_cached(str(name)))


def _name_variants_impl(name) -> list:
    if name is None or (isinstance(name, float)) or not str(name).strip():
        return []
    name = str(name)
    parts = re.split(r"\s*\|\s*", name)
    out = []
    for p in parts:
        out.append(p)
        runs = re.findall(r"[A-Za-z0-9][A-Za-z0-9\s&'\-]*|[؀-ۿ][؀-ۿ\s]*", p)
        out.extend(r.strip() for r in runs if len(r.strip()) >= MIN_VARIANT_LEN)
    return list(dict.fromkeys(v for v in out if v))


@lru_cache(maxsize=200_000)
def normalize(s: str) -> str:
    s = unidecode(str(s)).lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


@lru_cache(maxsize=200_000)
def skeleton(s: str) -> str:
    return re.sub(r"[aeiou\s]", "", normalize(s))


@lru_cache(maxsize=200_000)
def strip_generic(s: str) -> str:
    """Remove generic/locality tokens, leaving distinctive content."""
    # NOTE: the length filter is >1, not >2. Dropping all 2-char tokens
    # cleanly fixes Arabic locality fragments ("المعادي" -> "lm dy") but
    # breaks genuinely short business names ("Hara 9" / "حارة 9"), whose
    # distinctive content IS two or three characters. The specific
    # transliteration fragments are stoplisted individually instead.
    toks = [t for t in normalize(s).split() if t not in GENERIC_TOKENS
            and skeleton(t) not in GENERIC_TOKENS and len(t) > 1]
    return " ".join(toks)


def _partial(a: str, b: str) -> float:
    plain = SequenceMatcher(None, a, b).ratio()
    if len(a) > len(b):
        a, b = b, a
    if not a or len(a) < MIN_SKELETON_LEN_FOR_WINDOWING:
        return plain
    best = 0.0
    for i in range(len(b) - len(a) + 1):
        best = max(best, SequenceMatcher(None, a, b[i:i + len(a)]).ratio())
    return max(best, plain)


def _pair_score(a: str, b: str) -> float:
    na, nb = normalize(a), normalize(b)
    sa, sb = skeleton(a), skeleton(b)
    return max(SequenceMatcher(None, na, nb).ratio(), _partial(sa, sb))


def name_similarity(name_a, name_b, full_thresh=0.72, distinct_thresh=0.62) -> float:
    """Returns a similarity in [0,1], but returns 0.0 when the match is
    driven only by generic tokens (i.e. the distinctive bar is not met).
    Callers compare against full_thresh."""
    va, vb = name_variants(name_a), name_variants(name_b)
    if not va or not vb:
        return 0.0

    full = max((_pair_score(a, b) for a in va for b in vb), default=0.0)
    if full < full_thresh:
        return full

    # Run the distinctive check PER VARIANT PAIR, not on the raw names.
    # A bilingual name ("starbucks ( ستاربكس )") is ~2x the length of its
    # monolingual counterpart, which trips the length-ratio guard below even
    # though the two are identical once the matching variant is isolated.
    best = 0.0
    for a in va:
        for b in vb:
            if _pair_score(a, b) < full_thresh:
                continue
            got = _distinctive_ok(a, b, full, distinct_thresh)
            best = max(best, got)
    return best


def _distinctive_ok(name_a: str, name_b: str, full: float, distinct_thresh: float) -> float:
    da, db = strip_generic(name_a), strip_generic(name_b)

    # ASYMMETRIC-GENERIC GUARD. If one name is entirely generic once stripped
    # ("Downtown Mall" -> "") and the other still carries distinctive content
    # ("Buffalo Burger - Downtown Mall" -> "buffalo burger"), they are a venue
    # and a tenant of that venue, not the same business. Reject.
    if bool(da) != bool(db):
        return 0.0
    # Both entirely generic. Two names that reduce to nothing but venue and
    # locality words ("Downtown Mall" vs "Cairo-New Cairo/Downtown Mall";
    # both halves of a Sheikh Zayed pair) carry no evidence of being the same
    # business - they only prove both sit in the same place. Reject.
    if not da and not db:
        return 0.0

    ska, skb = skeleton(da), skeleton(db)
    short, long_ = sorted((ska, skb), key=len)

    # SHORT-DISTINCTIVE GUARD. Two- or three-character distinctive skeletons
    # ("amt" vs "metagoo" -> "mt" vs "mtg") score high by coincidence.
    # Demand a near-exact match when there is barely any content to compare.
    if len(short) < 4:
        return full if SequenceMatcher(None, ska, skb).ratio() >= 0.9 else 0.0

    # LENGTH-RATIO GUARD. A short distinctive string appearing inside a much
    # longer one ("ktchn" inside "kdcktchnsdtcrtv") is a substring coincidence,
    # not evidence of the same business - unless the whole names agree.
    if long_ and len(short) / len(long_) < 0.5:
        return full if SequenceMatcher(None, da, db).ratio() >= 0.9 else 0.0

    distinct = max(SequenceMatcher(None, da, db).ratio(), _partial(ska, skb))
    return full if distinct >= distinct_thresh else 0.0


# --------------------------------------------------------------- labelled set
# (name_a, name_b, is_same_business) - all verified by hand during the study.
LABELLED_PAIRS = [
    # --- TRUE duplicates / same place across or within sources
    ("Hara 9", "حارة 9", True),
    ("ChemTech", "Chemtech", True),
    ("starbucks ( ستاربكس )", "ستاربكس", True),
    ("The Body Shop", "The Body Shop", True),
    ("Wafflicious", "Wafflicious", True),
    ("قهوة قمر الزمان المعادي ش ٩", "Amar El Zaman", True),
    ("كازوزه", "Kazouza | كازوزه", True),
    ("Sonata Music Center    سوناتا لتعليم العزف و الغناء", "Sonata Music Center", True),
    ("Chimney Cone Factory", "Chimney Cone Factory", True),
    ("اولاد سلطان - Sultan Sons", "أسواق أولاد سلطان", True),
    ("كريب ووافل نيو", "New Crepe & Waffle | نيو كريب و وافل", True),
    ("WienerWald Egypt", "Wienerwald | وينروالد", True),
    ("Kiro cafe", "Kiro’s Cafe", True),
    ("بلال", "Belal", True),
    ("البحيري", "El Beheiry", True),
    ("German Beauty Center", "German Beauty Center Heidi", True),
    ("Desoky and Soda", "Desoky & Soda", True),
    ("Il Pennello Ceramic Cafe", "IL Pennello Ceramic Café", True),
    ("Maadi used books", "Maadi Used Books", True),
    # --- FALSE: distinct businesses sharing generic/locality words
    ("Noha.Ali.Designs", "Nony Designs", False),
    ("Noha.Ali.Designs", "Ocho Design Studio", False),
    ("Cava home designs", "Noha.Ali.Designs", False),
    ("Evento Designs", "Noha.Ali.Designs", False),
    ("AMT - Marketing Agency", "MetaGoo Marketing Agency", False),
    ("Downtown Mall", "Buffalo Burger - Downtown Mall", False),
    ("Downtown Katameya", "Etisalat Downtown Katameya", False),
    ("Downtown Mall", "Sixt Rent a Car | Cairo-New Cairo/Downtown Mall", False),
    ("Downtown Parking", "dowon tawon", False),
    ("Syriana palace الشيخ زايد", "Sheikh Zayed Downtown Mall | داون تاون مول الشيخ زايد", False),
    ("Dr.karim Abdelmoaty", "Dr. Taher Abdel Razek Dental Clinic", False),
    ("كريب ووافل نيو", "Lan Yuan", False),
    ("Chocolate Spot - Maadi Branch", "English Capsules Maadi Branch", False),
    ("Mansour’s Space", "Spaces", False),
    ("Tm cafe", "Kiro’s Cafe", False),
    ("Mega AI", "Matigoo", False),
    ("KDC Kitchensdotcreative", "Kitchino", False),
    ("Grasses Landscape", "Green decor_landscape", False),
    ("Medline clinics", "medline clinics zayed", True),
]


def evaluate(thresh=0.72):
    tp = fp = tn = fn = 0
    errors = []
    for a, b, want in LABELLED_PAIRS:
        got = name_similarity(a, b) >= thresh
        if got and want:
            tp += 1
        elif got and not want:
            fp += 1; errors.append(("FALSE POSITIVE", a, b))
        elif not got and want:
            fn += 1; errors.append(("MISSED", a, b))
        else:
            tn += 1
    prec = tp / (tp + fp) if tp + fp else 0
    rec = tp / (tp + fn) if tp + fn else 0
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "precision": round(prec, 3), "recall": round(rec, 3)}, errors


if __name__ == "__main__":
    m, errs = evaluate()
    print(f"labelled pairs: {len(LABELLED_PAIRS)}")
    print(f"TP {m['tp']}  FP {m['fp']}  TN {m['tn']}  FN {m['fn']}")
    print(f"precision {m['precision']}   recall {m['recall']}")
    if errs:
        print("\nerrors:")
        for kind, a, b in errs:
            print(f"  {kind:15s} {a!r} <-> {b!r}")

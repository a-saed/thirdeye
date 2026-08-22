"""
Explicit mapping from Overture `categories.primary` values to the business
types Third Eye cares about, built from the real category vocabulary
observed across the three study districts (358 distinct values - see
output/category_vocabulary.txt).

Each set below is a deliberate, reviewable inclusion list, not a substring
match - substring matching on category strings is fragile (e.g. matching
"restaurant" would silently pull in "restaurant_equipment_and_supply" and
"restaurant_wholesale", which are not restaurants). Ambiguous/adjacent
categories that were considered and EXCLUDED are listed per group with the
reason, so the exclusion is a decision, not an oversight.
"""

CAFE = {
    "cafe",
    "coffee_shop",
    "coffee_roastery",
}
# Excluded: internet_cafe (primarily a computer/internet-access business,
# not a coffee venue), coffee_and_tea_supplies (a retail supply store, not
# a place to sit and drink coffee).

RESTAURANT = {
    "restaurant",
    "american_restaurant",
    "armenian_restaurant",
    "asian_restaurant",
    "bar_and_grill_restaurant",
    "barbecue_restaurant",
    "brazilian_restaurant",
    "breakfast_and_brunch_restaurant",
    "buffet_restaurant",
    "burger_restaurant",
    "chicken_wings_restaurant",
    "chinese_restaurant",
    "comfort_food_restaurant",
    "diner",
    "doner_kebab",
    "egyptian_restaurant",
    "european_restaurant",
    "falafel_restaurant",
    "fast_food_restaurant",
    "french_restaurant",
    "indian_restaurant",
    "indo_chinese_restaurant",
    "italian_restaurant",
    "japanese_restaurant",
    "latin_american_restaurant",
    "lebanese_restaurant",
    "mediterranean_restaurant",
    "middle_eastern_restaurant",
    "pizza_restaurant",
    "sandwich_shop",
    "seafood_restaurant",
    "soup_restaurant",
    "southern_restaurant",
    "steakhouse",
    "sushi_restaurant",
    "syrian_restaurant",
    "thai_restaurant",
    "theme_restaurant",
    "turkish_restaurant",
    "vegetarian_restaurant",
}
# Excluded: bar, cocktail_bar, pub, lounge, dance_club (alcohol/nightlife
# venues, not primarily food service even though some serve food);
# food_stand (informal street food, a materially different business type
# from a seated/counter restaurant); eat_and_drink (too generic/ambiguous
# a parent bucket to trust); restaurant_equipment_and_supply,
# restaurant_wholesale (B2B suppliers, not restaurants themselves).

PHARMACY = {
    "pharmacy",
}
# No pharmacy-adjacent variant (e.g. a separate "drugstore" category)
# exists in the observed vocabulary, so naive and mapped counts for
# pharmacy are expected to be identical.

GYM = {
    "gym",
    "gymnastics_center",
    "pilates_studio",
    "yoga_studio",
    "martial_arts_club",
}
# Excluded: active_life (too generic/umbrella - not fitness-specific),
# swimming_pool (could be a public/residential amenity rather than a
# fitness business), sports_club_and_league (often an organization/league,
# not a physical gym facility).

GROCERY = {
    "grocery_store",
    "supermarket",
    "organic_grocery_store",
    "specialty_grocery_store",
}
# Excluded: convenience_store (materially smaller/different business
# model), farmers_market (informal/periodic, not a standing store),
# fruits_and_vegetables (a produce stand, not a full grocery store),
# health_food_store (a distinct specialty retail category).

GROUPS = {
    "cafe": CAFE,
    "restaurant": RESTAURANT,
    "pharmacy": PHARMACY,
    "gym": GYM,
    "grocery": GROCERY,
}


# ---------------------------------------------------------------------------
# Foursquare category mapping - SEPARATE from the Overture mapping above,
# not reused. FSQ's fsq_category_labels are genuinely hierarchical strings
# (e.g. "Dining and Drinking > Restaurant > Italian Restaurant"), unlike
# Overture's flat category strings - this makes PREFIX matching safe for the
# restaurant group (every subtype nests under one exact prefix, verified
# against the real 312-label vocabulary observed in our 3 districts - see
# output/fsq_category_vocabulary.txt), where flat substring matching was
# fragile for Overture. Built from that real vocabulary, not guessed.
# ---------------------------------------------------------------------------

FSQ_CAFE = {
    "Dining and Drinking > Cafe, Coffee, and Tea House",
    "Dining and Drinking > Cafe, Coffee, and Tea House > Café",
    "Dining and Drinking > Cafe, Coffee, and Tea House > Coffee Shop",
    "Retail > Food and Beverage Retail > Coffee Roaster",
}
# Excluded: Bubble Tea Shop (distinct product, not coffee), Gaming Cafe /
# Internet Cafe (not coffee venues - same reasoning as Overture's
# internet_cafe exclusion).

FSQ_RESTAURANT_PREFIX = "Dining and Drinking > Restaurant"
# Every restaurant subtype (American, Asian incl. Chinese/Japanese/Thai/etc,
# BBQ, Burger, Fast Food, Italian, Middle Eastern incl. Egyptian/Lebanese/
# Shawarma/Syrian, Pizzeria, Seafood, Steakhouse, Vegan, ...) nests under
# this exact prefix in FSQ's hierarchy - trusting FSQ's own taxonomy here
# rather than hand-picking each leaf, since the hierarchy delimiter makes
# prefix matching precise (unlike Overture's flat strings, where e.g.
# "restaurant" as a prefix would wrongly also match
# "restaurant_equipment_and_supply").

FSQ_PHARMACY = {
    "Retail > Pharmacy",
}

FSQ_GYM = {
    "Sports and Recreation > Gym and Studio",
    "Sports and Recreation > Gym and Studio > Gym",
    "Sports and Recreation > Gym and Studio > Pilates Studio",
    "Sports and Recreation > Gym and Studio > Yoga Studio",
    "Sports and Recreation > Gym and Studio > Cycle Studio",
    "Sports and Recreation > Gymnastics > Gymnastics Center",
}
# Excluded: Dance Studio (instruction/dance, not fitness-gym - same
# judgment as Overture excluding dance_school from GYM).

FSQ_GROCERY = {
    "Retail > Food and Beverage Retail > Grocery Store",
    "Retail > Food and Beverage Retail > Grocery Store > Organic Grocery",
    "Retail > Food and Beverage Retail > Supermarket",
}
# Excluded: Convenience Store, Farmers Market, Fruit and Vegetable Store,
# Health Food Store - same reasoning as the Overture GROCERY exclusions.


def fsq_group_match(labels, group: str) -> bool:
    """labels: the fsq_category_labels array (or None/NA) for one place."""
    try:
        if labels is None or len(labels) == 0:
            return False
    except TypeError:
        return False
    if group == "restaurant":
        return any(l == FSQ_RESTAURANT_PREFIX or l.startswith(FSQ_RESTAURANT_PREFIX + " > ") for l in labels)
    members = {"cafe": FSQ_CAFE, "pharmacy": FSQ_PHARMACY, "gym": FSQ_GYM, "grocery": FSQ_GROCERY}[group]
    return any(l in members for l in labels)


FSQ_GROUPS = ["cafe", "restaurant", "pharmacy", "gym", "grocery"]


def main():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from pipeline.config._common import ROOT, PLACES_PATH, get_con, load_districts, bbox_where

    con = get_con()
    districts = load_districts()
    base = f"read_parquet('{PLACES_PATH}', hive_partitioning=1)"

    print(f"{'district':14s} {'group':10s} {'naive':>7s} {'mapped':>7s} {'delta':>7s} {'error %':>8s}")
    rows = []
    for name, d in districts.items():
        where = bbox_where(d["bbox"])
        q = f"SELECT categories.primary AS cat, count(*) AS n FROM {base} WHERE {where} GROUP BY 1"
        counts = dict(con.execute(q).fetchall())

        for group, members in GROUPS.items():
            naive = counts.get(group, 0)
            mapped = sum(counts.get(m, 0) for m in members)
            delta = mapped - naive
            err_pct = round(100.0 * delta / naive, 1) if naive else (None if mapped == 0 else float("inf"))
            print(f"{name:14s} {group:10s} {naive:7d} {mapped:7d} {delta:7d} {str(err_pct):>8s}")
            rows.append({
                "district": name, "group": group, "naive": naive, "mapped": mapped,
                "delta": delta, "error_pct": err_pct,
                "members_present": sorted(m for m in members if counts.get(m, 0) > 0),
            })

    import pandas as pd
    out = pd.DataFrame(rows)
    out_path = ROOT / "output" / "test1b_category_mapping_comparison.csv"
    out.to_csv(out_path, index=False)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()

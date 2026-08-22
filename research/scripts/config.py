"""Shared config for the Third Eye data feasibility study.

Verified live on 2026-08-18 by listing s3://overturemaps-us-west-2/release/
directly (README's STAC catalog link was stale/404). Do not hardcode a
different release without re-checking.
"""

OVERTURE_RELEASE = "2026-07-22.0"
OVERTURE_PLACES_PATH = (
    f"s3://overturemaps-us-west-2/release/{OVERTURE_RELEASE}/theme=places/type=place/*"
)

OHSOME_BASE = "https://api.ohsome.org/v1"

# Filled in once the user supplies the study area.
DISTRICTS = {
    # "name": {"xmin": ..., "ymin": ..., "xmax": ..., "ymax": ...},
}

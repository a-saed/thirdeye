"""
Test-0 (prep step): geocode district center points via Nominatim and build
fixed 1.5km x 1.5km bboxes around each. Writes data/districts.json and
prints a confirmation table with OSM links.

Respects Nominatim usage policy: custom User-Agent, 1 request/sec.
"""
import json
import math
import sys
import time
from pathlib import Path

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Nominatim requires an identifying User-Agent. Points at the repository
# rather than a personal address, matching the live API.
USER_AGENT = "third-eye-feasibility-study/0.1 (research use; https://github.com/a-saed/thirdeye)"

HALF_SIDE_KM = 0.75  # 1.5km box => 0.75km half-width in each direction

QUERIES = [
    ("Sheikh Zayed", "Arkan Plaza Sheikh Zayed"),
    ("Maadi", "Maadi, Cairo, Egypt"),
    ("Imbaba", "Imbaba, Giza, Egypt"),
]


def geocode(query: str) -> dict:
    resp = requests.get(
        NOMINATIM_URL,
        params={"q": query, "format": "jsonv2", "limit": 1},
        headers={"User-Agent": USER_AGENT},
        timeout=15,
    )
    resp.raise_for_status()
    results = resp.json()
    if not results:
        raise RuntimeError(f"No geocoding result for: {query}")
    return results[0]


def bbox_around(lat: float, lon: float, half_km: float) -> dict:
    dlat = half_km / 111.32
    dlon = half_km / (111.32 * math.cos(math.radians(lat)))
    return {
        "xmin": round(lon - dlon, 6),
        "xmax": round(lon + dlon, 6),
        "ymin": round(lat - dlat, 6),
        "ymax": round(lat + dlat, 6),
    }


def osm_link(bbox: dict, lat: float, lon: float) -> str:
    return (
        f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}"
        f"#map=16/{lat}/{lon}"
    )


def bbox_link(bbox: dict) -> str:
    return (
        "https://www.openstreetmap.org/export#map=16"
        f"&bbox={bbox['xmin']}%2C{bbox['ymin']}%2C{bbox['xmax']}%2C{bbox['ymax']}"
    )


def main():
    districts = {}
    for i, (label, query) in enumerate(QUERIES):
        if i > 0:
            time.sleep(1.1)  # respect 1 req/sec
        result = geocode(query)
        lat = float(result["lat"])
        lon = float(result["lon"])
        bbox = bbox_around(lat, lon, HALF_SIDE_KM)
        districts[label] = {
            "query": query,
            "nominatim_display_name": result.get("display_name"),
            "center": {"lat": lat, "lon": lon},
            "bbox": bbox,
            "point_link": osm_link(bbox, lat, lon),
            "bbox_link": bbox_link(bbox),
        }

    out_path = Path(__file__).resolve().parent.parent / "data" / "districts.json"
    out_path.write_text(json.dumps(districts, indent=2))

    print(f"Wrote {out_path}\n")
    for label, d in districts.items():
        print(f"=== {label} ===")
        print(f"  query:        {d['query']}")
        print(f"  matched name: {d['nominatim_display_name']}")
        print(f"  center:       lat={d['center']['lat']:.6f}, lon={d['center']['lon']:.6f}")
        print(f"  bbox:         xmin={d['bbox']['xmin']}, ymin={d['bbox']['ymin']}, "
              f"xmax={d['bbox']['xmax']}, ymax={d['bbox']['ymax']}")
        print(f"  point on OSM: {d['point_link']}")
        print(f"  bbox on OSM:  {d['bbox_link']}")
        print()


if __name__ == "__main__":
    main()

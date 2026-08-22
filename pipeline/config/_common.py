"""Shared helpers for the Third Eye feasibility study scripts."""
import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]   # repo root (pipeline/config/_common.py)
OVERTURE_RELEASE = "2026-07-22.0"
PLACES_PATH = f"s3://overturemaps-us-west-2/release/{OVERTURE_RELEASE}/theme=places/type=place/*"


def get_con():
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;")
    con.execute("SET s3_region='us-west-2'; SET enable_progress_bar=false;")
    return con


def load_districts() -> dict:
    return json.loads((ROOT / "data" / "districts.json").read_text())


def bbox_where(bbox: dict) -> str:
    return (
        f"bbox.xmin <= {bbox['xmax']} AND bbox.xmax >= {bbox['xmin']} "
        f"AND bbox.ymin <= {bbox['ymax']} AND bbox.ymax >= {bbox['ymin']}"
    )


# ---------------------------------------------------------------------------
# SHARED THRESHOLDS
#
# config/thresholds.json is the single source for every tunable value in the
# product, read here, by the Go API and by the frontend build. Nothing may
# redeclare one of these: a constant copied into two languages is a rule with
# two places to get it wrong, and this project has already shipped that.
#
# Access is strict for the same reason the API refuses to start without them —
# a KeyError naming the missing setting is better than a default that silently
# disagrees with what the API used.
# ---------------------------------------------------------------------------
import json as _json

THRESHOLDS = _json.loads((ROOT / "config" / "thresholds.json").read_text())


def threshold(*path):
    """threshold('saturation', 'saturated_pct') -> 40.0, or raise."""
    node = THRESHOLDS
    for key in path:
        if key not in node:
            raise KeyError(
                f"config/thresholds.json is missing {'.'.join(path)} — "
                f"refusing to guess a value the API may not share"
            )
        node = node[key]
    return node

"""
Shared helper: stitch OSM way segments into one ordered path, then slide
a fixed-length window along it and find the highest-POI-density stretch.
Used for El Shabab Street (Sheikh Zayed) and 90th Street (New Cairo),
both too long to ground-truth in full - test.md's Test 2B calls for
picking the commercial "heart" of each street rather than a guessed
sub-stretch.
"""
import sys
from pathlib import Path

import numpy as np
import pyproj
from shapely.geometry import LineString, Point
from shapely.ops import transform

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import PLACES_PATH, get_con

to_utm = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32636", always_xy=True).transform
to_wgs84 = pyproj.Transformer.from_crs("EPSG:32636", "EPSG:4326", always_xy=True).transform


def stitch_ways(ways: list) -> list:
    """ways: list of lists of (lon, lat) tuples (one per OSM way, in their
    own internal order). Returns one ordered list of (lon, lat) by
    greedily chaining whichever remaining way's start/end is closest to
    the current path's current end."""
    remaining = [list(w) for w in ways]
    path = remaining.pop(0)
    while remaining:
        end = path[-1]
        best_i, best_reversed, best_d = None, False, float("inf")
        for i, w in enumerate(remaining):
            d_start = (w[0][0] - end[0]) ** 2 + (w[0][1] - end[1]) ** 2
            d_end = (w[-1][0] - end[0]) ** 2 + (w[-1][1] - end[1]) ** 2
            if d_start < best_d:
                best_d, best_i, best_reversed = d_start, i, False
            if d_end < best_d:
                best_d, best_i, best_reversed = d_end, i, True
        w = remaining.pop(best_i)
        if best_reversed:
            w = list(reversed(w))
        path.extend(w)
    return path


def find_best_window(path_lonlat: list, window_m: float, buffer_m: float, step_m: float, extra_bboxes_for_pushdown=None):
    """Returns (best_window_start_latlon, best_window_end_latlon,
    best_window_polygon_wgs84, overture_count, all_windows_df)."""
    line_utm = transform(to_utm, LineString(path_lonlat))
    total_len = line_utm.length

    con = get_con()
    base = f"read_parquet('{PLACES_PATH}', hive_partitioning=1)"
    line_bounds_wgs = transform(to_wgs84, line_utm.buffer(buffer_m)).bounds
    minx, miny, maxx, maxy = line_bounds_wgs
    q = f"""
        SELECT names.primary AS name, categories.primary AS category,
               ST_X(geometry) AS lon, ST_Y(geometry) AS lat
        FROM {base}
        WHERE bbox.xmin <= {maxx} AND bbox.xmax >= {minx} AND bbox.ymin <= {maxy} AND bbox.ymax >= {miny}
    """
    df = con.execute(q).fetchdf()
    pts_utm = [transform(to_utm, Point(r.lon, r.lat)) for r in df.itertuples()]

    positions = np.arange(0, max(total_len - window_m, 0) + 1e-9, step_m)
    best = None
    results = []
    for start_d in positions:
        end_d = min(start_d + window_m, total_len)
        sub = _substring(line_utm, start_d, end_d)
        buf = sub.buffer(buffer_m)
        count = sum(1 for p in pts_utm if buf.contains(p))
        results.append((start_d, end_d, count))
        if best is None or count > best[2]:
            best = (start_d, end_d, count)

    start_d, end_d, count = best
    best_sub = _substring(line_utm, start_d, end_d)
    best_buf_wgs = transform(to_wgs84, best_sub.buffer(buffer_m))
    start_pt_wgs = transform(to_wgs84, Point(best_sub.coords[0]))
    end_pt_wgs = transform(to_wgs84, Point(best_sub.coords[-1]))
    return {
        "start_latlon": (start_pt_wgs.y, start_pt_wgs.x),
        "end_latlon": (end_pt_wgs.y, end_pt_wgs.x),
        "polygon_wgs84": best_buf_wgs,
        "overture_count": count,
        "total_street_length_m": total_len,
        "all_windows": results,
    }


def _substring(line: LineString, start_d: float, end_d: float) -> LineString:
    from shapely.ops import substring
    return substring(line, start_d, end_d)

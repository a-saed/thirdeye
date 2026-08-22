"""
Worker for scripts/ingest_open_buildings.py — processes ONE TILE and spools
its result to disk.

Design note (four iterations on 2026-08-20; recorded so it is not
"simplified" back into an earlier broken form):

  v1  task = whole tile, read in one go.
      FAILED: a tile is 25000x25000 px at 0.5m = 625M px ~= 2.5 GB for one
      band. OOMs at any useful worker count.

  v2  task = one 2km x 2km block, GDAL caches disabled to bound memory.
      Memory fixed (~200 MB/worker) but ~7x SLOWER: 4,206 blocks scattered
      across workers meant the same tile was reopened constantly, and
      VSI_CACHE=False forced re-reads. Projected 121 min vs 18 min.

  v3  task = one tile, blocks iterated INSIDE the worker, bounded VSI cache.
      Correct shape. Added 10m super-pixel aggregation (below) after
      profiling showed the per-pixel h3 loop was the bottleneck.

  v4  (this) + SPOOL TO DISK + HTTP TIMEOUTS.
      The v3 run reached 150/152 tiles and then wedged for >2 hours on the
      last two, with network throughput measured at 3 KB/s - a hung HTTP
      connection that GDAL's retry settings do not cover (retries apply to
      failed requests, not to a connection that stays open and idle).
      Because v3 accumulated everything in the parent and wrote only at the
      end, killing it discarded 150 completed tiles.
      Now: each worker writes its own result file, so the job is RESUMABLE -
      a hang costs one tile, not the run - and GDAL_HTTP_TIMEOUT /
      CONNECTTIMEOUT make a wedged socket fail instead of hanging forever.

SUPER-PIXEL AGGREGATION: pixels are 0.5m, a res-9 cell is ~174m across, so
per-pixel h3 lookups are ~400x more work than the output resolution
justifies. The presence mask is summed into 10m super-pixels (20x20 blocks)
and ONE h3 lookup is done per non-empty super-pixel, weighted by its pixel
count. Pixel counts are preserved EXACTLY - only the lookup coordinate is
coarsened, from 0.5m to 10m, far below the 174m cell size.
"""
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import from_bounds

PRESENCE_THRESHOLD = 0.5
BLOCK_M = 2000
SUPER = 20          # 20 x 0.5m pixels = 10m super-pixel for the h3 lookup


def spool_path(spool_dir: str, url: str) -> Path:
    h = hashlib.sha1(url.encode()).hexdigest()[:16]
    return Path(spool_dir) / f"{h}.json"


def process_tile(args):
    """args: (url, zone, tile_extent, coverage_bbox_utm, res_list, spool_dir)
    Writes {res: {h3: count}} to a spool file and returns (path, n_px)."""
    url, zone, tile_ext, cov, res_list, spool_dir = args
    sp = spool_path(spool_dir, url)
    if sp.exists():                       # resume: already done
        try:
            d = json.loads(sp.read_text())
            return {"_done": str(sp)}, d.get("_n_px", 0)
        except Exception:
            pass                          # corrupt spool -> recompute

    import h3
    import pyproj

    to_wgs = pyproj.Transformer.from_crs(f"EPSG:{zone}", "EPSG:4326", always_xy=True)
    out = {r: {} for r in res_list}
    total_px = 0

    txmin, tymin, txmax, tymax = tile_ext
    cx0, cy0 = max(txmin, cov[0]), max(tymin, cov[1])
    cx1, cy1 = min(txmax, cov[2]), min(tymax, cov[3])
    if cx0 >= cx1 or cy0 >= cy1:
        sp.write_text(json.dumps({"_n_px": 0, **{str(r): {} for r in res_list}}))
        return {"_done": str(sp)}, 0

    try:
        with rasterio.Env(GDAL_CACHEMAX=96,
                          CPL_VSIL_CURL_CACHE_SIZE=33554432,
                          GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                          # A wedged-but-open socket is what killed the v3 run;
                          # retries do not help there, timeouts do.
                          GDAL_HTTP_TIMEOUT=120,
                          GDAL_HTTP_CONNECTTIMEOUT=30,
                          GDAL_HTTP_MAX_RETRY=3, GDAL_HTTP_RETRY_DELAY=2):
            with rasterio.open("/vsicurl/" + url) as src:
                bx0 = max(cx0, src.bounds.left); by0 = max(cy0, src.bounds.bottom)
                bx1 = min(cx1, src.bounds.right); by1 = min(cy1, src.bounds.top)
                x = bx0
                while x < bx1:
                    y = by0
                    while y < by1:
                        wx1, wy1 = min(x + BLOCK_M, bx1), min(y + BLOCK_M, by1)
                        win = from_bounds(x, y, wx1, wy1, src.transform)
                        presence = src.read(3, window=win)
                        tr = src.window_transform(win)
                        mask = presence > PRESENCE_THRESHOLD
                        del presence
                        n_here = int(mask.sum())
                        if n_here:
                            H, W = mask.shape
                            ph, pw = (-H) % SUPER, (-W) % SUPER
                            if ph or pw:
                                mask = np.pad(mask, ((0, ph), (0, pw)))
                            sh, sw = mask.shape[0] // SUPER, mask.shape[1] // SUPER
                            counts = mask.reshape(sh, SUPER, sw, SUPER).sum(axis=(1, 3))
                            si, sj = np.nonzero(counts)
                            cnt = counts[si, sj]
                            px = tr.c + (sj * SUPER + SUPER / 2) * tr.a
                            py = tr.f + (si * SUPER + SUPER / 2) * tr.e
                            lon, lat = to_wgs.transform(px, py)
                            for r in res_list:
                                acc = out[r]
                                for la, lo, n in zip(lat, lon, cnt):
                                    c = h3.latlng_to_cell(la, lo, r)
                                    acc[c] = acc.get(c, 0) + int(n)
                            total_px += n_here
                        del mask
                        y += BLOCK_M
                    x += BLOCK_M
    except Exception as e:
        return {"_error": f"{url}: {e}"}, 0

    payload = {"_n_px": total_px}
    payload.update({str(r): out[r] for r in res_list})
    tmp = sp.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload))
    tmp.replace(sp)                        # atomic: no half-written spool
    return {"_done": str(sp)}, total_px

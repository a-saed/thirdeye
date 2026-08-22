"""
Re-clip archived Overture releases at the 4-governorate OPERATIONAL extent.

Why this exists: the original archive (Part I) clipped every release to the
three 1.5km Cairo study districts. That was correct for the feasibility
study and is useless for a citywide product - it is 6.75 km^2 of history out
of 8,708 km^2. This re-fetches the same releases at full extent while they
are still available.

SOURCES AND THEIR WINDOWS (verified 2026-08-20):
  official S3 (overturemaps-us-west-2) - retains only ~2 releases at a time.
      Currently 2026-07-22.0 and 2026-08-19.0.
  Source Cooperative mirror (data.source.coop/fused/overture) - 21 releases,
      2024-02-15-alpha-0 .. 2026-05-20-0.

  ==> 2026-07-22.0 exists ONLY on S3 and is NOT on the mirror. It will drop
      off S3 when the next release ships. It is re-clipped FIRST.
  ==> 2026-06-17.0 is PERMANENTLY LOST at any extent (Azure held only
      0-byte placeholders, the mirror never received it, S3 has dropped it).

Writes to the Part II raw layer: data/raw/overture/snapshot=<release>/
Immutable - a snapshot directory that already has _manifest.json is skipped.

Schema drift is handled per release, not assumed: early releases use
bbox.minx/maxx/miny/maxy and categories.main; later ones use
bbox.xmin/xmax/ymin/ymax and categories.primary.
"""
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.config._common import ROOT

RAW_ROOT = ROOT / "data" / "raw" / "overture"
MIRROR = "https://data.source.coop/fused/overture/"
S3_BASE = "s3://overturemaps-us-west-2/release"

# operational polygon bbox (config/coverage_area.gpkg)
BBOX = {"xmin": 29.5803, "ymin": 29.1717, "xmax": 31.8979, "ymax": 31.352}

PERMANENTLY_LOST = {"2026-06-17.0"}


def get_con():
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")
    con.execute("SET s3_region='us-west-2'; SET enable_progress_bar=false;")
    con.execute("SET memory_limit='3GB';")
    con.execute(f"SET temp_directory='{ROOT/'data'/'duckdb_tmp'}';")
    return con


def s3_releases() -> list:
    r = requests.get("https://overturemaps-us-west-2.s3.amazonaws.com/",
                     params={"list-type": "2", "delimiter": "/", "prefix": "release/"}, timeout=60)
    return sorted(re.findall(r"<CommonPrefixes><Prefix>release/(.*?)/</Prefix></CommonPrefixes>", r.text))


def mirror_releases() -> list:
    r = requests.get(MIRROR, params={"delimiter": "/"}, timeout=60)
    rels = re.findall(r"<CommonPrefixes><Prefix>overture/(.*?)/</Prefix></CommonPrefixes>", r.text)
    return sorted(p for p in rels if p != "docs")


def mirror_files(release: str) -> list:
    r = requests.get(MIRROR, params={"delimiter": "/", "prefix": f"{release}/theme=places/type=place/"}, timeout=60)
    keys = [k for k in re.findall(r"<Key>(.*?)</Key>", r.text)
            if not k.rsplit("/", 1)[-1].startswith(("_metadata", "_common_metadata", "_SUCCESS"))]
    return [f"https://data.source.coop/fused/{k}" for k in keys]


def detect_schema(con, source_expr: str) -> dict:
    cols = con.execute(f"DESCRIBE SELECT * FROM {source_expr} LIMIT 0").fetchall()
    types = {c[0]: c[1] for c in cols}
    bbox_t = types.get("bbox", "")
    bf = ({"xmin": "xmin", "xmax": "xmax", "ymin": "ymin", "ymax": "ymax"}
          if "xmin" in bbox_t else
          {"xmin": "minx", "xmax": "maxx", "ymin": "miny", "ymax": "maxy"})
    cat_t = types.get("categories", "")
    cf = "primary" if '"primary"' in cat_t else "main"
    return {"bbox_fields": bf, "cat_field": cf}


def reclip(con, release: str, source_expr: str, origin: str) -> dict:
    snap_dir = RAW_ROOT / f"snapshot={release}"
    manifest_path = snap_dir / "_manifest.json"
    if manifest_path.exists():
        return {"release": release, "status": "already_present"}

    sch = detect_schema(con, source_expr)
    bf, cf = sch["bbox_fields"], sch["cat_field"]
    where = (f"bbox.{bf['xmin']} <= {BBOX['xmax']} AND bbox.{bf['xmax']} >= {BBOX['xmin']} "
             f"AND bbox.{bf['ymin']} <= {BBOX['ymax']} AND bbox.{bf['ymax']} >= {BBOX['ymin']}")

    snap_dir.mkdir(parents=True, exist_ok=True)
    out = snap_dir / "places.parquet"
    t0 = time.time()
    con.execute(f"""
        COPY (
            SELECT id, names.primary AS name, categories.{cf} AS category,
                   confidence, ST_X(geometry) AS lon, ST_Y(geometry) AS lat,
                   '{release}' AS _snapshot_id, 'overture' AS _source
            FROM {source_expr}
            WHERE {where}
        ) TO '{out}' (FORMAT PARQUET)
    """)
    n = con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
    el = round(time.time() - t0, 1)
    manifest_path.write_text(json.dumps({
        "_source": "overture", "_snapshot_id": release, "_origin": origin,
        "_fetched_at": datetime.now(timezone.utc).isoformat(),
        "_fetch_query": {"bbox": BBOX, "schema": sch},
        "rows": n, "elapsed_s": el,
    }, indent=2))
    return {"release": release, "status": "written", "rows": n, "elapsed_s": el, "origin": origin}


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    con = get_con()
    s3 = s3_releases()
    mir = mirror_releases()

    plan = []
    # S3 first - these are the ones that expire
    for r in s3:
        plan.append((r, f"read_parquet('{S3_BASE}/{r}/theme=places/type=place/*', hive_partitioning=1)", "s3"))
    for r in mir:
        if r in s3:
            continue
        plan.append((r, None, "mirror"))

    if only:
        plan = [p for p in plan if p[0] == only]
        if not plan:
            print(f"release {only} not found on S3 or mirror"); sys.exit(1)

    print(f"S3 has {len(s3)}: {s3}")
    print(f"mirror has {len(mir)} (2024-02-15 .. {mir[-1]})")
    print(f"permanently lost, not recoverable at any extent: {sorted(PERMANENTLY_LOST)}")
    print(f"planned: {len(plan)} releases\n")

    results = []
    for rel, expr, origin in plan:
        if expr is None:
            files = mirror_files(rel)
            if not files:
                print(f"[{rel}] no files on mirror, skipping"); continue
            expr = "read_parquet([" + ",".join(f"'{u}'" for u in files) + "])"
        try:
            res = reclip(con, rel, expr, origin)
        except Exception as e:
            print(f"[{rel}] FAILED: {e}")
            results.append({"release": rel, "status": "failed", "error": str(e)})
            continue
        if res["status"] == "already_present":
            print(f"[{rel}] already present, skipping")
        else:
            print(f"[{rel}] {res['rows']:,} rows  ({res['elapsed_s']}s, {origin})")
        results.append(res)

    print("\n" + "=" * 70)
    ok = [r for r in results if r.get("status") == "written"]
    print(f"written {len(ok)} | skipped {sum(1 for r in results if r.get('status')=='already_present')} "
          f"| failed {sum(1 for r in results if r.get('status')=='failed')}")
    if ok:
        print(f"total rows across new snapshots: {sum(r['rows'] for r in ok):,}")


if __name__ == "__main__":
    main()

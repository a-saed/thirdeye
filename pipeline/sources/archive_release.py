"""
MONTHLY ARCHIVER — run every month, without fail.

Saves the current Overture release at the FULL 4-GOVERNORATE OPERATIONAL
EXTENT (config/coverage_area.gpkg), writing to the Part II raw layer at
data/raw/overture/snapshot=<release>/.

CHANGED 2026-08-20 - this previously archived only the three 1.5km Cairo
study bboxes (6.75 km^2 of 8,708 km^2). Every month it ran at that extent
produced citywide history that CANNOT be recovered later: Overture's own S3
retains only ~2 releases, and the Source Cooperative mirror lags by months
and has already missed at least one release entirely (2026-06-17.0, now
permanently lost at any extent). A month archived narrow is a month gone.

WHY THIS JOB IS THE PRODUCT'S TEMPORAL CAPABILITY:
The study has 23 releases of business-layer history only because releases
were archived rather than merged. Nothing upstream keeps them.

CHECK BOTH SOURCES. S3 is authoritative for the current release but retains
only ~2. The mirror (data.source.coop/fused/overture) holds a longer tail
but lags. If a release appears on neither, it is lost - so this job should
run monthly, and scripts/reclip_archive.py should be run periodically to
sweep up anything the mirror has that we do not.

Foursquare is NOT archived here. Its Iceberg catalog exposes only the
current snapshot (no historical snapshots are retained for OS Places), so
there is no equivalent back-catalogue to sweep, and a monthly pull costs a
full unpruned scan. Pull FSQ on demand instead.
"""
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.config._common import ROOT, OVERTURE_RELEASE, get_con

RAW_ROOT = ROOT / "data" / "raw" / "overture"
MIRROR = "https://data.source.coop/fused/overture/"

# operational polygon bbox - keep in sync with config/coverage_area.gpkg
BBOX = {"xmin": 29.5803, "ymin": 29.1717, "xmax": 31.8979, "ymax": 31.352}


def discover_latest_release() -> str:
    """Archiving always wants LATEST, which is deliberately NOT the pinned
    scripts/_common.py OVERTURE_RELEASE - that stays fixed so every analysis
    reproduces against one snapshot. Do not 'fix' the pin to match."""
    url = ("https://overturemaps-us-west-2.s3.amazonaws.com/"
           "?list-type=2&delimiter=/&prefix=release/")
    with urllib.request.urlopen(url, timeout=60) as resp:
        body = resp.read().decode()
    releases = re.findall(r"<CommonPrefixes><Prefix>release/(.*?)/</Prefix></CommonPrefixes>", body)
    if not releases:
        raise RuntimeError("no releases in S3 listing - bucket layout may have changed")
    return sorted(releases)[-1]


def mirror_releases():
    """Returns a sorted list, or None if the mirror could not be reached.
    None and [] mean different things here: [] would wrongly imply 'the
    mirror has nothing we lack', which is what a bare 403 produced before.
    data.source.coop 403s a default urllib User-Agent - it needs a real one."""
    req = urllib.request.Request(
        f"{MIRROR}?delimiter=/",
        headers={"User-Agent": "third-eye-archiver/1.0 (+monthly overture archive)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode()
    except Exception as e:
        print(f"    WARNING: mirror check failed ({e}) - gap detection SKIPPED this run")
        return None
    rels = re.findall(r"<CommonPrefixes><Prefix>overture/(.*?)/</Prefix></CommonPrefixes>", body)
    return sorted(p for p in rels if p != "docs")


def archive(release: str) -> dict:
    snap_dir = RAW_ROOT / f"snapshot={release}"
    manifest = snap_dir / "_manifest.json"
    if manifest.exists():
        return {"status": "already_present", "release": release}

    con = get_con()
    con.execute("SET memory_limit='3GB';")
    con.execute(f"SET temp_directory='{ROOT/'data'/'duckdb_tmp'}';")
    base = (f"read_parquet('s3://overturemaps-us-west-2/release/{release}"
            f"/theme=places/type=place/*', hive_partitioning=1)")
    where = (f"bbox.xmin <= {BBOX['xmax']} AND bbox.xmax >= {BBOX['xmin']} "
             f"AND bbox.ymin <= {BBOX['ymax']} AND bbox.ymax >= {BBOX['ymin']}")

    snap_dir.mkdir(parents=True, exist_ok=True)
    out = snap_dir / "places.parquet"
    con.execute(f"""
        COPY (
            SELECT id, names.primary AS name, categories.primary AS category,
                   confidence, ST_X(geometry) AS lon, ST_Y(geometry) AS lat,
                   '{release}' AS _snapshot_id, 'overture' AS _source
            FROM {base} WHERE {where}
        ) TO '{out}' (FORMAT PARQUET)
    """)
    n = con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
    manifest.write_text(json.dumps({
        "_source": "overture", "_snapshot_id": release, "_origin": "s3",
        "_fetched_at": datetime.now(timezone.utc).isoformat(),
        "_fetch_query": {"bbox": BBOX, "extent": "4-governorate operational"},
        "rows": n,
    }, indent=2))
    return {"status": "written", "release": release, "rows": n}


def main():
    release = discover_latest_release()
    print(f"=== Monthly archive — latest Overture release: {release} ===")
    print(f"    extent: 4-governorate operational bbox {BBOX}")
    print(f"    (analysis stays pinned to {OVERTURE_RELEASE} for reproducibility)")

    res = archive(release)
    if res["status"] == "already_present":
        print(f"    already archived — no-op (idempotent)")
    else:
        print(f"    archived {res['rows']:,} rows -> data/raw/overture/snapshot={release}/")

    # Coverage check across BOTH sources, so gaps are visible the month they happen.
    have = {p.name.split("=", 1)[1] for p in RAW_ROOT.glob("snapshot=*")} if RAW_ROOT.exists() else set()
    mir = mirror_releases()
    print(f"\n    local snapshots: {len(have)}")
    if mir is None:
        print("    mirror unreachable - cannot tell whether it holds releases we lack.")
    else:
        missing_from_local = sorted(set(mir) - have)
        print(f"    mirror offers: {len(mir)}")
        if missing_from_local:
            print(f"    NOT YET ARCHIVED LOCALLY (run scripts/reclip_archive.py): {missing_from_local}")
        else:
            print("    local archive covers everything the mirror offers")
    print("\n    Reminder: S3 retains only ~2 releases and the mirror lags by months.")
    print("    A release missing from both is permanently lost (e.g. 2026-06-17.0).")


if __name__ == "__main__":
    main()

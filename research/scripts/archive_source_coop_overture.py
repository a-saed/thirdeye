"""
Backfill historical Overture places snapshots from Source Cooperative's
community-maintained mirror (data.source.coop/fused/overture), the only
place we found real historical Overture data - official S3 and Azure only
retain the current release (verified directly: S3's release/ prefix has
exactly one folder; Azure's older release folder is real but contains
only 0-byte placeholder blobs in every theme).

Schema drifts across releases (e.g. bbox.minx/maxx/miny/maxy vs modern
bbox.xmin/xmax/ymin/ymax; categories.main vs modern categories.primary).
Each release's schema is probed before querying and normalised to the
modern field names at write time, so every vintage under data/archive/
shares one schema.

These files are NOT geo-partitioned (flat numbered parts, not sorted by
location), so parquet row-group pruning barely helps - each release
query is close to a full-file scan (~100-300MB). One super-bbox query
(the smallest rectangle covering all 3 districts) is used per release
instead of 3 separate per-district queries, since with pruning defeated
the cost is dominated by bytes scanned, not query count. This is slow
(observed: single-district test query exceeded 200s) - expect this
script to take a long time across 20+ releases. It is safe to re-run;
already-archived releases are skipped.
"""
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import ROOT, get_con, load_districts

ARCHIVE_ROOT = ROOT / "data" / "archive" / "overture"
SC_BASE = "https://data.source.coop/fused/overture/"


def list_releases() -> list[str]:
    r = requests.get(SC_BASE, params={"delimiter": "/"}, timeout=30)
    r.raise_for_status()
    prefixes = re.findall(r"<CommonPrefixes><Prefix>overture/(.*?)/</Prefix></CommonPrefixes>", r.text)
    return sorted(p for p in prefixes if p != "docs")


def list_release_files(release: str) -> list[str]:
    r = requests.get(SC_BASE, params={"delimiter": "/", "prefix": f"{release}/theme=places/type=place/"}, timeout=30)
    r.raise_for_status()
    keys = re.findall(r"<Key>(.*?)</Key>", r.text)
    # Spark write-side summary files, not per-row-group-readable data files.
    keys = [k for k in keys if not k.rsplit("/", 1)[-1].startswith(("_metadata", "_common_metadata", "_SUCCESS"))]
    return [f"https://data.source.coop/fused/{k}" for k in keys]


def super_bbox(districts: dict) -> dict:
    xmins = [d["bbox"]["xmin"] for d in districts.values()]
    xmaxs = [d["bbox"]["xmax"] for d in districts.values()]
    ymins = [d["bbox"]["ymin"] for d in districts.values()]
    ymaxs = [d["bbox"]["ymax"] for d in districts.values()]
    return {"xmin": min(xmins), "xmax": max(xmaxs), "ymin": min(ymins), "ymax": max(ymaxs)}


def detect_schema(con, sample_url: str) -> dict:
    cols = con.execute(f"DESCRIBE SELECT * FROM read_parquet(['{sample_url}']) LIMIT 0").fetchall()
    coltypes = {c[0]: c[1] for c in cols}
    bbox_type = coltypes.get("bbox", "")
    if "xmin" in bbox_type:
        bbox_fields = {"xmin": "xmin", "xmax": "xmax", "ymin": "ymin", "ymax": "ymax"}
    else:
        bbox_fields = {"xmin": "minx", "xmax": "maxx", "ymin": "miny", "ymax": "maxy"}
    cat_type = coltypes.get("categories", "")
    cat_field = "primary" if '"primary"' in cat_type else "main"
    return {"bbox_fields": bbox_fields, "cat_field": cat_field}


def point_in_bbox_sql(alias_lon: str, alias_lat: str, bbox: dict) -> str:
    return f"{alias_lon} BETWEEN {bbox['xmin']} AND {bbox['xmax']} AND {alias_lat} BETWEEN {bbox['ymin']} AND {bbox['ymax']}"


def main():
    con = get_con()
    districts = load_districts()
    sbbox = super_bbox(districts)

    releases = list_releases()
    print(f"Found {len(releases)} releases on Source Cooperative: {releases}\n")

    for release in releases:
        release_dir = ARCHIVE_ROOT / release
        marker = release_dir / "manifest.json"
        if marker.exists():
            print(f"[{release}] already archived, skipping")
            continue

        t0 = time.time()
        files = list_release_files(release)
        if not files:
            print(f"[{release}] no theme=places/type=place files found, skipping")
            continue

        schema = detect_schema(con, files[0])
        bf = schema["bbox_fields"]
        cf = schema["cat_field"]
        url_list = "[" + ",".join(f"'{u}'" for u in files) + "]"

        where = (
            f"bbox.{bf['xmin']} <= {sbbox['xmax']} AND bbox.{bf['xmax']} >= {sbbox['xmin']} "
            f"AND bbox.{bf['ymin']} <= {sbbox['ymax']} AND bbox.{bf['ymax']} >= {sbbox['ymin']}"
        )

        print(f"[{release}] {len(files)} files, schema bbox={bf}, category={cf} - querying...", flush=True)
        q = f"""
            SELECT id, names.primary AS name, categories.{cf} AS category,
                   confidence, ST_X(geometry) AS lon, ST_Y(geometry) AS lat
            FROM read_parquet({url_list})
            WHERE {where}
        """
        try:
            df = con.execute(q).fetchdf()
        except Exception as e:
            print(f"[{release}] FAILED: {e}")
            continue

        release_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "release": release,
            "source": "https://data.source.coop/fused/overture/",
            "pulled_at": datetime.now(timezone.utc).isoformat(),
            "schema_detected": schema,
            "districts": {},
        }
        for name, d in districts.items():
            sub = df[df.apply(lambda r: d["bbox"]["xmin"] <= r["lon"] <= d["bbox"]["xmax"] and d["bbox"]["ymin"] <= r["lat"] <= d["bbox"]["ymax"], axis=1)]
            out_path = release_dir / (name.replace(" ", "_").lower() + ".parquet")
            sub.to_parquet(out_path, index=False)
            manifest["districts"][name] = len(sub)

        (release_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
        print(f"[{release}] done in {round(time.time()-t0,1)}s - {manifest['districts']}")


if __name__ == "__main__":
    main()

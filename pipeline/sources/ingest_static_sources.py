"""
Register the already-downloaded raster/vector sources into the Part II raw
layer with provenance manifests: GHSL (BUILT-S + LAND), WSF Evolution, Kontur.

These were fetched during the feasibility study into ad-hoc cache dirs.
Rather than re-download identical bytes, they are moved into
data/raw/<source>/snapshot=<upstream_id>/ and given the mandatory provenance
manifest. The upstream id is the dataset's own release/epoch identifier, not
the pull date, per schema decision (b).

Idempotent: a snapshot with a manifest is left alone.
"""
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.config._common import ROOT

RAW = ROOT / "data" / "raw"

SOURCES = [
    # (source, snapshot_id, [files], origin)
    ("ghsl_built_s", "R2023A_E2015", [ROOT/"data/ghsl_cache/GHS_BUILT_S_E2015_GLOBE_R2023A_4326_3ss_V1_0_R6_C22.tif"],
     "jeodpp.jrc.ec.europa.eu GHS_BUILT_S_GLOBE_R2023A"),
    ("ghsl_built_s", "R2023A_E2020", [ROOT/"data/ghsl_cache/GHS_BUILT_S_E2020_GLOBE_R2023A_4326_3ss_V1_0_R6_C22.tif"],
     "jeodpp.jrc.ec.europa.eu GHS_BUILT_S_GLOBE_R2023A"),
    ("ghsl_built_s", "R2023A_E2025", [ROOT/"data/ghsl_cache/GHS_BUILT_S_E2025_GLOBE_R2023A_4326_3ss_V1_0_R6_C22.tif",
                                      ROOT/"data/ghsl_cache/GHS_BUILT_S_E2025_GLOBE_R2023A_4326_3ss_V1_0_R6_C21.tif"],
     "jeodpp.jrc.ec.europa.eu GHS_BUILT_S_GLOBE_R2023A"),
    ("ghsl_land", "R2022A_E2018", [ROOT/"data/ghsl_cache/GHS_LAND_E2018_GLOBE_R2022A_54009_100_V1_0_R6_C21.tif"],
     "jeodpp.jrc.ec.europa.eu GHS_LAND_GLOBE_R2022A"),
    ("wsf_evolution", "v1_1985_2015", [ROOT/"data/wsf_evolution_cache/WSFevolution_v1_30_30.tif",
                                       ROOT/"data/wsf_evolution_cache/WSFevolution_v1_30_28.tif"],
     "download.geoservice.dlr.de WSF_EVO"),
    ("kontur", "20231101", [ROOT/"data/raw/kontur/snapshot=20231101/kontur_population_EG_20231101.gpkg"],
     "HDX kontur-population-egypt"),
]


def sha256(p: Path, limit=64 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        read = 0
        while read < limit:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b); read += len(b)
    return h.hexdigest()[:16]


def main():
    for source, snap, files, origin in SOURCES:
        files = [f for f in files if f.exists()]
        if not files:
            print(f"[{source}/{snap}] SKIP - no source files found locally")
            continue
        d = RAW / source / f"snapshot={snap}"
        man = d / "_manifest.json"
        if man.exists():
            print(f"[{source}/{snap}] already registered")
            continue
        d.mkdir(parents=True, exist_ok=True)
        entries = []
        for f in files:
            dest = d / f.name
            if not dest.exists():
                shutil.copy2(f, dest)
            entries.append({"file": f.name, "bytes": dest.stat().st_size, "sha256_prefix": sha256(dest)})
        man.write_text(json.dumps({
            "_source": source, "_snapshot_id": snap, "_origin": origin,
            "_fetched_at": datetime.now(timezone.utc).isoformat(),
            "_fetch_query": "full tile(s) as published upstream",
            "files": entries,
        }, indent=2))
        total = sum(e["bytes"] for e in entries)
        print(f"[{source}/{snap}] registered {len(entries)} file(s), {total/1e6:.1f} MB")


if __name__ == "__main__":
    main()

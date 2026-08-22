"""
Foursquare ingest -> data/raw/fsq/snapshot=<iceberg_snapshot_id>/

METHOD: PyIceberg, not DuckDB. The DuckDB iceberg extension ignores manifest
pruning on this table (it reported the same ~21.85M-row scan for every
filter, which is why the original 3-district pull took 43.5 minutes for
6.75 km^2). PyIceberg prunes to 4 files / 1.98 GB.

SCOPE: pulls ALL OF EGYPT in one go, then clips locally. This is not
over-fetching - the table has no partition spec and no sort order, so
pruning is coarse and file-level: a 300m street, the 4-governorate extent
and the whole country all resolve to the SAME 4 files. The marginal cost of
taking the country over one street is zero, and it means later coverage
changes need no re-download.

VERSIONING: snapshot directory is tagged with the Iceberg snapshot id, which
is the upstream immutable identifier - not the pull date. Re-running against
the same upstream snapshot is a no-op.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.config._common import ROOT

RAW_ROOT = ROOT / "data" / "raw" / "fsq"
CATALOG_URI = "https://catalog.h3-hub.foursquare.com/iceberg"
WAREHOUSE = "places"          # /v1/config 400s without this
TABLE = "datasets.places_os"

EGYPT = {"xmin": 24.7, "ymin": 21.9, "xmax": 37.0, "ymax": 31.7}
COLS = ("fsq_place_id", "name", "latitude", "longitude", "country", "locality",
        "region", "date_created", "date_refreshed", "date_closed",
        "fsq_category_ids", "fsq_category_labels", "unresolved_flags")


def main():
    load_dotenv()
    from pyiceberg.catalog.rest import RestCatalog
    from pyiceberg.expressions import And, GreaterThanOrEqual, LessThanOrEqual

    cat = RestCatalog("fsq", uri=CATALOG_URI, token=os.environ["FSQ_TOKEN"], warehouse=WAREHOUSE)
    tbl = cat.load_table(TABLE)
    snap = tbl.metadata.current_snapshot_id
    snap_dir = RAW_ROOT / f"snapshot={snap}"
    manifest = snap_dir / "_manifest.json"
    if manifest.exists():
        print(f"snapshot {snap} already ingested — no-op (immutable)")
        return

    expr = And(
        And(GreaterThanOrEqual("latitude", EGYPT["ymin"]), LessThanOrEqual("latitude", EGYPT["ymax"])),
        And(GreaterThanOrEqual("longitude", EGYPT["xmin"]), LessThanOrEqual("longitude", EGYPT["xmax"])),
    )
    planned = list(tbl.scan(row_filter=expr).plan_files())
    planned_bytes = sum(f.file.file_size_in_bytes for f in planned)
    print(f"iceberg snapshot {snap} | pruned to {len(planned)} files / {planned_bytes/1e9:.2f} GB")

    t0 = time.time()
    arrow = tbl.scan(row_filter=expr, selected_fields=COLS).to_arrow()
    el = round(time.time() - t0, 1)
    print(f"scanned Egypt: {arrow.num_rows:,} rows in {el}s")

    snap_dir.mkdir(parents=True, exist_ok=True)
    import pyarrow.parquet as pq
    pq.write_table(arrow, snap_dir / "places_egypt.parquet")

    manifest.write_text(json.dumps({
        "_source": "fsq", "_snapshot_id": str(snap), "_origin": CATALOG_URI,
        "_fetched_at": datetime.now(timezone.utc).isoformat(),
        "_fetch_query": {"bbox": EGYPT, "scope": "egypt-wide, clipped locally",
                         "files_pruned_to": len(planned), "bytes_scanned": planned_bytes},
        "rows": arrow.num_rows, "elapsed_s": el,
    }, indent=2))
    print(f"wrote {snap_dir/'places_egypt.parquet'}")


if __name__ == "__main__":
    main()

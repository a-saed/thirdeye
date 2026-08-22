"""
Builds h3_metric_history — business metrics per cell per archived snapshot.

This is the table the UI scrubber reads. It is deliberately SEPARATE from
h3_metric so the current-state read path stays small enough to hold in RAM:
history is millions of rows and stays on disk, queried lazily via DuckDB.

ONE SOURCE ONLY. The archive contains Overture snapshots and nothing else —
Foursquare's Iceberg catalog exposes only the current snapshot, so no FSQ
back-catalogue exists to archive. Every row here is therefore
confidence=single_source, and that is a fact about the data, not a defect in
this script. Do not "upgrade" it.

THE JUNE 2026 GAP IS REAL AND MUST BE DECLARED. Overture release
2026-06-17.0 is permanently lost (S3 retains ~2 releases and had aged it out;
Azure held only 0-byte placeholders; the community mirror never received it).
A consumer plotting this series will see a jump from 2026-05-20 to 2026-07-22.
That is missing data, NOT a real-world dip. The gap is written into a
sidecar manifest so the API can surface it rather than leaving the UI to
infer a decline.
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import h3
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.config._common import ROOT
from pipeline.config.categories import GROUPS as OV_GROUPS
from pipeline.qa.qa import (NOT_STOREFRONT_CATEGORIES, CAMPUS_INTERIOR_CATEGORIES,
                            NOT_STOREFRONT_NAME_KEYWORDS)
from pipeline.aggregate.artifacts import (detect_artifact_indices, JUMP_PCT,
                                          FLAT_TOL_PCT, MIN_FLAT, MIN_BASE, MIN_ABS_JUMP)

RAW = ROOT / "data" / "raw" / "overture"
OUT = ROOT / "data" / "derived" / "h3_tables"
RESOLUTIONS = (8, 9)

# Known permanent gaps in the archive, surfaced to the API.
KNOWN_GAPS = [{
    "missing_snapshot": "2026-06-17.0",
    "between": ["2026-05-20-0", "2026-07-22.0"],
    "reason": ("Overture S3 retains only ~2 releases and had aged it out; Azure held "
               "only 0-byte placeholder blobs; the Source Cooperative mirror never "
               "received it. Permanently unrecoverable at any extent."),
    "consumer_note": "Treat as missing data. Do NOT render as a decline or as zero.",
}]

_EXCLUDE_CATS = set(NOT_STOREFRONT_CATEGORIES) | set(CAMPUS_INTERIOR_CATEGORIES)
_NAME_RE = re.compile("|".join(NOT_STOREFRONT_NAME_KEYWORDS), re.IGNORECASE)


def storefront_mask(df: pd.DataFrame) -> pd.Series:
    """Vectorised equivalent of qa.check_non_storefront for the Overture-only
    archive. Row-wise apply is far too slow across 23 snapshots x ~250k rows."""
    cat = df["category"].astype(str)
    bad = cat.isin(_EXCLUDE_CATS)
    bad |= df["name"].astype(str).str.contains(_NAME_RE, na=False)
    return ~bad


def snapshot_date(snap: str) -> str:
    m = re.match(r"(\d{4}-\d{2}-\d{2})", snap)
    return m.group(1) if m else snap


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    snaps = sorted(RAW.glob("snapshot=*"))
    if not snaps:
        raise SystemExit("no overture snapshots found")
    print(f"snapshots: {len(snaps)}")

    per_res = {r: [] for r in RESOLUTIONS}
    for i, sd in enumerate(snaps, 1):
        snap = sd.name.split("=", 1)[1]
        f = sd / "places.parquet"
        if not f.exists():
            print(f"  [{snap}] missing places.parquet — skipped")
            continue
        df = pd.read_parquet(f, columns=["name", "category", "lat", "lon"])
        df = df[storefront_mask(df)]
        as_of = snapshot_date(snap)

        for res in RESOLUTIONS:
            cells = [h3.latlng_to_cell(a, b, res) for a, b in zip(df.lat, df.lon)]
            t = pd.DataFrame({"h3_index": cells, "category": df.category.astype(str).values})
            rows = []
            for grp, members in OV_GROUPS.items():
                sub = t[t.category.isin(members)]
                if len(sub):
                    g = sub.groupby("h3_index").size().reset_index(name="value")
                    g["metric"] = f"business_count.{grp}"
                    rows.append(g)
            gt = t.groupby("h3_index").size().reset_index(name="value")
            gt["metric"] = "business_count.total"
            rows.append(gt)
            out = pd.concat(rows, ignore_index=True)
            out["h3_res"] = res
            out["track"] = "business"
            out["snapshot_id"] = snap
            out["as_of"] = as_of
            # Overture is the only archived source; see module docstring.
            out["confidence"] = "single_source"
            out["n_sources"] = 1
            per_res[res].append(out)
        print(f"  [{i:2d}/{len(snaps)}] {snap}: {len(df):,} storefront places", flush=True)

    # ---- artifact detection, per cell per metric -------------------------
    # Flag only. Nothing is removed or smoothed here: the API returns the raw
    # series plus flags, and a corrected series alongside, so the caller
    # decides. Silently smoothing would hide the very thing the study spent
    # weeks establishing.
    snap_order = {s.name.split("=", 1)[1]: i for i, s in enumerate(snaps)}
    stats = {}
    for res in RESOLUTIONS:
        d = pd.concat(per_res[res], ignore_index=True)
        d["_ord"] = d.snapshot_id.map(snap_order)
        d = d.sort_values(["h3_index", "metric", "_ord"])
        d["point_status"] = "ok"
        d["excluded_from_corrected"] = False

        flagged_cells, total_series, flagged_series = set(), 0, 0
        idx_status = d.columns.get_loc("point_status")
        idx_excl = d.columns.get_loc("excluded_from_corrected")
        for (cell, metric), grp in d.groupby(["h3_index", "metric"], sort=False):
            total_series += 1
            vals = grp.value.tolist()
            hits = detect_artifact_indices(vals)
            if not hits:
                continue
            flagged_series += 1
            flagged_cells.add(cell)
            pos = [d.index.get_loc(i) for i in grp.index]
            for h in hits:
                d.iat[pos[h], idx_status] = "artifact_suspected"
            # Corrected series starts at the LAST artifact: everything before
            # it belongs to a different, pre-import baseline. This is the
            # method that turned Imbaba's +78.5% into -4.0%.
            last = hits[-1]
            for j in range(0, last):
                d.iat[pos[j], idx_excl] = True

        d = d.drop(columns=["_ord"])
        p = OUT / f"h3_metric_history_res{res}.parquet"
        d.to_parquet(p, index=False)
        n_cells = d.h3_index.nunique()
        stats[res] = {
            "cells": int(n_cells),
            "cells_with_artifact": len(flagged_cells),
            "pct_cells_with_artifact": round(100 * len(flagged_cells) / n_cells, 1),
            "series": total_series,
            "series_with_artifact": flagged_series,
            "pct_series_with_artifact": round(100 * flagged_series / total_series, 1),
            "points_flagged": int((d.point_status == "artifact_suspected").sum()),
            "points_excluded_from_corrected": int(d.excluded_from_corrected.sum()),
            "rows": len(d),
        }
        print(f"res-{res}: {len(d):,} rows | cells with >=1 artifact_suspected: "
              f"{len(flagged_cells):,}/{n_cells:,} ({stats[res]['pct_cells_with_artifact']}%) | "
              f"series flagged {flagged_series:,}/{total_series:,} "
              f"({stats[res]['pct_series_with_artifact']}%)")

    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "snapshots": [s.name.split("=", 1)[1] for s in snaps],
        "sources": ["overture"],
        "confidence_note": ("All rows are single_source: the archive contains Overture "
                            "only. Foursquare exposes no historical snapshots."),
        "known_gaps": KNOWN_GAPS,
        "artifact_detector": {
            "jump_pct": JUMP_PCT, "flat_tol_pct": FLAT_TOL_PCT, "min_flat_releases": MIN_FLAT,
            "min_base": MIN_BASE, "min_abs_jump": MIN_ABS_JUMP,
            "note": ("Flag only - nothing removed or smoothed. MIN_BASE/MIN_ABS_JUMP "
                     "exist because the rule was calibrated on district-level counts "
                     "(hundreds); at cell level a 40% jump can be a single record."),
        },
        "artifact_stats": stats,
    }
    (OUT / "h3_metric_history_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nwrote manifest with {len(KNOWN_GAPS)} declared gap(s)")


if __name__ == "__main__":
    main()

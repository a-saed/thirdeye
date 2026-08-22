"""
Test 4 - Is the population layer sane?

Kontur Population (400m H3 hexagons), Egypt subset, downloaded from HDX
(data.humdata.org/dataset/kontur-population-egypt, most recent vintage
2023-11-01, direct S3 URL, no key needed). Clips to the 3 district
bboxes, reports population totals, and produces a choropleth PNG per
district.

Reference points (dense residential / commercial / empty) to be
supplied by the user afterward for ordering sanity check - not run yet.
"""
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import ROOT, load_districts

GPKG_PATH = ROOT / "data" / "kontur" / "kontur_population_EG_20231101.gpkg"


def main():
    districts = load_districts()
    gdf = gpd.read_file(GPKG_PATH)  # EPSG:3857
    gdf_wgs84 = gdf.to_crs("EPSG:4326")

    print("=" * 70)
    print("Kontur Population - district totals")
    print("=" * 70)

    results = []
    for name, d in districts.items():
        bbox = d["bbox"]
        district_poly = box(bbox["xmin"], bbox["ymin"], bbox["xmax"], bbox["ymax"])
        clip = gdf_wgs84[gdf_wgs84.intersects(district_poly)].copy()
        # weight by fraction of hexagon area inside the bbox, since hexagons straddle the boundary
        clip["frac_in_bbox"] = clip.geometry.apply(lambda g: g.intersection(district_poly).area / g.area if g.area else 0)
        clip["pop_weighted"] = clip["population"] * clip["frac_in_bbox"]
        total_pop = clip["pop_weighted"].sum()
        n_hex = len(clip)
        print(f"\n=== {name} ===")
        print(f"  hexagons intersecting bbox: {n_hex}")
        print(f"  total population (area-weighted): {total_pop:.0f}")
        print(f"  density: {total_pop/2.25:.0f} people/km^2  (2.25 km^2 bbox)")
        results.append({"district": name, "n_hexagons": n_hex, "total_population": round(total_pop), "density_per_km2": round(total_pop/2.25)})

        # choropleth PNG
        fig, ax = plt.subplots(figsize=(7, 7))
        clip_proj = clip.to_crs("EPSG:32636")
        clip_proj.plot(column="population", cmap="YlOrRd", legend=True, ax=ax, edgecolor="grey", linewidth=0.3)
        bbox_gdf = gpd.GeoDataFrame(geometry=[district_poly], crs="EPSG:4326").to_crs("EPSG:32636")
        bbox_gdf.boundary.plot(ax=ax, color="blue", linewidth=1.5)
        ax.set_title(f"Kontur population - {name}\ntotal (area-weighted): {total_pop:.0f}")
        ax.set_axis_off()
        fig.tight_layout()
        out_png = ROOT / "output" / f"test4_kontur_{name.replace(' ', '_').lower()}.png"
        fig.savefig(out_png, dpi=150)
        plt.close(fig)
        print(f"  Wrote {out_png}")

    import pandas as pd
    out_csv = ROOT / "output" / "test4_kontur_population.csv"
    pd.DataFrame(results).to_csv(out_csv, index=False)
    print(f"\nWrote {out_csv}")


if __name__ == "__main__":
    main()

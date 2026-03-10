#!/usr/bin/env python3
"""
make_candidates_osm_v2.py — Diversified EV charger candidate sites
===================================================================
v1 only fetched amenity=parking. v2 adds:
  - Supermarkets (dwell time = charging opportunity)
  - Petrol stations (transition infrastructure)
  - Leisure centres / sports centres
  - Railway stations (park & ride)
  - Hospitals & health centres
  - Shopping centres / retail parks

Each candidate is tagged with its source type so the planner
can weight or filter by site suitability.

Usage:
  python make_candidates_osm_v2.py
"""

import pandas as pd
import geopandas as gpd
import osmnx as ox
from pathlib import Path
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

PLACE = "Cardiff, Wales, United Kingdom"
OUT = Path("data/processed/candidates_osm_v2.geojson")

# Each query: (osm_tags, site_type_label, suitability_score 0-1)
QUERIES = [
    ({"amenity": "parking"},           "car_park",      0.8),
    ({"shop": "supermarket"},          "supermarket",   0.9),
    ({"amenity": "fuel"},              "petrol_station", 0.7),
    ({"leisure": "sports_centre"},     "leisure",       0.6),
    ({"leisure": "fitness_centre"},    "leisure",       0.5),
    ({"railway": "station"},           "rail_station",  0.85),
    ({"amenity": "hospital"},          "hospital",      0.7),
    ({"shop": "mall"},                 "shopping_centre",0.8),
    ({"amenity": "community_centre"},  "community",     0.5),
    ({"tourism": "hotel"},             "hotel",         0.6),
]

# Minimum spacing (m) to deduplicate overlapping candidates
DEDUP_DIST_M = 50


def fetch_category(tags, site_type, score):
    """Fetch OSM features and convert to point GeoDataFrame."""
    try:
        gdf = ox.features_from_place(PLACE, tags=tags)
    except Exception as e:
        print(f"  [WARN] No results for {tags}: {e}")
        return gpd.GeoDataFrame()

    if gdf.empty:
        return gpd.GeoDataFrame()

    # Convert polygons to centroids
    pts = gdf[gdf.geometry.type.isin(["Point", "MultiPoint"])].copy()
    polys = gdf[gdf.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()
    if len(polys) > 0:
        polys = polys.copy()
        polys["geometry"] = polys.geometry.centroid
        pts = gpd.GeoDataFrame(pd.concat([pts, polys], ignore_index=True), crs=gdf.crs)

    if pts.empty:
        return gpd.GeoDataFrame()

    # Extract useful name
    for col in ["name", "operator", "brand"]:
        if col in pts.columns:
            pts["_name"] = pts[col].fillna("")
            break
    else:
        pts["_name"] = ""

    # Keep only essential columns
    pts = pts[["geometry", "_name"]].copy()
    pts["site_type"] = site_type
    pts["suitability"] = score

    return pts


def deduplicate(gdf, min_dist_m=DEDUP_DIST_M):
    """Remove near-duplicate points (within min_dist_m of each other)."""
    if len(gdf) < 2:
        return gdf

    gdf_proj = gdf.to_crs(27700)
    keep = [True] * len(gdf_proj)
    coords = list(zip(gdf_proj.geometry.x, gdf_proj.geometry.y))

    for i in range(len(coords)):
        if not keep[i]:
            continue
        for j in range(i + 1, len(coords)):
            if not keep[j]:
                continue
            dx = coords[i][0] - coords[j][0]
            dy = coords[i][1] - coords[j][1]
            if (dx * dx + dy * dy) < min_dist_m * min_dist_m:
                # Keep the one with higher suitability
                if gdf.iloc[j]["suitability"] > gdf.iloc[i]["suitability"]:
                    keep[i] = False
                    break
                else:
                    keep[j] = False

    return gdf[keep].reset_index(drop=True)


def main():
    all_pts = []

    for tags, site_type, score in QUERIES:
        print(f"Fetching {site_type} ({tags})...")
        pts = fetch_category(tags, site_type, score)
        if not pts.empty:
            print(f"  → {len(pts)} features")
            all_pts.append(pts)

    if not all_pts:
        raise RuntimeError("No candidates found from any category!")

    combined = gpd.GeoDataFrame(pd.concat(all_pts, ignore_index=True), crs="EPSG:4326")
    print(f"\nCombined: {len(combined)} raw candidates")

    # Deduplicate
    combined = deduplicate(combined)
    print(f"After dedup ({DEDUP_DIST_M}m): {len(combined)} candidates")

    # Project to BNG for consistency with pipeline
    combined = combined.to_crs(27700)

    # Rename columns
    combined = combined.rename(columns={"_name": "name"})

    # Summary
    print(f"\nBy site type:")
    for st, cnt in combined["site_type"].value_counts().items():
        print(f"  {st}: {cnt}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    combined.to_file(OUT, driver="GeoJSON")
    print(f"\nSaved: {OUT} ({len(combined)} candidates)")


if __name__ == "__main__":
    main()

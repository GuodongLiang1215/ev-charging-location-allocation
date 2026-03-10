#!/usr/bin/env python3
"""
join_traffic_to_candidates.py — Enrich candidates with DfT traffic data
=========================================================================
Joins Annual Average Daily Flow (AADF) from DfT traffic count points
to candidate EV charger sites. Sites near high-traffic roads get a
traffic_demand_bonus that can improve their score in the planner.

Method:
  - For each candidate, find all DfT count points within radius
  - Sum the AADF (all_motor_vehicles or cars_and_taxis) as traffic_volume
  - Normalize to 0-1 as traffic_demand_score

Input:
  - DfT AADF CSV (from dft_traffic_fetch.py → cardiff_aadf_2024.csv)
  - DfT count points CSV (from dft_traffic_fetch.py → cardiff_count_points_2024.csv)
  - Candidates GeoJSON

Output:
  - Enriched candidates GeoJSON with traffic_volume and traffic_demand_score

Usage:
  python join_traffic_to_candidates.py
  python join_traffic_to_candidates.py --aadf cardiff_aadf_2024.csv --candidates data/processed/candidates_osm_v2.geojson --radius 500
"""

import argparse
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point


# Default paths
AADF_CSV    = Path("cardiff_aadf_2024.csv")
CP_CSV      = Path("cardiff_count_points_2024.csv")
CAND        = Path("data/processed/candidates_osm_v2.geojson")
CAND_FB     = Path("data/processed/candidates_osm_parking.geojson")
OUT         = Path("data/processed/candidates_with_traffic.geojson")

SEARCH_RADIUS_M = 500  # meters: how close a count point must be to a candidate


def load_count_points(cp_path, aadf_path=None):
    """
    Load DfT count points with coordinates and optionally join AADF volumes.
    """
    cp = pd.read_csv(cp_path)

    # Get coordinates
    if "latitude" in cp.columns and "longitude" in cp.columns:
        cp = cp.dropna(subset=["latitude", "longitude"])
        cp["lat"] = pd.to_numeric(cp["latitude"], errors="coerce")
        cp["lng"] = pd.to_numeric(cp["longitude"], errors="coerce")
    elif "easting" in cp.columns and "northing" in cp.columns:
        # BNG coordinates — will handle in GeoDataFrame
        cp["easting"] = pd.to_numeric(cp["easting"], errors="coerce")
        cp["northing"] = pd.to_numeric(cp["northing"], errors="coerce")
        cp = cp.dropna(subset=["easting", "northing"])
    else:
        raise ValueError(f"Cannot find coordinate columns. Available: {list(cp.columns)[:20]}")

    # Join AADF if available
    if aadf_path and Path(aadf_path).exists():
        aadf = pd.read_csv(aadf_path)
        # Find traffic volume column
        vol_col = None
        for c in ["all_motor_vehicles", "cars_and_taxis", "all_hgvs", "total_volume"]:
            if c in aadf.columns:
                vol_col = c
                break
        if vol_col:
            # Merge on count_point_id
            cp_id_col = "count_point_id" if "count_point_id" in cp.columns else "id"
            aadf_id_col = "count_point_id" if "count_point_id" in aadf.columns else "id"
            if cp_id_col in cp.columns and aadf_id_col in aadf.columns:
                aadf_sub = aadf[[aadf_id_col, vol_col]].copy()
                aadf_sub.columns = [cp_id_col, "aadf_volume"]
                aadf_sub["aadf_volume"] = pd.to_numeric(aadf_sub["aadf_volume"], errors="coerce")
                aadf_sub = aadf_sub.groupby(cp_id_col, as_index=False)["aadf_volume"].max()
                cp = cp.merge(aadf_sub, on=cp_id_col, how="left")

    # Build GeoDataFrame
    if "lat" in cp.columns:
        gdf = gpd.GeoDataFrame(cp, geometry=gpd.points_from_xy(cp["lng"], cp["lat"]), crs="EPSG:4326")
        gdf = gdf.to_crs("EPSG:27700")
    else:
        gdf = gpd.GeoDataFrame(cp, geometry=gpd.points_from_xy(cp["easting"], cp["northing"]), crs="EPSG:27700")

    if "aadf_volume" not in gdf.columns:
        gdf["aadf_volume"] = 1  # fallback: just count of nearby points

    print(f"Loaded {len(gdf)} count points, {gdf['aadf_volume'].notna().sum()} with AADF volume")
    return gdf


def join_traffic(candidates, count_points, radius_m=SEARCH_RADIUS_M):
    """
    For each candidate, sum AADF volume of count points within radius.
    """
    cand_proj = candidates.to_crs("EPSG:27700") if candidates.crs != "EPSG:27700" else candidates
    cp_proj = count_points.to_crs("EPSG:27700") if count_points.crs != "EPSG:27700" else count_points

    c_xy = np.c_[cand_proj.geometry.x.values, cand_proj.geometry.y.values]
    cp_xy = np.c_[cp_proj.geometry.x.values, cp_proj.geometry.y.values]
    cp_vol = cp_proj["aadf_volume"].fillna(0).values

    traffic_volumes = np.zeros(len(cand_proj))
    traffic_counts = np.zeros(len(cand_proj), dtype=int)

    for i in range(len(c_xy)):
        dists = np.sqrt(((c_xy[i] - cp_xy) ** 2).sum(axis=1))
        nearby = dists <= radius_m
        traffic_volumes[i] = cp_vol[nearby].sum()
        traffic_counts[i] = nearby.sum()

    # Normalize to 0-1
    max_vol = traffic_volumes.max()
    if max_vol > 0:
        traffic_score = traffic_volumes / max_vol
    else:
        traffic_score = np.zeros(len(cand_proj))

    candidates = candidates.copy()
    candidates["traffic_volume"] = traffic_volumes
    candidates["traffic_count_pts"] = traffic_counts
    candidates["traffic_demand_score"] = np.round(traffic_score, 4)

    n_with_traffic = (traffic_volumes > 0).sum()
    print(f"Candidates with nearby traffic data: {n_with_traffic}/{len(candidates)}")
    print(f"Traffic volume range: {traffic_volumes.min():.0f} – {traffic_volumes.max():.0f}")

    return candidates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count-points", type=str, default=str(CP_CSV))
    parser.add_argument("--aadf", type=str, default=str(AADF_CSV))
    parser.add_argument("--candidates", type=str, default=None)
    parser.add_argument("--radius", type=int, default=SEARCH_RADIUS_M)
    parser.add_argument("--output", type=str, default=str(OUT))
    args = parser.parse_args()

    # Find candidates
    cand_path = args.candidates
    if not cand_path:
        cand_path = str(CAND) if CAND.exists() else str(CAND_FB)
    if not Path(cand_path).exists():
        raise FileNotFoundError(f"Candidates not found: {cand_path}")

    cand = gpd.read_file(cand_path).to_crs(27700).reset_index(drop=True)
    print(f"Loaded {len(cand)} candidates from {cand_path}")

    # Load traffic data
    cp_path = Path(args.count_points)
    aadf_path = args.aadf if Path(args.aadf).exists() else None

    if not cp_path.exists():
        print(f"[WARN] Count points CSV not found: {cp_path}")
        print("Run dft_traffic_fetch.py first to download DfT data.")
        print("Saving candidates with zero traffic scores...")
        cand["traffic_volume"] = 0
        cand["traffic_count_pts"] = 0
        cand["traffic_demand_score"] = 0
    else:
        cp = load_count_points(str(cp_path), aadf_path)
        cand = join_traffic(cand, cp, radius_m=args.radius)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cand.to_file(out_path, driver="GeoJSON")
    print(f"\nSaved: {out_path} ({len(cand)} candidates)")


if __name__ == "__main__":
    main()

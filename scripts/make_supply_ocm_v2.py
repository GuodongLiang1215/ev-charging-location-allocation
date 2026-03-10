#!/usr/bin/env python3
"""
make_supply_ocm_v2.py — Enhanced OCM charger data for Cardiff EV Planner
=========================================================================
Fetches FULL charger data from OpenChargeMap API including:
  - Connector types (Type 2, CCS, CHAdeMO, etc.)
  - Power levels per connection (kW)
  - AC/DC current type
  - Operator name (not just ID)
  - Usage type (Public, Restricted, Private, etc.)
  - Status description (Operational, Planned, etc.)
  - Number of sockets/connectors
  - Date last verified
  - Charging cost information

Key changes from v1:
  1. compact=false, verbose=false → returns nested Connections[] array
  2. Flattens Connections into per-site summary fields
  3. Resolves OperatorInfo, StatusType, UsageType to human names
  4. Adds power classification (Slow/Fast/Rapid/Ultra-Rapid)
  5. Saves both raw JSON and enriched GeoJSON

Usage:
  python make_supply_ocm_v2.py                    # default: Cardiff, 15km
  python make_supply_ocm_v2.py --radius 20        # wider radius
  python make_supply_ocm_v2.py --output data/processed/supply_v2.geojson

Requires: OCM_API_KEY in .env or environment variable
"""

import os
import json
import argparse
from pathlib import Path
from collections import Counter

import requests
from dotenv import load_dotenv
import geopandas as gpd
from shapely.geometry import Point


BASE_URL = "https://api.openchargemap.io/v3"

# --- OCM Reference Data (IDs → human labels) ---
# Source: https://openchargemap.org/develop/api#/

STATUS_TYPES = {
    0:  "Unknown",
    10: "Currently Available",
    20: "Planned",
    30: "Under Construction",
    50: "Operational",
    75: "Partly Operational",
    100: "Not Operational",
    150: "Removed/Decommissioned",
    200: "Temporarily Unavailable",
    210: "Removed (Duplicate)",
}

USAGE_TYPES = {
    0:  "Unknown",
    1:  "Public",
    2:  "Private - Restricted",
    3:  "Privately Owned - Notice Required",
    4:  "Public - Membership Required",
    5:  "Public - Pay At Location",
    6:  "Private - Staff & Visitors",
    7:  "Public - Notice Required",
}

CONNECTION_TYPES = {
    0:   "Unknown",
    1:   "Type 1 (J1772)",
    2:   "CHAdeMO",
    25:  "Type 2 (Mennekes)",
    27:  "Tesla Supercharger",
    28:  "Type 2 (Socket Only)",
    30:  "Tesla (Roadster)",
    32:  "IEC 60309 (Single Phase)",
    33:  "CCS (Type 2 / CCS2)",
    34:  "IEC 60309 (3-Phase)",
    36:  "Type I (CCS1 / SAE)",
    38:  "IEC 62196-2 Type 2 (Tethered)",
    1036: "Type 2 (Tethered Connector)",
}

CURRENT_TYPES = {
    0:  "Unknown",
    10: "AC (Single Phase)",
    20: "AC (Three Phase)",
    30: "DC",
}

CHARGER_LEVELS = {
    1: "Level 1 (Slow, <5kW)",
    2: "Level 2 (Standard, 5-22kW)",
    3: "Level 3 (Rapid, >22kW)",
}

# Known OCM operator IDs → names for Cardiff area
# (The API returns OperatorInfo when compact=false, but this serves as fallback)
OPERATOR_NAMES = {
    3:    "Pod Point",
    5:    "Charge Your Car",
    15:   "Ecotricity",
    23:   "BP Pulse (was Chargemaster / POLAR)",
    32:   "MFG EV Power / ESB Energy",
    45:   "Tesla",
    69:   "Ionity",
    100:  "Smart Charge",
    150:  "Osprey",
    203:  "Connected Kerb",
    268:  "GeniePoint",
    388:  "Fastned",
    3296: "mer (uk) (formerly Stor)",
    3341: "Believ",
    3509: "ubitricity",
    3614: "GRIDSERVE",
    3615: "Dragon Charging (was Swarco)",
}


def classify_power(kw):
    """Classify charger speed tier by power output."""
    if kw is None or kw <= 0:
        return "Unknown"
    if kw < 5:
        return "Slow (<5kW)"
    if kw <= 7:
        return "Fast (5-7kW)"
    if kw <= 22:
        return "Fast (7-22kW)"
    if kw <= 50:
        return "Rapid (22-50kW)"
    if kw <= 100:
        return "Ultra-Rapid (50-100kW)"
    return "Ultra-Rapid (>100kW)"


def fetch_ocm_full(api_key, lat=51.4816, lon=-3.1791, radius_km=15, max_results=1000):
    """Fetch full (non-compact) POI data from OCM API."""
    url = f"{BASE_URL}/poi/"
    params = {
        "output": "json",
        "countrycode": "GB",
        "latitude": lat,
        "longitude": lon,
        "distance": radius_km,
        "distanceunit": "km",
        "maxresults": max_results,
        "compact": "false",      # ← KEY CHANGE: get full nested data
        "verbose": "false",
        "client": "cardiff-fyp-v2",
    }
    headers = {
        "X-API-Key": api_key,
        "User-Agent": "cardiff-fyp/0.2",
    }
    r = requests.get(url, params=params, headers=headers, timeout=90)
    r.raise_for_status()
    return r.json()


def flatten_connections(connections):
    """
    Flatten the Connections[] array into summary fields.
    Returns a dict with:
      - connector_types: list of type names
      - connector_types_str: comma-separated
      - max_power_kw: highest power across all connectors
      - total_sockets: sum of Quantity across connections
      - power_levels: list of kW values
      - current_types: set of AC/DC
      - has_ccs, has_chademo, has_type2, has_type1: boolean flags
      - speed_tier: classification of max power
    """
    if not connections:
        return {
            "connector_types_str": "",
            "max_power_kw": None,
            "total_sockets": None,
            "current_types_str": "",
            "has_ccs": False,
            "has_chademo": False,
            "has_type2": False,
            "has_type1": False,
            "speed_tier": "Unknown",
        }

    types = []
    powers = []
    currents = set()
    total_qty = 0
    has_ccs = has_chademo = has_type2 = has_type1 = False

    for conn in connections:
        # Connection type
        ct = conn.get("ConnectionType") or {}
        ct_id = ct.get("ID") or conn.get("ConnectionTypeID", 0)
        ct_name = ct.get("Title") or CONNECTION_TYPES.get(ct_id, f"Type-{ct_id}")
        types.append(ct_name)

        # Connector flags
        if ct_id in (33, 36):
            has_ccs = True
        elif ct_id == 2:
            has_chademo = True
        elif ct_id in (25, 28, 38, 1036):
            has_type2 = True
        elif ct_id == 1:
            has_type1 = True

        # Power
        kw = conn.get("PowerKW")
        if kw:
            powers.append(float(kw))

        # Current type
        cur = conn.get("CurrentType") or {}
        cur_id = cur.get("ID") or conn.get("CurrentTypeID", 0)
        cur_name = cur.get("Title") or CURRENT_TYPES.get(cur_id, "")
        if cur_name:
            currents.add(cur_name)

        # Quantity (sockets)
        qty = conn.get("Quantity") or 1
        total_qty += int(qty)

    max_kw = max(powers) if powers else None

    return {
        "connector_types_str": ", ".join(sorted(set(types))),
        "max_power_kw": max_kw,
        "total_sockets": total_qty if total_qty > 0 else None,
        "current_types_str": ", ".join(sorted(currents)),
        "has_ccs": has_ccs,
        "has_chademo": has_chademo,
        "has_type2": has_type2,
        "has_type1": has_type1,
        "speed_tier": classify_power(max_kw),
    }


def poi_to_row(poi):
    """Convert a single OCM POI (full format) to a flat dict."""
    addr = poi.get("AddressInfo") or {}
    lat = addr.get("Latitude")
    lon = addr.get("Longitude")
    if lat is None or lon is None:
        return None

    # Operator
    op = poi.get("OperatorInfo") or {}
    op_id = op.get("ID") or poi.get("OperatorID")
    op_name = op.get("Title") or OPERATOR_NAMES.get(op_id, f"Operator-{op_id}")

    # Status
    st = poi.get("StatusType") or {}
    st_id = st.get("ID") or poi.get("StatusTypeID", 0)
    st_name = st.get("Title") or STATUS_TYPES.get(int(st_id) if st_id else 0, "Unknown")
    is_operational = st_id in (0, 10, 50, 75, None)

    # Usage type
    ut = poi.get("UsageType") or {}
    ut_id = ut.get("ID") or poi.get("UsageTypeID", 0)
    ut_name = ut.get("Title") or USAGE_TYPES.get(ut_id, "Unknown")
    is_public = ut_id in (0, 1, 4, 5, 7, None)

    # Connections
    conn_info = flatten_connections(poi.get("Connections") or [])

    # Dates
    date_verified = poi.get("DateLastVerified") or ""
    date_updated = poi.get("DateLastStatusUpdate") or ""
    date_created = poi.get("DateCreated") or ""

    # Socket count: prefer our computed total, fall back to NumberOfPoints
    num_points = poi.get("NumberOfPoints")
    sockets = conn_info["total_sockets"] or num_points or None

    row = {
        "ocm_id":             poi.get("ID"),
        "name":               addr.get("Title", ""),
        "address":            addr.get("AddressLine1", ""),
        "town":               addr.get("Town", ""),
        "postcode":           addr.get("Postcode", ""),

        # Operator
        "operator":           op_name,
        "operator_id":        op_id,

        # Status
        "status":             st_name,
        "status_id":          st_id,
        "is_operational":     is_operational,

        # Usage
        "usage_type":         ut_name,
        "usage_type_id":      ut_id,
        "is_public":          is_public,

        # Connectors (flattened)
        "sockets":            sockets,
        "connector_types":    conn_info["connector_types_str"],
        "max_power_kw":       conn_info["max_power_kw"],
        "current_types":      conn_info["current_types_str"],
        "speed_tier":         conn_info["speed_tier"],
        "has_ccs":            conn_info["has_ccs"],
        "has_chademo":        conn_info["has_chademo"],
        "has_type2":          conn_info["has_type2"],
        "has_type1":          conn_info["has_type1"],

        # Cost
        "usage_cost":         poi.get("UsageCost", ""),

        # Dates
        "date_verified":      date_verified[:10] if date_verified else "",
        "date_updated":       date_updated[:10] if date_updated else "",
        "date_created":       date_created[:10] if date_created else "",

        # Geometry
        "geometry":           Point(float(lon), float(lat)),
    }
    return row


def print_summary(gdf):
    """Print a comprehensive summary of the enriched dataset."""
    print(f"\n{'='*60}")
    print(f"  Cardiff EV Charger Supply — Enriched Summary")
    print(f"{'='*60}")
    print(f"  Total locations:    {len(gdf)}")
    print(f"  Total sockets:      {gdf['sockets'].sum():.0f}" if gdf["sockets"].notna().any() else "  Total sockets: N/A")
    print(f"  Operational:        {gdf['is_operational'].sum()}")
    print(f"  Public:             {gdf['is_public'].sum()}")

    print(f"\n  --- Operators (top 10) ---")
    for op, cnt in gdf["operator"].value_counts().head(10).items():
        print(f"    {op}: {cnt}")

    print(f"\n  --- Speed tiers ---")
    for tier, cnt in gdf["speed_tier"].value_counts().items():
        print(f"    {tier}: {cnt}")

    print(f"\n  --- Connector types ---")
    print(f"    CCS:      {gdf['has_ccs'].sum()}")
    print(f"    CHAdeMO:  {gdf['has_chademo'].sum()}")
    print(f"    Type 2:   {gdf['has_type2'].sum()}")
    print(f"    Type 1:   {gdf['has_type1'].sum()}")

    print(f"\n  --- Status ---")
    for st, cnt in gdf["status"].value_counts().items():
        print(f"    {st}: {cnt}")

    if gdf["max_power_kw"].notna().any():
        print(f"\n  --- Power (kW) ---")
        pw = gdf["max_power_kw"].dropna()
        print(f"    min={pw.min():.0f}, median={pw.median():.0f}, max={pw.max():.0f}, mean={pw.mean():.1f}")

    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Fetch enriched OCM charger data for Cardiff")
    parser.add_argument("--radius", type=int, default=15, help="Search radius in km (default: 15)")
    parser.add_argument("--output", type=str, default="data/processed/supply_chargers_ocm.geojson")
    parser.add_argument("--raw-output", type=str, default="data/raw/ocm/cardiff_poi_full.json")
    args = parser.parse_args()

    load_dotenv()
    api_key = os.getenv("OCM_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing OCM_API_KEY. Set it in a .env file or as an environment variable.\n"
            "Get a free key at: https://openchargemap.org/site/develop/api"
        )

    print(f"Fetching OCM data (radius={args.radius}km, compact=false)...")
    pois = fetch_ocm_full(api_key, radius_km=args.radius)
    print(f"  → {len(pois)} POIs returned")

    # Save raw JSON
    raw_path = Path(args.raw_output)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps(pois, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  → Raw JSON saved: {raw_path}")

    # Convert to GeoDataFrame
    rows = []
    for poi in pois:
        row = poi_to_row(poi)
        if row:
            rows.append(row)

    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")

    # Filter: only Cardiff area (some OCM results might be outside)
    cardiff_bbox = (-3.33, 51.41, -3.06, 51.57)
    gdf = gdf.cx[cardiff_bbox[0]:cardiff_bbox[2], cardiff_bbox[1]:cardiff_bbox[3]]

    # Print summary
    print_summary(gdf)

    # Save
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(out_path, driver="GeoJSON")
    print(f"Saved enriched GeoJSON: {out_path} ({len(gdf)} features)")

    # Also save a WGS84 version for the planner
    wgs_path = out_path.parent / out_path.name.replace(".geojson", "_wgs84.geojson")
    gdf.to_crs("EPSG:4326").to_file(wgs_path, driver="GeoJSON")
    print(f"Saved WGS84 version: {wgs_path}")


if __name__ == "__main__":
    main()

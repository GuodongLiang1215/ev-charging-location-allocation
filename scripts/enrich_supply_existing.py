#!/usr/bin/env python3
"""
enrich_supply_existing.py - Enrich existing supply_chargers_ocm.geojson
========================================================================
Adds operator names, status, speed tier, socket count to existing OCM data.
Auto-detects column names so it works with both compact and full OCM data.

Usage:
  python enrich_supply_existing.py --input data/processed/supply_chargers_ocm.geojson --output data/processed/supply_chargers_ocm_enriched.geojson
"""

import argparse
import re
from pathlib import Path

import geopandas as gpd
import pandas as pd
import numpy as np


OPERATOR_NAMES = {
    3:"Pod Point",5:"Charge Your Car",7:"Nissan/BMW Dealers",15:"Ecotricity",
    19:"National Trust / Workplace",23:"BP Pulse",24:"InstaVolt",
    32:"MFG EV Power / ESB Energy",38:"Lidl (Customer)",45:"Tesla",
    69:"Ionity",100:"Smart Charge",136:"Drax / Opus Energy",
    150:"Osprey",198:"NewMotion / Shell Recharge",202:"Industrial / Private",
    203:"Connected Kerb",268:"GeniePoint",388:"Fastned",
    3296:"mer (UK)",3341:"Believ",3356:"Welsh Water (Workplace)",
    3430:"Applegreen Electric",3473:"Spire Healthcare",3496:"Local Authority",
    3509:"ubitricity",3534:"Tesla (Destination)",3562:"EVC Ltd",
    3614:"GRIDSERVE",3615:"Dragon Charging",3747:"MFG Ultra Rapid",
}

STATUS_TYPES = {
    0:"Unknown",10:"Currently Available",20:"Planned",30:"Under Construction",
    50:"Operational",75:"Partly Operational",100:"Not Operational",
    150:"Removed/Decommissioned",200:"Temporarily Unavailable",210:"Removed (Duplicate)",
}

OPERATOR_TYPICAL_SPEED = {
    "ubitricity":"Slow (5-7kW)","Pod Point":"Fast (7-22kW)","Connected Kerb":"Slow (5-7kW)",
    "BP Pulse":"Mixed (7-50kW)","Dragon Charging":"Fast (7-22kW)","Believ":"Fast (7-22kW)",
    "MFG EV Power / ESB Energy":"Mixed (7-50kW)","Osprey":"Rapid (50-150kW)",
    "GRIDSERVE":"Rapid (50-350kW)","Tesla":"Ultra-Rapid (120-250kW)","Tesla (Destination)":"Fast (7-22kW)",
    "Ionity":"Ultra-Rapid (150-350kW)","Fastned":"Ultra-Rapid (150-300kW)",
    "mer (UK)":"Fast (7-22kW)","GeniePoint":"Rapid (50kW)",
    "InstaVolt":"Rapid (50-125kW)","Applegreen Electric":"Rapid (50-150kW)",
    "MFG Ultra Rapid":"Ultra-Rapid (150-350kW)","Nissan/BMW Dealers":"Fast (7-50kW)",
    "NewMotion / Shell Recharge":"Fast (7-22kW)","EVC Ltd":"Fast (7-22kW)",
    "Local Authority":"Fast (7-22kW)",
}


def _find_col(df, candidates, default=None):
    """Find the first matching column (case-insensitive)."""
    df_lower = {c.lower().strip(): c for c in df.columns}
    for c in candidates:
        if c.lower().strip() in df_lower:
            return df_lower[c.lower().strip()]
    return default


def _safe_int(x, fallback=0):
    try:
        if pd.isna(x):
            return fallback
        return int(float(x))
    except (ValueError, TypeError):
        return fallback


def _safe_get(row, col, fallback=""):
    if col is None:
        return fallback
    val = row.get(col)
    if pd.isna(val):
        return fallback
    return val


def guess_speed_from_cost(cost_str):
    if not cost_str or not isinstance(cost_str, str):
        return None
    cost = cost_str.lower()
    if "dc" in cost or "rapid" in cost or "ultra" in cost:
        return "Rapid/DC"
    m = re.search(r'([\d.]+)\s*/?\s*kwh', cost)
    if m:
        price = float(m.group(1))
        if price >= 0.70:
            return "Rapid (high per kWh)"
        if price >= 0.40:
            return "Fast"
    if "free" in cost or "inclusive" in cost:
        return "Workplace/Free"
    return None


def enrich(gdf):
    gdf = gdf.copy()
    print(f"  Input columns: {list(gdf.columns)}")

    # Auto-detect columns
    operator_id_col = _find_col(gdf, ["operator_id", "OperatorID", "operatorid"])
    status_id_col = _find_col(gdf, ["status_type_id", "StatusTypeID", "statustypeid", "status_id", "StatusID"])
    sockets_col = _find_col(gdf, ["num_points", "NumberOfPoints", "sockets", "SocketCount", "num_sockets"])
    name_col = _find_col(gdf, ["title", "name", "Title", "Name"])
    cost_col = _find_col(gdf, ["usage_cost", "UsageCost", "cost"])
    addr_col = _find_col(gdf, ["address", "Address", "AddressLine1"])
    town_col = _find_col(gdf, ["town", "Town"])
    post_col = _find_col(gdf, ["postcode", "Postcode"])

    print(f"  Found: operator_id={operator_id_col}, status_id={status_id_col}, sockets={sockets_col}, name={name_col}")

    # 1. Operator name
    if operator_id_col:
        gdf["operator"] = gdf[operator_id_col].apply(
            lambda x: OPERATOR_NAMES.get(_safe_int(x, -1), f"Operator-{_safe_int(x)}") if pd.notna(x) else "Unknown"
        )
    else:
        gdf["operator"] = "Unknown"

    # 2. Status + operational flag
    if status_id_col:
        gdf["status"] = gdf[status_id_col].apply(
            lambda x: STATUS_TYPES.get(_safe_int(x, 0), "Unknown") if pd.notna(x) else "Unknown"
        )
        gdf["is_operational"] = gdf[status_id_col].apply(
            lambda x: _safe_int(x, 0) in (0, 10, 50, 75) if pd.notna(x) else True
        )
    else:
        gdf["status"] = "Unknown"
        gdf["is_operational"] = True

    # 3. Public flag
    gdf["is_public"] = True

    # 4. Sockets
    if sockets_col:
        gdf["sockets"] = gdf[sockets_col].apply(lambda x: max(1, _safe_int(x, 1)))
    else:
        gdf["sockets"] = 1

    # 5. Name
    if name_col and "name" not in gdf.columns:
        gdf["name"] = gdf[name_col]
    elif "name" not in gdf.columns:
        gdf["name"] = ""

    # 6. Speed tier from operator + cost text
    speeds = []
    for _, row in gdf.iterrows():
        op_name = row.get("operator", "")
        op_speed = OPERATOR_TYPICAL_SPEED.get(op_name, None)
        cost_val = _safe_get(row, cost_col, "")
        cost_speed = guess_speed_from_cost(cost_val)
        speeds.append(cost_speed or op_speed or "Unknown")
    gdf["speed_tier"] = speeds

    # 7. Ensure standard columns exist
    if "usage_cost" not in gdf.columns:
        gdf["usage_cost"] = gdf[cost_col] if cost_col else ""
    if "postcode" not in gdf.columns:
        gdf["postcode"] = gdf[post_col] if post_col else ""
    if "address" not in gdf.columns:
        gdf["address"] = gdf[addr_col] if addr_col else ""
    if "town" not in gdf.columns:
        gdf["town"] = gdf[town_col] if town_col else ""

    return gdf


def print_summary(gdf):
    print(f"\n{'='*55}")
    print(f"  Cardiff EV Supply - Enriched Summary")
    print(f"{'='*55}")
    print(f"  Locations: {len(gdf)}, Sockets: {gdf['sockets'].sum()}, Operational: {gdf['is_operational'].sum()}")

    print(f"\n  Operators (top 10):")
    for op, cnt in gdf["operator"].value_counts().head(10).items():
        print(f"    {op}: {cnt}")

    print(f"\n  Speed tiers:")
    for sp, cnt in gdf["speed_tier"].value_counts().items():
        print(f"    {sp}: {cnt}")

    print(f"\n  Status:")
    for st, cnt in gdf["status"].value_counts().items():
        print(f"    {st}: {cnt}")
    print(f"{'='*55}\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/processed/supply_chargers_ocm.geojson")
    parser.add_argument("--output", default="data/processed/supply_chargers_ocm_enriched.geojson")
    args = parser.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        raise FileNotFoundError(f"Input not found: {in_path}")

    gdf = gpd.read_file(in_path)
    print(f"Loaded: {in_path} ({len(gdf)} features)")

    gdf = enrich(gdf)
    print_summary(gdf)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(out_path, driver="GeoJSON")
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
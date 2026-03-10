#!/usr/bin/env python3
"""
enrich_supply_existing.py — Enrich existing supply_chargers_ocm.geojson
========================================================================
This script takes the EXISTING supply GeoJSON (which only has basic fields
from compact=true OCM fetch) and enriches it with:
  1. Operator name lookup (from operator_id)
  2. Status description lookup (from status_type_id)
  3. Estimated speed tier (from usage_cost text parsing)
  4. Public/operational flags
  5. Socket count cleanup

Run this if you can't re-fetch from OCM API right away.
For full enrichment (connector types, power levels), use make_supply_ocm_v2.py instead.

Usage:
  python enrich_supply_existing.py
  python enrich_supply_existing.py --input data/processed/supply_chargers_ocm.geojson --output data/processed/supply_enriched.geojson
"""

import argparse
import json
import re
from pathlib import Path

import geopandas as gpd
import pandas as pd
import numpy as np


# ─── OCM Reference Lookups ───

OPERATOR_NAMES = {
    3:    "Pod Point",
    5:    "Charge Your Car",
    15:   "Ecotricity",
    23:   "BP Pulse",
    32:   "MFG EV Power / ESB Energy",
    45:   "Tesla",
    69:   "Ionity",
    100:  "Smart Charge",
    150:  "Osprey",
    203:  "Connected Kerb",
    268:  "GeniePoint",
    388:  "Fastned",
    3296: "mer (UK)",
    3341: "Believ",
    3509: "ubitricity",
    3614: "GRIDSERVE",
    3615: "Dragon Charging",
}

STATUS_TYPES = {
    0:   "Unknown",
    10:  "Currently Available",
    20:  "Planned",
    30:  "Under Construction",
    50:  "Operational",
    75:  "Partly Operational",
    100: "Not Operational",
    150: "Removed/Decommissioned",
    200: "Temporarily Unavailable",
    210: "Removed (Duplicate)",
}

# Operators known to provide certain charger types
# (heuristic when we don't have connection data)
OPERATOR_TYPICAL_SPEED = {
    "ubitricity":        "Slow (5-7kW lamp post)",
    "Pod Point":         "Fast (7-22kW)",
    "Connected Kerb":    "Slow (5-7kW)",
    "BP Pulse":          "Mixed (7-50kW)",
    "Dragon Charging":   "Fast (7-22kW)",
    "Believ":            "Fast (7-22kW)",
    "MFG EV Power / ESB Energy": "Mixed (7-50kW)",
    "Osprey":            "Rapid (50-150kW)",
    "GRIDSERVE":         "Rapid (50-350kW)",
    "Tesla":             "Ultra-Rapid (120-250kW)",
    "Ionity":            "Ultra-Rapid (150-350kW)",
    "Fastned":           "Ultra-Rapid (150-300kW)",
    "mer (UK)":          "Fast (7-22kW)",
    "GeniePoint":        "Rapid (50kW)",
}


def guess_speed_from_cost(cost_str):
    """Try to infer speed tier from usage_cost text."""
    if not cost_str or not isinstance(cost_str, str):
        return None
    cost = cost_str.lower()
    if "dc" in cost or "rapid" in cost or "ultra" in cost:
        return "Rapid/DC"
    if "kwh" in cost:
        # Extract price per kWh
        match = re.search(r'[£$]?([\d.]+)\s*/?\s*kwh', cost)
        if match:
            price = float(match.group(1))
            # Higher £/kWh often indicates rapid
            if price >= 0.70:
                return "Rapid (high £/kWh)"
            elif price >= 0.40:
                return "Fast"
    if "free" in cost or "inclusive" in cost:
        return "Workplace/Free"
    return None


def enrich(gdf):
    """Add derived fields to supply GeoDataFrame."""
    gdf = gdf.copy()

    # 1. Operator name
    gdf["operator"] = gdf["operator_id"].apply(
        lambda x: OPERATOR_NAMES.get(int(x), f"Operator-{int(x)}") if pd.notna(x) else "Unknown"
    )

    # 2. Status description + operational flag
    gdf["status"] = gdf["status_type_id"].apply(
        lambda x: STATUS_TYPES.get(int(x), "Unknown") if pd.notna(x) else "Unknown"
    )
    gdf["is_operational"] = gdf["status_type_id"].apply(
        lambda x: int(x) in (0, 10, 50, 75) if pd.notna(x) else True  # assume operational if missing
    )

    # 3. Public flag (heuristic: most OCM Cardiff entries are public)
    gdf["is_public"] = True  # default; can be refined with UsageTypeID from v2

    # 4. Rename and clean num_points → sockets
    gdf["sockets"] = gdf["num_points"].fillna(1).astype(int)

    # 5. Estimated speed tier from operator + cost text
    speeds = []
    for _, row in gdf.iterrows():
        # Try operator heuristic first
        op_speed = OPERATOR_TYPICAL_SPEED.get(row.get("operator"), None)
        # Then try cost text
        cost_speed = guess_speed_from_cost(row.get("usage_cost"))
        speeds.append(cost_speed or op_speed or "Unknown")
    gdf["speed_tier"] = speeds

    # 6. Rename for consistency with planner_map_v6.html FIELD mappings
    gdf = gdf.rename(columns={
        "title": "name",
    })

    # 7. Reorder columns for clarity
    col_order = [
        "ocm_id", "name", "address", "town", "postcode",
        "operator", "operator_id",
        "status", "status_type_id", "is_operational",
        "is_public",
        "sockets", "speed_tier",
        "usage_cost",
        "data_provider_id",
        "geometry",
    ]
    # Keep any extra columns not in our list
    extras = [c for c in gdf.columns if c not in col_order and c != "num_points"]
    gdf = gdf[[c for c in col_order if c in gdf.columns] + extras]

    return gdf


def print_summary(gdf):
    print(f"\n{'='*55}")
    print(f"  Cardiff EV Charger Supply — Enriched Summary")
    print(f"{'='*55}")
    print(f"  Total locations:  {len(gdf)}")
    print(f"  Total sockets:    {gdf['sockets'].sum()}")
    print(f"  Operational:      {gdf['is_operational'].sum()}")

    print(f"\n  Operators (top 10):")
    for op, cnt in gdf["operator"].value_counts().head(10).items():
        print(f"    {op}: {cnt}")

    print(f"\n  Status:")
    for st, cnt in gdf["status"].value_counts().items():
        print(f"    {st}: {cnt}")

    print(f"\n  Speed tiers (estimated):")
    for sp, cnt in gdf["speed_tier"].value_counts().items():
        print(f"    {sp}: {cnt}")

    print(f"{'='*55}\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/processed/supply_chargers_ocm.geojson")
    parser.add_argument("--output", default="data/processed/supply_chargers_ocm_enriched.geojson")
    args = parser.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)

    if not in_path.exists():
        raise FileNotFoundError(f"Input not found: {in_path}")

    gdf = gpd.read_file(in_path)
    print(f"Loaded: {in_path} ({len(gdf)} features)")

    gdf = enrich(gdf)
    print_summary(gdf)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(out_path, driver="GeoJSON")
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()

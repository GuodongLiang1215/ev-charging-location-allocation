import os
import json
from pathlib import Path

import requests
from dotenv import load_dotenv

import geopandas as gpd
from shapely.geometry import Point


BASE_URL = "https://api.openchargemap.io/v3"
OUT_RAW = Path("data/raw/ocm")
OUT_PROCESSED = Path("data/processed")

OUT_RAW.mkdir(parents=True, exist_ok=True)
OUT_PROCESSED.mkdir(parents=True, exist_ok=True)


def fetch_ocm_poi(api_key: str) -> list:
    url = f"{BASE_URL}/poi/"

    # Easiest method: center point + radius
    # Cardiff city centre approx: (51.4816, -3.1791)
    params = {
        "output": "json",
        "countrycode": "GB",
        "latitude": 51.4816,
        "longitude": -3.1791,
        "distance": 20,           # 20 km radius (adjust)
        "distanceunit": "km",
        "maxresults": 500,        # adjust if you need more
        "compact": "true",
        "verbose": "false",
        "client": "cardiff-fyp"
        # Optional:
        # "opendata": "true"  # only open-licensed subset (may reduce coverage)
    }

    headers = {
        "X-API-Key": api_key,  # case sensitive per OCM spec
        "User-Agent": "cardiff-fyp/0.1"
    }

    r = requests.get(url, params=params, headers=headers, timeout=60)
    r.raise_for_status()
    return r.json()


def to_geojson(pois: list) -> gpd.GeoDataFrame:
    rows = []
    for poi in pois:
        addr = poi.get("AddressInfo") or {}
        lat = addr.get("Latitude")
        lon = addr.get("Longitude")
        if lat is None or lon is None:
            continue

        rows.append({
            "ocm_id": poi.get("ID"),
            "title": addr.get("Title"),
            "address": addr.get("AddressLine1"),
            "town": addr.get("Town"),
            "postcode": addr.get("Postcode"),
            "num_points": poi.get("NumberOfPoints"),
            "usage_cost": poi.get("UsageCost"),
            "status_type_id": poi.get("StatusTypeID"),
            "operator_id": poi.get("OperatorID"),
            "data_provider_id": poi.get("DataProviderID"),
            "geometry": Point(float(lon), float(lat))
        })

    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    return gdf


def main():
    load_dotenv()
    api_key = os.getenv("OCM_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OCM_API_KEY. Put it in a .env file or environment variable.")

    pois = fetch_ocm_poi(api_key)

    # Save raw JSON for provenance
    raw_path = OUT_RAW / "cardiff_poi.json"
    raw_path.write_text(json.dumps(pois, ensure_ascii=False), encoding="utf-8")

    # Convert to GeoJSON
    gdf = to_geojson(pois)

    out_path = OUT_PROCESSED / "supply_chargers_ocm.geojson"
    gdf.to_file(out_path, driver="GeoJSON")
    print(f"Saved {len(gdf)} chargepoints to: {out_path}")


if __name__ == "__main__":
    main()

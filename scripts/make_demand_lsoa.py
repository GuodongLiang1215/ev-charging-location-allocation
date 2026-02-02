from pathlib import Path
import geopandas as gpd

LSOA_FILE = Path("data/raw/boundaries/lsoa_2021/lsoa_2021_bsc.geojson")

OUT_POLY = Path("data/processed/demand_lsoa_cardiff.geojson")
OUT_PTS  = Path("data/processed/demand_points_cardiff.geojson")

# Cardiff rough bbox (WGS84 lon/lat). Fast for Week 2.
# (min_lon, min_lat, max_lon, max_lat)
CARDIFF_BBOX = (-3.30, 51.40, -3.00, 51.60)

def main():
    gdf = gpd.read_file(LSOA_FILE)

    # Your GeoJSON uses CRS84 (lon/lat). Ensure WGS84 order.
    gdf = gdf.to_crs("EPSG:4326")

    minx, miny, maxx, maxy = CARDIFF_BBOX
    cardiff = gdf.cx[minx:maxx, miny:maxy].copy()

    # Keep key fields only (clean + lighter)
    keep = [c for c in ["LSOA21CD", "LSOA21NM", "LSOA21NMW", "RUC21CD", "RUC21NM", "geometry"] if c in cardiff.columns]
    cardiff = cardiff[keep].copy()

    # Project to UK CRS for distances
    cardiff_27700 = cardiff.to_crs("EPSG:27700")

    # Demand points: centroid (Week 2). Later you can replace with population-weighted centroids.
    pts = cardiff_27700[["LSOA21CD", "LSOA21NM", "geometry"]].copy()
    pts["geometry"] = pts.geometry.centroid

    OUT_POLY.parent.mkdir(parents=True, exist_ok=True)
    cardiff_27700.to_file(OUT_POLY, driver="GeoJSON")
    pts.to_file(OUT_PTS, driver="GeoJSON")

    print(f"Saved Cardiff LSOA polygons: {OUT_POLY}  (n={len(cardiff_27700)})")
    print(f"Saved Cardiff demand points: {OUT_PTS}   (n={len(pts)})")

if __name__ == "__main__":
    main()

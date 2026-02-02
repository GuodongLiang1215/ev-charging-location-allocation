import osmnx as ox
import geopandas as gpd
from pathlib import Path

OUT = Path("data/processed/candidates_osm_parking.geojson")

def main():
    place = "Cardiff, Wales, United Kingdom"
    tags = {"amenity": "parking"}

    gdf = ox.features_from_place(place, tags=tags)

    # Keep points; many car parks are polygons. Convert polygons to centroids as candidate points.
    pts = gdf[gdf.geometry.type.isin(["Point", "MultiPoint"])].copy()
    polys = gdf[gdf.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()
    if len(polys) > 0:
        polys["geometry"] = polys.geometry.centroid
        pts = gpd.GeoDataFrame(pd.concat([pts, polys], ignore_index=True), crs=gdf.crs)

    pts = pts.to_crs(27700)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    pts.to_file(OUT, driver="GeoJSON")
    print(f"Saved candidates: {OUT} (n={len(pts)})")

if __name__ == "__main__":
    import pandas as pd
    main()

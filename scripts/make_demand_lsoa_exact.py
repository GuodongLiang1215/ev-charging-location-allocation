from pathlib import Path
import geopandas as gpd

LSOA_FILE = Path("data/raw/boundaries/lsoa_2021/lsoa_2021_bsc.geojson")
LAD_FILE  = Path("data/raw/boundaries/lad_2024/lad_2024_bsc.geojson")

OUT_POLY = Path("data/processed/demand_lsoa_cardiff_exact.geojson")
OUT_PTS  = Path("data/processed/demand_points_cardiff_exact.geojson")

def main():
    lsoa = gpd.read_file(LSOA_FILE).to_crs("EPSG:27700")
    lad  = gpd.read_file(LAD_FILE).to_crs("EPSG:27700")

    # Find Cardiff LAD polygon
    # LAD datasets usually have a name field like LAD24NM / LAD23NM / etc.
    name_cols = [c for c in lad.columns if c.lower().endswith("nm") or "name" in c.lower()]
    if not name_cols:
        raise ValueError(f"Cannot find a name column in LAD file. Columns: {list(lad.columns)}")

    name_col = name_cols[0]  # pick first likely name column
    cardiff = lad[lad[name_col].astype(str).str.lower().eq("cardiff")].copy()

    if len(cardiff) == 0:
        # print unique names to help debugging
        sample = lad[name_col].dropna().astype(str).unique()[:20]
        raise ValueError(f"Cannot find 'Cardiff' in column '{name_col}'. Sample values: {sample}")

    cardiff_geom = cardiff.geometry.unary_union

    # Clip LSOA to Cardiff boundary (use within/intersects)
    # within is strict; intersects is safer for boundary-touching polygons
    lsoa_cardiff = lsoa[lsoa.intersects(cardiff_geom)].copy()

    # Keep useful columns
    keep = [c for c in ["LSOA21CD", "LSOA21NM", "LSOA21NMW", "RUC21CD", "RUC21NM", "geometry"] if c in lsoa_cardiff.columns]
    lsoa_cardiff = lsoa_cardiff[keep].copy()

    pts = lsoa_cardiff[["LSOA21CD", "LSOA21NM", "geometry"]].copy()
    pts["geometry"] = pts.geometry.centroid

    OUT_POLY.parent.mkdir(parents=True, exist_ok=True)
    lsoa_cardiff.to_file(OUT_POLY, driver="GeoJSON")
    pts.to_file(OUT_PTS, driver="GeoJSON")

    print(f"Saved exact Cardiff LSOA polygons: {OUT_POLY} (n={len(lsoa_cardiff)})")
    print(f"Saved exact Cardiff demand points: {OUT_PTS} (n={len(pts)})")

if __name__ == "__main__":
    main()

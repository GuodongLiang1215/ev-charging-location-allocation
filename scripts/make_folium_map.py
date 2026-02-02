from pathlib import Path
import geopandas as gpd
import folium
from folium.plugins import MarkerCluster

LSOA  = Path("data/processed/demand_lsoa_cardiff_exact.geojson")
DEMAND= Path("data/processed/demand_points_cardiff_exact.geojson")
SUPPLY= Path("data/processed/supply_chargers_ocm.geojson")
NEW   = Path("data/processed/new_sites_p10.geojson")

OUT   = Path("outputs/figures/cardiff_solution_map_p10.html")

def add_geojson_layer(m, gdf, name, style_fn=None):
    folium.GeoJson(
        gdf.to_json(),
        name=name,
        style_function=style_fn
    ).add_to(m)

def main():
    lsoa = gpd.read_file(LSOA).to_crs(4326)
    demand = gpd.read_file(DEMAND).to_crs(4326)
    supply = gpd.read_file(SUPPLY).to_crs(4326)
    new_sites = gpd.read_file(NEW).to_crs(4326)

    # map center: Cardiff boundary centroid
    center = lsoa.geometry.unary_union.centroid
    m = folium.Map(location=[center.y, center.x], zoom_start=12, tiles="CartoDB positron")

    # LSOA boundary layer (light)
    add_geojson_layer(
        m, lsoa, "LSOA (Cardiff)",
        style_fn=lambda x: {"fillOpacity": 0.05, "weight": 1}
    )

    # Demand points cluster (optional)
    demand_cluster = MarkerCluster(name="Demand points (LSOA centroids)").add_to(m)
    for _, row in demand.iterrows():
        folium.CircleMarker(
            location=[row.geometry.y, row.geometry.x],
            radius=3,
            weight=1,
            fill=True,
            fill_opacity=0.6,
            popup=str(row.get("LSOA21CD", "demand"))
        ).add_to(demand_cluster)

    # Existing supply points cluster
    supply_cluster = MarkerCluster(name="Existing chargers (OCM)").add_to(m)
    for _, row in supply.iterrows():
        folium.CircleMarker(
            location=[row.geometry.y, row.geometry.x],
            radius=4,
            weight=1,
            fill=True,
            fill_opacity=0.7,
            popup="Existing charger"
        ).add_to(supply_cluster)

    # New sites: standout markers
    for _, row in new_sites.iterrows():
        sid = row.get("site_id", "")
        folium.Marker(
            location=[row.geometry.y, row.geometry.x],
            popup=f"NEW site (P=10) id={sid}",
            icon=folium.Icon(icon="flash", prefix="fa")
        ).add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(OUT))
    print("Saved folium map:", OUT)

if __name__ == "__main__":
    main()

# scripts/make_folium_map.py
from pathlib import Path
import geopandas as gpd
import folium
from folium.plugins import Fullscreen, MeasureControl

# -----------------------
# Inputs / Outputs
# -----------------------
LSOA   = Path("data/processed/demand_lsoa_cardiff_exact.geojson")      # polygons
DEMAND = Path("data/processed/demand_points_cardiff_exact.geojson")    # points (centroids)
SUPPLY = Path("data/processed/supply_chargers_ocm.geojson")            # existing chargers
NEW    = Path("data/processed/new_sites_p10.geojson")                  # new sites (selected)

OUT    = Path("outputs/figures/cardiff_solution_map_p10.html")


# -----------------------
# Helpers
# -----------------------
def guess_distance_col(gdf):
    """
    Try to find a column representing distance-to-nearest (meters) for choropleth.
    If none found, we will still draw boundaries (outline only).
    """
    candidates = [
        "nearest_m", "dist_nearest_m", "distance_m", "d_nearest_m",
        "baseline_nearest_m", "nearest_existing_m", "min_dist_m"
    ]
    cols = set(gdf.columns)
    for c in candidates:
        if c in cols:
            return c
    return None


def color_for_distance_m(d):
    """
    0–500: green (good)
    500–1000: yellow
    1000–2000: orange
    >2000: red (underserved)
    """
    try:
        d = float(d)
    except Exception:
        return "#CCCCCC"  # unknown/NA

    if d < 0:
        return "#CCCCCC"
    if d <= 500:
        return "#2ECC71"
    if d <= 1000:
        return "#F1C40F"
    if d <= 2000:
        return "#E67E22"
    return "#E74C3C"


def add_legend(m):
    legend_html = """
    <div style="
        position: fixed;
        bottom: 25px;
        left: 25px;
        z-index: 9999;
        background: white;
        border: 2px solid #666;
        border-radius: 6px;
        padding: 10px 12px;
        width: 310px;
        font-size: 13px;
        ">
      <b>Legend</b><br>
      <div style="margin-top:6px;"><b>LSOA fill</b>: distance to nearest charger (m)</div>
      <div style="margin-top:6px;">
        <span style="display:inline-block;width:12px;height:12px;background:#2ECC71;border:1px solid #555;"></span>
        &nbsp;0–500m (good)<br>
        <span style="display:inline-block;width:12px;height:12px;background:#F1C40F;border:1px solid #555;"></span>
        &nbsp;500–1000m<br>
        <span style="display:inline-block;width:12px;height:12px;background:#E67E22;border:1px solid #555;"></span>
        &nbsp;1000–2000m<br>
        <span style="display:inline-block;width:12px;height:12px;background:#E74C3C;border:1px solid #555;"></span>
        &nbsp;>2000m (underserved)<br>
      </div>
      <div style="margin-top:8px;"><b>Points</b></div>
      <div>
        <span style="color:#1f77b4;"><b>Blue circles</b></span>: existing chargers (OCM)<br>
        <span style="color:#d62728;"><b>Red stars</b></span>: new sites selected (P=10)<br>
        <span style="color:#7f7f7f;"><b>Grey dots</b></span>: demand centroids
      </div>
      <div style="margin-top:8px;color:#444;">
        If you don't see points at first, zoom into Cardiff (markers are small).
      </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))


def main():
    # ---- Load data ----
    lsoa = gpd.read_file(LSOA).to_crs(4326)
    demand = gpd.read_file(DEMAND).to_crs(4326)
    supply = gpd.read_file(SUPPLY).to_crs(4326)
    new_sites = gpd.read_file(NEW).to_crs(4326)

    print(f"Loaded: LSOA {len(lsoa)} Demand {len(demand)} Supply {len(supply)} New {len(new_sites)}")

    # ---- Build map (no JS injection, stable rendering) ----
    # Use bounds to set view reliably
    minx, miny, maxx, maxy = lsoa.total_bounds  # (W, S, E, N)
    center_lat = (miny + maxy) / 2
    center_lon = (minx + maxx) / 2

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=12,
        tiles=None,
        control_scale=True
    )

    folium.TileLayer("CartoDB positron", name="Light", show=True).add_to(m)
    folium.TileLayer("OpenStreetMap", name="OSM", show=False).add_to(m)

    # ---- LSOA polygons ----
    dist_col = guess_distance_col(lsoa)

    lsoa_fg = folium.FeatureGroup(name="LSOA polygons (Cardiff)", show=True)

    if dist_col:
        # Put distance into a standard field so tooltip/style is consistent
        lsoa2 = lsoa.copy()
        lsoa2["dist_m"] = lsoa2[dist_col]

        def style_fn(feat):
            d = feat["properties"].get("dist_m", -1)
            return {
                "fillColor": color_for_distance_m(d),
                "color": "#555555",
                "weight": 0.7,
                "fillOpacity": 0.45,
            }

        gj = folium.GeoJson(
            lsoa2.to_json(),
            name="LSOA fill (distance bands)",
            style_function=style_fn,
            highlight_function=lambda x: {"weight": 2.0, "fillOpacity": 0.60},
            tooltip=folium.GeoJsonTooltip(
                fields=[c for c in ["LSOA21CD", "LSOA21NM", "dist_m"] if c in lsoa2.columns],
                aliases=["LSOA code", "LSOA name", "Nearest (m)"],
                localize=True,
                sticky=False
            ),
        )
        gj.add_to(lsoa_fg)
    else:
        # fallback: outline only
        gj = folium.GeoJson(
            lsoa.to_json(),
            name="LSOA outline",
            style_function=lambda x: {"fillOpacity": 0.05, "color": "#555555", "weight": 1.0},
        )
        gj.add_to(lsoa_fg)

    lsoa_fg.add_to(m)

    # ---- Demand points (grey) ----
    demand_fg = folium.FeatureGroup(name="Demand centroids (LSOA)", show=True)
    for _, row in demand.iterrows():
        folium.CircleMarker(
            location=[row.geometry.y, row.geometry.x],
            radius=2,
            color="#7f7f7f",
            weight=1,
            fill=True,
            fill_opacity=0.8,
            popup=str(row.get("LSOA21CD", "demand"))
        ).add_to(demand_fg)
    demand_fg.add_to(m)

    # ---- Existing chargers (blue) ----
    supply_fg = folium.FeatureGroup(name="Existing chargers (OCM)", show=True)
    for _, row in supply.iterrows():
        folium.CircleMarker(
            location=[row.geometry.y, row.geometry.x],
            radius=4,
            color="#1f77b4",
            weight=1,
            fill=True,
            fill_opacity=0.8,
            popup="Existing charger (OCM)"
        ).add_to(supply_fg)
    supply_fg.add_to(m)

    # ---- New sites (red star) ----
    new_fg = folium.FeatureGroup(name="New sites selected (P=10)", show=True)
    for _, row in new_sites.iterrows():
        sid = row.get("site_id", "")
        folium.Marker(
            location=[row.geometry.y, row.geometry.x],
            popup=f"NEW site (P=10) id={sid}",
            icon=folium.Icon(color="red", icon="star", prefix="fa")
        ).add_to(new_fg)
    new_fg.add_to(m)

    # ---- Controls ----
    Fullscreen(position="topleft").add_to(m)
    MeasureControl(position="topleft").add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    add_legend(m)

    # ---- Fit bounds to Cardiff LSOA ----
    m.fit_bounds([[miny, minx], [maxy, maxx]])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(OUT))
    print("Saved folium map:", OUT)


if __name__ == "__main__":
    main()

from pathlib import Path
import geopandas as gpd
import pandas as pd
import numpy as np

DEMAND_PTS = Path("data/processed/demand_points_cardiff_exact.geojson")
SUPPLY     = Path("data/processed/supply_chargers_ocm.geojson")
OUT        = Path("outputs/tables/baseline_metrics.csv")

THRESHOLD_M = 1000.0  # 1km coverage threshold

def main():
    d = gpd.read_file(DEMAND_PTS).to_crs("EPSG:27700")
    s = gpd.read_file(SUPPLY).to_crs("EPSG:27700")

    d_xy = np.vstack([d.geometry.x.values, d.geometry.y.values]).T
    s_xy = np.vstack([s.geometry.x.values, s.geometry.y.values]).T

    # nearest Euclidean distance (Week 2 baseline)
    dist = np.sqrt(((d_xy[:, None, :] - s_xy[None, :, :]) ** 2).sum(axis=2))
    nearest = dist.min(axis=1)

    d["nearest_m"] = nearest
    d["covered_1km"] = (d["nearest_m"] <= THRESHOLD_M).astype(int)

    metrics = {
        "n_demand_units": int(len(d)),
        "n_supply_points": int(len(s)),
        "mean_nearest_m": float(d["nearest_m"].mean()),
        "median_nearest_m": float(d["nearest_m"].median()),
        "coverage_1km": float(d["covered_1km"].mean()),
        "threshold_m": THRESHOLD_M
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([metrics]).to_csv(OUT, index=False)

    print("Baseline metrics saved:", OUT)
    print(metrics)

if __name__ == "__main__":
    main()

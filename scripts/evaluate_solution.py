import numpy as np
import pandas as pd
import geopandas as gpd
from pathlib import Path

DEMAND = Path("data/processed/demand_points_cardiff_exact.geojson")
SUPPLY = Path("data/processed/supply_chargers_ocm.geojson")
CAND   = Path("data/processed/candidates_osm_parking.geojson")
SOL    = Path("outputs/tables/solution_max_coverage.csv")
OUT    = Path("outputs/tables/metrics_after_solution.csv")

THRESHOLD_M = 1000.0

def main():
    d = gpd.read_file(DEMAND).to_crs(27700)
    s = gpd.read_file(SUPPLY).to_crs(27700)
    c = gpd.read_file(CAND).to_crs(27700)
    chosen = pd.read_csv(SOL)["chosen_candidate_id"].tolist()
    c_new = c.iloc[chosen].copy()

    # combine existing + new
    s_all = pd.concat([s[["geometry"]], c_new[["geometry"]]], ignore_index=True)
    d_xy = np.c_[d.geometry.x.values, d.geometry.y.values]
    s_xy = np.c_[s_all.geometry.x.values, s_all.geometry.y.values]

    dist = np.sqrt(((d_xy[:, None, :] - s_xy[None, :, :]) ** 2).sum(axis=2))
    nearest = dist.min(axis=1)

    metrics = {
        "n_demand_units": int(len(d)),
        "n_existing_supply": int(len(s)),
        "n_new_sites": int(len(chosen)),
        "mean_nearest_m": float(nearest.mean()),
        "median_nearest_m": float(np.median(nearest)),
        "coverage_1km": float((nearest <= THRESHOLD_M).mean()),
        "threshold_m": THRESHOLD_M
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([metrics]).to_csv(OUT, index=False)
    print("Saved:", OUT)
    print(metrics)

if __name__ == "__main__":
    main()

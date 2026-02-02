import numpy as np
import pandas as pd
import geopandas as gpd
from pathlib import Path

DEMAND = Path("data/processed/demand_points_cardiff_exact.geojson")
CAND   = Path("data/processed/candidates_osm_parking.geojson")
OUT    = Path("data/processed/cost_matrix_full.csv")

def main():
    d = gpd.read_file(DEMAND).to_crs(27700).reset_index(drop=True)
    c = gpd.read_file(CAND).to_crs(27700).reset_index(drop=True)

    d_xy = np.c_[d.geometry.x.values, d.geometry.y.values]  # (I,2)
    c_xy = np.c_[c.geometry.x.values, c.geometry.y.values]  # (J,2)

    # dist matrix (I,J)
    dist = np.sqrt(((d_xy[:, None, :] - c_xy[None, :, :]) ** 2).sum(axis=2))

    # build long table
    I, J = dist.shape
    df = pd.DataFrame({
        "i": np.repeat(np.arange(I), J),
        "j": np.tile(np.arange(J), I),
        "demand_id": np.repeat(d["LSOA21CD"].astype(str).values, J),
        "candidate_id": np.tile(np.arange(J), I),
        "cost_m": dist.reshape(-1).astype(float),
    })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"Saved full cost matrix: {OUT} rows={len(df)} (I={I}, J={J})")

if __name__ == "__main__":
    main()

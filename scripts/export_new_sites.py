from pathlib import Path
import geopandas as gpd
import pandas as pd

CAND = Path("data/processed/candidates_osm_parking.geojson")
SOL  = Path("outputs/tables/solution_max_coverage.csv")
OUT  = Path("data/processed/new_sites_p10.geojson")

def main():
    cand = gpd.read_file(CAND).to_crs(4326).reset_index(drop=True)
    chosen = pd.read_csv(SOL)["chosen_candidate_id"].astype(int).tolist()

    new_sites = cand.iloc[chosen].copy()
    new_sites["site_id"] = chosen

    OUT.parent.mkdir(parents=True, exist_ok=True)
    new_sites.to_file(OUT, driver="GeoJSON")
    print(f"Saved new sites: {OUT} (n={len(new_sites)})")

if __name__ == "__main__":
    main()

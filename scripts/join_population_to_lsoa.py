import pandas as pd
import geopandas as gpd
from pathlib import Path

# -----------------------
# Paths (match your repo)
# -----------------------
POP_XLSX = "data/raw/demand/ons_lsoa_population_mid2024.xlsx"

LSOA_GEOJSON = "docs/data/processed/demand_lsoa_cardiff_exact.geojson"
PTS_GEOJSON  = "docs/data/processed/demand_points_cardiff_exact.geojson"

OUT_LSOA = "docs/data/processed/demand_lsoa_cardiff_exact_pop.geojson"
OUT_PTS  = "docs/data/processed/demand_points_cardiff_exact_pop.geojson"

# -----------------------
# Config
# -----------------------
TARGET_YEAR = 2024  # you can switch to 2022/2023 if needed

YEAR_SHEET = {
    2022: "Mid-2022 LSOA 2021",
    2023: "Mid-2023 LSOA 2021",
    2024: "Mid-2024 LSOA 2021",
}

MEDIAN_AGE_SHEET = "Median age LSOA 2011-2024"
MEDIAN_AGE_COL_BY_YEAR = {
    2022: "Median age mid-2022",
    2023: "Median age mid-2023",
    2024: "Median age mid-2024",
}

# Set False if you only want population
INCLUDE_MEDIAN_AGE = True


def _norm(x) -> str:
    return str(x).strip().lower()


def find_header_row(xlsx_path: str, sheet_name: str, must_have: list[str], scan_rows: int = 80) -> int:
    """
    Find the row index (0-based) that contains all must_have strings in that row (case-insensitive).
    This is used because ONS sheets have a big title row before the real header row.
    """
    preview = pd.read_excel(xlsx_path, sheet_name=sheet_name, header=None, nrows=scan_rows)
    must = [_norm(s) for s in must_have]

    for i in range(len(preview)):
        row = preview.iloc[i].astype(str).map(_norm)
        ok = True
        for m in must:
            if not row.str.contains(m, na=False).any():
                ok = False
                break
        if ok:
            return i

    raise ValueError(
        f"Cannot find header row in sheet '{sheet_name}'. "
        f"Expected columns containing: {must_have}. "
        f"Open the sheet and confirm the header row."
    )


def read_ons_table(xlsx_path: str, sheet_name: str, must_have: list[str]) -> pd.DataFrame:
    """
    Read the ONS table from a sheet by auto-detecting the true header row.
    """
    hdr = find_header_row(xlsx_path, sheet_name, must_have=must_have)
    df = pd.read_excel(xlsx_path, sheet_name=sheet_name, header=hdr)

    # drop unnamed columns created by Excel formatting
    df = df.loc[:, ~df.columns.astype(str).str.match(r"^Unnamed")]

    return df


def load_population(xlsx_path: str, year: int) -> pd.DataFrame:
    """
    Return DataFrame with columns: LSOA21CD, population
    """
    sheet = YEAR_SHEET[year]
    df = read_ons_table(
        xlsx_path, sheet,
        must_have=["LSOA 2021 Code", "Total"]  # these definitely exist in your screenshot
    )

    # exact column names from your screenshot
    code_col = "LSOA 2021 Code"
    total_col = "Total"

    if code_col not in df.columns or total_col not in df.columns:
        raise ValueError(
            f"Sheet '{sheet}' does not contain expected columns '{code_col}' and '{total_col}'. "
            f"Detected columns: {list(df.columns)[:20]}"
        )

    pop = df[[code_col, total_col]].copy()
    pop.columns = ["LSOA21CD", "population"]

    pop["LSOA21CD"] = pop["LSOA21CD"].astype(str).str.strip()
    pop["population"] = pd.to_numeric(pop["population"], errors="coerce")

    pop = pop.dropna(subset=["population"])
    pop = pop.groupby("LSOA21CD", as_index=False)["population"].sum()

    print(f"[OK] Loaded population from '{sheet}': rows={len(pop)}")
    print(pop.head(3))
    return pop


def load_median_age(xlsx_path: str, year: int) -> pd.DataFrame:
    """
    Return DataFrame with columns: LSOA21CD, median_age
    """
    sheet = MEDIAN_AGE_SHEET
    age_col = MEDIAN_AGE_COL_BY_YEAR[year]

    df = read_ons_table(
        xlsx_path, sheet,
        must_have=["LSOA 2021 Code", "Median age"]  # your screenshot shows these
    )

    code_col = "LSOA 2021 Code"
    if code_col not in df.columns or age_col not in df.columns:
        raise ValueError(
            f"Sheet '{sheet}' does not contain expected columns '{code_col}' and '{age_col}'. "
            f"Detected columns: {list(df.columns)[:30]}"
        )

    med = df[[code_col, age_col]].copy()
    med.columns = ["LSOA21CD", "median_age"]
    med["LSOA21CD"] = med["LSOA21CD"].astype(str).str.strip()
    med["median_age"] = pd.to_numeric(med["median_age"], errors="coerce")
    med = med.dropna(subset=["median_age"])
    med = med.groupby("LSOA21CD", as_index=False)["median_age"].mean()

    print(f"[OK] Loaded median age from '{sheet}' ({age_col}): rows={len(med)}")
    print(med.head(3))
    return med


def attach_to_points(points_gdf: gpd.GeoDataFrame, lsoa_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Attach population/median_age to points.
    - If points already have LSOA21CD -> attribute join
    - Else -> spatial join within LSOA polygons
    """
    if "LSOA21CD" in points_gdf.columns:
        out = points_gdf.merge(lsoa_gdf[["LSOA21CD", "population"] + (["median_age"] if "median_age" in lsoa_gdf.columns else [])],
                               on="LSOA21CD", how="left")
        return out

    # spatial join requires same CRS
    if points_gdf.crs != lsoa_gdf.crs:
        # If points CRS is missing, assume it's same as LSOA; else reproject
        if points_gdf.crs is None and lsoa_gdf.crs is not None:
            points_gdf = points_gdf.set_crs(lsoa_gdf.crs, allow_override=True)
        elif points_gdf.crs is not None and lsoa_gdf.crs is not None:
            points_gdf = points_gdf.to_crs(lsoa_gdf.crs)

    join_cols = ["LSOA21CD", "population"] + (["median_age"] if "median_age" in lsoa_gdf.columns else [])
    out = gpd.sjoin(points_gdf, lsoa_gdf[join_cols + ["geometry"]], how="left", predicate="within")
    if "index_right" in out.columns:
        out = out.drop(columns=["index_right"])
    return out


def main():
    # 1) load LSOA geojson
    lsoa = gpd.read_file(LSOA_GEOJSON)
    if "LSOA21CD" not in lsoa.columns:
        raise ValueError("Your LSOA GeoJSON must contain 'LSOA21CD' (your file does).")

    # 2) load population + optional median age
    pop = load_population(POP_XLSX, TARGET_YEAR)

    if INCLUDE_MEDIAN_AGE:
        med = load_median_age(POP_XLSX, TARGET_YEAR)
        pop = pop.merge(med, on="LSOA21CD", how="left")

    # 3) merge into polygons
    lsoa2 = lsoa.merge(pop, on="LSOA21CD", how="left")
    missing_pop = int(lsoa2["population"].isna().sum())
    print(f"[JOIN] LSOA polygons={len(lsoa2)} | missing population={missing_pop}")

    lsoa2["population"] = lsoa2["population"].fillna(0)
    if "median_age" in lsoa2.columns:
        # keep NaN if missing, or fill with 0 if you prefer:
        # lsoa2["median_age"] = lsoa2["median_age"].fillna(0)
        pass

    # 4) write LSOA output
    Path(OUT_LSOA).parent.mkdir(parents=True, exist_ok=True)
    lsoa2.to_file(OUT_LSOA, driver="GeoJSON")
    print("[SAVED]", OUT_LSOA)

    # 5) attach to demand points
    pts = gpd.read_file(PTS_GEOJSON)
    pts2 = attach_to_points(pts, lsoa2)

    if "population" in pts2.columns:
        pts2["population"] = pts2["population"].fillna(0)

    Path(OUT_PTS).parent.mkdir(parents=True, exist_ok=True)
    pts2.to_file(OUT_PTS, driver="GeoJSON")
    print("[SAVED]", OUT_PTS)

    print("\nDONE ✅")
    print("Next step: update planner_map.html to use:")
    print("  LSOA: demand_lsoa_cardiff_exact_pop.geojson")
    print("  Points: demand_points_cardiff_exact_pop.geojson")


if __name__ == "__main__":
    main()

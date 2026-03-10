@echo off
REM ================================================================
REM  Cardiff EV Charger — Full Pipeline Runner
REM  Run from project root: D:\Projects\ev-charging-location-allocation
REM ================================================================

echo ============================================================
echo  Cardiff EV Charger Pipeline
echo  Running from: %CD%
echo ============================================================
echo.

REM ── Step 1: Supply data (skip if already enriched recently) ──
echo [Step 1] Enriching supply charger data...
if exist "data\processed\supply_chargers_ocm.geojson" (
    python scripts\enrich_supply_existing.py --input data\processed\supply_chargers_ocm.geojson --output data\processed\supply_chargers_ocm_enriched.geojson
    if errorlevel 1 (echo   ERROR in Step 1 & pause & exit /b 1)
    echo   OK: supply_chargers_ocm_enriched.geojson created
) else (
    echo   SKIP: supply_chargers_ocm.geojson not found. Run make_supply_ocm_v2.py first.
)
echo.

REM ── Step 2: Demand boundaries (population-weighted centroids) ──
echo [Step 2] Generating demand boundaries...
python scripts\make_demand_lsoa_exact_v2.py
if errorlevel 1 (echo   ERROR in Step 2 & pause & exit /b 1)
echo   OK: demand_lsoa_cardiff_exact_v2.geojson created
echo.

REM ── Step 3: Attach population ──
echo [Step 3] Attaching population to LSOAs...
REM NOTE: This script has hardcoded paths. Make sure lines 10-13 in
REM join_population_to_lsoa.py point to the v2 files, OR use the
REM original files if you haven't changed them.
python scripts\join_population_to_lsoa.py
if errorlevel 1 (echo   ERROR in Step 3 & pause & exit /b 1)
echo   OK: population attached
echo.

REM ── Step 4: Enrich with WIMD + Census ──
echo [Step 4] Enriching demand with WIMD + Census...
python scripts\join_wimd_census_to_demand.py ^
    --demand data\processed\demand_lsoa_cardiff_exact_pop.geojson ^
    --wimd data\raw\wimd\wimd.geojson ^
    --ts044 data\raw\census\census2021-ts044-lsoa.csv ^
    --ts045 data\raw\census\ts045-lsoa.csv ^
    --ts054 data\raw\census\2021-ts054-lsoa.csv ^
    --out data\processed\demand_lsoa_cardiff_exact_pop_enriched.geojson
if errorlevel 1 (echo   ERROR in Step 4 & pause & exit /b 1)
echo   OK: demand enriched with WIMD + Census
echo.

REM ── Step 5: Reproject to WGS84 ──
echo [Step 5] Reprojecting to WGS84...
python scripts\reproject_geojson_to_wgs84.py ^
    --infile data\processed\demand_lsoa_cardiff_exact_pop_enriched.geojson ^
    --outfile data\processed\demand_lsoa_cardiff_exact_pop_wgs84_enriched.geojson
if errorlevel 1 (echo   ERROR in Step 5a & pause & exit /b 1)

python scripts\reproject_geojson_to_wgs84.py ^
    --infile data\processed\demand_points_cardiff_exact_pop.geojson ^
    --outfile data\processed\demand_points_cardiff_exact_pop_wgs84.geojson
if errorlevel 1 (echo   ERROR in Step 5b & pause & exit /b 1)
echo   OK: WGS84 files created
echo.

REM ── Step 6: Candidates (skip if already done) ──
echo [Step 6] Fetching diversified candidates from OSM...
if not exist "data\processed\candidates_osm_v2.geojson" (
    python scripts\make_candidates_osm_v2.py
    if errorlevel 1 (echo   ERROR in Step 6 & pause & exit /b 1)
    echo   OK: candidates_osm_v2.geojson created
) else (
    echo   SKIP: candidates_osm_v2.geojson already exists
)
echo.

REM ── Step 7: Join traffic data ──
echo [Step 7] Joining DfT traffic data to candidates...
if exist "cardiff_count_points_2024.csv" (
    python scripts\join_traffic_to_candidates.py ^
        --count-points cardiff_count_points_2024.csv ^
        --aadf cardiff_aadf_2024.csv ^
        --candidates data\processed\candidates_osm_v2.geojson ^
        --output data\processed\candidates_with_traffic.geojson
    if errorlevel 1 (echo   ERROR in Step 7 & pause & exit /b 1)
    echo   OK: traffic data joined
) else (
    echo   SKIP: cardiff_count_points_2024.csv not found.
    echo   Run dft_traffic_fetch.py first, or proceed without traffic data.
)
echo.

REM ── Step 8: Solver ──
echo [Step 8] Running weighted MCLP solver (P=20)...
python scripts\solve_max_coverage_weighted.py --p 20 --threshold 1000 --capacity-mode
if errorlevel 1 (echo   ERROR in Step 8 — solver may need OR-Tools: pip install ortools & pause & exit /b 1)
echo   OK: solution saved
echo.

REM ── Step 9: Copy to docs/ for planner ──
echo [Step 9] Copying final files to docs\data\processed\ ...
if not exist "docs\data\processed" mkdir "docs\data\processed"

copy /Y "data\processed\supply_chargers_ocm_enriched.geojson" "docs\data\processed\supply_chargers_ocm_enriched.geojson" >nul
copy /Y "data\processed\demand_lsoa_cardiff_exact_pop_wgs84_enriched.geojson" "docs\data\processed\demand_lsoa_cardiff_exact_pop_wgs84_enriched.geojson" >nul
copy /Y "data\processed\demand_points_cardiff_exact_pop_wgs84.geojson" "docs\data\processed\demand_points_cardiff_exact_pop_wgs84.geojson" >nul

echo   OK: files copied to docs\data\processed\
echo.

echo ============================================================
echo  PIPELINE COMPLETE
echo ============================================================
echo.
echo  Files in docs\data\processed\ (planner reads these):
dir /b docs\data\processed\*.geojson 2>nul
echo.
echo  Open docs\planner_map_v6.html in your browser (via Live Server).
echo ============================================================
pause

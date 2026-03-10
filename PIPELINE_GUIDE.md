# Cardiff EV Charger Project — Pipeline Guide
## Your Project Structure Explained

```
ev-charging-location-allocation/
├── scripts/                    ← All Python scripts live here
├── data/
│   ├── raw/                    ← Source data (never modified)
│   │   ├── boundaries/
│   │   │   ├── lsoa_2021/lsoa_2021_bsc.geojson
│   │   │   └── lad_2024/lad_2024_bsc.geojson
│   │   ├── census/
│   │   │   ├── census2021-ts044-lsoa.csv
│   │   │   ├── ts045-lsoa.csv
│   │   │   └── 2021-ts054-lsoa.csv
│   │   ├── demand/
│   │   │   └── ons_lsoa_population_mid2024.xlsx
│   │   ├── wimd/
│   │   │   └── wimd.geojson
│   │   └── ocm/
│   │       ├── cardiff_poi.json
│   │       └── cardiff_poi_full.json
│   └── processed/              ← Scripts output here (intermediate)
│       ├── supply_chargers_ocm.geojson
│       ├── supply_chargers_ocm_enriched.geojson
│       ├── candidates_osm_parking.geojson
│       ├── candidates_osm_v2.geojson
│       ├── demand_lsoa_cardiff_exact.geojson
│       ├── demand_lsoa_cardiff_exact_pop.geojson
│       ├── demand_points_cardiff_exact.geojson
│       ├── demand_points_cardiff_exact_pop.geojson
│       └── ... (more intermediate files)
│
├── docs/                       ← WEB-SERVED folder (planner reads from here)
│   ├── data/processed/         ← COPY final files here for the planner
│   │   ├── supply_chargers_ocm_enriched.geojson  ← planner reads this
│   │   ├── demand_lsoa_cardiff_exact_pop_wgs84_enriched.geojson
│   │   └── demand_points_cardiff_exact_pop_wgs84.geojson
│   ├── planner_map_v6.html     ← Your planner
│   ├── driver_map.html
│   └── index.html
│
├── outputs/
│   ├── figures/
│   └── tables/
│       ├── solution_max_coverage.csv
│       └── metrics_weighted.csv
│
├── cardiff_aadf_2024.csv       ← DfT traffic (in project root)
├── cardiff_count_points_2024.csv
├── .env                        ← API keys
└── README.md
```

**KEY RULE:** Scripts save to `data/processed/`. The planner reads from `docs/data/processed/`. After running scripts, you must COPY the final WGS84 files to `docs/data/processed/`.

---

## Complete Pipeline — Run These In Order

Open your terminal in the project root: `D:\Projects\ev-charging-location-allocation`

### Step 1: Fetch supply data (existing chargers)
```
python scripts/make_supply_ocm_v2.py --radius 15
```
- **Reads:** OCM API (needs OCM_API_KEY in .env)
- **Creates:** `data/processed/supply_chargers_ocm.geojson` + `data/raw/ocm/cardiff_poi_full.json`
- **Then enrich it:**
```
python scripts/enrich_supply_existing.py --input data/processed/supply_chargers_ocm.geojson --output data/processed/supply_chargers_ocm_enriched.geojson
```

### Step 2: Generate demand boundaries (LSOA polygons + centroids)
```
python scripts/make_demand_lsoa_exact_v2.py
```
- **Reads:** `data/raw/boundaries/lsoa_2021/lsoa_2021_bsc.geojson` + `data/raw/boundaries/lad_2024/lad_2024_bsc.geojson`
- **Creates:** `data/processed/demand_lsoa_cardiff_exact_v2.geojson` + `data/processed/demand_points_cardiff_exact_v2.geojson`

### Step 3: Attach population to LSOA polygons
**IMPORTANT:** First edit `join_population_to_lsoa.py` lines 10-13 to point to the correct files:
```python
LSOA_GEOJSON = "data/processed/demand_lsoa_cardiff_exact_v2.geojson"
PTS_GEOJSON  = "data/processed/demand_points_cardiff_exact_v2.geojson"
OUT_LSOA = "data/processed/demand_lsoa_cardiff_exact_pop.geojson"
OUT_PTS  = "data/processed/demand_points_cardiff_exact_pop.geojson"
```
Then run:
```
python scripts/join_population_to_lsoa.py
```
- **Reads:** `data/raw/demand/ons_lsoa_population_mid2024.xlsx`
- **Creates:** `data/processed/demand_lsoa_cardiff_exact_pop.geojson` + `data/processed/demand_points_cardiff_exact_pop.geojson`

### Step 4: Enrich demand with WIMD + Census data
```
python scripts/join_wimd_census_to_demand.py --demand data/processed/demand_lsoa_cardiff_exact_pop.geojson --wimd data/raw/wimd/wimd.geojson --ts044 data/raw/census/census2021-ts044-lsoa.csv --ts045 data/raw/census/ts045-lsoa.csv --ts054 data/raw/census/2021-ts054-lsoa.csv --out data/processed/demand_lsoa_cardiff_exact_pop_enriched.geojson
```
- **Creates:** `data/processed/demand_lsoa_cardiff_exact_pop_enriched.geojson`

### Step 5: Reproject to WGS84 (for web planner)
```
python scripts/reproject_geojson_to_wgs84.py --infile data/processed/demand_lsoa_cardiff_exact_pop_enriched.geojson --outfile data/processed/demand_lsoa_cardiff_exact_pop_wgs84_enriched.geojson
```
```
python scripts/reproject_geojson_to_wgs84.py --infile data/processed/demand_points_cardiff_exact_pop.geojson --outfile data/processed/demand_points_cardiff_exact_pop_wgs84.geojson
```

### Step 6: Fetch candidates (diversified)
```
python scripts/make_candidates_osm_v2.py
```
- **Creates:** `data/processed/candidates_osm_v2.geojson`

### Step 7: Join traffic data to candidates
```
python scripts/join_traffic_to_candidates.py --count-points cardiff_count_points_2024.csv --aadf cardiff_aadf_2024.csv --candidates data/processed/candidates_osm_v2.geojson --output data/processed/candidates_with_traffic.geojson
```

### Step 8: Run weighted MCLP solver
```
python scripts/solve_max_coverage_weighted.py --p 20 --threshold 1000 --capacity-mode
```
- **Creates:** `outputs/tables/solution_max_coverage_weighted.csv` + `outputs/tables/metrics_weighted.csv`

### Step 9: COPY final files to docs/ for planner

This is the critical step that connects scripts → planner:

```
copy data\processed\supply_chargers_ocm_enriched.geojson docs\data\processed\supply_chargers_ocm_enriched.geojson

copy data\processed\demand_lsoa_cardiff_exact_pop_wgs84_enriched.geojson docs\data\processed\demand_lsoa_cardiff_exact_pop_wgs84_enriched.geojson

copy data\processed\demand_points_cardiff_exact_pop_wgs84.geojson docs\data\processed\demand_points_cardiff_exact_pop_wgs84.geojson
```

### Step 10: Open the planner
Open `docs/planner_map_v6.html` in your browser (via Live Server in VS Code, or any local server).

---

## Quick Reference: Which file does what?

| Script | Input | Output |
|--------|-------|--------|
| `make_supply_ocm_v2.py` | OCM API | `supply_chargers_ocm.geojson` |
| `enrich_supply_existing.py` | `supply_chargers_ocm.geojson` | `supply_chargers_ocm_enriched.geojson` |
| `make_demand_lsoa_exact_v2.py` | LSOA + LAD boundaries | `demand_lsoa_cardiff_exact_v2.geojson` + points |
| `join_population_to_lsoa.py` | LSOA + ONS population | `demand_*_pop.geojson` |
| `join_wimd_census_to_demand.py` | demand + WIMD + Census CSVs | `demand_*_enriched.geojson` |
| `reproject_geojson_to_wgs84.py` | any EPSG:27700 file | WGS84 version |
| `make_candidates_osm_v2.py` | OSM API | `candidates_osm_v2.geojson` |
| `join_traffic_to_candidates.py` | candidates + DfT CSVs | `candidates_with_traffic.geojson` |
| `solve_max_coverage_weighted.py` | demand + supply + candidates | solution CSV |

## If a script fails: common fixes

**"SystemExit: 2" / "arguments are required"**
→ The script uses argparse. You need to pass `--flag value` arguments (see Step 4 above).

**"FileNotFoundError"**
→ Check the file path. Scripts assume you run from project root `D:\Projects\ev-charging-location-allocation\`.

**"ModuleNotFoundError: No module named 'geopandas'"**
→ Run: `pip install geopandas pandas numpy shapely`

**Files don't appear in planner**
→ You forgot Step 9 (copy to `docs/data/processed/`). The planner only reads from `docs/`.

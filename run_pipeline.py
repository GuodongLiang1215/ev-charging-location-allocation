"""
run_pipeline.py - Cardiff EV Charger Full Pipeline
====================================================
Run from project root:
    cd D:\Projects\ev-charging-location-allocation
    conda activate evgis
    python run_pipeline.py
"""

import subprocess
import sys
import shutil
from pathlib import Path

ROOT = Path(".")

STEPS = [
    {
        "name": "Step 1: Enrich supply charger data",
        "cmd": [
            sys.executable, "scripts/enrich_supply_existing.py",
            "--input", "data/processed/supply_chargers_ocm.geojson",
            "--output", "data/processed/supply_chargers_ocm_enriched.geojson",
        ],
        "check": "data/processed/supply_chargers_ocm.geojson",
    },
    {
        "name": "Step 2: Generate demand boundaries (weighted centroids)",
        "cmd": [
            sys.executable, "scripts/make_demand_lsoa_exact_v2.py",
        ],
        "check": "data/raw/boundaries/lsoa_2021/lsoa_2021_bsc.geojson",
    },
    {
        "name": "Step 3: Attach population to LSOAs",
        "cmd": [
            sys.executable, "scripts/join_population_to_lsoa.py",
        ],
        "check": "data/raw/demand/ons_lsoa_population_mid2024.xlsx",
    },
    {
        "name": "Step 4: Enrich demand with WIMD + Census",
        "cmd": [
            sys.executable, "scripts/join_wimd_census_to_demand.py",
            "--demand", "data/processed/demand_lsoa_cardiff_exact_pop.geojson",
            "--wimd", "data/raw/wimd/wimd.geojson",
            "--ts044", "data/raw/census/census2021-ts044-lsoa.csv",
            "--ts045", "data/raw/census/ts045-lsoa.csv",
            "--ts054", "data/raw/census/2021-ts054-lsoa.csv",
            "--out", "data/processed/demand_lsoa_cardiff_exact_pop_enriched.geojson",
        ],
        "check": "data/raw/wimd/wimd.geojson",
    },
    {
        "name": "Step 5a: Reproject LSOA polygons to WGS84",
        "cmd": [
            sys.executable, "scripts/reproject_geojson_to_wgs84.py",
            "--infile", "data/processed/demand_lsoa_cardiff_exact_pop_enriched.geojson",
            "--outfile", "data/processed/demand_lsoa_cardiff_exact_pop_wgs84_enriched.geojson",
        ],
    },
    {
        "name": "Step 5b: Reproject demand points to WGS84",
        "cmd": [
            sys.executable, "scripts/reproject_geojson_to_wgs84.py",
            "--infile", "data/processed/demand_points_cardiff_exact_pop.geojson",
            "--outfile", "data/processed/demand_points_cardiff_exact_pop_wgs84.geojson",
        ],
    },
    {
        "name": "Step 6: Fetch diversified candidates from OSM",
        "cmd": [
            sys.executable, "scripts/make_candidates_osm_v2.py",
        ],
        "skip_if_exists": "data/processed/candidates_osm_v2.geojson",
    },
    {
        "name": "Step 6b: Reproject candidates to WGS84",
        "cmd": [
            sys.executable, "scripts/reproject_geojson_to_wgs84.py",
            "--infile", "data/processed/candidates_osm_v2.geojson",
            "--outfile", "data/processed/candidates_osm_v2_wgs84.geojson",
        ],
    },
    {
        "name": "Step 7: Join DfT traffic data to candidates",
        "cmd": [
            sys.executable, "scripts/join_traffic_to_candidates.py",
            "--count-points", "cardiff_count_points_2024.csv",
            "--aadf", "cardiff_aadf_2024.csv",
            "--candidates", "data/processed/candidates_osm_v2.geojson",
            "--output", "data/processed/candidates_with_traffic.geojson",
        ],
        "check": "cardiff_count_points_2024.csv",
        "optional": True,
    },
    {
        "name": "Step 8: Run weighted MCLP solver (P=20)",
        "cmd": [
            sys.executable, "scripts/solve_max_coverage_weighted.py",
            "--p", "20", "--threshold", "1000", "--capacity-mode",
        ],
        "optional": True,
    },
]

COPY_TO_DOCS = [
    ("data/processed/supply_chargers_ocm_enriched.geojson",
     "docs/data/processed/supply_chargers_ocm_enriched.geojson"),
    ("data/processed/demand_lsoa_cardiff_exact_pop_wgs84_enriched.geojson",
     "docs/data/processed/demand_lsoa_cardiff_exact_pop_wgs84_enriched.geojson"),
    ("data/processed/demand_points_cardiff_exact_pop_wgs84.geojson",
     "docs/data/processed/demand_points_cardiff_exact_pop_wgs84.geojson"),
    ("data/processed/candidates_osm_v2_wgs84.geojson",
     "docs/data/processed/candidates_osm_v2.geojson"),
]


def run_step(step):
    name = step["name"]
    cmd = step["cmd"]

    # Skip if output already exists
    skip = step.get("skip_if_exists")
    if skip and Path(skip).exists():
        print(f"  SKIP (file exists: {skip})")
        return True

    # Check required input
    check = step.get("check")
    if check and not Path(check).exists():
        msg = f"  MISSING INPUT: {check}"
        if step.get("optional"):
            print(msg + " -- skipping (optional step)")
            return True
        else:
            print(msg)
            return False

    # Run
    result = subprocess.run(cmd, cwd=str(ROOT.resolve()))
    if result.returncode != 0:
        if step.get("optional"):
            print(f"  WARNING: failed but optional, continuing...")
            return True
        return False
    return True


def copy_to_docs():
    docs_dir = ROOT / "docs" / "data" / "processed"
    docs_dir.mkdir(parents=True, exist_ok=True)

    for src, dst in COPY_TO_DOCS:
        src_path = ROOT / src
        dst_path = ROOT / dst
        if src_path.exists():
            shutil.copy2(src_path, dst_path)
            print(f"  Copied: {src} -> {dst}")
        else:
            print(f"  WARNING: {src} not found, skipping copy")


def main():
    print("=" * 55)
    print("  Cardiff EV Charger - Full Pipeline")
    print("  Working dir:", ROOT.resolve())
    print("=" * 55)
    print()

    failed = []
    for i, step in enumerate(STEPS):
        print(f"[{step['name']}]")
        ok = run_step(step)
        if ok:
            print(f"  OK")
        else:
            print(f"  FAILED")
            failed.append(step["name"])
            # Stop on non-optional failure
            if not step.get("optional"):
                print(f"\nStopped at: {step['name']}")
                print("Fix the error above, then run this script again.")
                print("Completed steps will skip if output files exist.")
                sys.exit(1)
        print()

    # Step 9: Copy to docs
    print("[Step 9: Copy final files to docs/data/processed/]")
    copy_to_docs()
    print()

    print("=" * 55)
    if failed:
        print(f"  DONE (with {len(failed)} optional warnings)")
        for f in failed:
            print(f"    - {f}")
    else:
        print("  PIPELINE COMPLETE - ALL STEPS OK")
    print()
    print("  Open docs/planner_map_v6.html in your browser.")
    print("=" * 55)


if __name__ == "__main__":
    main()
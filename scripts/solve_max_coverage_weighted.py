#!/usr/bin/env python3
"""
solve_max_coverage_weighted.py — Capacity-weighted MCLP
=========================================================
v1 used binary coverage: is there ANY charger within threshold?
v2 incorporates charger capacity weights:
  - A 50kW rapid hub "covers" more demand than a 5kW lamp post
  - Existing supply capacity reduces the marginal benefit of new sites nearby
  - Population-weighted demand (not just count of demand points)

Formulation:
  max  Σ_i  w_i * y_i                     (population-weighted coverage)
  s.t. y_i ≤ Σ_{j∈N(i)} x_j              (coverage constraint)
       Σ_j x_j = P                         (exactly P new sites)
       x_j, y_i ∈ {0,1}

  where w_i = population weight of demand point i
        N(i) = {j : dist(i,j) ≤ threshold AND existing_coverage(i) < full}

  Optional: subtract existing capacity from coverage requirement,
  so demand points already well-served by existing chargers have
  lower marginal value for new placement.

Usage:
  python solve_max_coverage_weighted.py
  python solve_max_coverage_weighted.py --p 20 --threshold 1500
  python solve_max_coverage_weighted.py --capacity-mode  # use capacity weighting
"""

import argparse
import numpy as np
import pandas as pd
import geopandas as gpd
from pathlib import Path
from ortools.linear_solver import pywraplp

DEMAND  = Path("data/processed/demand_points_cardiff_exact_pop_wgs84.geojson")
SUPPLY  = Path("data/processed/supply_chargers_ocm_enriched.geojson")
CAND    = Path("data/processed/candidates_osm_v2.geojson")  # or candidates_osm_parking.geojson
OUT     = Path("outputs/tables/solution_max_coverage_weighted.csv")
OUT_MET = Path("outputs/tables/metrics_weighted.csv")

# Fallback paths
DEMAND_FALLBACK = Path("data/processed/demand_points_cardiff_exact.geojson")
CAND_FALLBACK   = Path("data/processed/candidates_osm_parking.geojson")
SUPPLY_FALLBACK = Path("data/processed/supply_chargers_ocm.geojson")


def estimate_capacity_kw(row):
    """Estimate charger capacity from enriched fields."""
    # Try direct max_power_kw
    pkw = row.get("max_power_kw")
    if pd.notna(pkw) and float(pkw) > 0:
        sockets = max(1, int(row.get("sockets", 1) or 1))
        return float(pkw) * sockets

    # Estimate from speed_tier
    tier = str(row.get("speed_tier", "")).lower()
    sockets = max(1, int(row.get("sockets", 1) or 1))

    if "ultra" in tier:
        return 150 * sockets
    elif "rapid" in tier:
        return 50 * sockets
    elif "fast" in tier:
        return 11 * sockets
    elif "slow" in tier:
        return 5 * sockets
    elif "mixed" in tier:
        return 22 * sockets
    else:
        return 7 * sockets  # default


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--p", type=int, default=20, help="Number of new sites")
    parser.add_argument("--threshold", type=float, default=1000.0, help="Coverage threshold (m)")
    parser.add_argument("--capacity-mode", action="store_true",
                        help="Weight demand by existing capacity deficit")
    args = parser.parse_args()

    P = args.p
    THRESHOLD_M = args.threshold

    # Load data with fallbacks
    d_path = DEMAND if DEMAND.exists() else DEMAND_FALLBACK
    c_path = CAND if CAND.exists() else CAND_FALLBACK
    s_path = SUPPLY if SUPPLY.exists() else SUPPLY_FALLBACK

    d = gpd.read_file(d_path).to_crs(27700).reset_index(drop=True)
    s = gpd.read_file(s_path).to_crs(27700).reset_index(drop=True)
    c = gpd.read_file(c_path).to_crs(27700).reset_index(drop=True)

    print(f"Demand points: {len(d)}")
    print(f"Existing supply: {len(s)}")
    print(f"Candidates: {len(c)}")
    print(f"P={P}, threshold={THRESHOLD_M}m, capacity_mode={args.capacity_mode}")

    # Demand weights (population-based)
    if "population" in d.columns:
        d["_weight"] = pd.to_numeric(d["population"], errors="coerce").fillna(1).clip(lower=1)
    else:
        d["_weight"] = 1.0

    # Normalize weights to sum to number of demand points (keeps solver scale similar)
    w_total = d["_weight"].sum()
    if w_total > 0:
        d["_weight"] = d["_weight"] / w_total * len(d)

    d_xy = np.c_[d.geometry.x.values, d.geometry.y.values]
    s_xy = np.c_[s.geometry.x.values, s.geometry.y.values]
    c_xy = np.c_[c.geometry.x.values, c.geometry.y.values]

    # ── Existing coverage analysis ──
    if len(s) > 0:
        dist_to_existing = np.sqrt(
            ((d_xy[:, None, :] - s_xy[None, :, :]) ** 2).sum(axis=2)
        ).min(axis=1)
    else:
        dist_to_existing = np.full(len(d), 1e9)

    existing_covered = (dist_to_existing <= THRESHOLD_M)
    print(f"Existing coverage: {existing_covered.mean()*100:.1f}%")

    # ── Capacity-weighted demand adjustment ──
    if args.capacity_mode and "speed_tier" in s.columns:
        # Compute total existing capacity within threshold of each demand point
        s["_cap"] = s.apply(estimate_capacity_kw, axis=1)
        total_cap = s["_cap"].sum()
        print(f"Total existing capacity: {total_cap:.0f} kW")

        # For each demand point, sum capacity of chargers within threshold
        dist_ds = np.sqrt(((d_xy[:, None, :] - s_xy[None, :, :]) ** 2).sum(axis=2))
        cap_array = s["_cap"].values
        nearby_cap = np.where(dist_ds <= THRESHOLD_M, cap_array[None, :], 0).sum(axis=1)

        # Demand points with less nearby capacity get higher weight
        # Scale: 0 capacity → weight × 1.5, very high capacity → weight × 0.3
        max_cap = nearby_cap.max() if nearby_cap.max() > 0 else 1
        cap_factor = 1.5 - 1.2 * (nearby_cap / max_cap)
        cap_factor = np.clip(cap_factor, 0.3, 1.5)
        d["_weight"] = d["_weight"].values * cap_factor
        print(f"Capacity-adjusted weight range: [{d['_weight'].min():.2f}, {d['_weight'].max():.2f}]")

    # ── Build coverage sets ──
    I = list(range(len(d)))
    J = list(range(len(c)))

    # dist(demand, candidate)
    dist_dc = np.sqrt(((d_xy[:, None, :] - c_xy[None, :, :]) ** 2).sum(axis=2))

    cover = {}
    for i in I:
        # Candidates that cover this demand point (new coverage)
        cover[i] = [j for j in J if dist_dc[i, j] <= THRESHOLD_M]

    # ── Solve MCLP ──
    solver = pywraplp.Solver.CreateSolver("SCIP")
    if not solver:
        raise RuntimeError("SCIP solver not available")

    x = {j: solver.BoolVar(f"x[{j}]") for j in J}
    y = {i: solver.BoolVar(f"y[{i}]") for i in I}

    for i in I:
        if len(cover[i]) == 0:
            solver.Add(y[i] == 0)
        else:
            solver.Add(y[i] <= sum(x[j] for j in cover[i]))

    solver.Add(sum(x[j] for j in J) == P)

    # Weighted objective
    weights = d["_weight"].values
    solver.Maximize(sum(weights[i] * y[i] for i in I))

    status = solver.Solve()
    if status != pywraplp.Solver.OPTIMAL:
        print(f"WARNING: Solver status = {status} (not optimal)")
        if status == pywraplp.Solver.INFEASIBLE:
            raise RuntimeError("Problem is infeasible. Check P vs candidate count.")

    chosen = [j for j in J if x[j].solution_value() > 0.5]
    covered_new = sum(1 for i in I if y[i].solution_value() > 0.5)
    covered_total = sum(1 for i in I if y[i].solution_value() > 0.5 or existing_covered[i])
    weighted_cov = sum(weights[i] for i in I if y[i].solution_value() > 0.5 or existing_covered[i])

    # ── Compute post-solution metrics ──
    c_new = c.iloc[chosen]
    s_all_xy = np.vstack([s_xy, np.c_[c_new.geometry.x.values, c_new.geometry.y.values]])
    dist_after = np.sqrt(((d_xy[:, None, :] - s_all_xy[None, :, :]) ** 2).sum(axis=2)).min(axis=1)

    metrics = {
        "P": P,
        "threshold_m": THRESHOLD_M,
        "capacity_mode": args.capacity_mode,
        "n_demand": len(d),
        "n_existing_supply": len(s),
        "n_candidates": len(c),
        "n_chosen": len(chosen),
        "coverage_existing_pct": float(existing_covered.mean() * 100),
        "coverage_after_pct": float((dist_after <= THRESHOLD_M).mean() * 100),
        "coverage_improvement_pp": float((dist_after <= THRESHOLD_M).mean() * 100 - existing_covered.mean() * 100),
        "mean_nearest_m_before": float(dist_to_existing.mean()),
        "mean_nearest_m_after": float(dist_after.mean()),
        "max_nearest_m_after": float(dist_after.max()),
        "weighted_coverage": float(weighted_cov / weights.sum() * 100) if weights.sum() > 0 else 0,
    }

    # ── Save ──
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"chosen_candidate_id": chosen}).to_csv(OUT, index=False)

    OUT_MET.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([metrics]).to_csv(OUT_MET, index=False)

    print(f"\n{'='*55}")
    print(f"  RESULTS: P={P}, threshold={THRESHOLD_M}m")
    print(f"{'='*55}")
    for k, v in metrics.items():
        if isinstance(v, float):
            print(f"  {k}: {v:.2f}")
        else:
            print(f"  {k}: {v}")
    print(f"\nSaved solution: {OUT}")
    print(f"Saved metrics: {OUT_MET}")


if __name__ == "__main__":
    main()

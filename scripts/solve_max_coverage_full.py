import pandas as pd
from ortools.linear_solver import pywraplp
from pathlib import Path

COST = Path("data/processed/cost_matrix_full.csv")
OUT  = Path("outputs/tables/solution_max_coverage.csv")

P = 10
THRESHOLD_M = 1000.0

def main():
    df = pd.read_csv(COST)

    I = sorted(df["i"].unique())
    J = sorted(df["j"].unique())

    cover = {}
    for i in I:
        cover[i] = df[(df["i"] == i) & (df["cost_m"] <= THRESHOLD_M)]["j"].tolist()

    solver = pywraplp.Solver.CreateSolver("SCIP")
    x = {j: solver.BoolVar(f"x[{j}]") for j in J}
    y = {i: solver.BoolVar(f"y[{i}]") for i in I}

    for i in I:
        if len(cover[i]) == 0:
            solver.Add(y[i] == 0)
        else:
            solver.Add(y[i] <= sum(x[j] for j in cover[i]))

    solver.Add(sum(x[j] for j in J) == P)
    solver.Maximize(sum(y[i] for i in I))

    status = solver.Solve()
    if status != pywraplp.Solver.OPTIMAL:
        raise RuntimeError("No optimal solution found")

    chosen = [j for j in J if x[j].solution_value() > 0.5]
    covered = sum(1 for i in I if y[i].solution_value() > 0.5)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"chosen_candidate_id": chosen}).to_csv(OUT, index=False)

    print(f"P={P}, threshold={THRESHOLD_M}m -> covered {covered}/{len(I)} demand points")
    print("Saved:", OUT)

if __name__ == "__main__":
    main()

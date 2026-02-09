# scripts/join_wimd_census_to_demand.py
import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd


def _die(msg: str):
    raise SystemExit(msg)


def _norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _lower_map(cols):
    return {str(c).strip().lower(): c for c in cols}


def _find_col(cols, candidates):
    """Find exact match in a case-insensitive way."""
    mp = _lower_map(cols)
    for cand in candidates:
        key = cand.strip().lower()
        if key in mp:
            return mp[key]
    return None


def _find_col_contains(cols, patterns):
    """Find first column whose lowercase contains any pattern substring."""
    cols_list = list(cols)
    low = [str(c).lower() for c in cols_list]
    pats = [p.lower() for p in patterns]
    for i, c in enumerate(low):
        for p in pats:
            if p in c:
                return cols_list[i]
    return None


def _to_num(s):
    return pd.to_numeric(s, errors="coerce")


def _safe_div(a, b):
    a = _to_num(a)
    b = _to_num(b)
    out = np.where((b > 0) & np.isfinite(b), a / b, np.nan)
    return out


def _guess_lsoa_code_field(props_cols):
    # demand geojson might have any of these
    candidates = ["LSOA21CD", "lsoa21cd", "LSOA11CD", "lsoa11cd", "code", "id"]
    return _find_col(props_cols, candidates)


def _read_demand(path: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    if gdf.empty:
        _die(f"[ERROR] Demand file is empty: {path}")

    code_field = _guess_lsoa_code_field(gdf.columns)
    if not code_field:
        _die(f"[ERROR] Cannot find LSOA code field in demand. Columns: {list(gdf.columns)[:30]} ...")

    gdf = gdf.copy()
    gdf["_lsoa_code"] = gdf[code_field].astype(str).str.strip()
    return gdf


def _read_wimd(path: Path) -> pd.DataFrame:
    w = gpd.read_file(path)
    if w.empty:
        return pd.DataFrame(columns=["_lsoa_code"])

    # try find LSOA code field
    code_field = _find_col(w.columns, ["LSOA11CD", "lsoa11cd", "LSOA21CD", "lsoa21cd", "code"])
    if not code_field:
        # last resort: any column contains "lsoa" and "cd"
        code_field = _find_col_contains(w.columns, ["lsoa", "cd"])

    if not code_field:
        # still allow but no join key
        return pd.DataFrame(columns=["_lsoa_code"])

    df = pd.DataFrame(w.drop(columns="geometry"))
    df["_lsoa_code"] = df[code_field].astype(str).str.strip()

    # try find an overall rank/score
    rank_col = _find_col_contains(df.columns, ["overall rank", "rank"])
    decile_col = _find_col_contains(df.columns, ["decile"])
    score_col = _find_col_contains(df.columns, ["score"])

    keep = ["_lsoa_code"]
    if rank_col: keep.append(rank_col)
    if decile_col and decile_col not in keep: keep.append(decile_col)
    if score_col and score_col not in keep: keep.append(score_col)

    out = df[keep].copy()

    # rename to stable names
    rename = {}
    if rank_col: rename[rank_col] = "wimd_rank"
    if decile_col: rename[decile_col] = "wimd_decile"
    if score_col: rename[score_col] = "wimd_score"
    out = out.rename(columns=rename)

    # wimd_norm: 1 = more deprived (if rank exists and smaller rank = more deprived)
    if "wimd_rank" in out.columns:
        r = pd.to_numeric(out["wimd_rank"], errors="coerce")
        mn, mx = np.nanmin(r), np.nanmax(r)
        if np.isfinite(mn) and np.isfinite(mx) and mx > mn:
            out["wimd_norm"] = (mx - r) / (mx - mn)
        else:
            out["wimd_norm"] = np.nan
    return out


def _read_census(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = _norm_cols(df)

    code_col = _find_col(df.columns, ["geography code", "geography_code", "LSOA21CD", "LSOA11CD", "lsoa21cd", "lsoa11cd"])
    if not code_col:
        _die(f"[ERROR] Cannot find geography code column in {path}. First columns: {list(df.columns)[:10]}")

    df["_lsoa_code"] = df[code_col].astype(str).str.strip()
    return df


def _metrics_ts044(df: pd.DataFrame) -> pd.DataFrame:
    # Accommodation type
    total = _find_col_contains(df.columns, ["accommodation type: total"])
    terr = _find_col_contains(df.columns, ["accommodation type: terraced"])
    flats = _find_col_contains(df.columns, ["purpose-built block of flats", "tenement"])
    conv1 = _find_col_contains(df.columns, ["converted or shared house"])
    conv2 = _find_col_contains(df.columns, ["another converted building"])
    comm = _find_col_contains(df.columns, ["commercial building"])

    if not total:
        _die("[ERROR] ts044: cannot find 'Accommodation type: Total' column.")

    out = df[["_lsoa_code"]].copy()
    tot = df[total]

    # shares
    if flats:
        out["share_flats"] = _safe_div(df[flats], tot)
    else:
        out["share_flats"] = np.nan

    if terr:
        out["share_terraced"] = _safe_div(df[terr], tot)
    else:
        out["share_terraced"] = np.nan

    # additional “dense housing” share (optional)
    parts = []
    for col in [flats, conv1, conv2, comm]:
        if col:
            parts.append(_to_num(df[col]))
    if parts:
        dense = np.sum(parts, axis=0)
        out["share_dense_housing"] = np.where(_to_num(tot) > 0, dense / _to_num(tot), np.nan)
    else:
        out["share_dense_housing"] = np.nan

    return out


def _metrics_ts045(df: pd.DataFrame) -> pd.DataFrame:
    # Cars or vans
    total = _find_col_contains(df.columns, ["number of cars or vans: total"])
    nocar = _find_col_contains(df.columns, ["no cars or vans"])
    if not total:
        _die("[ERROR] ts045: cannot find 'Number of cars or vans: Total' column.")
    out = df[["_lsoa_code"]].copy()
    if nocar:
        out["share_no_car"] = _safe_div(df[nocar], df[total])
    else:
        out["share_no_car"] = np.nan
    return out


def _metrics_ts054(df: pd.DataFrame) -> pd.DataFrame:
    # Tenure
    total = _find_col_contains(df.columns, ["tenure of household: total"])
    owned = _find_col_contains(df.columns, ["tenure of household: owned"])
    social = _find_col_contains(df.columns, ["tenure of household: social rented"])
    priv = _find_col_contains(df.columns, ["tenure of household: private rented"])
    rentfree = _find_col_contains(df.columns, ["lives rent free"])

    if not total:
        _die("[ERROR] ts054: cannot find 'Tenure of household: Total' column.")

    out = df[["_lsoa_code"]].copy()
    tot = df[total]

    if owned:
        out["share_owned"] = _safe_div(df[owned], tot)
    else:
        out["share_owned"] = np.nan

    # rented = social + private
    parts = []
    if social: parts.append(_to_num(df[social]))
    if priv: parts.append(_to_num(df[priv]))
    if parts:
        rented = np.sum(parts, axis=0)
        out["share_rented"] = np.where(_to_num(tot) > 0, rented / _to_num(tot), np.nan)
    else:
        out["share_rented"] = np.nan

    if rentfree:
        out["share_rent_free"] = _safe_div(df[rentfree], tot)
    else:
        out["share_rent_free"] = np.nan

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demand", required=True)
    ap.add_argument("--wimd", required=True)
    ap.add_argument("--ts044", required=True)
    ap.add_argument("--ts045", required=True)
    ap.add_argument("--ts054", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    demand_path = Path(args.demand)
    wimd_path = Path(args.wimd)
    ts044_path = Path(args.ts044)
    ts045_path = Path(args.ts045)
    ts054_path = Path(args.ts054)
    out_path = Path(args.out)

    if not demand_path.exists():
        _die(f"[ERROR] demand not found: {demand_path}")
    if not wimd_path.exists():
        _die(f"[ERROR] wimd not found: {wimd_path}")
    for p in [ts044_path, ts045_path, ts054_path]:
        if not p.exists():
            _die(f"[ERROR] census file not found: {p}")

    gdf = _read_demand(demand_path)
    codes = set(gdf["_lsoa_code"].tolist())
    print(f"[OK] Demand LSOAs: {len(gdf)}")

    # WIMD join (by code)
    wimd_df = _read_wimd(wimd_path)
    if not wimd_df.empty and "_lsoa_code" in wimd_df.columns:
        wimd_df = wimd_df[wimd_df["_lsoa_code"].isin(codes)]
        print(f"[OK] WIMD matched rows: {len(wimd_df)}")
        gdf = gdf.merge(wimd_df, on="_lsoa_code", how="left")
    else:
        print("[WARN] WIMD loaded but no join key found. Skipping WIMD join.")

    # Census metrics
    df044 = _read_census(ts044_path)
    df045 = _read_census(ts045_path)
    df054 = _read_census(ts054_path)

    m044 = _metrics_ts044(df044)
    m045 = _metrics_ts045(df045)
    m054 = _metrics_ts054(df054)

    # filter to demand codes
    m044 = m044[m044["_lsoa_code"].isin(codes)]
    m045 = m045[m045["_lsoa_code"].isin(codes)]
    m054 = m054[m054["_lsoa_code"].isin(codes)]
    print(f"[OK] ts044 matched: {len(m044)} | ts045 matched: {len(m045)} | ts054 matched: {len(m054)}")

    gdf = gdf.merge(m044, on="_lsoa_code", how="left")
    gdf = gdf.merge(m045, on="_lsoa_code", how="left")
    gdf = gdf.merge(m054, on="_lsoa_code", how="left")

    # Build a parking constraint proxy (0..1)
    # - flats/dense housing & terraced & rented generally means less off-street parking
    def clip01(x):
        return np.clip(x, 0.0, 1.0)

    # prefer share_dense_housing if available
    dense = gdf.get("share_dense_housing")
    flats = gdf.get("share_flats")
    terr = gdf.get("share_terraced")
    rent = gdf.get("share_rented")

    base = np.zeros(len(gdf), dtype=float)
    cnt = np.zeros(len(gdf), dtype=float)

    for s, w in [(dense, 0.5), (flats, 0.5), (terr, 0.3), (rent, 0.2)]:
        if s is None:
            continue
        v = pd.to_numeric(s, errors="coerce").to_numpy()
        m = np.isfinite(v)
        base[m] += w * v[m]
        cnt[m] += w

    gdf["parking_constraint"] = np.where(cnt > 0, clip01(base / cnt), np.nan)

    # Equity proxy (0..1): prefer wimd_norm if exists, otherwise fallback to parking_constraint
    if "wimd_norm" in gdf.columns:
        wn = pd.to_numeric(gdf["wimd_norm"], errors="coerce").to_numpy()
        pc = pd.to_numeric(gdf["parking_constraint"], errors="coerce").to_numpy()
        gdf["equity_proxy"] = np.nanmean(np.vstack([wn, pc]), axis=0)
    else:
        gdf["equity_proxy"] = gdf["parking_constraint"]

    # Save
    out_path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(out_path, driver="GeoJSON")
    print(f"[SAVED] {out_path}")


if __name__ == "__main__":
    main()

import json
from pathlib import Path
from pyproj import Transformer

T = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)

def tx_pt(pt):
    x, y = pt[0], pt[1]
    lon, lat = T.transform(x, y)
    out = [lon, lat]
    if len(pt) > 2:
        out.extend(pt[2:])
    return out

def recurse_coords(coords):
    if isinstance(coords, list) and coords and isinstance(coords[0], (int, float)):
        return tx_pt(coords)
    return [recurse_coords(c) for c in coords]

def main(infile, outfile):
    infile = Path(infile)
    outfile = Path(outfile)

    if not infile.exists():
        raise FileNotFoundError(f"Input not found: {infile.resolve()}")

    outfile.parent.mkdir(parents=True, exist_ok=True)

    data = json.loads(infile.read_text(encoding="utf-8"))

    # remove CRS tag (optional)
    data.pop("crs", None)

    n = 0
    for f in data.get("features", []):
        geom = f.get("geometry")
        if not geom or "coordinates" not in geom:
            continue
        geom["coordinates"] = recurse_coords(geom["coordinates"])
        n += 1

    outfile.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    # strong confirmation prints
    print("[OK] Reprojected features:", n)
    print("[SAVED]", str(outfile.resolve()))

    # quick sanity check: print first coordinate if possible
    try:
        fc = data["features"][0]["geometry"]["coordinates"]
        # for point: [lon,lat], for polygon: nested; just print a sample
        if isinstance(fc[0], (int, float)):
            sample = fc
        else:
            # dig into nested list
            x = fc
            while isinstance(x, list) and x and not isinstance(x[0], (int, float)):
                x = x[0]
            sample = x
        print("[SAMPLE COORD]", sample)
    except Exception:
        pass

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--infile", required=True)
    ap.add_argument("--outfile", required=True)
    args = ap.parse_args()
    main(args.infile, args.outfile)

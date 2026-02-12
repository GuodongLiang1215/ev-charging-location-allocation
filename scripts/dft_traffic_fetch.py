import requests
import csv

BASE = "https://roadtraffic.dft.gov.uk"
HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
}

def fetch_json(url, params=None, timeout=30):
    r = requests.get(url, headers=HEADERS, params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()

def fetch_paged(path, params=None, page_size=2000):
    """
    For endpoints like /api/count-points or /api/average-annual-daily-flow
    that return a paging wrapper:
      { current_page, data, next_page_url, last_page, ... }

    If an endpoint returns a raw list, we yield it directly.
    """
    url = BASE + path
    params = dict(params or {})
    params.setdefault("page[size]", page_size)

    page = 1
    while True:
        params["page[number]"] = page
        js = fetch_json(url, params=params)

        # Some endpoints return a raw list (e.g., /api/local-authorities)
        if isinstance(js, list):
            for item in js:
                yield item
            return

        data = js.get("data", []) if isinstance(js, dict) else []
        for item in data:
            yield item

        # Stop condition
        next_url = js.get("next_page_url")
        last_page = js.get("last_page", page)

        if not next_url or page >= int(last_page):
            return

        page += 1

def get_local_authority_id(name="Cardiff"):
    """
    /api/local-authorities returns a LIST like:
      [ {id, name, region_id, ...}, ... ]
    """
    url = BASE + "/api/local-authorities"
    js = fetch_json(url)

    if isinstance(js, dict) and "data" in js:
        items = js["data"]
    elif isinstance(js, list):
        items = js
    else:
        raise RuntimeError(f"Unexpected response type for local-authorities: {type(js)}")

    targets = {name.strip().lower(), "caerdydd"}  # Welsh name just in case

    for it in items:
        nm = str(it.get("name", "")).strip().lower()
        if nm in targets:
            return int(it["id"])

    # fallback: contains match
    for it in items:
        nm = str(it.get("name", "")).strip().lower()
        if name.strip().lower() in nm:
            return int(it["id"])

    raise RuntimeError(f"Cannot find {name} in /api/local-authorities")

def get_cardiff_count_points(aadf_year=2024):
    la_id = get_local_authority_id("Cardiff")

    params = {
        "filter[local_authority_id]": la_id,
        "filter[aadf_year]": int(aadf_year),
        # optional: "filter[road_type]": "Major"
    }

    rows = list(fetch_paged("/api/count-points", params=params, page_size=2000))
    return la_id, rows

def get_cardiff_aadf(year=2024):
    la_id = get_local_authority_id("Cardiff")

    params = {
        "filter[local_authority_id]": la_id,
        "filter[year]": int(year),
    }

    rows = list(fetch_paged("/api/average-annual-daily-flow", params=params, page_size=5000))
    return la_id, rows

def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})

def main():
    # 1) Count points (locations + metadata)
    la_id, cps = get_cardiff_count_points(aadf_year=2024)
    print(f"Cardiff local_authority_id = {la_id}")
    print(f"Count points rows = {len(cps)}")

    # Choose columns commonly useful for mapping
    cp_fields = [
        "id", "count_point_id", "aadf_year",
        "region_id", "local_authority_id",
        "road_name", "road_type",
        "start_junction_road_name", "end_junction_road_name",
        "easting", "northing", "latitude", "longitude",
        "link_length_km", "link_length_miles",
    ]
    write_csv("cardiff_count_points_2024.csv", cps, cp_fields)
    print("Saved: cardiff_count_points_2024.csv")

    # 2) AADF flows (traffic volumes)
    _, aadf = get_cardiff_aadf(year=2024)
    print(f"AADF rows = {len(aadf)}")

    # This endpoint typically includes flows like all_motor_vehicles, cars_and_taxis, etc.
    # We keep a wide set; adjust to your need.
    if aadf:
        aadf_fields = sorted({k for row in aadf for k in row.keys()})
        write_csv("cardiff_aadf_2024.csv", aadf, aadf_fields)
        print("Saved: cardiff_aadf_2024.csv")
    else:
        print("No AADF rows returned (check year or filters).")

if __name__ == "__main__":
    main()

"""
niah_lookup.py

Source 4 of the geo-history agent: the National Inventory of Architectural
Heritage (buildingsofireland.ie).

The NIAH catalogues built heritage from c.1700 to the mid-20th century —
big houses, farmhouses, mills, bridges, churches, forges, industrial
structures — filling the post-medieval gap left by the SMR, which focuses
on pre-1700 archaeology.

Access method (confirmed June 2026):
  - Open ArcGIS REST FeatureServer, same host as SMR. No API key.
  - Data licensed CC BY 4.0.

Install: pip install requests  (already required)
"""

import math
import requests

NIAH_QUERY_URL = (
    "https://services-eu1.arcgis.com/HyjXgkV6KGMSF3jt/arcgis/rest/services/"
    "NIAH_OpenData/FeatureServer/0/query"
)

# Rating codes from the NIAH schema.
RATING_LABELS = {
    "N": "National Interest",
    "R": "Regional Interest",
    "L": "Local Interest",
}


def _haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in kilometres (standard haversine)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def find_buildings_near(latitude, longitude, radius_km=2.0, max_results=10):
    """Return NIAH-recorded buildings within radius_km of a coordinate.

    Args:
        latitude, longitude: townland centre (WGS84, from Logainm).
        radius_km: search radius. 2 km covers most townlands; go wider for
                   rural areas where estate buildings sit at a distance.
        max_results: cap on results returned (nearest first).

    Returns a list of dicts, nearest first:
        {
            "name", "reg_no", "original_use", "date_text",
            "rating", "rating_label", "description", "distance_km",
        }
    Returns [] if nothing is recorded nearby.
    """
    params = {
        "geometry":     f"{longitude},{latitude}",
        "geometryType": "esriGeometryPoint",
        "inSR":         "4326",
        "distance":     radius_km,
        "units":        "esriSRUnit_Kilometer",
        "spatialRel":   "esriSpatialRelIntersects",
        "outFields":    "REG_NO,NAME,ORIGINAL_USE,DATE_TEXT,RATING,DESCRIPTION,LATITUDE,LONGITUDE",
        "returnGeometry": "false",
        "f":            "json",
    }

    try:
        response = requests.get(NIAH_QUERY_URL, params=params, timeout=20)
        response.raise_for_status()
    except requests.RequestException as exc:
        # NIAH being unavailable shouldn't break the whole pipeline.
        raise RuntimeError(f"NIAH query failed: {exc}") from exc

    features = response.json().get("features", [])

    buildings = []
    for feature in features:
        attrs = feature.get("attributes", {})
        blat = attrs.get("LATITUDE")
        blon = attrs.get("LONGITUDE")
        if blat is None or blon is None:
            continue
        rating = attrs.get("RATING") or ""
        buildings.append({
            "name":         attrs.get("NAME"),
            "reg_no":       attrs.get("REG_NO"),
            "original_use": attrs.get("ORIGINAL_USE"),
            "date_text":    attrs.get("DATE_TEXT"),
            "rating":       rating,
            "rating_label": RATING_LABELS.get(rating.strip().upper(), rating),
            "description":  attrs.get("DESCRIPTION"),
            "distance_km":  round(_haversine_km(latitude, longitude, blat, blon), 2),
        })

    buildings.sort(key=lambda b: b["distance_km"])
    return buildings[:max_results]


if __name__ == "__main__":
    # Quick manual test — Crumlin, Dublin.
    #   python3 niah_lookup.py
    results = find_buildings_near(53.3141, -6.3198, radius_km=2.0)
    if results:
        for b in results:
            print(f"{b['distance_km']:>5} km  {b['rating']}  {b['name'] or '—'}  "
                  f"({b['original_use'] or '?'}, {b['date_text'] or '?'})")
    else:
        print("No NIAH buildings found at this location.")

"""
niah_lookup.py

Source 4 of the geo-history agent: the National Inventory of Architectural
Heritage (buildingsofireland.ie).

The NIAH catalogues built heritage from c.1700 to the mid-20th century —
big houses, farmhouses, mills, bridges, churches, forges, industrial
structures — filling the post-medieval gap left by the SMR, which focuses
on pre-1700 archaeology.

Access method (confirmed June 2026):
  - Open ArcGIS REST FeatureServer, same host/org as the SMR. No API key.
  - Service: NIAHBuildingsOpenData / FeatureServer / layer 0.
  - Each record carries WGS84 LATITUDE/LONGITUDE, a RATING ("National",
    "Regional", "Local"), DATEFROM/DATETO years, a link to its
    buildingsofireland.ie page, and a survey photo.

Install: pip install requests  (already required)
"""

import math
import requests

NIAH_QUERY_URL = (
    "https://services-eu1.arcgis.com/HyjXgkV6KGMSF3jt/arcgis/rest/services/"
    "NIAHBuildingsOpenData/FeatureServer/0/query"
)

# The RATING field holds the full word; map it to the NIAH's formal label.
RATING_LABELS = {
    "national": "National Interest",
    "regional": "Regional Interest",
    "local":    "Local Interest",
}


def _haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in kilometres (standard haversine)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _date_text(date_from, date_to):
    """Turn the DATEFROM/DATETO year integers into a readable span.

    The NIAH gives a build-date range (e.g. 1785–1795). We collapse it to a
    single year when both ends match, and cope with either end being missing.
    """
    if date_from and date_to:
        return str(date_from) if date_from == date_to else f"{date_from}–{date_to}"
    return str(date_from or date_to) if (date_from or date_to) else None


def find_buildings_near(latitude, longitude, radius_km=2.0, max_results=10):
    """Return NIAH-recorded buildings within radius_km of a coordinate.

    Args:
        latitude, longitude: townland centre (WGS84, from Logainm).
        radius_km: search radius. 2 km covers most townlands; go wider for
                   rural areas where estate buildings sit at a distance.
        max_results: cap on results returned (nearest first).

    Returns a list of dicts, nearest first:
        {
            "name", "reg_no", "original_use", "current_use", "date_text",
            "rating", "rating_label", "description", "townland", "county",
            "url", "image_url", "distance_km",
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
        "outFields": (
            "REG_NO,NAME,ORIGINAL_TYPE,IN_USE_AS_TYPE,DATEFROM,DATETO,RATING,"
            "DESCRIPTION,TOWNLAND,COUNTY,WEBSITE_LINK,IMAGE_LINK,LATITUDE,LONGITUDE"
        ),
        "returnGeometry": "false",
        "f":            "json",
    }

    try:
        response = requests.get(NIAH_QUERY_URL, params=params, timeout=20)
        response.raise_for_status()
    except requests.RequestException as exc:
        # NIAH being unavailable shouldn't break the whole pipeline.
        raise RuntimeError(f"NIAH query failed: {exc}") from exc

    payload = response.json()
    # ArcGIS reports query errors in a 200 body, not via HTTP status — surface
    # them rather than silently returning "no buildings".
    if "error" in payload:
        raise RuntimeError(f"NIAH query error: {payload['error']}")

    features = payload.get("features", [])

    buildings = []
    for feature in features:
        attrs = feature.get("attributes", {})
        blat = attrs.get("LATITUDE")
        blon = attrs.get("LONGITUDE")
        if blat is None or blon is None:
            continue
        rating = (attrs.get("RATING") or "").strip()
        buildings.append({
            "name":         attrs.get("NAME"),
            "reg_no":       attrs.get("REG_NO"),
            "original_use": attrs.get("ORIGINAL_TYPE"),
            "current_use":  attrs.get("IN_USE_AS_TYPE"),
            "date_text":    _date_text(attrs.get("DATEFROM"), attrs.get("DATETO")),
            "rating":       rating,
            "rating_label": RATING_LABELS.get(rating.lower(), rating),
            "description":  attrs.get("DESCRIPTION"),
            "townland":     attrs.get("TOWNLAND"),
            "county":       attrs.get("COUNTY"),
            "url":          attrs.get("WEBSITE_LINK"),
            "image_url":    attrs.get("IMAGE_LINK"),
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
            print(f"{b['distance_km']:>5} km  {b['rating'] or '—':9}  {b['name'] or '—'}  "
                  f"({b['original_use'] or '?'}, {b['date_text'] or '?'})")
    else:
        print("No NIAH buildings found at this location.")

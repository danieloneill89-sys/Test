"""
monuments_lookup.py

Source 2 of the geo-history agent: the Archaeological Survey of Ireland
(National Monuments Service) Sites and Monuments Record (SMR).

Given a coordinate (which we get from Logainm), this returns the recorded
archaeological monuments within a radius, sorted nearest-first.

Access method (confirmed June 2026):
  - Open ArcGIS REST FeatureServer. No API key, no registration.
  - Endpoint: SMROpenData / FeatureServer / layer 0.
  - Supports spatial (radius) queries; returns JSON. Licensed CC BY 4.0.

Install: pip install requests
"""

import json
import math
import requests

# Layer 0 of the open Sites and Monuments Record feature service.
SMR_QUERY_URL = (
    "https://services-eu1.arcgis.com/HyjXgkV6KGMSF3jt/arcgis/rest/services/"
    "SMROpenData/FeatureServer/0/query"
)


def _spatial_params(latitude, longitude, radius_km, boundary):
    """Build the ArcGIS geometry parameters for the query.

    The ArcGIS FeatureServer can filter by any geometry, so when we know the
    townland's real boundary we use it instead of a circle:

      - exact polygon  → search precisely what falls inside the townland;
      - bounding box   → the townland's real extent (used when we have a
                         boundary but couldn't stitch the exact ring);
      - point + radius → the original behaviour, used when no boundary is known.

    `boundary` is the dict returned by boundary_lookup.find_boundary, or None.
    """
    if boundary and boundary.get("polygon"):
        geometry = {
            "rings": [boundary["polygon"]],
            "spatialReference": {"wkid": 4326},
        }
        return {
            "geometry": json.dumps(geometry),
            "geometryType": "esriGeometryPolygon",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
        }

    if boundary and boundary.get("bbox"):
        b = boundary["bbox"]
        geometry = {
            "xmin": b["xmin"], "ymin": b["ymin"],
            "xmax": b["xmax"], "ymax": b["ymax"],
            "spatialReference": {"wkid": 4326},
        }
        return {
            "geometry": json.dumps(geometry),
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
        }

    # Fallback: a point and a radius (ArcGIS point order is x,y = lon,lat).
    return {
        "geometry": f"{longitude},{latitude}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "distance": radius_km,
        "units": "esriSRUnit_Kilometer",
        "spatialRel": "esriSpatialRelIntersects",
    }


def _haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance between two lat/lon points, in kilometres.

    We compute distance ourselves (rather than asking the server for it) so we
    can sort monuments nearest-first and report a clean "x km from the centre".
    This is the standard haversine formula.
    """
    radius = 6371.0  # Earth's mean radius in km
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def find_monuments_near(latitude, longitude, radius_km=2.0, max_results=15,
                        boundary=None):
    """Return recorded monuments near a coordinate, or inside a townland.

    Args:
        latitude, longitude: the townland centre (WGS84, from Logainm).
                             Always used to measure each monument's distance.
        radius_km: how far out to look when no boundary is supplied.
        max_results: cap on how many we return (nearest first), so the
                     synthesis step gets a focused list, not hundreds of sites.
        boundary: optional dict from boundary_lookup.find_boundary. When given,
                  the search is constrained to the townland's real shape
                  (polygon, or its bounding box) instead of a radius. When
                  None, the original point-and-radius behaviour applies.

    Returns a list of dicts, nearest first:
        {
            "monument_class", "smr_number", "townland", "county",
            "description", "distance_km",
        }
    Returns [] if nothing is recorded nearby (a normal, expected outcome).
    """
    # Let the ArcGIS server do the geographic filtering. We send geometry as
    # WGS84 lon/lat (inSR=4326); the server reprojects to its own grid.
    params = {
        # Only the fields we actually use, to keep responses small.
        "outFields": "MONUMENT_CLASS,SMRS,TOWNLAND,COUNTY,LATITUDE,LONGITUDE,WEB_NOTES",
        "returnGeometry": "false",
        "f": "json",
    }
    params.update(_spatial_params(latitude, longitude, radius_km, boundary))

    response = requests.get(SMR_QUERY_URL, params=params, timeout=20)
    response.raise_for_status()
    features = response.json().get("features", [])

    monuments = []
    for feature in features:
        attrs = feature.get("attributes", {})
        mlat = attrs.get("LATITUDE")
        mlon = attrs.get("LONGITUDE")
        # We need the monument's own coordinate to measure distance; skip any
        # record missing it rather than guessing.
        if mlat is None or mlon is None:
            continue
        monuments.append(
            {
                "monument_class": attrs.get("MONUMENT_CLASS"),
                "smr_number": attrs.get("SMRS"),
                "townland": attrs.get("TOWNLAND"),
                "county": attrs.get("COUNTY"),
                "description": attrs.get("WEB_NOTES"),
                "distance_km": round(_haversine_km(latitude, longitude, mlat, mlon), 2),
            }
        )

    # Nearest first, then trim to the cap.
    monuments.sort(key=lambda m: m["distance_km"])
    return monuments[:max_results]


if __name__ == "__main__":
    # Quick manual test using Ballinakill, Co. Laois coordinates.
    #     python3 monuments_lookup.py
    for m in find_monuments_near(52.8742, -7.3080, radius_km=2.0):
        print(f"{m['distance_km']:>5} km  {m['monument_class']}  ({m['smr_number']})")

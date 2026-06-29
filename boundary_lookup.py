"""
boundary_lookup.py

Support source for the geo-history agent: the real *shape* of a townland.

Every other source works from a single centre coordinate plus a radius. But a
townland is a small, irregular polygon (the Irish average is barely over a
square kilometre), so a 2 km circle around the centre spills into three or four
neighbouring townlands and calls their monuments "here". This module fetches
the townland's actual boundary so the spatial searches can ask the precise
question — "what is recorded *inside this townland*?" — instead of "what is
within 2 km of a point?".

Access method:
  - OpenStreetMap, queried live through the Overpass API. Irish townlands were
    imported into OSM by the townlands.ie project, so each is a boundary
    relation with geometry. No API key. Data licensed ODbL.
  - We query by COORDINATE, not by name: "which boundaries contain this point?"
    That sidesteps the placename-disambiguation problem entirely — we already
    have a trustworthy coordinate from Logainm.

Robustness:
  - Overpass can be slow or rate-limited, and not every townland is mapped.
    Every failure path returns None so the caller falls back cleanly to the
    existing point-and-radius search. Boundaries are an enhancement, never a
    dependency.

NOTE (verify on a networked machine): the exact OSM tag scheme for Irish
townlands is assumed, not confirmed from this sandbox. To stay tag-agnostic we
ask Overpass for *all* administrative boundaries containing the point (county,
barony, civil parish, townland …) and keep the SMALLEST one — the townland is
always the most fine-grained unit, whatever its tags happen to be.

Install: pip install requests  (already required)
"""

import math
import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Overpass (like Wikipedia) rejects requests without a descriptive User-Agent,
# answering 406 Not Acceptable. Identify ourselves.
_HEADERS = {
    "User-Agent": "AnAit/1.0 (Irish townland geo-history agent; "
                  "https://github.com/danieloneill89-sys/Test) python-requests",
    "Accept": "*/*",
}

# Find the boundaries containing the point, then keep only the townland. In the
# OSM Ireland scheme a townland is boundary=administrative at admin_level 10
# (the hierarchy runs 6=county, 8=municipal district, 9=electoral division,
# 10=townland); a few legacy imports use boundary=townland. We fetch ONLY that
# level's geometry — fetching every containing boundary would pull the entire
# outline of Ireland. {lat}/{lon} are filled in per request.
_OVERPASS_QUERY = """
[out:json][timeout:25];
is_in({lat},{lon})->.here;
(
  relation(pivot.here)["boundary"="administrative"]["admin_level"="10"];
  relation(pivot.here)["boundary"="townland"];
);
out geom;
"""


def _ring_bbox(points):
    """Bounding box of a list of (lon, lat) points → (xmin, ymin, xmax, ymax)."""
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    return min(lons), min(lats), max(lons), max(lats)


def _bbox_area_deg2(bbox):
    """Rough area of a bbox in square degrees — only used to rank candidates.

    We just need a consistent "which is smallest" comparison between the nested
    boundaries the point falls inside, so an exact area is unnecessary.
    """
    xmin, ymin, xmax, ymax = bbox
    return (xmax - xmin) * (ymax - ymin)


def _bbox_area_km2(bbox):
    """Approximate bbox area in km², for human-readable reporting.

    Uses the local-scale conversion: 1° latitude ≈ 111 km, 1° longitude ≈
    111 km · cos(latitude). Good enough to say "about 1.4 km²".
    """
    xmin, ymin, xmax, ymax = bbox
    mid_lat = math.radians((ymin + ymax) / 2)
    width_km = (xmax - xmin) * 111.0 * math.cos(mid_lat)
    height_km = (ymax - ymin) * 111.0
    return round(abs(width_km * height_km), 2)


def _bbox_of(el):
    """Return (xmin, ymin, xmax, ymax) for an Overpass relation element.

    Tries the `bounds` field first (present with `out bb;` / `out body;`),
    then falls back to deriving the bbox from member geometry (needed when
    the query uses `out geom;`, which returns geometry but no bounds object).
    Returns None if there is too little data to compute a bbox.
    """
    b = el.get("bounds") or {}
    if all(k in b for k in ("minlon", "minlat", "maxlon", "maxlat")):
        return (b["minlon"], b["minlat"], b["maxlon"], b["maxlat"])
    pts = [(g["lon"], g["lat"])
           for m in (el.get("members") or [])
           for g in (m.get("geometry") or [])
           if "lon" in g and "lat" in g]
    return _ring_bbox(pts) if len(pts) >= 3 else None


def _stitch_outer_ring(members, tol=1e-7):
    """Join a relation's 'outer' member ways into a single closed ring.

    Overpass returns each member way as an ordered list of {lat, lon} points,
    but the ways arrive in arbitrary order and direction. We chain them end to
    end: start with the first way, then repeatedly attach whichever remaining
    way begins (or, reversed, ends) where the current chain leaves off.

    Returns a list of (lon, lat) points forming a closed ring, or None if the
    pieces don't connect up (in which case the caller falls back to the bbox).
    """
    segments = []
    for m in members:
        if m.get("type") != "way":
            continue
        if m.get("role") not in ("outer", ""):
            continue
        geom = m.get("geometry") or []
        pts = [(g["lon"], g["lat"]) for g in geom if "lon" in g and "lat" in g]
        if len(pts) >= 2:
            segments.append(pts)

    if not segments:
        return None

    def close(a, b):
        return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol

    ring = list(segments.pop(0))
    # Keep attaching until nothing connects or the ring closes on itself.
    while segments and not close(ring[0], ring[-1]):
        tail = ring[-1]
        for i, seg in enumerate(segments):
            if close(seg[0], tail):
                ring.extend(seg[1:])
                segments.pop(i)
                break
            if close(seg[-1], tail):
                ring.extend(reversed(seg[:-1]))
                segments.pop(i)
                break
        else:
            # Nothing matched the current tail: the ring can't be completed.
            return None

    if not close(ring[0], ring[-1]):
        return None
    if len(ring) < 4:
        return None
    return ring


def find_boundary(latitude, longitude, county=None):
    """Return the townland boundary that contains a coordinate.

    Args:
        latitude, longitude: a point inside the townland (from Logainm).
        county: optional, reserved for future name-based disambiguation;
                unused by the coordinate query but accepted so the call site
                reads the same as the other lookups.

    Returns a dict, or None if no boundary is found / the service is down:
        {
            "name", "name_ga",
            "osm_id",
            "area_km2",
            "bbox":    {"xmin","ymin","xmax","ymax"},
            "polygon": [[lon, lat], ...] | None,   # exact ring if we could
                                                   # stitch it; else None
        }

    Never raises — any network, parsing, or geometry problem returns None so
    the spatial searches fall back to the existing radius behaviour.
    """
    query = _OVERPASS_QUERY.format(lat=latitude, lon=longitude)
    try:
        response = requests.post(
            OVERPASS_URL, data={"data": query}, headers=_HEADERS, timeout=30
        )
        response.raise_for_status()
        elements = response.json().get("elements", [])
        print(f"[boundary] Overpass returned {len(elements)} element(s)")
    except (requests.RequestException, ValueError) as exc:
        print(f"[boundary] Overpass failed: {exc}")
        return None

    # The query already narrows to townland level; if more than one comes back
    # (rare overlaps) keep the smallest. _bbox_of is defined at module level
    # and used here and in find_neighbours.
    candidates = []
    for el in elements:
        bbox = _bbox_of(el)
        if bbox:
            candidates.append((_bbox_area_deg2(bbox), el, bbox))

    if not candidates:
        return None

    candidates.sort(key=lambda c: c[0])
    _, el, bbox = candidates[0]

    tags = el.get("tags", {})
    polygon = _stitch_outer_ring(el.get("members") or [])
    xmin, ymin, xmax, ymax = bbox

    return {
        "name":        tags.get("name"),
        "name_ga":     tags.get("name:ga"),
        "osm_id":      el.get("id"),
        "logainm_ref": tags.get("logainm:ref"),
        "area_km2":    _bbox_area_km2(bbox),
        "bbox":        {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax},
        "polygon":     polygon,
    }


# Fetch all townland relations within a bounding box. Much simpler and more
# reliable than node-sharing: Overpass handles bbox queries efficiently, and
# a townland bbox is small so the buffer naturally captures only neighbours.
# {south}/{west}/{north}/{east} are filled in per request.
_NEIGHBOURS_QUERY = """
[out:json][timeout:30];
(
  relation["boundary"="administrative"]["admin_level"="10"]
    ({south},{west},{north},{east});
  relation["boundary"="townland"]
    ({south},{west},{north},{east});
);
out geom;
"""


def find_neighbours(bbox, exclude_osm_id=None):
    """Return townland boundaries within a buffered bounding box.

    Args:
        bbox: dict with keys xmin/ymin/xmax/ymax (from find_boundary).
        exclude_osm_id: the main townland's OSM id -- excluded from results.

    Each entry matches find_boundary's shape:
        {"name", "name_ga", "osm_id", "area_km2", "bbox", "polygon"}

    Returns an empty list on any failure -- neighbours are decorative.
    """
    if not bbox:
        return []
    buf = 0.012
    query = _NEIGHBOURS_QUERY.format(
        south=bbox["ymin"] - buf,
        west=bbox["xmin"]  - buf,
        north=bbox["ymax"] + buf,
        east=bbox["xmax"]  + buf,
    )
    try:
        response = requests.post(
            OVERPASS_URL, data={"data": query}, headers=_HEADERS, timeout=35
        )
        response.raise_for_status()
        elements = response.json().get("elements", [])
        print(f"[neighbours] Overpass returned {len(elements)} element(s)")
    except (requests.RequestException, ValueError) as exc:
        print(f"[neighbours] Overpass failed: {exc}")
        return []

    neighbours = []
    for el in elements:
        if el.get("id") == exclude_osm_id:
            continue
        tags = el.get("tags", {})
        # out geom; does not include a bounds field — derive it from member
        # geometry the same way find_boundary does via _bbox_of.
        el_bbox = _bbox_of(el)
        if not el_bbox:
            continue
        polygon = _stitch_outer_ring(el.get("members") or [])
        neighbours.append({
            "name":     tags.get("name"),
            "name_ga":  tags.get("name:ga"),
            "osm_id":   el.get("id"),
            "area_km2": _bbox_area_km2(el_bbox),
            "bbox":     {"xmin": el_bbox[0], "ymin": el_bbox[1],
                         "xmax": el_bbox[2], "ymax": el_bbox[3]},
            "polygon":  polygon,
        })

    return neighbours


if __name__ == "__main__":
    # Quick manual test — a point in Ballinakill, Co. Laois.
    #   python3 boundary_lookup.py
    b = find_boundary(52.8742, -7.3080)
    if b:
        shape = f"{len(b['polygon'])}-point polygon" if b["polygon"] else "bbox only"
        print(f"{b['name']} ({b['name_ga'] or '—'}) "
              f"— OSM {b['osm_id']}, ~{b['area_km2']} km², {shape}")
        print(f"  bbox: {b['bbox']}")
    else:
        print("No boundary found (or Overpass unavailable).")

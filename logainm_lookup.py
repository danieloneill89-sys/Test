"""
logainm_lookup.py

Source 1 of the geo-history agent: the Logainm placenames database.

Given an English townland name, this returns the structured facts we need to
drive the rest of the pipeline: the Irish form of the name (the primary
source for what was historically there), any recorded word-meanings
(etymology), the county, the feature type, and — crucially — a coordinate we
can hand to the monuments database next.

Access method (confirmed June 2026):
  - JSON HTTP API at https://www.logainm.ie/api/v1.0/
  - Free API key, sent in the "X-Api-Key" header (register at gaois.ie).
  - Data licensed CC BY 4.0.

Install: pip install requests
"""

import os
import requests

LOGAINM_BASE_URL = "https://www.logainm.ie/api/v1.0/"


def _placename_for_language(placenames, language):
    """Return the full placename record for a given language code ('en'/'ga').

    We return the whole record (not just the text) because the Irish record
    also carries the genitive form, which is useful context. We prefer the
    one flagged 'main' (the canonical name) if there are several.
    """
    candidates = [p for p in placenames if p.get("language") == language]
    if not candidates:
        return None
    # Prefer the canonical name; otherwise just take the first.
    for p in candidates:
        if p.get("main"):
            return p
    return candidates[0]


def _county(place):
    """Find the county a place sits in.

    Logainm models the administrative hierarchy in 'includedIn': a townland is
    included in a civil parish, a barony, AND a county. Each entry has its own
    'category'; we return the one whose category is 'county'.
    """
    for unit in place.get("includedIn", []):
        category = unit.get("category") or {}
        if category.get("nameEN") == "county":
            return unit.get("nameEN")
    return None


def _feature_type(place):
    """Return the place's own feature type, e.g. 'townland' or 'civil parish'.

    A place can have several categories; the first is the primary one.
    """
    categories = place.get("categories", [])
    if categories:
        return categories[0].get("nameEN")
    return None


def _coordinate(place):
    """Return (latitude, longitude) for the place, or (None, None).

    Not every record has a coordinate, so we fail soft: the caller decides
    what to do when it's missing.
    """
    geography = place.get("geography") or {}
    coords = geography.get("coordinates") or []
    if coords:
        first = coords[0]
        return first.get("latitude"), first.get("longitude")
    return None, None


def _etymology(place):
    """Return recorded word-meanings as a list of {'word', 'meaning'} dicts.

    Logainm's 'glossary' breaks the name into its constituent Irish words and
    gives their meaning (e.g. 'baile' -> 'townland, town', 'coill' -> 'wood').
    This is the etymological core that should, in later versions, steer what
    the agent goes looking for next.
    """
    out = []
    for g in place.get("glossary", []):
        out.append({"word": g.get("headword"), "meaning": g.get("translation")})
    return out


def lookup_townland(name, county=None):
    """Look up an English townland name in Logainm.

    Args:
        name:   English townland name, e.g. "Ballinakill".
        county: Optional county name to disambiguate (e.g. "Laois"). Place
                names repeat across Ireland, so this filter is how the caller
                narrows 7 Ballinakills down to the one they mean.

    Returns a list of matches; each match is a dict:
        {
            "english_name", "irish_name", "irish_genitive",
            "county", "feature_type",
            "latitude", "longitude",
            "etymology": [ {"word", "meaning"}, ... ],
        }

    Returning a list (not a single result) is deliberate: 0 = not found,
    1 = clean match, many = ambiguous and the caller must choose.
    """
    api_key = os.environ.get("LOGAINM_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No API key found. Set LOGAINM_API_KEY in your environment. "
            "Get a free key from the Gaois Developer Hub (gaois.ie)."
        )

    # 'Query' is Logainm's free-text search. It is accent-sensitive and matches
    # exact wording, so "Ballinakill" returns places named exactly that.
    response = requests.get(
        LOGAINM_BASE_URL,
        params={"Query": name},
        headers={"X-Api-Key": api_key},
        timeout=15,
    )
    response.raise_for_status()

    # v1.0 puts the records in "results".
    places = response.json().get("results", [])

    matches = []
    for place in places:
        placenames = place.get("placenames", [])
        irish = _placename_for_language(placenames, "ga")
        english = _placename_for_language(placenames, "en")
        # Logainm's own record ID. We keep it so we can build a permalink back
        # to the canonical page (https://www.logainm.ie/en/<id>) — that lets the
        # synthesis cite a verifiable source for the placename and etymology.
        logainm_id = place.get("id")
        matches.append(
            {
                "logainm_id": logainm_id,
                "logainm_url": f"https://www.logainm.ie/en/{logainm_id}" if logainm_id else None,
                "english_name": english.get("wording") if english else None,
                "irish_name": irish.get("wording") if irish else None,
                "irish_genitive": irish.get("genitive") if irish else None,
                "county": _county(place),
                "feature_type": _feature_type(place),
                "latitude": _coordinate(place)[0],
                "longitude": _coordinate(place)[1],
                "etymology": _etymology(place),
            }
        )

    # If the caller named a county, keep only matches in that county.
    # Case-insensitive so "laois" and "Laois" both work.
    if county:
        wanted = county.strip().lower()
        matches = [m for m in matches if (m["county"] or "").lower() == wanted]

    return matches


if __name__ == "__main__":
    # Quick manual test of just this module.
    #     export LOGAINM_API_KEY="your-key-here"
    #     python3 logainm_lookup.py
    for m in lookup_townland("Ballinakill", county="Laois"):
        print(
            f"{m['english_name']} ({m['irish_name']}) - {m['feature_type']}, "
            f"Co. {m['county']} @ {m['latitude']}, {m['longitude']}"
        )
        for e in m["etymology"]:
            print(f"    {e['word']}: {e['meaning']}")

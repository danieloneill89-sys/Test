"""
logainm_lookup.py

A single, simple function for looking up an Irish townland (or other place)
by its English name using the Logainm API (the State's Placenames Database
of Ireland, logainm.ie).

Access method (confirmed June 2026):
  - Logainm exposes a JSON HTTP API at https://www.logainm.ie/api/v1.0/
  - You need a free API key. Register on the Gaois Developer Hub (gaois.ie)
    or email logainm@dcu.ie to request one. (Docs: docs.gaois.ie, and
    github.com/gaois/LogainmAPI-docs)
  - The key is sent in the "X-Api-Key" request header.
  - Data is licensed CC BY 4.0.

Install the one dependency:
    pip install requests
"""

import os
import requests

# The base URL of the Logainm API v1.0.
LOGAINM_BASE_URL = "https://www.logainm.ie/api/v1.0/"


def _english_name(placenames):
    """Pull the English-language wording out of a place's 'placenames' list.

    Each placename has a 'language' code (ISO 639-1, so 'en' / 'ga') and the
    actual text in 'wording'. We look for the English one; if none is tagged
    'en' we fall back to whichever name is marked 'main', so we always return
    something sensible rather than crashing.
    """
    for p in placenames:
        if p.get("language") == "en":
            return p.get("wording")
    for p in placenames:
        if p.get("main"):
            return p.get("wording")
    return None


def _irish_name(placenames):
    """Pull the Irish-language ('ga') wording out of a place's 'placenames'."""
    for p in placenames:
        if p.get("language") == "ga":
            return p.get("wording")
    return None


def _county(place):
    """Find the county a place sits in.

    Logainm models the administrative hierarchy in the 'includedIn' list:
    a townland is "included in" a civil parish, a barony, AND a county, etc.
    Each entry has its own 'category' (the kind of unit it is). We walk that
    list and return the one whose category is 'county'.
    """
    for unit in place.get("includedIn", []):
        category = unit.get("category") or {}
        if category.get("nameEN") == "county":
            return unit.get("nameEN")
    return None


def _feature_type(place):
    """Return the place's own feature type, e.g. 'townland' or 'civil parish'.

    A place can belong to several categories; the first is the primary one,
    which is what we want here.
    """
    categories = place.get("categories", [])
    if categories:
        return categories[0].get("nameEN")
    return None


def lookup_townland(name):
    """Look up an English townland name in Logainm.

    Returns a list of matches, where each match is a small dict:
        {
            "english_name": str,
            "irish_name":   str | None,
            "county":       str | None,
            "feature_type": str | None,  # e.g. "townland", "civil parish"
        }

    Why a list? Place names in Ireland are not unique — there are several
    townlands called "Ballinakill" in different counties. Returning a list
    lets the caller see all of them:
        - 0 results -> the name wasn't found (empty list)
        - 1 result  -> a clean single match
        - many      -> ambiguous; the caller can pick by county, etc.
    """
    # The API key is read from an environment variable so we never hard-code
    # a secret into the source. Set it once in your shell:
    #     export LOGAINM_API_KEY="your-key-here"
    api_key = os.environ.get("LOGAINM_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No API key found. Set LOGAINM_API_KEY in your environment. "
            "Get a free key from the Gaois Developer Hub (gaois.ie)."
        )

    # 'Query' is Logainm's free-text search parameter. Searches are
    # accent-sensitive and match exact wording, so "Ballinakill" finds
    # places named exactly that.
    response = requests.get(
        LOGAINM_BASE_URL,
        params={"Query": name},
        headers={"X-Api-Key": api_key},
        timeout=15,  # never hang forever on a slow network
    )
    # Turn any HTTP error (bad key = 401, etc.) into a clear exception.
    response.raise_for_status()

    # v1.0 returns a object where results live in "results" (not "Places").
    data = response.json()
    places = data.get("results", [])

    # Flatten each raw place record down to just the four fields we care about.
    matches = []
    for place in places:
        placenames = place.get("placenames", [])
        matches.append(
            {
                "english_name": _english_name(placenames),
                "irish_name": _irish_name(placenames),
                "county": _county(place),
                "feature_type": _feature_type(place),
            }
        )
    return matches


if __name__ == "__main__":
    # --- Example run -------------------------------------------------------
    # From the command line (after `pip install requests` and setting your key):
    #
    #     export LOGAINM_API_KEY="your-key-here"
    #     python3 logainm_lookup.py
    #
    # This looks up "Ballinakill" and shows all matches, highlighting Laois.
    search_term = "Ballinakill"
    matches = lookup_townland(search_term)

    if not matches:
        print(f'No places found for "{search_term}".')
    else:
        print(f'Found {len(matches)} place(s) for "{search_term}":\n')
        for m in matches:
            print(
                f"  {m['english_name']} ({m['irish_name']}) "
                f"- {m['feature_type']} in Co. {m['county']}"
            )

        # Pick out the Laois one specifically, to match the example.
        laois = [m for m in matches if m["county"] == "Laois"]
        if laois:
            print("\nIn County Laois:")
            for m in laois:
                print(f"  {m['english_name']} = {m['irish_name']} ({m['feature_type']})")

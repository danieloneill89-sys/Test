"""
logainm_lookup.py

A single, simple function for looking up an Irish townland (or other place)
by its English name using the Logainm API (the State's Placenames Database
of Ireland, logainm.ie).

Access method (confirmed June 2026):
  - Logainm exposes a JSON HTTP API. The documented base endpoint is
    https://www.logainm.ie/api/v0.9/
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

# The documented base URL of the Logainm API. It's a module-level constant
# so there's a single, obvious place to bump the version if the hub moves on
# (the developer hub currently also references a "v1.0").
LOGAINM_BASE_URL = "https://www.logainm.ie/api/v0.9/"


def _english_name(placenames):
    """Pull the English-language wording out of a place's 'Placenames' list.

    Each placename has a 'Language' code (ISO 639-1, so 'en' / 'ga') and the
    actual text in 'Wording'. We look for the English one; if none is tagged
    'en' we fall back to whichever name is marked 'Main', so we always return
    *something* sensible rather than crashing.
    """
    for p in placenames:
        if p.get("Language") == "en":
            return p.get("Wording")
    for p in placenames:
        if p.get("Main"):
            return p.get("Wording")
    return None


def _irish_name(placenames):
    """Pull the Irish-language ('ga') wording out of a place's 'Placenames'."""
    for p in placenames:
        if p.get("Language") == "ga":
            return p.get("Wording")
    return None


def _county(place):
    """Find the county a place sits in.

    Logainm models the administrative hierarchy in the 'IncludedIn' list:
    a townland is "included in" a civil parish, a barony, AND a county, etc.
    Each entry is a small summary with its own 'Category' (the kind of unit
    it is). We walk that list and return the one whose category is 'County'.
    """
    for unit in place.get("IncludedIn", []):
        category = unit.get("Category") or {}
        if category.get("NameEN") == "County":
            return unit.get("NameEN")
    return None


def _feature_type(place):
    """Return the place's own feature type, e.g. 'Townland' or 'Civil Parish'.

    A place can belong to several categories; the first is the primary one,
    which is what we want here.
    """
    categories = place.get("Categories", [])
    if categories:
        return categories[0].get("NameEN")
    return None


def lookup_townland(name):
    """Look up an English townland name in Logainm.

    Returns a list of matches, where each match is a small dict:
        {
            "english_name": str,
            "irish_name":   str | None,
            "county":       str | None,
            "feature_type": str | None,  # e.g. "Townland", "Civil Parish"
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

    # 'Query' is Logainm's free-text search parameter. Note from the docs:
    # searches are accent-sensitive and match exact wording, so "Ballinakill"
    # finds places named exactly that.
    response = requests.get(
        LOGAINM_BASE_URL,
        params={"Query": name},
        headers={"X-Api-Key": api_key},
        timeout=15,  # never hang forever on a slow network
    )
    # Turn any HTTP error (bad key = 401, etc.) into a clear exception.
    response.raise_for_status()

    # A search returns a "placeList" object. The actual records live in
    # "Places"; if Logainm found nothing, that list is simply empty.
    data = response.json()
    places = data.get("Places", [])

    # Flatten each raw place record down to just the four fields we care about.
    results = []
    for place in places:
        placenames = place.get("Placenames", [])
        results.append(
            {
                "english_name": _english_name(placenames),
                "irish_name": _irish_name(placenames),
                "county": _county(place),
                "feature_type": _feature_type(place),
            }
        )
    return results


if __name__ == "__main__":
    # --- Example run -------------------------------------------------------
    # From the command line (after `pip install requests` and setting your key):
    #
    #     export LOGAINM_API_KEY="your-key-here"
    #     python logainm_lookup.py
    #
    # This looks up "Ballinakill" and then shows the match(es) in Co. Laois.
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

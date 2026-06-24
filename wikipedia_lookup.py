"""
wikipedia_lookup.py

Optional enrichment source for the geo-history agent.

Wikipedia is not a primary source, but for townlands with a notable landmark,
castle, or famous family it often provides population history, named individuals,
and contextual narrative that the purely archaeological SMR record lacks.

Access method: Wikipedia REST API (no key, CC BY-SA).
  - Search:  https://en.wikipedia.org/w/api.php  (MediaWiki action API)
  - Summary: https://en.wikipedia.org/api/rest_v1/page/summary/{title}

Install: pip install requests  (already required)
"""

import requests

_SEARCH_URL  = "https://en.wikipedia.org/w/api.php"
_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{}"


def search_wikipedia(query, max_chars=700):
    """Search Wikipedia and return a summary for the best matching article.

    Args:
        query: free-text search, e.g. "Crumlin Dublin" or "Dunamase Castle Laois".
        max_chars: trim the extract to this length at a sentence boundary.

    Returns one of:
        {"found": True,  "title": str, "extract": str, "url": str}
        {"found": False, "query": query}
    """
    # Step 1 — find candidate articles.
    search_resp = requests.get(
        _SEARCH_URL,
        params={
            "action":      "query",
            "list":        "search",
            "srsearch":    query,
            "format":      "json",
            "srlimit":     5,
            "srnamespace": 0,   # main namespace only
        },
        timeout=12,
    )
    search_resp.raise_for_status()
    hits = search_resp.json().get("query", {}).get("search", [])
    if not hits:
        return {"found": False, "query": query}

    # Step 2 — fetch the full summary for the top hit.
    title   = hits[0]["title"]
    encoded = requests.utils.quote(title.replace(" ", "_"), safe="")
    sum_resp = requests.get(
        _SUMMARY_URL.format(encoded),
        headers={"Accept": "application/json"},
        timeout=12,
    )
    if sum_resp.status_code != 200:
        return {"found": False, "query": query}

    data    = sum_resp.json()
    extract = (data.get("extract") or "").strip()
    if not extract:
        return {"found": False, "query": query}

    # Trim to max_chars at the last sentence boundary so we don't mid-cut.
    if len(extract) > max_chars:
        cut = extract[:max_chars]
        boundary = max(cut.rfind(". "), cut.rfind(".\n"))
        if boundary > 80:
            cut = cut[:boundary + 1]
        extract = cut + "…"

    url = (
        data.get("content_urls", {}).get("desktop", {}).get("page")
        or f"https://en.wikipedia.org/wiki/{encoded}"
    )

    return {
        "found":   True,
        "title":   title,
        "extract": extract,
        "url":     url,
    }


if __name__ == "__main__":
    # Quick manual test
    #   python3 wikipedia_lookup.py
    result = search_wikipedia("Crumlin Dublin Ireland")
    if result["found"]:
        print(f"Title:   {result['title']}")
        print(f"URL:     {result['url']}")
        print(f"Extract: {result['extract'][:200]}...")
    else:
        print("Not found.")

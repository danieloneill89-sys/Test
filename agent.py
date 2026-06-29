"""
agent.py — geo-history agent (v3: four sources + townland boundaries)

Tools available to the model:
  lookup_townland     — Logainm: Irish name, etymology, historical forms, coordinate
  find_monuments      — NMS SMR: archaeological sites within the townland (or radius)
  search_wikipedia    — Wikipedia: additional context for notable places/landmarks
  find_built_heritage — NIAH: post-medieval buildings c.1700–1960 (nearby radius)

The monument search is sharpened by an OpenStreetMap townland boundary (looked
up automatically), so it can ask "what is recorded inside this townland?"
rather than "what is within 2 km of its centre?". Boundaries are best-effort:
if OSM has no shape or is unreachable, the search falls back to point+radius.
The NIAH search deliberately stays on a nearby radius — for built heritage it
is more useful to surface notable buildings just beyond the boundary too.
"""

import json
import re
import argparse

# Load keys from a local .env file (if present) before the Anthropic client or
# the Logainm lookup read them. Optional — falls back to real env vars.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from anthropic import Anthropic

from logainm_lookup import lookup_townland as _lookup_townland
from monuments_lookup import find_monuments_near
from wikipedia_lookup import search_wikipedia as _search_wikipedia
from boundary_lookup import find_boundary, find_neighbours
from niah_lookup import find_buildings_near

# Haiku drives the whole tool loop and the synthesis. It is ~3x cheaper than
# Sonnet ($1/$5 vs $3/$15 per 1M tokens) and faster, which matters because the
# API is stateless: every turn resends the full conversation, so a lean run is
# mostly about keeping the resent payload small (see the _lean_* trimmers below).
MODEL = "claude-haiku-4-5"

# How much of each tool result we feed back to the model. The UI still gets the
# full records (they live in `collected`); these caps only bound what is resent
# to the model on every subsequent turn, which is the main cost driver.
_MAX_MONUMENTS_TO_MODEL = 8
_MAX_BUILDINGS_TO_MODEL = 6
_MAX_HISTORICAL_FORMS_TO_MODEL = 8
_MAX_DESCRIPTION_CHARS = 240


def _clip(text, limit=_MAX_DESCRIPTION_CHARS):
    """Truncate a long free-text field at a word boundary for the model payload."""
    if not text or len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + "…"


def _lean_place(place):
    """Model-facing view of a Logainm record: just what steers the search and
    the synthesis. Drops UI-only fields (ids, permalink) and caps the dated
    historical forms, since the model only weaves in one or two."""
    return {
        "english_name":  place.get("english_name"),
        "irish_name":    place.get("irish_name"),
        "irish_genitive": place.get("irish_genitive"),
        "county":        place.get("county"),
        "feature_type":  place.get("feature_type"),
        "latitude":      place.get("latitude"),
        "longitude":     place.get("longitude"),
        "etymology":     place.get("etymology"),
        "historical_forms": (place.get("historical_forms") or [])[:_MAX_HISTORICAL_FORMS_TO_MODEL],
    }


def _lean_monument(m):
    """Model-facing view of one monument: class, SMR number (for citation),
    distance, and a clipped description. Drops townland/county (redundant)."""
    return {
        "monument_class": m.get("monument_class"),
        "smr_number":     m.get("smr_number"),
        "distance_km":    m.get("distance_km"),
        "description":    _clip(m.get("description")),
    }


def _lean_building(b):
    """Model-facing view of one NIAH building: what the synthesis can use.
    Drops UI-only fields (reg_no, url, image_url, current_use)."""
    return {
        "name":         b.get("name"),
        "original_use": b.get("original_use"),
        "date_text":    b.get("date_text"),
        "rating":       b.get("rating"),
        "distance_km":  b.get("distance_km"),
        "description":  _clip(b.get("description")),
    }

TOOLS = [
    {
        "name": "lookup_townland",
        "description": (
            "Look up an Irish townland by English name in the Logainm placenames database. "
            "Returns the Irish name, etymology (word-by-word meanings of the Irish components), "
            "county, feature type, and coordinate. "
            "Always call this first — the etymology tells you what was historically at this place "
            "and should guide everything you search for next."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "English townland name, e.g. 'Ballinakill'."
                },
                "county": {
                    "type": "string",
                    "description": "County to disambiguate, e.g. 'Laois'. Only needed if the name appears in multiple counties."
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "find_monuments",
        "description": (
            "Search the National Monuments Service Archaeological Survey of Ireland (SMR) for "
            "recorded archaeological monuments near a coordinate, steered by the etymology from "
            "lookup_townland. See radius_km for how the boundary-first / widen-if-thin search "
            "works, and monument_type to filter by a specific class."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "latitude": {
                    "type": "number",
                    "description": "Latitude (WGS84), from the lookup_townland result."
                },
                "longitude": {
                    "type": "number",
                    "description": "Longitude (WGS84), from the lookup_townland result."
                },
                "radius_km": {
                    "type": "number",
                    "description": (
                        "Optional. OMIT to search within the townland's own boundary (the preferred "
                        "first call). Provide a value to instead search a circle of that radius from "
                        "the centre — use this to widen the net (e.g. 3.0–5.0) when the townland "
                        "itself has little recorded, or when the etymology points to a major feature "
                        "that may sit just beyond the boundary."
                    )
                },
                "monument_type": {
                    "type": "string",
                    "description": (
                        "Optional filter for a specific monument class, e.g. 'Ringfort', 'Church', "
                        "'Holy Well', 'Castle'. Use this when the etymology strongly suggests one type."
                    )
                }
            },
            "required": ["latitude", "longitude"]
        }
    },
    {
        "name": "search_wikipedia",
        "description": (
            "Search Wikipedia for additional context about this townland or its notable features. "
            "Use this AFTER lookup_townland and find_monuments, and ONLY when the place is likely "
            "to have meaningful Wikipedia coverage — e.g. the etymology or SMR records mention a "
            "well-known castle, a famous monastery, a notable landlord estate, or a historically "
            "significant village. Skip it for obscure townlands with no distinctive features. "
            "Wikipedia is a secondary source — use it to add narrative colour (population history, "
            "named individuals, broader context) but ground all specific factual claims in Logainm "
            "or SMR records."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Search query, e.g. 'Crumlin Dublin history', 'Dunamase Castle Laois', "
                        "'Ballinakill Laois'. Include the county to reduce ambiguity."
                    )
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "find_built_heritage",
        "description": (
            "Search the National Inventory of Architectural Heritage (NIAH) for recorded "
            "buildings near a coordinate. The NIAH covers c.1700–1960 and catalogues "
            "post-medieval structures: mills, big houses, farmhouses, churches, forges, "
            "industrial buildings, and bridges. Call this AFTER find_monuments — it fills "
            "the gap between pre-1700 archaeology (SMR) and the modern landscape. "
            "Always call it; most townlands have at least one NIAH-rated building."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "latitude": {
                    "type": "number",
                    "description": "Latitude (WGS84), from the lookup_townland result."
                },
                "longitude": {
                    "type": "number",
                    "description": "Longitude (WGS84), from the lookup_townland result."
                },
                "radius_km": {
                    "type": "number",
                    "description": (
                        "Search radius in kilometres. Defaults to 2.0. "
                        "Use 3.0–5.0 for rural areas where estate buildings "
                        "may sit at a distance from the townland centre."
                    )
                }
            },
            "required": ["latitude", "longitude"]
        }
    },
]

SYSTEM_PROMPT = """<role>
You are a knowledgeable Irish local historian. Your job is to write a vivid, specific geo-history note about a townland — grounded entirely in the records the tools return. You write for a curious general reader, not an academic. Never invent dates, names, or details.
</role>

<process>
1. Call lookup_townland first. Note the Irish name, etymology, county, and any historical_forms with their dates.

2. Read the etymology — it is your primary clue about what was historically present:
   • ráth, lios, dún → ringforts or earthworks
   • cill, teampall, domhnach → early Christian / ecclesiastical sites
   • tobar → holy wells
   • coill, doire → woodland; search broadly
   • baile, achadh → settlement; search broadly
   • caisleán → castle
   • muileann → mill

3. Call find_monuments, steered by the etymology — search the boundary first and widen only if little is recorded (the tool's parameters explain how). Read each monument's description field; it carries specific detail beyond the class name. Watch for pattern: one ringfort is ordinary, but five signals a densely farmed early medieval landscape worth noting explicitly.

3b. Optionally call search_wikipedia (the tool description explains when it is worth calling). If you do, mine it for population figures, famine-era decline, named individuals, and significant events.

3c. Always call find_built_heritage. For each building note the name, original_use, rating, and especially date_text — a date like "c.1847" or "1780" often carries meaning (famine-era, pre-rebellion, plantation period).

4. Write the note — 2–3 short paragraphs synthesising all the evidence:
   • Historical forms: if a date is recorded (e.g. "Ballinachill, 1302"), write "first recorded in 1302 as..." — the century matters
   • Monuments: cite SMR numbers in parentheses; use the description text for specific detail; if multiple monuments of the same type appear, note the pattern
   • Buildings: lead with the highest-rated building, its original_use, and its date_text if present
   • Wikipedia: weave in naturally — population figures or famine-era decline are especially valuable for Irish townlands; do not cite a URL
   • Use ONLY facts from the tool results
</process>

<output_rules>
CRITICAL: Begin your response with the very first word of the historical note. No title. No preamble. No "Here is the note:" or any other opening phrase. No sign-off or closing sentence at the end.

After the final paragraph, on its own line, write exactly:
CURIOSITY: [one sentence — the single most surprising or unusual fact the records reveal about this place]
</output_rules>"""


def _execute_tool(name, inputs, collected):
    """Run one tool call and accumulate results into `collected`."""
    if name == "lookup_townland":
        results = _lookup_townland(inputs["name"], county=inputs.get("county"))
        if not results:
            return {"status": "not_found"}

        counties = sorted({m["county"] for m in results if m["county"]})
        if len(counties) > 1 and not inputs.get("county"):
            return {
                "status": "ambiguous",
                "counties": counties,
                "message": (
                    f"'{inputs['name']}' appears in {len(counties)} counties: "
                    f"{', '.join(counties)}. Call lookup_townland again with a specific county."
                ),
            }

        townlands = [m for m in results if m["feature_type"] == "townland"]
        place = townlands[0] if townlands else results[0]
        collected["place"] = place
        return {"status": "ok", "place": _lean_place(place)}

    if name == "find_monuments":
        place = collected.get("place") or {}
        # Resolve the townland boundary once, then reuse it. We cache even a
        # None result so a miss (or an Overpass outage) isn't retried per call.
        if "boundary" not in collected:
            try:
                collected["boundary"] = find_boundary(
                    inputs["latitude"],
                    inputs["longitude"],
                    county=place.get("county"),
                )
            except Exception:  # noqa: BLE001 - boundary is best-effort
                collected["boundary"] = None
            # Fetch neighbouring townlands once we have the OSM relation ID.
            # Best-effort — an empty list is fine; neighbours are decorative.
            osm_id = (collected["boundary"] or {}).get("osm_id")
            try:
                collected["neighbours"] = find_neighbours(osm_id) if osm_id else []
            except Exception:  # noqa: BLE001
                collected["neighbours"] = []
        boundary = collected["boundary"]

        # Default = search within the townland boundary. An explicit radius_km
        # means the model is deliberately widening, so honour the circle and
        # ignore the boundary for that call.
        widening = inputs.get("radius_km") is not None
        monuments = find_monuments_near(
            inputs["latitude"],
            inputs["longitude"],
            radius_km=inputs.get("radius_km", 2.0),
            boundary=None if widening else boundary,
        )
        # Apply optional type filter; fall back to unfiltered if it removes everything.
        monument_type = inputs.get("monument_type")
        if monument_type:
            filtered = [
                m for m in monuments
                if monument_type.lower() in (m["monument_class"] or "").lower()
            ]
            if filtered:
                monuments = filtered

        # Accumulate across multiple calls, deduplicating by SMR number.
        seen = {m["smr_number"] for m in collected.get("monuments", [])}
        new_ones = [m for m in monuments if m["smr_number"] not in seen]
        collected.setdefault("monuments", []).extend(new_ones)

        if widening or not boundary:
            scope = f"a {inputs.get('radius_km', 2.0)} km radius from the centre"
        else:
            area = boundary.get("area_km2")
            scope = ("within the townland boundary"
                     + (f" (~{area} km²)" if area else ""))
        # Feed back only the nearest few, trimmed — the synthesis cites a handful
        # of SMR numbers, not all fifteen, and this payload is resent every turn.
        lean = [_lean_monument(m) for m in monuments[:_MAX_MONUMENTS_TO_MODEL]]
        return {"count": len(monuments), "scope": scope, "monuments": lean}

    if name == "search_wikipedia":
        result = _search_wikipedia(inputs["query"])
        if result.get("found"):
            collected.setdefault("wikipedia", []).append(result)
        return result

    if name == "find_built_heritage":
        try:
            buildings = find_buildings_near(
                inputs["latitude"],
                inputs["longitude"],
                radius_km=inputs.get("radius_km", 2.0),
            )
        except RuntimeError as exc:
            return {"error": str(exc), "count": 0, "buildings": []}
        seen = {b["reg_no"] for b in collected.get("buildings", [])}
        new_ones = [b for b in buildings if b["reg_no"] not in seen]
        collected.setdefault("buildings", []).extend(new_ones)
        lean = [_lean_building(b) for b in buildings[:_MAX_BUILDINGS_TO_MODEL]]
        return {"count": len(buildings), "buildings": lean}

    return {"error": f"Unknown tool: {name}"}


def _strip_preamble(text):
    """Remove any conversational preamble the model adds before the note.

    Despite the system prompt, the model sometimes opens with chatter such as
    "Excellent — a rich set of 15 monuments returned. Here is the historical
    note:" optionally followed by a "---" rule. We can't rely on it starting
    with a fixed phrase, so we look for a preamble that ends in "... note:"
    (or "follows:") within the first few hundred characters and cut everything
    up to and including it, then trim any leading horizontal rule.
    """
    text = (text or "").strip()

    # Cut everything up to and including an opener that ends in "note:"/"follows:".
    opener = re.match(r'(?is)^.{0,400}?\b(?:note|follows|below)\s*:\s*', text)
    if opener:
        text = text[opener.end():]

    # Strip a leading markdown rule and any blank lines left behind.
    text = re.sub(r'^\s*(?:-{3,}\s*)+', '', text)
    return text.strip()


def run_agent(townland, county=None, default_radius_km=2.0):
    """Run the agentic pipeline and return a result dict.

    Returns one of:
        {"status": "ok",        "place": ..., "monuments": [...], "synthesis": "..."}
        {"status": "not_found"}
        {"status": "ambiguous", "counties": [...]}
    """
    client = Anthropic()
    collected = {}  # accumulates place and monuments as tools fire

    user_msg = f"Research the townland '{townland}'"
    if county:
        user_msg += f" in Co. {county}"
    user_msg += (
        f" and write a short historical note about it. "
        f"Search the townland's own boundary first; if little is recorded there, "
        f"widen to about {default_radius_km} km."
    )

    messages = [{"role": "user", "content": user_msg}]

    for _ in range(10):  # safety cap — a well-formed run needs 3–4 turns at most
        response = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            synthesis = next(
                (block.text for block in response.content if hasattr(block, "text")), ""
            )
            synthesis = _strip_preamble(synthesis)
            return {
                "status": "ok",
                "place": collected.get("place"),
                "boundary": collected.get("boundary"),
                "monuments": collected.get("monuments", []),
                "wikipedia": collected.get("wikipedia", []),
                "buildings": collected.get("buildings", []),
                "neighbours": collected.get("neighbours", []),
                "synthesis": synthesis,
            }

        # Process tool calls and feed results back into the conversation.
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result = _execute_tool(block.name, block.input, collected)
            # Surface not_found / ambiguous immediately rather than letting
            # Claude try to handle it — the caller (CLI or web) owns that UX.
            if result.get("status") in ("not_found", "ambiguous"):
                return result
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result),
            })

        if tool_results:
            messages.append({"role": "user", "content": tool_results})

    return {"status": "error", "message": "Agent did not complete within the turn limit."}


def main():
    parser = argparse.ArgumentParser(description="Geo-history agent for Irish townlands.")
    parser.add_argument("townland", nargs="?", default="Ballinakill",
                        help="English townland name (default: Ballinakill)")
    parser.add_argument("--county", default=None, help="County to disambiguate, e.g. Laois")
    parser.add_argument("--radius", type=float, default=2.0,
                        help="Starting monument search radius in km (default: 2.0)")
    args = parser.parse_args()

    result = run_agent(args.townland, county=args.county, default_radius_km=args.radius)

    if result["status"] == "not_found":
        print(f'No match found for "{args.townland}"'
              + (f' in Co. {args.county}.' if args.county else '.'))
        return

    if result["status"] == "ambiguous":
        print(f'"{args.townland}" appears in several counties:')
        for c in result["counties"]:
            print(f"  - {c}")
        print(f'\nRe-run with --county, e.g. '
              f'python3 agent.py "{args.townland}" --county "{result["counties"][0]}"')
        return

    p = result["place"]
    print(f"Found: {p['english_name']} ({p['irish_name']}), "
          f"{p['feature_type']} in Co. {p['county']}\n")
    b = result.get("boundary")
    if b:
        shape = "exact boundary" if b.get("polygon") else "bounding box"
        print(f"Townland boundary: {shape}, ~{b.get('area_km2')} km² (OSM {b.get('osm_id')}).")
    print(f"Found {len(result['monuments'])} monument(s), "
          f"{len(result.get('buildings', []))} NIAH building(s).\n")
    print("-" * 70)
    print(result["synthesis"])
    print("-" * 70)


if __name__ == "__main__":
    main()

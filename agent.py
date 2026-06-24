"""
agent.py — geo-history agent (v2: three sources)

Tools available to the model:
  lookup_townland  — Logainm: Irish name, etymology, historical forms, coordinate
  find_monuments   — NMS SMR: archaeological sites near the coordinate
  search_wikipedia — Wikipedia: additional context for notable places/landmarks
"""

import json
import re
import argparse

from anthropic import Anthropic

from logainm_lookup import lookup_townland as _lookup_townland
from monuments_lookup import find_monuments_near
from wikipedia_lookup import search_wikipedia as _search_wikipedia

SYNTHESIS_MODEL = "claude-sonnet-4-6"

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
            "Search the National Monuments Service Archaeological Survey of Ireland for recorded "
            "monuments near a coordinate. Use the etymology from lookup_townland to guide the search: "
            "words like 'ráth', 'lios', 'dún' suggest ringforts or enclosures; 'cill', 'teampall' "
            "suggest ecclesiastical sites; 'tobar' suggests holy wells; 'caisleán' suggests a castle. "
            "If nothing is found at the default radius, try a wider search before concluding there are "
            "no recorded monuments."
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
                        "Use smaller (0.5–1.0) for a tight local search; "
                        "use larger (3.0–5.0) if the etymology suggests a significant feature "
                        "that may sit just outside the townland boundary."
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
    }
]

SYSTEM_PROMPT = """You are a knowledgeable Irish local historian building a geo-history note about a townland.

Follow these steps:
1. Call lookup_townland to get the Irish name, etymology, and any historical forms of the name.
2. Read the etymology carefully — it is your primary clue about what was historically present:
   - Words like ráth, lios, dún → look for ringforts or earthworks
   - Words like cill, teampall, domhnach → look for early Christian / ecclesiastical sites
   - Words like tobar → look for holy wells
   - Words like coill, doire → woodland context, search broadly for any monuments
   - Words like baile, achadh → settlement, search broadly
3. Call find_monuments guided by what the etymology suggests. Adjust the radius and monument_type accordingly. If nothing is found, try a wider radius before concluding there are no recorded monuments.
3b. Optionally call search_wikipedia if the etymology or monuments suggest the place has notable Wikipedia coverage — a famous castle, a well-known monastic site, a historically significant village. Skip it for unremarkable townlands.
4. Write 2–3 short paragraphs synthesising ALL the evidence. Use ONLY facts from the tool results — do not invent dates, events, or details. Be vivid and specific: include named individuals, unusual architectural features, striking historical details. If historical_forms are present in the lookup result, weave in one or two to show how the name evolved across the centuries. Cite each monument's SMR number in parentheses. If Wikipedia was useful, you may mention it naturally but do not cite a URL — the synthesis should read as a continuous narrative.

OUTPUT FORMAT — follow exactly or the page will break:
• Begin with the very first word of the historical note. No title. No "Here is the note:". No preamble of any kind.
• No closing sentence or sign-off after the note ends.
• After the final paragraph, add one line formatted precisely as:
  CURIOSITY: [one sentence — the single most surprising or unusual fact the records reveal about this place]"""


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
        return {"status": "ok", "place": place}

    if name == "find_monuments":
        monuments = find_monuments_near(
            inputs["latitude"],
            inputs["longitude"],
            radius_km=inputs.get("radius_km", 2.0),
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
        return {"count": len(monuments), "monuments": monuments}

    if name == "search_wikipedia":
        result = _search_wikipedia(inputs["query"])
        if result.get("found"):
            collected.setdefault("wikipedia", []).append(result)
        return result

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
        f"Start with a {default_radius_km} km monument search radius."
    )

    messages = [{"role": "user", "content": user_msg}]

    for _ in range(10):  # safety cap — a well-formed run needs 3–4 turns at most
        response = client.messages.create(
            model=SYNTHESIS_MODEL,
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
                "monuments": collected.get("monuments", []),
                "wikipedia": collected.get("wikipedia", []),
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
    print(f"Found {len(result['monuments'])} monument(s).\n")
    print("-" * 70)
    print(result["synthesis"])
    print("-" * 70)


if __name__ == "__main__":
    main()

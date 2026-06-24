"""
agent.py — the geo-history agent (v0)

End to end:
  1. Take an English townland name (and optional county to disambiguate).
  2. Ask Logainm for the Irish name, etymology, county, and coordinate.
  3. Use that coordinate to ask the monuments database for nearby sites.
  4. Hand both results to Claude and ask for a short historical synthesis.
  5. Print it.

This v0 is a fixed pipeline (Logainm -> coordinate -> monuments -> synthesis).
It is the scaffold the "agentic" version grows from: later, the etymology from
step 2 can decide what step 3 actually looks for.

Install: pip install requests anthropic
Set two environment variables before running:
    export LOGAINM_API_KEY="your-logainm-key"
    export ANTHROPIC_API_KEY="your-anthropic-key"

Example:
    python3 agent.py Ballinakill --county Laois
"""

import argparse

from anthropic import Anthropic

from logainm_lookup import lookup_townland
from monuments_lookup import find_monuments_near

# The model that writes the synthesis.
SYNTHESIS_MODEL = "claude-sonnet-4-6"


def choose_place(matches):
    """Pick the single place to describe from Logainm's list of matches.

    The caller has already filtered by county if they gave one. From whatever
    remains we prefer the actual townland (the project's unit of interest) over
    the town or electoral division that may share the name and coordinate.
    """
    townlands = [m for m in matches if m["feature_type"] == "townland"]
    if townlands:
        return townlands[0]
    return matches[0]  # fall back to whatever we have


def build_prompt(place, monuments):
    """Assemble the human-readable brief we send to Claude.

    We give the model the *facts* (name, etymology, monuments) and ask it to do
    the one thing it's good at here: weave them into readable prose. We do NOT
    ask it to recall facts about the place from memory — everything it should
    rely on is in the brief, which keeps the output grounded in real records.
    """
    # Turn the etymology list into a simple readable block.
    if place["etymology"]:
        etymology_lines = "\n".join(
            f"  - {e['word']}: {e['meaning']}" for e in place["etymology"]
        )
    else:
        etymology_lines = "  (no word-by-word etymology recorded)"

    # Turn the monuments into a compact list. We trim each description so a
    # dozen long archaeological notes don't bloat the prompt.
    if monuments:
        monument_lines = []
        for m in monuments:
            note = (m["description"] or "").strip().replace("\n", " ")
            if len(note) > 400:
                note = note[:400] + "..."
            monument_lines.append(
                f"  - {m['monument_class']} ({m['distance_km']} km away): {note}"
            )
        monuments_block = "\n".join(monument_lines)
    else:
        monuments_block = "  (no recorded monuments found within the search radius)"

    return f"""You are a knowledgeable local historian writing a short note about an Irish townland. Use ONLY the facts provided below — do not add events, dates, or details that are not supported here. If the records are sparse, say so honestly.

PLACE
  English name: {place['english_name']}
  Irish name: {place['irish_name']} (genitive: {place['irish_genitive']})
  County: {place['county']}
  Type: {place['feature_type']}

WHAT THE IRISH NAME MEANS (etymology)
{etymology_lines}

RECORDED MONUMENTS NEARBY
{monuments_block}

Write two or three short paragraphs that connect the meaning of the name to what is physically recorded on the ground. Start from what the Irish name tells us, then bring in the monuments where they fit. Readable and grounded, the kind of note a knowledgeable local might write — not a data dump."""


def synthesize(prompt):
    """Send the brief to Claude and return the written synthesis.

    Anthropic() reads ANTHROPIC_API_KEY from the environment automatically.
    """
    client = Anthropic()
    message = client.messages.create(
        model=SYNTHESIS_MODEL,
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def main():
    parser = argparse.ArgumentParser(description="Geo-history agent for Irish townlands.")
    parser.add_argument("townland", nargs="?", default="Ballinakill",
                        help="English townland name (default: Ballinakill)")
    parser.add_argument("--county", default=None,
                        help="County to disambiguate, e.g. Laois")
    parser.add_argument("--radius", type=float, default=2.0,
                        help="Monument search radius in km (default: 2.0)")
    args = parser.parse_args()

    # --- Step 1 & 2: Logainm -------------------------------------------------
    matches = lookup_townland(args.townland, county=args.county)

    if not matches:
        # Could be a genuinely unknown name, or a county filter that excluded
        # everything. Either way, tell the user plainly.
        print(f'No Logainm match for "{args.townland}"'
              + (f' in Co. {args.county}.' if args.county else '.'))
        return

    # If the name is ambiguous across counties and the user didn't pick one,
    # don't guess — show the counties and ask them to narrow it down.
    counties = sorted({m["county"] for m in matches if m["county"]})
    if len(counties) > 1 and not args.county:
        print(f'"{args.townland}" matches places in several counties:')
        for c in counties:
            print(f"  - {c}")
        print('\nRe-run with --county, e.g. '
              f'python3 agent.py "{args.townland}" --county "{counties[0]}"')
        return

    place = choose_place(matches)
    print(f"Found: {place['english_name']} ({place['irish_name']}), "
          f"{place['feature_type']} in Co. {place['county']}\n")

    # --- Step 3: monuments ---------------------------------------------------
    # A coordinate is required to search for monuments. If Logainm has none,
    # we carry on with an empty list rather than crashing — the synthesis can
    # still work from the name alone.
    if place["latitude"] is None or place["longitude"] is None:
        print("No coordinate available — skipping the monuments search.\n")
        monuments = []
    else:
        monuments = find_monuments_near(
            place["latitude"], place["longitude"], radius_km=args.radius
        )
        print(f"Found {len(monuments)} recorded monument(s) within "
              f"{args.radius} km.\n")

    # --- Step 4 & 5: synthesise and print ------------------------------------
    prompt = build_prompt(place, monuments)
    print("-" * 70)
    print(synthesize(prompt))
    print("-" * 70)


if __name__ == "__main__":
    main()

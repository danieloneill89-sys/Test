"""
app.py — a small Flask web front end for the geo-history agent.

This does NOT reimplement any logic. It imports the exact same functions used
by agent.py and exposes them through a web page:

    browser  ->  Flask (/lookup)  ->  Logainm + monuments + Claude  ->  JSON

Run it locally:
    export LOGAINM_API_KEY="..."      # same keys as the CLI
    export ANTHROPIC_API_KEY="..."
    pip install -r requirements.txt
    python3 app.py
Then open http://localhost:5000 in your browser.

Your keys stay on your machine — the browser never sees them. It only ever
talks to your own local server.
"""

from flask import Flask, render_template, request, jsonify

# Reuse the building blocks we already wrote and tested.
from logainm_lookup import lookup_townland
from monuments_lookup import find_monuments_near
from agent import choose_place, build_prompt, synthesize

app = Flask(__name__)


def run_pipeline(townland, county, radius_km):
    """Run the full lookup + synthesis and return a plain dict for the page.

    The dict always has a "status" the front end can branch on:
        "ok"        -> includes place, monuments, synthesis
        "not_found" -> nothing matched
        "ambiguous" -> matched several counties; includes the list to choose from
    """
    matches = lookup_townland(townland, county=county or None)

    if not matches:
        return {"status": "not_found"}

    # If the name spans several counties and the user didn't pick one, don't
    # guess — hand the list back so the page can ask them to choose.
    counties = sorted({m["county"] for m in matches if m["county"]})
    if len(counties) > 1 and not county:
        return {"status": "ambiguous", "counties": counties}

    place = choose_place(matches)

    # Monuments need a coordinate; if there isn't one, carry on without them.
    if place["latitude"] is None or place["longitude"] is None:
        monuments = []
    else:
        monuments = find_monuments_near(
            place["latitude"], place["longitude"], radius_km=radius_km
        )

    synthesis = synthesize(build_prompt(place, monuments))

    return {
        "status": "ok",
        "place": place,
        "monuments": monuments,
        "synthesis": synthesis,
    }


@app.route("/")
def home():
    """Serve the single page."""
    return render_template("index.html")


@app.route("/lookup", methods=["POST"])
def lookup():
    """Receive a townland from the page, run the pipeline, return JSON."""
    data = request.get_json(force=True)
    townland = (data.get("townland") or "").strip()
    county = (data.get("county") or "").strip()
    # Radius arrives as text from the slider; default sensibly if it's odd.
    try:
        radius_km = float(data.get("radius") or 2.0)
    except ValueError:
        radius_km = 2.0

    if not townland:
        return jsonify({"status": "error", "message": "Please enter a townland name."})

    # Any unexpected failure (bad key, network, API change) becomes a clean
    # message on the page instead of a server crash.
    try:
        return jsonify(run_pipeline(townland, county, radius_km))
    except Exception as exc:  # noqa: BLE001 - we want to surface anything to the UI
        return jsonify({"status": "error", "message": str(exc)})


if __name__ == "__main__":
    # debug=True auto-reloads when you edit the code, and shows errors in detail.
    app.run(host="127.0.0.1", port=5000, debug=True)

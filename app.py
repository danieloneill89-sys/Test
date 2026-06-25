"""
app.py — a small Flask web front end for the geo-history agent.

This does NOT reimplement any logic. It imports the exact same functions used
by agent.py and exposes them through a web page:

    browser  ->  Flask (/lookup)  ->  Logainm + monuments + Claude  ->  JSON

Run it locally:
    pip install -r requirements.txt
    python3 app.py
Then open http://localhost:5001 in your browser.

API keys are read from a `.env` file in the project folder (LOGAINM_API_KEY
and ANTHROPIC_API_KEY) — copy `.env.example` to `.env` and fill them in once.
Already-set environment variables still take precedence, so `export VAR=...`
also works. Your keys stay on your machine — the browser never sees them; it
only ever talks to your own local server.
"""

# Load keys from a local .env file before anything reads the environment.
# Wrapped so the app still runs if python-dotenv isn't installed (you can
# always fall back to `export LOGAINM_API_KEY=...` etc.).
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from flask import Flask, render_template, request, jsonify

from agent import run_agent

app = Flask(__name__)


def run_pipeline(townland, county, radius_km):
    """Run the agentic pipeline and return a plain dict for the page.

    The dict always has a "status" the front end can branch on:
        "ok"        -> includes place, monuments, synthesis
        "not_found" -> nothing matched
        "ambiguous" -> matched several counties; includes the list to choose from
    """
    return run_agent(townland, county=county or None, default_radius_km=radius_km)


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
    # Port 5001 (not 5000) — macOS reserves 5000 for its AirPlay Receiver.
    app.run(host="127.0.0.1", port=5001, debug=True)

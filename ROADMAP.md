# Roadmap — An Áit (Irish geo-history agent)

A running list of where the project is and where it's going. This lives in the
repo so it survives between sessions and is visible on any machine.

## The goal

Take an Irish townland name and return a short, readable historical synthesis —
connecting the Irish etymology of the name to what is physically recorded on the
ground. Everything the synthesis says must be grounded in real records, not the
model's memory.

## Done

- **Logainm lookup** (`logainm_lookup.py`) — Irish name, etymology, historical
  name forms (dated documentary attestations), county, coordinate, and a
  permalink back to the canonical Logainm page.
- **Monuments lookup** (`monuments_lookup.py`) — archaeological sites near a
  coordinate from the National Monuments Service (SMR), nearest-first.
- **Wikipedia lookup** (`wikipedia_lookup.py`) — optional secondary source for
  notable places; searched only when etymology or monuments suggest meaningful
  coverage. Fails gracefully if unavailable.
- **Agentic pipeline** (`agent.py`) — Claude drives four tools via tool use:
  it reads the etymology, decides what monument types to search for and at what
  radius, optionally searches Wikipedia for additional context, and always queries
  the NIAH for post-medieval buildings. Ends with a vivid narrative synthesis
  that weaves all sources together. Includes a `CURIOSITY:` line — one striking
  fact from the records.
- **Web UI** (`app.py` + `templates/index.html`) — dark archival theme (near-
  black, amber accents, Fraunces serif + JetBrains Mono). Features: staggered
  rise animations, cycling loading messages, animated monument + building
  counters, curiosity callout box, stats strip, monument cards with type glyphs
  (◎ † ≈ ▲ ⊕), NIAH building cards with rating badges (National / Regional /
  Local), and an evidence drawer showing etymology pills, historical name forms,
  Wikipedia excerpt, NIAH buildings, and full monument list.
- **NIAH built heritage** (`niah_lookup.py`) — National Inventory of
  Architectural Heritage. Bridges the post-medieval gap (c.1700–1960) between
  the archaeological SMR and the modern landscape. Buildings rated N/R/L
  (National / Regional / Local interest).
- **Source citations** — Logainm permalink + SMR numbers + Wikipedia URL so
  every claim can be traced back to a record.
- **Sticky county bug fixed** — form fields have no hardcoded defaults.

## Next up (data — makes the output richer)

- **Dúchas folklore** (`duchas_lookup.py`) — the National Folklore Collection.
  Filters by Logainm ID, so it drops straight into our pipeline. Blocked: the
  v0.6 API currently returns HTTP 500 on all endpoints; emailed gaois@dcu.ie.
  This is the single biggest enrichment — it adds human stories (fairy forts,
  holy wells, local memory) that no other source provides.
- **Townland boundaries** (townlands.ie / OpenStreetMap) — the real *shape* of
  a townland instead of a single centre point, so the monument search matches
  the actual area rather than a radius from the centre.

## Next up (features)

- **Clickable map** — interactive Leaflet + OpenStreetMap map (no API key
  needed). Click a place instead of typing; monuments and buildings shown as pins.
  Best built *after* boundaries and folklore land, so the map has rich data to show.

## Maybe later

- Cache repeated townland lookups to avoid re-hitting the APIs.
- Prompt caching — only worth it once prompts get large (e.g. when folklore
  text is injected into the context).
- More sources investigated but not programmatically usable yet: census
  records (1901/1911/1926) and church records — both are web-only and block
  automation, so useful for manual research but not for the agent.

## Notes

- Models: the synthesis runs on `claude-sonnet-4-6` (capable, fast, cheap for
  the tool loop). No need for a larger model here.
- Keys are read from environment variables (`LOGAINM_API_KEY`,
  `ANTHROPIC_API_KEY`) and never hard-coded.
- Data sources: Logainm CC BY 4.0, National Monuments CC BY 4.0,
  NIAH CC BY 4.0, Wikipedia CC BY-SA, Dúchas CC BY 4.0 (pending API fix).

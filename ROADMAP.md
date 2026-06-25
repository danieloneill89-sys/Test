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
- **Monuments lookup** (`monuments_lookup.py`) — archaeological sites from the
  National Monuments Service (SMR), nearest-first. Searches within the townland's
  real boundary when one is known, otherwise a point+radius circle.
- **Townland boundaries** (`boundary_lookup.py`) — the real *shape* of a
  townland from OpenStreetMap (via Overpass), looked up by coordinate. Lets the
  monument search ask "what is recorded inside this townland?" instead of
  "within 2 km of its centre". Best-effort: falls back to point+radius if OSM
  has no shape or is unreachable.
- **Wikipedia lookup** (`wikipedia_lookup.py`) — optional secondary source for
  notable places; searched only when etymology or monuments suggest meaningful
  coverage. Fails gracefully if unavailable.
- **Agentic pipeline** (`agent.py`) — Claude drives three tools via tool use:
  it reads the etymology, decides what monument types to search for and at what
  radius, and optionally searches Wikipedia for additional context. Ends with a
  vivid narrative synthesis that weaves all sources together. Includes a
  `CURIOSITY:` line — one striking fact from the records.
- **Web UI** (`app.py` + `templates/index.html`) — dark archival theme (near-
  black, amber accents, Fraunces serif + JetBrains Mono). Features: staggered
  rise animations, cycling loading messages, animated monument counter, curiosity
  callout box, stats strip, monument cards with type glyphs (◎ † ≈ ▲ ⊕), and
  an evidence drawer showing etymology pills, historical name forms, Wikipedia
  excerpt, and full monument list.
- **Source citations** — Logainm permalink + SMR numbers + Wikipedia URL so
  every claim can be traced back to a record.
- **Sticky county bug fixed** — form fields have no hardcoded defaults.

## Next up (data — makes the output richer)

- **Dúchas folklore** (`duchas_lookup.py`) — the National Folklore Collection.
  Filters by Logainm ID, so it drops straight into our pipeline. Blocked: the
  v0.6 API currently returns HTTP 500 on all endpoints; emailed gaois@dcu.ie.
  This is the single biggest enrichment — it adds human stories (fairy forts,
  holy wells, local memory) that no other source provides.

## Next up (features)

- **Clickable map** — interactive Leaflet + OpenStreetMap map (no API key
  needed). Click a place instead of typing; monuments shown as pins. Best built
  *after* boundaries and folklore land, so the map has rich data to show.
- **NIAH built heritage** (buildingsofireland.ie) — bridges the gap between
  ancient archaeology (SMR, pre-1700) and the modern landscape. Catalogues
  1700–1900 buildings: mills, big houses, churches, bridges, forges.

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
  OpenStreetMap ODbL (townland boundaries), Wikipedia CC BY-SA,
  Dúchas CC BY 4.0 (pending API fix).

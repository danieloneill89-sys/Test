# Roadmap — An Áit (Irish geo-history agent)

A running list of where the project is and where it's going. This lives in the
repo so it survives between sessions and is visible on any machine.

## The goal

Take an Irish townland name and return a short, readable historical synthesis —
connecting the Irish etymology of the name to what is physically recorded on the
ground. Everything the synthesis says must be grounded in real records, not the
model's memory.

## Done

- **Logainm lookup** (`logainm_lookup.py`) — Irish name, etymology, county,
  coordinate, and a permalink back to the canonical Logainm page.
- **Monuments lookup** (`monuments_lookup.py`) — archaeological sites near a
  coordinate from the National Monuments Service (SMR), nearest-first.
- **Agentic pipeline** (`agent.py`) — Claude drives the lookups via tool use:
  it reads the etymology and decides what monument types to search for, at what
  radius, and whether to retry. No longer a fixed sequence.
- **Web UI** (`app.py` + `templates/index.html`) — themed Flask page with a
  search form, the synthesis, and an evidence drawer showing etymology and
  monuments (with SMR numbers).
- **Source citations** — Logainm permalink + SMR numbers so claims can be
  traced back to records.

## Next up (data — makes the output richer)

- **Dúchas folklore** (`duchas_lookup.py`) — the National Folklore Collection.
  Filters by Logainm ID, so it drops straight into our pipeline. Blocked: the
  v0.6 API currently returns HTTP 500 on all endpoints; emailed gaois@dcu.ie.
  This is the single biggest enrichment — it adds human stories (fairy forts,
  holy wells, local memory) to the etymology + archaeology we already have.
- **Townland boundaries** (townlands.ie / OpenStreetMap) — the real *shape* of
  a townland instead of a single centre point, so the monument search matches
  the actual area.

## Next up (features)

- **Clickable map** — interactive Leaflet + OpenStreetMap map (no API key
  needed). Click a place instead of typing; monuments shown as pins. Best built
  *after* boundaries and folklore land, so the map has rich data to show.
- **Fix sticky county field** — the county input in the web form keeps the
  previous search's value, which can wrongly filter a new search.

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
- Data sources are licensed CC BY 4.0 (Logainm, National Monuments, Dúchas).

# T-017 Implementation Report — GET /api/stats + live hero numbers

**Status:** DONE

## Scope

`onrecord/api.py` + `ui/index.html` + `ui/OnRecord App.dc.html` only (identical
edit to both UI files, kept byte-for-byte identical as before). Did not touch
`tests/`, `onrecord/ingest/prices.py`, or its tests (separate session's file
scope).

## `onrecord/api.py` — `GET /api/stats`

- `_compute_stats(index)`: one-pass enumeration over `index.get_doc(i)` for
  `i in range(index.doc_count())` (the same per-doc idiom `/api/tickers`
  already uses immediately above it), building the distinct-non-null
  `jurisdiction`/`ticker` sets and the `{source_type: count}` breakdown.
  Returns `{"documents", "jurisdictions", "tickers", "sources",
  "corpus_version": "v1"}`.
- Wired into `_lifespan`: `app.state.stats_cache = _compute_stats(...)` runs
  once, right after `app.state.index` is finalized (after the
  load-or-bootstrap-from-corpus branch), so it is computed exactly once at
  ASGI startup and never recomputed per request (AC-2). `None` when
  `app.state.index` is `None`.
- `GET /api/stats` route: returns `app.state.stats_cache` verbatim, or
  `_missing_index_response()` (the same flat 503 `{"error": ...}` shape every
  other data endpoint uses) when the cache is `None` (AC-3). `/health` is
  untouched and independent.
- Route placed directly after `/api/tickers`, before `/api/metrics`, matching
  the test report's/docstring's description of the enumeration idiom's
  location.
- Module docstring's endpoint-seam summary extended with a one-paragraph
  `/api/stats` entry for future readers.

## UI wiring (`ui/index.html`, `ui/OnRecord App.dc.html` — identical edit)

- Hero strip static figures replaced with template bindings:
  `24,412` → `{{ heroDocuments }}`, `31` → `{{ heroJurisdictions }}` (the
  `{{ tickerTotal }}` figure was already live from T-016 and is untouched).
- New `loadStats()` method, mirroring the existing `loadTickers()` /
  `loadMetrics()` fetch pattern (`this.fetchJson('/api/stats')`), called from
  `bootstrap()` alongside the other three on-mount fetches. Unlike
  `loadTickers()`, it is deliberately NOT a liveness probe — it only sets
  `state.stats` on a well-shaped 200, and leaves it `null` on any failure
  (503, network error, malformed body), never touching `apiDown`/`apiLive`.
- `render()` derives `heroDocuments`/`heroJurisdictions` from `state.stats`
  when present (formatted via a new small `fmtCount()` helper —
  `toLocaleString('en-US')` for thousands separators, e.g. `24,115`), falling
  back to the designer's original literal copy (`'24,412'` / `'31'`) whenever
  `state.stats` is `null` — covering both the loading window (first paint,
  before the fetch resolves) and any failure. The strip is therefore never
  blank, per the ticket's explicit requirement.
- No layout/style changes — same DOM structure, same inline styles, only the
  two text nodes became bindings.

## Verification

- `uv run pytest tests/unit/test_stats.py -v` → 3 passed (all 3 ACs green).
- `.tdd-swarm/run-local-gates.sh . tickets/T-017.md` → format/lint/full unit
  suite (310 passed)/spec-lint all green.
- Browser pass (own throwaway `uvicorn` instances on the worktree's corpus,
  not the shared swarm preview server):
  - Live index (24,115 docs bootstrapped from `corpus/v1/corpus.jsonl.gz`):
    hero strip renders **24,115 / 28 / 102** (documents/jurisdictions/
    tickers), matching `curl /api/stats` exactly
    (`{"documents":24115,"jurisdictions":28,"tickers":76,"sources":
    {"filing":958,"county_meeting":23157},"corpus_version":"v1"}` — note
    `tickers` in `/api/stats` counts *distinct tickers present in the
    index*, 76, vs. the hero's separate `{{ tickerTotal }}` which is the
    full 102-symbol registry universe from `/api/tickers`, an existing,
    unrelated T-016 figure). Network tab confirms a single
    `GET /api/stats` fired on mount.
  - Missing index (`ONRECORD_INDEX` pointed at a nonexistent dir): `curl`
    confirms 503 flat error; hero strip renders the untouched design copy
    **24,412 / 31 / 102** exactly as before, header shows the existing
    "demo data · API unreachable" state — strip never blank.

## Commit

`feat(T-017): add GET /api/stats and wire hero strip to live corpus numbers`
— stages exactly `onrecord/api.py`, `ui/index.html`,
`ui/OnRecord App.dc.html`, `.tdd-swarm/reports/T-017-impl.md`. No push.

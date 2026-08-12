# T-017 Test Agent Report — GET /api/stats (hero-strip live corpus numbers)

**Status:** DONE

## Scope

New file only: `tests/unit/test_stats.py`. Did not touch `test_api.py`,
`test_serve.py`, `onrecord/ingest/prices.py`, or any UI file (UI wiring is
verified by the orchestrator's browser pass per the ticket's Test Plan, no
pytest surface for it). Encodes tickets/T-017.md AC-1..AC-3, tagged
`spec(T-017:AC-n)`.

## Tests written (3)

1. `test_stats_returns_exact_counts_and_corpus_version` — `spec(T-017:AC-1)`.
   Builds a real `InvertedIndex` from 20 fixture `Doc`s: 12 `county_meeting`
   docs (ticker always `None`) spread 5/4/3 across 3 jurisdictions, 8
   `filing` docs (jurisdiction always `None`) spread 2/2/2/2 across 4
   tickers. Asserts the exact top-level key set, `documents == 20`,
   `jurisdictions == 3`, `tickers == 4` (both counts proven to correctly
   exclude the `None`-valued half of the corpus, not just tautologically
   match doc counts), `sources == {"county_meeting": 12, "filing": 8}`, and
   `corpus_version == "v1"`.
2. `test_stats_second_request_does_not_recount` — `spec(T-017:AC-2)`.
   Monkeypatches `InvertedIndex.get_doc` (wrapped, behavior-preserving) with
   a call counter, patched before the `TestClient` context is entered so it
   covers a computed-at-startup implementation as well as a
   lazy-memoized-on-first-request one. Asserts the counter is `> 0` after
   the first `/api/stats` request (proves the seam is actually wired to
   whatever enumeration strategy the implementation uses) and unchanged
   after a second request, plus both responses are byte-identical JSON.
3. `test_stats_503_when_index_missing_but_health_still_ok` —
   `spec(T-017:AC-3)`. Missing `ONRECORD_INDEX` → `/api/stats` 503s with the
   same flat `{"error": "<mentions index>"}` shape `test_api.py`'s AC-5
   section already pins for `/api/search`/`/api/tickers`; `/health` on the
   same client still 200s.

## Design decisions (ticket underspecified these; documented in full in the
file's module docstring)

- **`sources` shape**: pinned as exactly the `{source_type: count}`
  breakdown of source types actually present in the index (no zero-valued
  placeholder key for the ticket's illustrative third example, `"docket"`,
  which no ingestion adapter in this repo ever emits as a real
  `source_type` — grep confirms only `county_meeting`/`earnings_call`/
  `filing` occur). Mirrors how `jurisdictions`/`tickers` are exact observed
  counts, never padded to a larger universe.
- **`corpus_version`**: pinned as the literal string `"v1"` per the
  ticket's own JSON example — distinct from and unrelated to
  `onrecord/eval/run.py`'s `_corpus_version()` (returns `"unversioned"`,
  feeds a different history-row schema, no shared manifest).
- **AC-2 caching seam**: `InvertedIndex.get_doc` call-counting, chosen
  because it's the same public accessor `/api/tickers`'s existing
  implementation already loops over (`onrecord/api.py`, immediately above
  where `/api/stats` will land) — the established enumeration idiom in this
  file. Deliberately timing-free/agnostic to *when* the one-time count
  happens (eager at ASGI startup vs. lazy-memoized on first request both
  satisfy it).

## Achievability verification (throwaway patch, reverted)

Added a minimal `/api/stats` route + `_compute_stats` helper to
`onrecord/api.py` (eager computation at ASGI startup into
`app.state.stats_cache`, reusing the existing `_missing_index_response()`
503 helper). All 3 new tests went GREEN; the full existing
`test_api.py` + `test_serve.py` suite (46 tests) stayed green throughout.
Patch fully reverted via `git checkout -- onrecord/api.py` before commit —
confirmed via `git diff` (empty) and a final RED re-run (all 3 tests fail
cleanly: 2 via a 404 from the SPA catch-all since the route doesn't exist,
1 via the missing-index case's `404 != 503`).

## Gates

- `uv run ruff format --check tests/unit/test_stats.py` — clean.
- `uv run ruff check tests/unit/test_stats.py` — clean (0 violations).
- `uv run pytest tests/unit/test_stats.py -v` — 3 failed (RED, as required
  for a Test Agent handoff — `/api/stats` not implemented yet).
- `uv run pytest tests/unit/test_api.py tests/unit/test_serve.py -q` — 46
  passed, untouched.

## Handoff

Frozen after this commit — the Implementation Agent should make these 3
tests pass by adding `GET /api/stats` to `onrecord/api.py` (file scope per
the ticket: `onrecord/api.py`, `ui/**`), not by editing this test file.

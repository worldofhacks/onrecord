# T-008 Implementation Agent Report — FMP earnings-transcript adapter

**Status:** DONE

**File touched:** `onrecord/ingest/fmp.py` (only file in scope; frozen tests/
fixtures untouched)

## What was implemented

Minimal implementation of the two functions specified in the Test Agent's
API contract (`.tdd-swarm/reports/T-008-test.md`, mirrored in the
`tests/unit/ingest/test_fmp.py` module docstring):

- `parse_transcript(payload, ticker) -> list[Doc]` — pure, no I/O. Splits
  `payload["content"]` on newlines, matches leading `"Name: text"` markers
  (first `": "` on the line), merges consecutive same-speaker turns (space-
  joined), renumbers ids `fmp:<ticker>:<year>q<quarter>:turn<nnn>` after
  merge, normalizes `date` to `YYYY-MM-DD` (drops any time-of-day suffix),
  sets `source_type="earnings_call"`, `venue_type="coached"`,
  `jurisdiction=None`, populates `speaker`/`ticker`, and builds a
  `deep_link` from the FMP transcript endpoint URL + ticker/year/quarter
  query params (always `https://…`). Content with zero speaker markers
  falls back to exactly one whole-transcript Doc (`turn001`), per AC-4.
- `fetch_transcripts(ticker, quarters, api_key=None, transport=None) ->
  list[Doc]` — resolves the effective key from `api_key` or
  `FMP_API_KEY`; if neither is set (or blank), logs one INFO line naming
  `FMP_API_KEY` and returns `[]` with zero network calls (AC-2). Builds
  `httpx.Client(transport=transport)` and, per quarter (processed in
  order, one fully retried/skipped before the next starts), does one GET;
  on HTTP 429 sleeps via `time.sleep(...)` (module-level `import time`, so
  tests can monkeypatch it) and retries exactly once — a second 429 logs
  one line containing `"429"` and skips that quarter, continuing with the
  rest (AC-3). A successful response's `[0]` element is passed to
  `parse_transcript`. Logging goes through
  `logger = logging.getLogger(__name__)`.

No gold-plating: no caching, no configurable retry counts/backoff curves,
no pagination, no CLI wiring — matches the ticket's explicit timebox and
"Out of Scope" note.

## Verification

```
uv run pytest tests/unit/ingest/test_fmp.py -v
```
8 passed (all of AC-1..AC-4).

`.tdd-swarm/run-local-gates.sh . tickets/T-008.md`:
- format: 24 files already formatted
- lint: All checks passed!
- unit: 22 passed (full suite, no regressions)
- spec-lint: `spec-lint OK: all ACs covered for T-008`
- ALL LOCAL GATES GREEN

Zero live network in tests — every `fetch_transcripts` call in the test
suite passes an explicit `transport=` (`httpx.MockTransport`).

## Notes / deviations

None. No ambiguity encountered; the Test Agent's documented contract was
sufficient to implement against directly. No dispute raised.

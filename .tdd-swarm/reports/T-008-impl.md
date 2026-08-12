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

---

## AMENDMENT — security review REJECTED, fix applied

**Status:** DONE

Trigger: `.tdd-swarm/reports/T-008-review.md` REJECTED the original
implementation (commit `a174677`) with 1 Critical (C1: API key leaked in
plaintext via an unhandled `httpx.HTTPStatusError` on non-429 error
statuses — its `str()` embeds the `apikey` query param) and 2 Important
(I1: no name-validation on the speaker-marker split, so a continuation
line containing `": "` was emitted as its own bogus-speaker Doc; I2: same
root cause as C1 also aborted the whole multi-quarter batch instead of
skip-and-continue). The Test Agent extended the frozen suite at
`0c53e6b` with 5 new tests (13 total) pinning the corrected behavior.

### Fix

- **C1/I2 (`_fetch_one_quarter`):** branch on `response.status_code`
  *before* ever calling `raise_for_status()`. 429 keeps its existing
  single-backoff-retry-then-skip behavior. Any other status `>= 400` is
  now handled as a single-attempt (no retry) skip: log one line
  containing only `ticker`/`year`/`quarter`/`status_code` — never the
  URL, query params, or response body — and return `[]` for that quarter
  only, letting the batch continue to the rest of `quarters`.
  `httpx.HTTPStatusError` (whose `str()` is the leak vector, since it
  embeds the full request URL including `apikey=...`) is now never
  constructed for a non-429 status, so it can never propagate or be
  logged in any form.
- **I1 (`parse_transcript`):** added `_looks_like_speaker_name(prefix)` —
  1-5 whitespace-split words, every word matching
  `^[A-Z][A-Za-z'’\-]*$` (title-cased, internal apostrophe/hyphen
  allowed). A `"<prefix>: <rest>"` line is only treated as a new speaker
  turn if `prefix` passes this check; otherwise the *whole line*
  (verbatim, including its own `": "`) is appended, space-joined, onto
  the immediately preceding raw turn — or treated as an unmarked line if
  there is no preceding turn yet (preserves the existing AC-4
  whole-transcript fallback for markerless content). The existing
  consecutive-same-speaker merge pass runs unchanged on top of this.

### Verification

```
uv run pytest tests/unit/ingest/test_fmp.py -v
```
13 passed (8 original + 5 new: 3× parametrized non-429 status codes
[401/403/500], the 429-no-leak regression guard, and the colon-in-
continuation-line test).

`.tdd-swarm/run-local-gates.sh . tickets/T-008.md`:
- format: 24 files already formatted
- lint: All checks passed!
- unit: 27 passed (full suite, no regressions — 14 T-001 + 13 T-008)
- spec-lint: `spec-lint OK: all ACs covered for T-008`
- ALL LOCAL GATES GREEN

No key leakage: every new/changed log call site interpolates only
`ticker`/`year`/`quarter`/`status_code`; `response.raise_for_status()` is
no longer called anywhere in the module, so `httpx.HTTPStatusError`
(the confirmed leak vector) is never constructed. Verified by the new
`sentinel_key not in caplog.text` assertions across all three error-log
code paths (no-key, 429-skip, non-429-skip), all passing.

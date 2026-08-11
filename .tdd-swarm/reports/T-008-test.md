# T-008 Test Agent Report — FMP earnings-transcript adapter

**Status:** DONE (frozen failing tests written, confirmed RED against the empty
`onrecord/ingest/fmp.py` stub, confirmed GREEN against a throwaway correct
implementation built in an isolated scratch copy — never in this worktree)

**Test file:** `tests/unit/ingest/test_fmp.py` (plus `tests/unit/ingest/__init__.py`)

**Fixtures:**
- `tests/fixtures/fmp/transcript_basic.json` — VST 2025 Q2, 3 speakers
  (Operator, Jim Burke, Kristopher Moldovan), 6 turns, no consecutive
  same-speaker repeats (AC-1).
- `tests/fixtures/fmp/transcript_consecutive_speaker.json` — VST 2025 Q1,
  4 raw turns with one consecutive same-speaker pair (Jim Burke × 2), to
  exercise the merge behavior named in AC-1/ticket context.
- `tests/fixtures/fmp/transcript_no_speaker_markers.json` — VST 2024 Q3,
  single narrative paragraph with zero `"Name: text"` markers (AC-4).

**Run command:**
```
uv run pytest tests/unit/ingest/test_fmp.py -v
```

## API contract designed and documented (ticket left this unpinned)

`tickets/T-008.md` specifies behavior at the acceptance-criteria level but not
the exact function contract. Per the task, the contract below was designed and
is documented in full at the top of `tests/unit/ingest/test_fmp.py` — treat it
as authoritative for the Implementation Agent, same status as T-001's test
report documenting the registry schema:

- `parse_transcript(payload: dict, ticker: str) -> list[Doc]` — pure, no I/O.
  Turns are lines matching `SpeakerName: text` at column 0; consecutive
  same-speaker turns merge (texts joined with a single space); ids
  `fmp:<ticker>:<year>q<quarter>:turn<nnn>` (1-indexed, 3-digit zero-padded,
  renumbered after merge); `date` normalized to `"YYYY-MM-DD"` (payload dates
  may carry a time-of-day suffix); `source_type="earnings_call"`,
  `venue_type="coached"`, `ticker=ticker`, `jurisdiction=None`; `deep_link`
  only constrained to be a non-empty `http(s)://` URL (ticket leaves the exact
  target flexible — "FMP-cited URL or ticker IR page"). No markers at all →
  exactly one whole-transcript Doc (`turn001`), never zero for non-empty
  content.
- `fetch_transcripts(ticker, quarters, api_key=None, transport=None) -> list[Doc]`.
  `quarters` is a list of `(year, quarter)` int tuples processed in order,
  each run to completion (incl. retry) before the next starts. Effective key
  = `api_key` or `os.environ["FMP_API_KEY"]`; if neither is set, log exactly
  one line naming `FMP_API_KEY` and return `[]` with **no network call**
  attempted at all (enforced in tests via a transport that raises if invoked).
  `transport` is the httpx dependency-injection point. Backoff MUST go
  through `import time; time.sleep(...)` (not `from time import sleep`) so
  tests can monkeypatch it globally. On 429: sleep, retry exactly once; if
  still failing, log exactly one line containing `"429"` and skip that
  quarter, continuing with the rest — no exception ever escapes.
  **Logging MUST use `logger = logging.getLogger(__name__)`** (name
  `"onrecord.ingest.fmp"`) — pinned explicitly so tests can isolate the
  adapter's own log lines from httpx's own INFO-level request/response
  logging (see gotcha below).

## Criterion → test mapping

| Criterion | Test(s) | What it checks |
|---|---|---|
| AC-1 | `test_parse_transcript_basic_three_speakers_six_turns` | Fixture with 3 speakers / 6 turns (no consecutive repeats) → exactly 6 Docs; exact ids, speakers, `source_type`, `venue_type`, `ticker`, `jurisdiction is None`, `date`, non-empty `http(s)` `deep_link`, spot-checked text |
| AC-1 | `test_parse_transcript_merges_consecutive_same_speaker_turns` | 4 raw turns with 1 consecutive same-speaker pair → merges to exactly 3 Docs; merged Doc's text is the exact single-space join of the two source turns, in order |
| AC-2 | `test_fetch_transcripts_no_api_key_returns_empty_with_one_log_line` | `FMP_API_KEY` env deleted, `api_key=None` explicit, network-guard transport (raises if ever called) → `[]`, exactly one log record mentioning `FMP_API_KEY`, no exception |
| AC-2 | `test_fetch_transcripts_no_api_key_default_param_and_unset_env` | Same, but `api_key` omitted entirely (exercises the default-parameter path, not just an explicit `None`) |
| AC-3 | `test_fetch_transcripts_429_retries_once_then_skips_and_logs` | Transport always returns 429; a 3rd call raises `AssertionError` (proves no more than 1 retry happens) → exactly 2 HTTP calls, `[]` result, exactly one log line containing `"429"`, no exception |
| AC-3 | `test_fetch_transcripts_429_skip_does_not_block_other_quarters` | Two quarters: first succeeds (200, real transcript body), second permanently 429s → result equals exactly the first quarter's parsed Docs (skip contributes nothing), 3 total HTTP calls (1 + 2), exactly one 429 log line |
| AC-4 | `test_parse_transcript_no_speaker_markers_yields_single_whole_transcript_doc` | Content with zero `Name:` markers → exactly 1 Doc, whole (stripped) content as text, correct id/fields |
| AC-4 | `test_parse_transcript_never_returns_zero_docs_for_non_empty_markerless_content` | Second, independent markerless payload (inline, not a fixture file) reinforcing the "never zero" property with different content/ticker/date |

8 test items total, all 4 ACs tagged `spec(T-008:AC-n)`; `spec-lint.sh` confirms
full coverage.

## Gotcha found and fixed during authoring (achievability verification)

While building the throwaway reference implementation to prove the tests are
achievable (see below), the two AC-3 tests initially failed against a
*correct* implementation: `caplog.at_level(logging.INFO)` without a `logger=`
argument also raises the **root** logger's level, which lets httpx's own
internal `httpx._client` INFO-level request/response logging through —
and that log line's text ("HTTP/1.1 429 Too Many Requests") itself contains
the substring `"429"`, so the message-substring count came out to 3 instead of
1 (2 httpx lines + 1 real adapter line). Fixed by scoping every
`caplog.at_level(...)` call in this file to `logger="onrecord.ingest.fmp"`,
and pinning `logging.getLogger(__name__)` as part of the documented contract
so this isolation is reliable for the real implementation too. Documented in
the module docstring so the Implementation Agent doesn't need to rediscover
this.

## Verification performed

1. Ran the suite against the current (stub) worktree — all 8 tests fail, each
   with a clean `Failed: onrecord.ingest.fmp.<name> is not implemented yet`
   message (via a `_callable_or_fail` guard) — no raw tracebacks, no pytest
   collection errors. Full output below.
2. Built a throwaway correct implementation in an isolated **scratch copy** of
   the repo (`/private/tmp/.../scratchpad/t008-verify`, never inside
   `/Users/quietguy/Documents/Dev/Gauntlet/wt-T-008`) satisfying the contract
   above, ran `uv sync` + the suite there, and confirmed all 8 tests **pass**.
   This confirms the tests are achievable and not vacuously red. Found and
   fixed the httpx-logging gotcha above during this pass, then re-verified
   GREEN. The scratch copy was deleted afterwards; `onrecord/ingest/fmp.py`
   in this worktree was never touched.
3. `uv run ruff format --check tests/` and `uv run ruff check tests/` — both
   clean.
4. `uv run pytest -q` (full suite) — `8 failed, 14 passed` (the 14 are
   T-001's pre-existing scaffold tests; unaffected, confirming no regression
   to the existing baseline).
5. `.tdd-swarm/spec-lint.sh tickets/T-008.md` → `spec-lint OK: all ACs covered
   for T-008`.
6. Zero live network in any test: `fetch_transcripts` is always called with an
   explicit `transport=` (either a network-guard `httpx.MockTransport` for the
   no-key tests, or a scripted `httpx.MockTransport` for the 429 tests); no
   test relies on a real HTTP connection.

## Failure output (current worktree, RED)

```
============================= test session starts ==============================
platform darwin -- Python 3.13.13, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/quietguy/Documents/Dev/Gauntlet/wt-T-008
collecting ... collected 8 items

tests/unit/ingest/test_fmp.py::test_parse_transcript_basic_three_speakers_six_turns FAILED [ 12%]
tests/unit/ingest/test_fmp.py::test_parse_transcript_merges_consecutive_same_speaker_turns FAILED [ 25%]
tests/unit/ingest/test_fmp.py::test_fetch_transcripts_no_api_key_returns_empty_with_one_log_line FAILED [ 37%]
tests/unit/ingest/test_fmp.py::test_fetch_transcripts_no_api_key_default_param_and_unset_env FAILED [ 50%]
tests/unit/ingest/test_fmp.py::test_fetch_transcripts_429_retries_once_then_skips_and_logs FAILED [ 62%]
tests/unit/ingest/test_fmp.py::test_fetch_transcripts_429_skip_does_not_block_other_quarters FAILED [ 75%]
tests/unit/ingest/test_fmp.py::test_parse_transcript_no_speaker_markers_yields_single_whole_transcript_doc FAILED [ 87%]
tests/unit/ingest/test_fmp.py::test_parse_transcript_never_returns_zero_docs_for_non_empty_markerless_content FAILED [100%]

=================================== FAILURES ===================================
(all 8 failures are the same shape — a clean pytest.fail via _callable_or_fail,
not an uncaught exception, e.g.:)

test_parse_transcript_basic_three_speakers_six_turns
  Failed: onrecord.ingest.fmp.parse_transcript is not implemented yet
  (module has no callable named 'parse_transcript')

test_fetch_transcripts_no_api_key_returns_empty_with_one_log_line
  Failed: onrecord.ingest.fmp.fetch_transcripts is not implemented yet
  (module has no callable named 'fetch_transcripts')

=========================== short test summary info ============================
FAILED tests/unit/ingest/test_fmp.py::test_parse_transcript_basic_three_speakers_six_turns
FAILED tests/unit/ingest/test_fmp.py::test_parse_transcript_merges_consecutive_same_speaker_turns
FAILED tests/unit/ingest/test_fmp.py::test_fetch_transcripts_no_api_key_returns_empty_with_one_log_line
FAILED tests/unit/ingest/test_fmp.py::test_fetch_transcripts_no_api_key_default_param_and_unset_env
FAILED tests/unit/ingest/test_fmp.py::test_fetch_transcripts_429_retries_once_then_skips_and_logs
FAILED tests/unit/ingest/test_fmp.py::test_fetch_transcripts_429_skip_does_not_block_other_quarters
FAILED tests/unit/ingest/test_fmp.py::test_parse_transcript_no_speaker_markers_yields_single_whole_transcript_doc
FAILED tests/unit/ingest/test_fmp.py::test_parse_transcript_never_returns_zero_docs_for_non_empty_markerless_content
============================== 8 failed in 0.15s ===============================
```

## Notes for the Implementation Agent

- Do not edit `tests/unit/ingest/test_fmp.py` or `tests/fixtures/fmp/*.json`
  to make them pass — these are frozen. If a genuine ambiguity or defect is
  found, escalate to the orchestrator/Reviewer rather than editing directly.
- `NotImplementedError` raised by a partial stub is treated identically to a
  missing function by these tests (`_call_or_fail` converts it into the same
  clean `pytest.fail`) — landing signature stubs that `raise
  NotImplementedError(...)` first is a safe intermediate step.
- Remember the `logging.getLogger(__name__)` requirement — using `print()`
  would also fail the repo's debug gate (`onrecord/ingest/` is not `cli/` or
  `scripts/`).
- `deep_link` format is intentionally loose (only "non-empty http(s) URL" is
  asserted) — pick whatever the ticket's "FMP-cited URL or ticker IR page"
  note suggests; it will not fail these tests either way.

---

## AMENDMENT — security review REJECTED, frozen suite extended

**Status:** DONE (5 new failing tests appended, confirmed to fail against the
current implementation for the reviewed reasons — existing 8 tests untouched
and still green — confirmed achievable GREEN against a throwaway *fixed*
implementation built in a second isolated scratch copy)

Trigger: `.tdd-swarm/reports/T-008-review.md` (Security/Review agent) rejected
the T-008 implementation (`onrecord/ingest/fmp.py` @ `a174677`) with **1
Critical, 2 Important** findings:

- **C1 (Critical):** an unhandled `httpx.HTTPStatusError` on any non-429 error
  status (401/403/5xx) propagates out of `fetch_transcripts`; its default
  `str()` embeds the full request URL **including the plaintext `apikey`
  query parameter** — a confirmed, reproducible secret-leak vector if any
  caller does standard exception logging.
- **I2 (Important):** same root cause — a non-429 error aborts the whole
  `for year, quarter in quarters` loop instead of skipping that quarter and
  continuing, unlike the (already-correct) 429 path.
- **I1 (Important):** the speaker-marker split (`line.partition(": ")`) has no
  validation that the pre-colon text is actually a name; a continuation line
  that merely contains `": "` (e.g. `"Turning to guidance: our outlook
  improved."`) is mis-parsed as its own turn with a bogus `speaker`.

Per the coordinator, this is addressed by **extending** the frozen suite (not
implementing the fix — that stays the Implementation Agent's job on
`onrecord/ingest/fmp.py`, untouched by the Test Agent).

### New fixture

- `tests/fixtures/fmp/transcript_colon_continuation.json` — NVDA 2025 Q4, 4
  lines: `Operator: ...`, `Jensen Huang: ...`, a bare continuation line
  `Turning to guidance: our full-year outlook remains unchanged from last
  quarter, and demand for Blackwell continues to outstrip supply across every
  major cloud partner.` (no real speaker prefix, but contains `": "` mid-line),
  then `Colette Kress: ...`. Correct parse: 3 Docs (Operator, Jensen Huang
  [continuation merged in], Colette Kress) — never 4.

### Contract amendment (documented in the docstring `AMENDMENT` block)

- **Speaker-name heuristic (pins the I1 fix):** a `"<prefix>: <rest>"` line is
  a new speaker turn only if `<prefix>` has 1-5 whitespace-split words and
  *every* word is title-cased (`^[A-Z][A-Za-z'\-]*$`-style — internal
  apostrophes/hyphens allowed). Otherwise it's continuation text, space-joined
  onto the immediately preceding raw turn (or treated as an unmarked line if
  there is no preceding turn yet). `"Turning to guidance"` fails on the word
  `"to"` (not title-cased) — by design, this is the pinned counter-example.
- **Non-429 HTTP error handling (pins the C1/I2 fix):** any status ≥400 other
  than 429 is a single-attempt (no retry, unlike 429's one backoff retry),
  skip-and-log-exactly-once, continue-with-remaining-quarters outcome — and
  **no exception of any kind (especially not `httpx.HTTPStatusError`) may
  ever escape `fetch_transcripts`** for an HTTP error status, precisely
  because that exception's `str()` is the leak vector.
- **No-key-leakage guarantee:** the effective API key must never appear
  anywhere in this module's log output, on *any* code path (no-key, 429-skip,
  or non-429-skip) — tests use a distinctive sentinel key
  (`"SENTINEL-KEY-XYZ"`) and assert `sentinel_key not in caplog.text`.

### New tests (all appended after the original 8; none of the original 8 were
modified)

| Criterion | Test(s) | What it checks |
|---|---|---|
| AC-3 | `test_fetch_transcripts_non_429_error_skips_continues_no_key_leak[401\|403\|500]` (parametrized, 3 cases) | First quarter returns the given status (no retry expected — exactly 1 call for it), second quarter still succeeds → result equals only the second quarter's Docs; exactly 2 total HTTP calls; exactly one log record from `onrecord.ingest.fmp`; **`sentinel_key not in caplog.text`** (the security-critical assertion); `_call_or_fail` intentionally does NOT catch `httpx.HTTPStatusError`, so against the current implementation this test fails via that uncaught exception itself — the clearest possible demonstration of C1 |
| AC-3 | `test_fetch_transcripts_429_skip_never_leaks_api_key_in_logs` | Re-verifies, with the same sentinel key, that the (already-correct) 429 skip-and-log path also never leaks the key into `caplog.text` — a defensive regression pin, not a new behavior; already passes against the current implementation |
| AC-1 | `test_parse_transcript_colon_in_continuation_line_merges_not_bogus_speaker` | `transcript_colon_continuation.json` → exactly 3 Docs (not 4); asserts `"Turning to guidance"` never appears as a `speaker`; asserts the exact merged text of Jensen Huang's turn (original turn + continuation line, space-joined, continuation's `"Turning to guidance: "` prefix preserved verbatim since it was never actually split) |

5 new test items (7 with parametrization expanded), all tagged
`spec(T-008:AC-1)` or `spec(T-008:AC-3)`; `spec-lint.sh` still reports full
coverage (these ACs were already covered by the original 8 — the amendment
tightens them, it doesn't add a new AC).

### Verification performed (amendment)

1. Ran the extended suite against the current implementation (`a174677`):
   **4 of the 5 new tests fail**, each for the reviewed reason —
   - `test_fetch_transcripts_non_429_error_skips_continues_no_key_leak[401]`,
     `[403]`, `[500]`: fail with an **uncaught `httpx.HTTPStatusError`**
     whose message literally reads `".../earning_call_transcript/VST?quarter=1&year=2025&apikey=SENTINEL-KEY-XYZ"`
     — directly reproducing C1 in a frozen, automated test.
   - `test_parse_transcript_colon_in_continuation_line_merges_not_bogus_speaker`:
     fails with `assert 4 == 3`, `speaker='Turning to guidance'` visible in the
     4th Doc — directly reproducing I1.
   - `test_fetch_transcripts_429_skip_never_leaks_api_key_in_logs` **passes**
     already (the 429 path was never the leak vector) — included as a
     permanent regression guard, not a new-failure demonstration.
   - The original 8 tests are unaffected: **9 passed, 4 failed** for
     `tests/unit/ingest/test_fmp.py` (8 original + 1 already-passing new one).
2. Built a *second* throwaway implementation in a new isolated scratch copy
   (`/private/tmp/.../scratchpad/t008-verify2`, again never inside this
   worktree) that fixes all three findings (name-heuristic filter on the
   speaker split; a `status_code >= 400` branch in `_fetch_one_quarter` that
   logs a sanitized ticker/year/quarter/status-code-only message and returns
   `[]` — never calling `raise_for_status()` for non-429 statuses, so
   `HTTPStatusError` is never even constructed). Ran the full extended suite
   there: **all 13 tests pass**. Confirms the amendment is achievable and not
   vacuously red/green. Scratch copy deleted afterwards;
   `onrecord/ingest/fmp.py` in this worktree was never touched.
3. `uv run ruff format --check tests/` and `uv run ruff check tests/` — clean.
4. `uv run pytest -q` (full repo suite) — `4 failed, 23 passed` (14 T-001
   baseline + 9 T-008-original-and-already-passing; no regression).
5. `.tdd-swarm/spec-lint.sh tickets/T-008.md` → still
   `spec-lint OK: all ACs covered for T-008`.

### Notes for the Implementation Agent (amendment)

- Do not edit `tests/unit/ingest/test_fmp.py` or any file under
  `tests/fixtures/fmp/` to make the new tests pass — same frozen-suite rule as
  before, now covering the amendment section too.
- The security fix should avoid ever constructing an `HTTPStatusError` for a
  non-429 status at all (branch on `response.status_code` before calling
  `raise_for_status()`), rather than catching-and-re-logging it — catching
  and then naively logging `str(exc)` would still leak the key and would
  **not** satisfy `sentinel_key not in caplog.text`.
- The name heuristic only needs to be good enough to reject
  `"Turning to guidance"` (fails on the lowercase word `"to"`) while still
  accepting every real speaker name already used across all fixtures
  (`Operator`, `Jim Burke`, `Kristopher Moldovan`, `Jensen Huang`,
  `Colette Kress`) — no fixture requires unicode names, honorifics, or
  hyphenated/apostrophe'd names, though the documented heuristic allows the
  latter two.

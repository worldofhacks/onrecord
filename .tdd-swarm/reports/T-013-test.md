# T-013 Test Agent Report — FastAPI layer (/api/search, /api/tickers, /api/metrics, /api/answer, /health)

**Status:** DONE (see "Update — op whitelist + k bounds" below for the
current state; original section preserved beneath it).

## Update — op whitelist + k bounds → 422 (post-review fix round)

**Trigger:** Review (`.tdd-swarm/reports/T-013-review.md`) APPROVED T-013
but flagged 1 Important + folded in 1 Minor, both live-confirmed against the
real ~24k-doc corpus: `GET /api/search?op=XOR` crashes with an unhandled
`ValueError` → a raw **500**, not a clean 422, because `op` had no
whitelist before reaching `boolean_search` (which itself only accepts
`"AND"`/`"OR"`, uppercase); separately, `k<=0` (e.g. `k=-5`) silently
returns a confusing-but-not-crashing result set via Python's negative-slice
semantics on `hits[:k]` instead of erroring. Both closed here by extending
the still-frozen `tests/unit/test_api.py` (no other files touched) — same
pattern as T-009's criterion-drift extension.

**New pinned contract** (module docstring's new "Extension — `op` whitelist
+ `k` lower bound" section has full detail):
- `op` whitelist is **exactly `"AND"` / `"OR"`, case-sensitive, uppercase
  only** — Test Agent design decision, resolving the review's explicit ask
  to "pin whether case-insensitive-accepted or 422." Chose uppercase-only
  to mirror `mode`'s existing Literal-style whitelist and
  `boolean_search`'s own uppercase-only contract, rather than inventing a
  case-folding rule nothing else in the codebase has. `"and"`/`"or"`/`"Or"`
  and any other value all 422.
- `k` must be a positive integer (`>= 1`), mirroring `onrecord/cli.py`'s
  `--k` convention exactly (`_positive_int`: "`--k` must be `>= 1`");
  `k <= 0` is 422.

**7 new failing tests** (all `spec(T-013:AC-1)` — same AC as the rest of
`/api/search`'s request-handling correctness, not a new AC), plus 3 new
"valid value still works" guard tests (passing, proving the pinned fix
doesn't over-reject legitimate `op=AND`/`op=OR`/`k=1` requests):

| Test | Result | What it checks |
|---|---|---|
| `test_search_invalid_op_returns_422_never_500` (parametrized `XOR`/`and`/`or`/`Or`) | **FAILED** — clean `assert 500 == 422` (not an uncaught exception) | reproduces the reviewer's exact live repro as a proper test failure |
| `test_search_valid_uppercase_op_still_works` (parametrized `AND`/`OR`) | passed | fix doesn't break the legitimate values |
| `test_search_non_positive_k_returns_422` (parametrized `0`/`-1`/`-5`) | **FAILED** — clean `assert 200 == 422` | `k<=0` currently 200s instead of 422ing |
| `test_search_k_equal_to_one_still_works` | passed | `k=1` (smallest valid) still works, no off-by-one |

**Test-harness change**: `_client(...)` gained an additive
`raise_server_exceptions: bool = True` keyword (default preserves every
prior call site byte-for-byte). The new op=XOR-style tests pass
`raise_server_exceptions=False` so an unhandled server exception comes back
as an actual `500` `Response` object (matching how a real deployed
`uvicorn` process behaves) instead of `TestClient`'s default of re-raising
the exception straight into the test process — which would otherwise turn
"op=XOR should 422, not 500" into an uncaught-exception test **ERROR**
instead of a clean, readable `assert resp.status_code == 422` failure
against a real `500` response. Confirmed both ways empirically before
settling on `False` for these 7 tests.

**Verification:**
1. `uv run --with fastapi --with 'httpx>=0.27' -- pytest tests/unit/test_api.py -v`
   against the current implementation (`onrecord/api.py` as committed by
   the Implementation Agent, `c58f0c5`) → **7 failed, 24 passed** — the
   original 21 tests are untouched and still green; exactly the 7 new
   `op`/`k` scenarios fail, cleanly (`assert 500 == 422` / `assert 200 ==
   422`, never an uncaught exception or collection error).
2. Full-repo regression, plain `uv run pytest -q` (fastapi is now a real
   pyproject dependency post-implementation, so no `--with` needed) →
   **7 failed, 207 passed** (204 prior baseline + 3 new passing guard
   tests = 207; the 7 new op/k tests are the only red).
3. `bash .tdd-swarm/spec-lint.sh tickets/T-013.md` → still `spec-lint OK:
   all ACs covered for T-013`.
4. `uv run ruff format tests/unit/test_api.py` (1 file reformatted) then
   `uv run ruff format --check tests/` → clean; `uv run ruff check tests/`
   → `All checks passed!`.
5. `git status --short` before commit: only `tests/unit/test_api.py`
   modified — no implementation files touched. (`.tdd-swarm/reports/
   T-013-review.md` is present in the worktree as the Reviewer's own
   artifact but is not this Test Agent's file and is left uncommitted
   here, per "commit only your files.")

**Notes for the Implementation Agent (round 2):**
- Simplest fix for `op`: type it `Literal["AND", "OR"]` (api.py:169),
  exactly mirroring how `mode` already gets free pydantic validation
  (api.py:168) — no manual whitelist code needed.
- Simplest fix for `k`: `Query(ge=1)` (or equivalent) instead of a bare
  `int = 20` default (api.py:170).
- Do not edit the 10 new/changed tests in `tests/unit/test_api.py` to make
  them pass — frozen, same as the rest of the file. If a genuine ambiguity
  is found, escalate rather than editing directly.

---

## Original report (initial handoff)

**Status:** DONE (frozen failing tests written; confirmed RED against the
current worktree, which has no `onrecord/api.py`; confirmed GREEN against a
throwaway reference implementation built outside the worktree, temporarily
copied in, run, then deleted — never committed).

**Test file:** `tests/unit/test_api.py` (21 test items, all individually
guarded against missing-module collection errors).

**Run command** (fastapi/uvicorn are NOT yet pyproject deps — the
Implementer adds them per the ticket's declared dep change):
```
uv run --with fastapi --with 'httpx>=0.27' -- pytest tests/unit/test_api.py -v
```

## Scope addition (mid-flight, owner-directed via coordinator)

While writing this file, the coordinator relayed an owner-directed addition:
the commissioned UI grew a grounded-Q&A "Ask" surface. Folded in before
freezing: `POST /api/answer` (JSON body `{"question", "mode", "k"}`) → for
now, 200 `{"error": "available_thursday"}`; missing `question` → 422. Tagged
`spec(T-013:AC-2)` (same AC as the `/api/search` semantic teaser — both are
stubbed "not yet" 200 responses gated by a 422 on bad input). The full
Thursday response contract (`answer_id`, `text` with `[n]` citation markers,
`citations[]`, `retrieved[]` with `cited` flags, `grounding`, `refusal`) is
pinned in the test file's module docstring as **PINNED-FOR-THURSDAY** —
documented, not implemented, not tested — so the RAG ticket freezes against
it without renegotiating shape with the UI later. 2 tests added
(`test_answer_returns_available_thursday_teaser`,
`test_answer_missing_question_returns_422`), both included in the 21/21
totals below.

## Why this file defines the API precisely

`onrecord/api.py` doesn't exist yet — no stub. The ticket sketches the
endpoint shapes but leaves several things unpinned. Per the task, this test
file's module docstring is the frozen, load-bearing contract (the UI is
built against it). Full detail is in the docstring; summary of the Test
Agent's design decisions where the ticket underspecified:

- **Two-layer import guard**: `pytest.importorskip("fastapi")` at module
  scope (fastapi isn't a pyproject dep yet — a plain `uv run pytest -q` run
  by any other in-flight ticket's agent, or the orchestrator, before T-013
  is implemented must not collection-error on this file; it now cleanly
  *skips* instead) **+** the standard `_require_module_spec(...)` /
  `pytest.fail("onrecord.api missing")` guard per test (this ticket's own
  target module). Verified both independently (see Verification below).
- **`/api/search` result shape**: exactly 9 keys per result
  (`doc_id, score, snippet` + `date, source_type, venue_type, jurisdiction,
  ticker, deep_link`) — `speaker` deliberately excluded (not in the
  ticket's AC-1 field list). Top-level body exactly
  `{"query", "mode", "results"}`.
- **`op` default `"OR"`**: read from the ticket's own example querystring
  (`op=OR`) as an illustrative default, same as `mode=lexical`/`k=20` in
  the same string. Filter combination (`source`/`venue`/`ticker`/
  `jurisdiction`) is AND, never OR — directly tested via an adversarial
  case (NEE's only doc is a filing, not an earnings_call; combining those
  two filters must yield `[]`, not the union).
- **Analyzer**: fixture indexes are built with the REAL analyzer
  (`InvertedIndex.build(docs)`, `analyzer=None`, T-002 already merged) —
  not the "trivial analyzer" the task permitted — because `boolean_search`'s
  own query-time default is also the real analyzer; a mismatched tokenizer
  at build time would silently break every match.
- **`mode=lexical` T-011 feature-detection**: pinned in the docstring
  (`ranked_search` used if importable, else `boolean_search` fallback with
  `score=0.0`) but only the fallback path is testable in this worktree
  (`onrecord/search/ranked.py` doesn't exist here — confirmed via
  `find onrecord -type f`). Flagged for re-verification at wave-5
  integration once T-011 merges.
- **`/api/tickers`**: registry-driven (`onrecord.registry.load()`'s
  `"tickers"` list), not corpus-driven — every registered ticker appears,
  zero-count or not. `receipt_count`/`last_receipt` computed via
  `index.get_doc(i) for i in range(index.doc_count())` (public API only,
  valid because fresh `.build()` indexes have contiguous internal ids —
  never reaches into `InvertedIndex`'s private `_docs`). Deterministic
  ordering pinned: sectors alpha by name, tickers alpha by symbol within a
  sector. Monkeypatch seam: `onrecord/api.py` MUST
  `from onrecord import registry` and call `registry.load()` fresh per
  request (mirrors the T-009 lesson on monkeypatchable module-level
  access — see `.tdd-swarm/reports/T-009-test.md`).
- **`/api/metrics`**: bare JSON array (not wrapped), independent of index
  state (tested with a simultaneously-missing index to prove this).
  Monkeypatch seam: module-level `SCOREBOARD_PATH` string constant, read
  fresh per-request.
- **AC-5 "data endpoints"**: read the ticket's Context paragraph ("missing
  index → 503 ... on data endpoints", plural) rather than just the AC-5
  bullet's one named example — `/api/search` **and** `/api/tickers` both
  503 on a missing index; `/api/metrics` and `/api/answer` are
  index-independent and never 503. Startup/env-var re-read seam: index
  loading happens in an ASGI startup handler reading `ONRECORD_INDEX` at
  *call* time (not baked in at module import), confirmed empirically to
  re-run on every `with TestClient(app) as client:` entry against the
  throwaway reference app, which is what makes per-test index swapping
  work at all.
- **503 body shape gotcha**: must be built via
  `fastapi.responses.JSONResponse(status_code=503, content={"error": ...})`
  directly, NOT `raise HTTPException(...)` — the latter wraps the body in
  `{"detail": ...}` by default, which would silently break the pinned flat
  `{"error": ...}` shape. Hit this exact bug while writing the throwaway
  reference app; called it out explicitly in the docstring for the
  Implementation Agent.

## Criterion → test mapping

| AC | Tests | What they check |
|---|---|---|
| guard | `test_api_module_is_importable` | clean `pytest.fail` on missing module, not a collection error |
| AC-1 | `test_search_returns_full_field_set_with_correct_values` | exact top-level + per-result key sets, correct values incl. `null` ticker/jurisdiction |
| AC-1 | `test_search_filters_narrow_results_by_metadata` (parametrized ×4: source/venue/ticker/jurisdiction) | each filter narrows correctly in isolation |
| AC-1 | `test_search_multiple_filters_combine_with_and_not_or` | adversarial: AND-combination, not OR |
| AC-1 | `test_search_op_and_narrows_to_docs_containing_all_terms` / `test_search_default_op_is_or` | `op` threading + pinned default |
| AC-1 | `test_search_k_truncates_after_filtering` | truncation order cross-checked against a direct `boolean_search` call (ground truth computed independently in-test, not hardcoded) |
| AC-2 | `test_search_semantic_and_hybrid_modes_return_available_wednesday_teaser` (parametrized) | exact `{"error": "available_wednesday"}` body |
| AC-2 | `test_search_unknown_mode_returns_422` | 422 on bad `mode` |
| AC-2 | `test_answer_returns_available_thursday_teaser` / `test_answer_missing_question_returns_422` | scope addition — stub teaser + 422 on missing `question`, index-independent |
| AC-3 | `test_tickers_groups_by_sector_with_receipt_counts` | sector grouping, receipt counts, `last_receipt` = max date, zero-count ticker included, unlisted-ticker doc silently excluded, deterministic ordering |
| AC-4 | `test_metrics_empty_list_when_scoreboard_missing_and_index_missing` | `[]` when absent, AND proves index-independence |
| AC-4 | `test_metrics_returns_parsed_rows_in_file_order` | exact round-trip incl. blank-line tolerance |
| AC-5 | `test_health_200_regardless_of_index_state` | 200 both with missing and present index |
| AC-5 | `test_search_503_with_actionable_message_when_index_missing` / `test_tickers_503_with_actionable_message_when_index_missing` | 503 + flat `{"error": ...}` body containing "index", for both data endpoints |

21 test items collected total (1 guard + 20 AC-tagged; the table above lists
test *definitions* — `test_search_filters_narrow_results_by_metadata` and
`test_search_semantic_and_hybrid_modes_return_available_wednesday_teaser`
each expand to multiple collected IDs via `@pytest.mark.parametrize`,
already included in the 21 total — confirmed via
`pytest --collect-only -q` → `21 tests collected`).

## Verification performed

1. **Achievability**: built a throwaway reference `onrecord/api.py` in the
   scratchpad (`/private/tmp/.../scratchpad/ref_impl/api.py`), temporarily
   copied it into `onrecord/api.py` in this worktree, ran
   `uv run --with fastapi --with 'httpx>=0.27' -- pytest tests/unit/test_api.py -v`
   → **21 passed** (all parametrized cases green). Then `rm onrecord/api.py`
   and cleared `__pycache__`; `git status --short` confirmed only
   `tests/unit/test_api.py` remains — zero diff outside `tests/`.
2. **RED against the real worktree** (no `onrecord/api.py`): same command →
   **21 failed**, every failure a clean `Failed: onrecord.api missing` from
   the `pytest.fail` guard — no uncaught `ImportError`, no collection
   error.
3. **Skip-when-fastapi-absent guard**: `uv run pytest tests/unit/test_api.py -v`
   (no `--with`, fastapi genuinely not installed in the project venv) →
   **1 skipped**, confirming `pytest.importorskip("fastapi")` fires cleanly
   instead of a `ModuleNotFoundError` collection error.
4. **Full-repo regression** (plain `uv run pytest -q`, no fastapi): **183
   passed, 1 skipped** — the pre-existing 183-test baseline is fully
   preserved; the new file contributes only a clean skip in this
   environment.
5. `bash .tdd-swarm/spec-lint.sh tickets/T-013.md` → `spec-lint OK: all ACs
   covered for T-013`.
6. `uv run ruff format tests/unit/test_api.py` (1 file reformatted — a
   single over-long `client.post(...)` call) then
   `uv run ruff format --check tests/` → clean, and
   `uv run ruff check tests/` → `All checks passed!`.
7. `git status --short` before commit: only `tests/unit/test_api.py`
   (+ this report) — no implementation files touched, nothing left over
   from the throwaway verification.

## Notes for the Implementation Agent

- Every pinned contract detail (exact JSON key sets, ordering, monkeypatch
  seams, the `JSONResponse`-not-`HTTPException` 503-body gotcha, the
  startup-event-reads-env-at-call-time requirement) is in
  `tests/unit/test_api.py`'s module docstring — read it in full before
  implementing, not just the ACs below.
- `README.md`'s Definition of Done item (`uv run uvicorn onrecord.api:app`
  documented in an API section) is out of this Test Agent's `test_scopes`
  (README.md isn't in `tests/`) — left for the Implementation Agent.
- The reference app used `@app.on_event("startup")`, which current FastAPI
  flags as deprecated in favor of `lifespan` context-manager handlers; the
  tests don't care which mechanism is used as long as `ONRECORD_INDEX` is
  re-read at each TestClient `__enter__`, but the Implementer may prefer
  `lifespan=` for a warning-free implementation.
- `onrecord/search/ranked.py` (T-011) does not exist in this worktree —
  only the boolean-fallback path is exercised here. Wave-5 integration
  should independently re-verify the `ranked_search`-present branch once
  T-011 merges (not this ticket's job, per its Out of Scope).
- Do not edit `tests/unit/test_api.py` to make it pass — frozen. If a
  genuine ambiguity or defect is found, escalate to the orchestrator/
  Reviewer rather than editing directly.

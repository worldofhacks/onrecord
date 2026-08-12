# T-013 Implementation Agent Report — FastAPI layer (/api/search, /api/tickers, /api/metrics, /api/answer, /health)

**Status:** DONE — all 31 tests in `tests/unit/test_api.py` pass (21
original + 10 added by the post-review contract extension at `5d32cd3`);
full repo suite green at 214 passing (183 baseline + 31); all Tier-1 local
gates green.

## Update — review follow-up (op whitelist + k lower bound)

Review (`.tdd-swarm/reports/T-013-review.md`, verdict APPROVED) flagged one
Important finding, live-confirmed against the real ~24k-doc corpus:
`GET /api/search?op=XOR` crashed with an unhandled `ValueError` (from
`onrecord.search.boolean.boolean_search`'s own
`raise ValueError(f"unknown boolean op: {op!r}")`) → a raw 500, not a clean
422. A related Minor finding: `k<=0` (e.g. `k=-5`) silently returned a
confusing-but-not-crashing result set via Python's negative-slice semantics
on `hits[:k]`, instead of erroring. Neither was a violation of the
originally-frozen contract (both were explicitly out of scope at first
freeze), but the Test Agent closed both by extending AC-1's pinned contract
(`5d32cd3`, +10 new test cases: `test_search_invalid_op_returns_422_never_500`
×4, `test_search_valid_uppercase_op_still_works` ×2,
`test_search_non_positive_k_returns_422` ×3,
`test_search_k_equal_to_one_still_works` ×1) rather than deferring to a
follow-up ticket.

**Fix (`onrecord/api.py` only, same file-scope rule as before):**
- `op: str = "OR"` → `op: Literal["AND", "OR"] = "OR"` — matches `mode`'s
  existing `Literal`-whitelist pattern, gets 422-on-mismatch for free from
  FastAPI/pydantic query validation, and is case-sensitive/uppercase-only
  per the Test Agent's pinned design decision (mirrors
  `boolean_search`'s own uppercase-only contract; `"and"`/`"or"`/`"Or"` all
  422, never silently case-folded).
- `k: int = 20` → `k: int = Query(default=20, ge=1)` — FastAPI's `Query`
  constraint produces a native 422 for `k <= 0` before the handler body
  ever runs (no manual bounds-check code needed), mirroring
  `onrecord/cli.py`'s `--k >= 1` convention.
- Module docstring updated with a short note on both constraints, pointing
  at `.tdd-swarm/reports/T-013-test.md`'s "op whitelist + k bounds"
  extension for the full pinned rationale.

**Verification (this update):**
- `uv run pytest tests/unit/test_api.py -v` → **31/31 passed** (the 10 new
  cases all green, including the two "still works" guard tests confirming
  the fix didn't over-reject `op=AND`/`OR` uppercase or `k=1`).
- Live smoke test (in-process `TestClient(app, raise_server_exceptions=False)`,
  reproducing the reviewer's exact repro cases): `op=XOR` → 422 (was 500),
  `op=and` (lowercase) → 422, `k=-5` → 422 (was 200 with a wrong-but-quiet
  result set), `k=0` → 422 — all four now match the pinned contract.
- `.tdd-swarm/run-local-gates.sh . tickets/T-013.md` → format clean, lint
  clean, **214 passed**, spec-lint OK, **ALL LOCAL GATES GREEN**.
- No `BLOCKED(TEST_DISPUTE)` — the extension's pinned contract was
  unambiguous and directly implementable; no test edits were needed or
  made.

Commit: `fix(T-013): op whitelist + k lower bound → 422` (staged exactly
`onrecord/api.py`, on top of the review's test-extension commit `5d32cd3`).

---

## Original report (initial handoff)

**Files touched (file scope, as instructed):**
- `onrecord/api.py` (new)
- `pyproject.toml` (added `fastapi>=0.115` + `uvicorn>=0.30` to
  `[project.dependencies]` — the ticket's declared dep change; nothing else
  touched)
- `uv.lock` (regenerated via `uv lock`, committed alongside)
- `README.md` (appended a new `## API` section per the Definition of Done)

No `tests/` file touched. `onrecord/cli_ranked_patch.py`, listed in the
ticket frontmatter's `file_scopes` but absent from the task instructions and
from `tests/unit/test_api.py`'s `test_scopes`, was intentionally not
created — no test exercises a CLI ranked-mode path in this worktree, and
inventing an untested file risked scope creep past the frozen contract.
Flagging this discrepancy for the orchestrator rather than guessing.

## Implementation summary

`onrecord/api.py` — new FastAPI app implementing every contract pinned in
`tests/unit/test_api.py`'s module docstring:

- **Index lifecycle (AC-5)**: a `lifespan` async context manager (not the
  deprecated `@app.on_event("startup")` the Test Agent's throwaway reference
  used — chosen per that report's own "Implementer may prefer `lifespan=`
  for a warning-free implementation" note) reads `ONRECORD_INDEX` from
  `os.environ` at *call* time (default `artifacts/index`, mirrors
  `onrecord/cli.py`'s `DEFAULT_INDEX_DIR`), stores the loaded
  `InvertedIndex` (or `None` on any load failure) on `app.state.index`.
  `/health` never touches it. `/api/search` and `/api/tickers` return a
  flat `JSONResponse(status_code=503, content={"error": "...index..."})`
  (built directly, never `raise HTTPException`, per the docstring's
  explicit gotcha callout) when `app.state.index is None`.
- **`GET /api/search`**: `mode: Literal["lexical", "semantic", "hybrid"]`
  query param — an invalid value 422s automatically via pydantic/FastAPI
  query validation, no manual check needed. `semantic`/`hybrid` short-circuit
  to `{"error": "available_wednesday"}` before touching the index (also
  works with a missing index, though untested). `lexical` feature-detects
  `onrecord.search.ranked.ranked_search` via a bare `try/except ImportError`
  import inside `_resolve_search_fn()`; absent in this worktree (T-011 not
  merged here), so every concrete test exercises the
  `boolean_search(index, q, op)` fallback (`score` always `0.0`). Metadata
  filters (`source`/`venue`/`ticker`/`jurisdiction`) are applied via a
  private `_matches(doc)` closure — AND-combined (each given filter must
  match; `None` filters are no-ops) — then results are truncated to `k`
  **after** filtering (mirrors `onrecord/cli.py`'s established order).
  Each result dict is built by `_doc_to_result_dict`, which emits exactly
  the pinned 9 keys (`doc_id, score, snippet` + 6 `Doc` fields;
  `speaker` excluded).
- **`POST /api/answer`**: a pydantic `AnswerRequest(question: str, mode: str
  = "lexical", k: int = 10)` body model — missing `question` 422s via
  pydantic body validation with zero extra code. Always returns
  `{"error": "available_thursday"}`, never touching `app.state.index`
  (works identically with a missing index, as the frozen test confirms).
- **`GET /api/tickers`**: `from onrecord import registry` at module level,
  `registry.load()` called fresh inside the handler (not cached) so
  `monkeypatch.setattr(api_module.registry, "load", fake)` works. Counts +
  `last_receipt` (max `Doc.date` string, ISO strings sort lexicographically)
  are computed via the pinned public-API iteration seam
  (`index.get_doc(i) for i in range(index.doc_count())`), skipping docs
  with a falsy `ticker`. Sectors built only from `registry.load()["tickers"]`
  entries — a doc whose ticker isn't registered is silently never counted
  (loop never visits it), and a registered ticker with zero matches still
  appears (`receipt_count=0, last_receipt=None`, since `dict.get` on the
  empty counts/last_receipt maps returns those defaults). Deterministic
  ordering: sectors sorted ascending by name, tickers within a sector
  sorted ascending by symbol.
- **`GET /api/metrics`**: module-level `SCOREBOARD_PATH = "artifacts/scoreboard.jsonl"`
  constant, read fresh via `Path(SCOREBOARD_PATH)` inside the handler (not
  captured in a closure at import time) so
  `monkeypatch.setattr(api_module, "SCOREBOARD_PATH", ...)` works. Returns
  `[]` when the path doesn't exist; otherwise parses one JSON object per
  non-blank line, in file order, verbatim — a bare JSON array, not wrapped.
  Never touches `app.state.index`.
- **CORS**: `CORSMiddleware` allowing `http://localhost:5173` (untested per
  the docstring's explicit out-of-scope note, but required by the ticket).

**`README.md`**: appended a new `## API` section (after the existing
"Searching directly" section) with the `uv run uvicorn onrecord.api:app
--reload` run command, a note on `ONRECORD_INDEX`/missing-index behavior/
CORS, and a table of all 5 endpoints — satisfying the DoD's
`uv run uvicorn onrecord.api:app` documentation requirement.

## Decisions / notes

- **`lifespan` over `on_event`**: the Test Agent's report explicitly flagged
  `on_event("startup")` as deprecated in current FastAPI and said the tests
  don't care which mechanism is used as long as `ONRECORD_INDEX` is re-read
  per `TestClient` `__enter__`. Verified empirically: switching to
  `lifespan=` keeps all 21 tests green and removes the
  `DeprecationWarning` that appeared during an initial `on_event`-based
  draft.
- **`q` has no explicit default-required marker** — a plain `str = ""`
  function parameter. Untested (every test passes `q` explicitly), but
  `boolean_search(index, "", op)` already degrades to `[]` gracefully per
  its own docstring, so an absent `q` never crashes.
- **`op` stays a bare unvalidated `str = "OR"`** — the module docstring
  explicitly says op-value validation is not pinned/tested; threaded
  straight into `boolean_search`'s own `op` param, which raises
  `ValueError` on a truly unknown op (untested here, matches the
  docstring's "implementer's choice" framing).
- **`onrecord/cli_ranked_patch.py` not created** — see "Files touched"
  above; the task instructions' explicit file scope (`onrecord/api.py` +
  `pyproject.toml` + `README.md`) superseded the ticket frontmatter's
  broader `file_scopes` list, and no test in `test_scopes` exercises it.
- No `BLOCKED(TEST_DISPUTE)`. The pinned contracts in
  `tests/unit/test_api.py`'s module docstring were unambiguous and directly
  implementable exactly as written; no ambiguity required escalation, and
  `tests/` was never touched.

## Verification performed

1. `uv run pytest tests/unit/test_api.py -v` → **21/21 passed**, 1 residual
   warning (`starlette.testclient`'s own httpx-deprecation notice, unrelated
   to this module — not something `onrecord/api.py` controls).
2. `uv run pytest -q` (full repo suite) → **204 passed** (baseline 183 + 21
   new; no regressions, no skips — fastapi/uvicorn are now real deps so the
   file's `importorskip` guard passes straight through).
3. `.tdd-swarm/run-local-gates.sh . tickets/T-013.md`:
   - format: `39 files already formatted`
   - lint: `All checks passed!`
   - unit: `204 passed`
   - spec-lint: `spec-lint OK: all ACs covered for T-013`
   - **ALL LOCAL GATES GREEN**
4. `git status --short` after `uv lock` + implementation: exactly
   `README.md`, `pyproject.toml`, `uv.lock` (modified) + `onrecord/api.py`
   (new, untracked) — no `tests/` diff, no stray files.
5. Manual re-read of `tests/unit/test_api.py`'s module docstring against the
   final `onrecord/api.py` line by line (9-key result shape, AND-not-OR
   filter combination, `k`-after-filter truncation order, flat
   `JSONResponse` 503 bodies, `registry`/`SCOREBOARD_PATH` monkeypatch
   seams, lifespan env re-read) — every pinned detail accounted for.

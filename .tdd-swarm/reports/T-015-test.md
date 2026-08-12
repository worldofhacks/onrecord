# T-015 Test Agent Report — serve UI + /api/prices route + index bootstrap

**Status:** DONE (see "Update — bootstrap resilience against a corrupt
corpus (post-review)" below for the current state; earlier sections
preserved beneath it).

## Update — bootstrap resilience against a corrupt corpus (post-review)

**Trigger:** Review REJECTED the T-015 implementation
(`.tdd-swarm/reports/T-015-review.md`, Critical-1): a corrupt/truncated
`ONRECORD_CORPUS` gzip snapshot raises uncaught out of `_lifespan`
(`onrecord/api.py`'s `_bootstrap_index_from_corpus` calls
`load_corpus_snapshot` with no `try/except`, unlike the sibling
`InvertedIndex.load` call one line above it, which is wrapped). Reproduced
live by the reviewer against a real `uvicorn` process: the process exits,
`/health` becomes unreachable — on Railway (`restartPolicyMaxRetries: 3`)
this is a full crash-loop outage, contradicting AC-4's own promise that
`/health`/the UI stay up when data is unavailable.

**Extended `tests/unit/test_serve.py` only** (no other files touched) with
one new parametrized test, `test_bootstrap_survives_corrupt_corpus_snapshot_never_crashes_startup`,
tagged `spec(T-015:AC-3) spec(T-015:AC-4)`, over 3 corruption fixtures:

- `truncated_gzip` — a valid gzip header, cut off mid-stream (partial
  upload/disk corruption) → `EOFError`.
- `non_gzip_file` — plain text at the expected `.jsonl.gz` path (wrong
  build artifact) → `gzip.BadGzipFile`.
- `malformed_utf8_gzip` — a validly gzip-compressed file whose
  decompressed content isn't valid UTF-8 (a garbled/corrupted download) →
  `UnicodeDecodeError`, raised during `load_corpus_snapshot`'s line-
  iteration itself, NOT caught by `_parse_jsonl_lines`'s existing per-line
  `json.JSONDecodeError` guard. **Design note, confirmed empirically**:
  plain non-JSON-but-valid-UTF8 lines do NOT reproduce this bug —
  `_parse_jsonl_lines` already catches `json.JSONDecodeError` per line,
  logs + skips, and `load_corpus_snapshot` gracefully returns `[]` (no
  crash). Only content that breaks OUTSIDE that per-line try/except (i.e.,
  breaks decoding/iteration itself) reproduces Critical-1, so this fixture
  is deliberately invalid-UTF-8 bytes rather than merely non-JSON text.

Each parametrization asserts: `TestClient.__enter__()` completes without
raising, `GET /health` → 200, `GET /` → 200 with the UI stub's exact
content, `GET /api/search` → 503 with the same flat
`{"error": "<message mentioning the index>"}` shape the already-pinned
both-missing AC-4 case uses, and at least one `ERROR`-level log record
exists (any logger — not pinned to a specific name/wording, since the fix
could reasonably live in `_bootstrap_index_from_corpus` or in `_lifespan`
around the call).

**Empirically confirmed `raise_server_exceptions=False` does NOT help
here** — that TestClient flag only suppresses request-handling exceptions
caught by Starlette's `ServerErrorMiddleware`; a lifespan-startup exception
propagates from `TestClient.__enter__()` unconditionally regardless of it
(verified via a throwaway repro script before writing the pinned test). So
the new test wraps `TestClient(...).__enter__()` in its own try/except
(`_client_expect_clean_startup`, a new helper alongside the existing
`_client`), converting any escaped exception into a clean, diagnostic
`pytest.fail(...)` naming the exception type/message — never an uncaught
traceback out of the test itself.

**Verification:**

```
uv run pytest tests/unit/test_serve.py -v
```
→ **15 collected, 3 failed, 12 passed.** The 3 new parametrizations fail
exactly as expected — cleanly, via `pytest.fail`, each naming the escaped
exception (`EOFError`, `gzip.BadGzipFile`, `UnicodeDecodeError`
respectively) — reproducing the reviewer's Critical-1 finding as a frozen,
automated regression. All 12 originally-frozen tests stay green,
unaffected (commit `cc1cf15`'s file is otherwise untouched above the new
"AMENDMENT" section).

`uv run pytest -q` (full repo) → **3 failed, 304 passed** — no regression
anywhere else (`tests/unit/test_api.py`'s 31 tests unaffected).

`uv run ruff format --check tests/unit/test_serve.py` /
`uv run ruff check tests/unit/test_serve.py` → clean.

No implementation files touched (`onrecord/api.py` untouched — verified
`git status --porcelain` shows only `tests/unit/test_serve.py` and this
report as changed/new).

---

## Original report (pre-review)

**Status:** DONE (failing tests written, achievability verified via a
throwaway patch then fully reverted, zero diff outside `tests/`).

**Worktree:** `/Users/quietguy/Documents/Dev/Gauntlet/wt-T-015`
(branch `ticket/T-015-serve`).

## What was written

`tests/unit/test_serve.py` — 12 new tests encoding tickets/T-015.md's
AC-1..AC-4, tagged `spec(T-015:AC-n)`. Does **not** touch
`tests/unit/test_api.py` (T-013's frozen file) or `onrecord/api.py` itself.

Unlike T-013/T-014's Test Agents, no "module not implemented yet" import
guard was needed: `onrecord.api` already exists and is fully tested by
T-013's frozen suite — every AC here targets *new* behavior layered on top
of that existing module, so a genuinely-missing route/feature just fails
its assertion cleanly (404, wrong status, etc.) rather than needing a
special `pytest.fail(...)` seam.

### Contracts pinned (Test Agent design decisions, since the ticket
underspecifies some seams — full rationale in the module docstring)

- `ONRECORD_UI_DIR` (default `"ui/"`, per the ticket), `ONRECORD_CORPUS`
  (default `"corpus/v1/corpus.jsonl.gz"`, per the ticket) — both re-read
  fresh at ASGI startup time, mirroring `ONRECORD_INDEX`'s established
  convention, so per-test `monkeypatch.setenv(...)` + a fresh
  `TestClient(app)` swap works against the one shared module-level `app`.
- `ONRECORD_PRICES_CACHE` (**new, not named by the ticket**) — default
  `"artifacts/prices"`, mirroring `onrecord.ingest.prices`'s own private
  `_DEFAULT_CACHE_DIR`. `api_payload`/`fetch_eod` both expose an explicit
  `cache_dir` injection seam that *something* must feed at the HTTP layer;
  this env var is the seam pinned here so tests can redirect it into a
  `tmp_path` with a pre-seeded, fresh cache file — the only way to get
  zero-network `/api/prices` tests at all (a stale/missing cache would
  make `fetch_eod` attempt a real network call).
- `/api/prices/{ticker}` query params: exactly `range` / `threshold`
  (literal from the ticket's own endpoint spec `?range=365&threshold=5.0`),
  threaded into `api_payload`'s `range_days`/`threshold_pct`. `range`'s
  trimming effect is a documented no-op under a fresh cache hit (per
  `fetch_eod`'s own frozen T-014 contract — cache hits return `series`
  verbatim, bypassing `_trim_to_range`), so this file only checks `range`
  is *accepted* (200), not that it visibly trims; `threshold` **is**
  independently verified (gates `significant_moves`, computed fresh
  regardless of cache state) by raising it past a known flagged move and
  confirming the move disappears.
- `/api/prices` is index-independent (mirrors `/api/metrics`'/
  `/api/answer`'s established independence from `ONRECORD_INDEX`): every
  price test points `ONRECORD_INDEX` at a deliberately-missing dir. AC-4's
  "data endpoints 503" is read as covering the index-dependent endpoints
  (`/api/search`, `/api/tickers`) only, not `/api/prices` (which degrades
  gracefully via `load_corpus_snapshot`'s own "missing path → `[]`"
  contract).

### Test list (12)

- AC-1 (static UI serving, no route shadowing): `test_index_html_served_at_root`,
  `test_support_js_served_with_javascript_content_type`,
  `test_api_search_not_shadowed_by_static_catch_all_route`,
  `test_unknown_path_without_extension_falls_back_to_index_spa`,
  `test_unknown_path_with_extension_returns_404`,
  `test_unknown_api_path_returns_404_not_spa_fallback`
- AC-2 (`/api/prices/{ticker}`, zero network): `test_prices_happy_path_matches_significant_move_and_nearby_receipt`,
  `test_prices_threshold_query_param_overrides_default_and_suppresses_move`,
  `test_prices_range_query_param_is_accepted`,
  `test_prices_hostile_ticker_returns_empty_series_and_moves`
- AC-3 (index bootstrap): `test_search_bootstraps_index_from_corpus_snapshot_when_index_missing`
- AC-4 (both missing → 503, UI still serves): `test_search_503_when_index_and_corpus_both_missing_but_ui_still_serves`

## Verification (throwaway patch, reverted)

Ran cold against the current, unmodified `onrecord/api.py`:

**9 failed, 3 passed** in `tests/unit/test_serve.py` (12 collected).

**3 pass already, honestly noted** — trivially, not because any AC is
implemented yet: with no static/prices routes and no catch-all defined at
all, `/api/search` obviously isn't shadowed
(`test_api_search_not_shadowed_by_static_catch_all_route` passes), and any
unmatched path — extensioned or under `/api/` — just hits FastAPI's plain
default 404 (`test_unknown_path_with_extension_returns_404`,
`test_unknown_api_path_returns_404_not_spa_fallback` pass). These 3 are
real regression guards, not false positives — they'll still need to keep
passing once the static/SPA catch-all route is added, which is the whole
point of having them.

**9 genuinely RED**, one per real missing feature: static serving
(`GET /`, `/support.js`, SPA fallback for extension-less unknown paths),
the entire `/api/prices/{ticker}` route (doesn't exist yet — every prices
test 404s), and index bootstrap-from-snapshot (currently always 503s when
`ONRECORD_INDEX` is missing, regardless of `ONRECORD_CORPUS`).

To confirm achievability, applied a throwaway patch to `onrecord/api.py`:
lifespan falls back to `InvertedIndex.build(load_corpus_snapshot(...))`
when the index fails to load and `ONRECORD_CORPUS` yields docs; a
`GET /api/prices/{ticker}` route wiring `prices.api_payload` with
`range`/`threshold` query params and the `ONRECORD_PRICES_CACHE` env var;
and a `GET /{full_path:path}` catch-all (registered last) that 404s any
unmatched `/api/...` path, serves a real static file when one exists,
404s an extensioned-but-missing path, and otherwise falls back to
`index.html`. Result: **12 passed** in `tests/unit/test_serve.py`, **307
passed** full-repo (`uv run pytest -q`). Confirms all 4 ACs are
implementable exactly as tested, with no hidden conflicts against T-013's
frozen `/api/search`/`/api/tickers`/`/api/metrics`/`/api/answer` routes.

Then reverted: `git checkout -- onrecord/api.py`. Confirmed
`git status --porcelain` shows only `tests/unit/test_serve.py` as
untracked (zero diff outside `tests/`), and re-ran cold to confirm the
same 9-failed/3-passed baseline holds unchanged post-revert.

## Other findings (heads-up, not this ticket's scope)

- The real committed `ui/` directory in this worktree currently contains
  `OnRecord App.dc.html`, not `index.html` (from the in-flight T-016
  design-studio import, wave-6 commit `f1fc7a6`). This ticket's own "Out of
  Scope" list excludes "the UI files themselves (T-016)", so no test here
  exercises the bare `ONRECORD_UI_DIR` default — every test points it at a
  fresh `tmp_path` stub dir instead, per the ticket's own suggestion. Flagging
  for whoever wires the real deploy: the default `ui/` dir will need an
  `index.html` present (likely T-016's or the orchestrator's job) before
  `GET /` works against the real committed assets, independent of T-015's
  own implementation correctness.
- `onrecord.ingest.build_corpus.load_corpus_snapshot` already
  unconditionally `gzip.open`s its input regardless of file suffix — so the
  ticket's "gz support: read via gzip when suffix .gz — extend the call
  site, not prices.py" note appears to already be satisfied as long as
  `ONRECORD_CORPUS` points at a real gzip file (which every corpus fixture
  in this suite, and the real default `corpus/v1/corpus.jsonl.gz`, already
  is). No extra call-site gz-detection logic was needed to make these tests
  pass in the throwaway verification patch.

## Commands

```sh
uv run pytest tests/unit/test_serve.py -v
uv run ruff format tests/unit/test_serve.py && uv run ruff check tests/unit/test_serve.py
```

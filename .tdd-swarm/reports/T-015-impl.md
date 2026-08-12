# T-015 Implementation Report — serve UI + `/api/prices` route + index bootstrap

**Status:** DONE (fix round 1, post-review). All 15
`tests/unit/test_serve.py` tests pass (12 original + 3 new parametrized
bootstrap-resilience cases); full local suite (`uv run pytest -q`) is 307
passed (292 baseline + 15, zero regressions); `.tdd-swarm/run-local-gates.sh
. tickets/T-015.md` is fully green (format, lint, unit, spec-lint). See
"Fix round 1" section below for the review-rejection response; the
original (pre-review) implementation section directly below is otherwise
unchanged from the first hand-off.

**Worktree:** `/Users/quietguy/Documents/Dev/Gauntlet/wt-T-015` (branch
`ticket/T-015-serve`).

## What changed

- `onrecord/api.py` (file-scope, modified) — extended `onrecord.api`
  in-place, no new module:
  - **Static UI (AC-1):** `GET /` serves `<ONRECORD_UI_DIR>/index.html`
    (default `ui/`). A catch-all route `GET /{full_path:path}`, registered
    LAST (after every `/api/*` route, including the new
    `/api/prices/{ticker}`), serves an existing static asset under the UI
    dir with a `mimetypes`-guessed content type (`support.js` →
    `text/javascript`), path-traversal-guarded via
    `candidate.is_relative_to(ui_dir.resolve())`; falls back to
    `index.html` for an unmatched extension-less path (SPA-style); 404s an
    unmatched path with an extension, and 404s any unmatched `/api/...`
    path outright (never SPA-fallback into `index.html`).
  - **`GET /api/prices/{ticker}?range=&threshold=` (AC-2):** wires
    `onrecord.ingest.prices.api_payload` with `range` → `range_days`,
    `threshold` → `threshold_pct`. Corpus path from `ONRECORD_CORPUS`
    (default `corpus/v1/corpus.jsonl.gz`), cache dir from
    `ONRECORD_PRICES_CACHE` (default `artifacts/prices`, mirroring
    `prices.py`'s own private `_DEFAULT_CACHE_DIR`) — both stashed on
    `app.state` at lifespan-startup, re-read fresh per ASGI startup so
    per-test env swapping works. Independent of index state; hostile/
    unknown tickers degrade to an empty series via `prices.py`'s own
    contract (no route-level special-casing needed).
  - **Index bootstrap (AC-3/AC-4):** `_lifespan` now falls back to
    `_bootstrap_index_from_corpus` when `InvertedIndex.load(index_dir)`
    raises — loads `ONRECORD_CORPUS` via `load_corpus_snapshot`, and if it
    yields docs, `InvertedIndex.build`s + `.save()`s back to
    `ONRECORD_INDEX` (warm restart) before serving. If the snapshot has no
    docs (missing path, empty, all-malformed), `app.state.index` stays
    `None` and the existing 503 path is unchanged.

- `Dockerfile` (new) — `python:3.12-slim`, installs `uv` via
  `COPY --from=ghcr.io/astral-sh/uv:latest`, two-stage `uv sync --no-dev
  --frozen` (deps-only layer first for cache reuse, then the full
  project), `CMD` binds `0.0.0.0:$PORT` via `uv run uvicorn
  onrecord.api:app`. Not built in CI (posture: syntax-reviewed only, per
  the ticket's DoD) — no `docker build` was run in this environment.

- `railway.json` (new) — `{"build": {"builder": "DOCKERFILE", ...},
  "deploy": {"startCommand": "uv run uvicorn onrecord.api:app --host
  0.0.0.0 --port $PORT", ...}}`.

- `README.md` (file-scope, modified) — added prices/static-UI rows to the
  existing API table, plus a new "Deploy (Railway, single service)"
  section: `railway login` / `railway init` / `railway up` steps and an
  env-var table (`ONRECORD_INDEX`, `ONRECORD_CORPUS`, `ONRECORD_UI_DIR`,
  `ONRECORD_PRICES_CACHE`, `FMP_API_KEY`, `PORT`).

## Design decision requiring a note (not a test dispute — both frozen
suites are simultaneously satisfiable; documented here per swarm practice
of recording underspecified-seam decisions)

**Index-bootstrap trigger is env-var-explicit, not default-path-implicit
— unlike `/api/prices`'s corpus path, which does default.** The real
`corpus/v1/corpus.jsonl.gz` snapshot (24,115 docs) is already committed in
this worktree (commit `3b9f513`, predates this ticket). A first
implementation attempt used `os.environ.get("ONRECORD_CORPUS",
DEFAULT_CORPUS_PATH)` uniformly for *both* the prices route's corpus path
*and* the bootstrap decision. That passed all 12 T-015 tests but broke 2
of T-013's frozen tests (`tests/unit/test_api.py`,
`test_search_503_with_actionable_message_when_index_missing` /
`test_tickers_503_with_actionable_message_when_index_missing`): those
tests point `ONRECORD_INDEX` at a missing dir and assert a `503`, without
ever setting `ONRECORD_CORPUS` — under a default-path bootstrap, the real
committed snapshot would silently satisfy the bootstrap and flip the
response to `200`, an unintended regression of a frozen contract, not a
sanctioned one.

Neither AC-3 nor AC-4's own test text actually requires *implicit*
default-path bootstrap: both explicitly set `ONRECORD_CORPUS` to a
specific path (a valid tmp snapshot for AC-3, a deliberately-missing tmp
path for AC-4) — never leaving it unset. So the fix scopes the bootstrap
*trigger* to require `ONRECORD_CORPUS` be explicitly present in
`os.environ` (`os.environ.get("ONRECORD_CORPUS")`, no default); only then
is `_bootstrap_index_from_corpus` attempted. This satisfies AC-3/AC-4
exactly as written, preserves T-013's frozen AC-5 3-word literal ("missing
index → 503" with no corpus override configured at all), and keeps the
`/api/prices` route's own default-path behavior (ticket-mandated, no
conflict since T-013 never touches `/api/prices`) unchanged. The README's
Deploy section calls this out explicitly: Railway deploys must set
`ONRECORD_CORPUS` to opt into cold-start index bootstrap.

## Verification

```
uv run pytest tests/unit/test_serve.py -v         # 12 passed
uv run pytest tests/unit/test_api.py -q            # 31 passed (frozen T-013 suite, unchanged)
uv run pytest -q                                   # 304 passed (292 baseline + 12; zero regressions)
uv run ruff format --check onrecord/api.py         # already formatted
uv run ruff check onrecord/api.py                  # all checks passed
.tdd-swarm/run-local-gates.sh . tickets/T-015.md   # ALL LOCAL GATES GREEN (incl. spec-lint)
```

TODO/debug-print gate checks (`git diff | grep -nE '^\+.*(TODO|FIXME|HACK)'`
and `...(print\(|breakpoint\()'`) both clean on the full diff, including
the two new files.

## Fix round 1 — response to REJECTED review (`.tdd-swarm/reports/T-015-review.md`)

Reviewer verdict: 1 Critical, 3 Important, 4 Minor. Test Agent pinned the
Critical as 3 new frozen parametrized tests at commit `0502fe0`
(`test_bootstrap_survives_corrupt_corpus_snapshot_never_crashes_startup`,
one per corruption flavor: `truncated_gzip`, `non_gzip_file`,
`malformed_utf8_gzip`). Addressed all 3 requested changes:

1. **Critical-1 fixed — bootstrap resilience.** `_bootstrap_index_from_corpus`
   (`onrecord/api.py`) now wraps its `load_corpus_snapshot(corpus_path)`
   call in `try/except Exception`, mirroring the sibling
   `InvertedIndex.load` pattern one line up in `_lifespan`: on any
   exception (the reviewer's live repro showed `EOFError` for truncated
   gzip, `gzip.BadGzipFile` for a non-gzip file at the expected path,
   `UnicodeDecodeError` for invalid UTF-8 inside an otherwise-valid gzip
   stream — none caught by `_parse_jsonl_lines`'s existing per-line
   `json.JSONDecodeError` guard, since these break file
   iteration/decoding itself, not per-line JSON parsing), logs at
   `logger.error(...)` (satisfies the new tests' `caplog.at_level(logging
   .ERROR)` assertion) and returns `None` — degrading cleanly to the same
   already-tested missing-index-and-corpus 503 path (AC-4) instead of
   letting the exception escape `_lifespan` and crash ASGI startup
   (previously: `TestClient(app).__enter__()` itself raised, and on a
   live `uvicorn` process the whole service exited — a Railway
   crash-loop). `/health` and `/` now verifiably keep serving in this
   scenario too, per the new tests.

2. **Important-2/3 fixed — added `.dockerignore`.** New file at repo root
   (granted file-scope addition). Excludes `.venv/` (the specific
   clobber risk called out — a host macOS/ARM `.venv/` silently
   overwriting the container's freshly `uv sync`'d Linux one via `COPY .
   .`), `.git/`, `.tdd-swarm/`, `tickets/`, `docs/`, `TICKETS.md`, `*.pdf`
   (the stray `Assignment_02_RelevanceEngine (1).pdf`), Python/tooling
   caches, `artifacts/` (runtime-built, never baked in), `corpus/raw/`
   (pre-merge adapter output, if ever present), `tests/` (not needed by
   the running production image — dropped per "your call"), and
   `.env*` (never bake real or example env files into an image; Railway
   supplies real config via its own env vars at runtime). Kept
   `corpus/v1/` and `ui/` unexcluded, as instructed (both genuinely
   needed at runtime: `/api/prices` + index bootstrap read the corpus
   snapshot; the static-UI routes read `ui/`).

3. **Important-1 (deploy-trap) resolved — container-scoped
   `ONRECORD_CORPUS` default.** Added `ENV
   ONRECORD_CORPUS=corpus/v1/corpus.jsonl.gz` to the `Dockerfile` only
   (after `EXPOSE 8000`), NOT to `onrecord/api.py`'s own Python-level
   default. This means: every deploy built from this image now
   bootstraps its index automatically on a cold start, with zero Railway
   env var configuration required (resolving the reviewer's "obvious
   `railway up` gets a silent 503" trap) — while `onrecord/api.py`'s own
   bootstrap-trigger logic is completely unchanged (still reads
   `os.environ.get("ONRECORD_CORPUS")` with no in-code default), so
   local runs, `uv run pytest`, and every frozen test in both
   `test_serve.py` and `test_api.py` (including the two T-013 AC-5 tests
   the original explicit-only design was built to protect) see zero
   behavior change — confirmed by the full-suite re-run below. Documented
   prominently in README's Deploy section (a new paragraph right after
   the `railway up` steps, not buried in the env-var table, per the
   reviewer's own suggestion) plus an inline `Dockerfile` comment
   explaining the image-local-only scoping.

Not addressed (reviewer explicitly marked these as non-blocking / no code
change required): Minor-4 (SPA-fallback extension-check cosmetic gap for
dotfile-shaped paths — reviewer confirmed zero content-disclosure risk),
Minor-5 (no rate limiting on `/api/prices` — inherited scope from T-014,
out of this ticket), Minor-6 (unpinned base-image tags — standard practice
per the reviewer's own note).

### Fix-round verification

```
uv run pytest tests/unit/test_serve.py -v         # 15 passed (12 original + 3 new)
uv run pytest tests/unit/test_api.py -q            # 31 passed (frozen T-013 suite, still unchanged)
uv run pytest -q                                   # 307 passed (292 baseline + 15; zero regressions)
uv run ruff format --check onrecord/api.py         # already formatted
uv run ruff check onrecord/api.py                  # all checks passed
.tdd-swarm/run-local-gates.sh . tickets/T-015.md   # ALL LOCAL GATES GREEN (incl. spec-lint)
python3 -m json.tool railway.json                  # still valid JSON (unchanged)
```

TODO/debug-print gate checks re-run clean on the fix-round diff too
(`onrecord/api.py`, `Dockerfile`, `README.md`, `.dockerignore`).

## Out of scope / heads-up (not touched, not this ticket's job)

- `Dockerfile` was not `docker build`-ed (no Docker in this environment;
  ticket's own DoD says "not required — syntax-reviewed instead").
- The real `ui/` dir still holds `OnRecord App.dc.html`, not `index.html`
  (T-016's in-flight import) — `GET /` against the *default* `ui/` dir in
  this worktree will 404 (`_serve_index` catches the `OSError` and raises
  a clean 404) until T-016 lands an `index.html`. No test in this ticket's
  suite exercises the bare default (every test points `ONRECORD_UI_DIR` at
  a fresh tmp stub), consistent with the Test Agent's own note in
  `.tdd-swarm/reports/T-015-test.md`.
- Actual Railway deployment (`railway up` against a real project) was not
  performed — out of scope per the ticket ("actual Railway deployment
  (orchestrator+owner)").

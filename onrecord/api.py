"""FastAPI layer — `/api/search`, `/api/tickers`, `/api/metrics`,
`/api/answer`, `/api/prices/{ticker}`, `/health`, plus static UI serving
(T-013, extended by T-015).

The commissioned UI (design studio, in flight) is built directly against
the JSON shapes pinned in `tests/unit/test_api.py`'s module docstring — that
file is the frozen, load-bearing contract for this module; read it in full
before touching this file. `tests/unit/test_serve.py`'s module docstring
pins T-015's additions (static UI serving, `/api/prices`, index bootstrap)
— read it too. Summary of the seams they pin:

- Index lifecycle: `ONRECORD_INDEX` (default `artifacts/index`, mirrors
  `onrecord/cli.py`'s `DEFAULT_INDEX_DIR`) is re-read from `os.environ` at
  ASGI *startup* time (not baked in at module-import time), so
  `monkeypatch.setenv(...)` before `with TestClient(app) as client:` works
  per-test. A missing/unloadable index falls back to bootstrapping an
  in-memory index from the `ONRECORD_CORPUS` snapshot (default
  `corpus/v1/corpus.jsonl.gz`) when that snapshot has docs — built +
  `.save()`d back to `ONRECORD_INDEX` so a restart is warm (T-015 AC-3).
  When neither the index nor the corpus snapshot is available,
  `app.state.index` stays `None`; "data endpoints" (`/api/search`,
  `/api/tickers`) 503 in that case, via a flat `JSONResponse({"error":
  ...})` body (never `HTTPException`, which would wrap the body in
  `{"detail": ...}`). `/health`, `/api/metrics`, and `/api/answer` never
  depend on index state.
- Static UI: `ONRECORD_UI_DIR` (default `ui/`) is served at `GET /`
  (`index.html`'s contents) and via a catch-all fallback for any other
  unmatched non-`/api/*` path — an existing static asset under the UI dir
  is served with a guessed content type (e.g. `support.js` as
  JavaScript); an unmatched extension-less path falls back to `index.html`
  (SPA-style); an unmatched path WITH an extension 404s. `/api/*` paths are
  never shadowed by this catch-all (T-015 AC-1).
- `/api/prices/{ticker}?range=365&threshold=5.0` wires
  `onrecord.ingest.prices.api_payload` (corpus path from `ONRECORD_CORPUS`,
  price cache dir from `ONRECORD_PRICES_CACHE`, default `artifacts/prices`
  mirroring `onrecord.ingest.prices`'s own private default). Independent of
  index state — a hostile/unknown ticker degrades to an empty series via
  `prices.py`'s own contract, never a 503 (T-015 AC-2).
- `mode=lexical` retrieval: feature-detects `onrecord.search.ranked
  .ranked_search` via import (T-011). If importable, used for real scoring;
  else falls back to `boolean_search(index, q, op)` with `score` pinned to
  `0.0` — the only path this worktree can exercise (T-011 hasn't merged
  here yet).
- `op` is whitelisted to exactly `"AND"` / `"OR"` (case-sensitive,
  uppercase only — mirrors `boolean_search`'s own contract); any other
  value 422s via FastAPI/pydantic query validation, never a raw 500 from
  `boolean_search`'s `ValueError`. `k` must be a positive integer (`>= 1`,
  `Query(ge=1)`); `k <= 0` 422s — mirrors `onrecord/cli.py`'s `--k`
  convention. Post-review contract extension, see
  `.tdd-swarm/reports/T-013-test.md`.
- `op=AND` under the BM25 path (wave-4 adjudication, see
  `.tdd-swarm/reports/T-013-test.md`'s "op=AND under BM25" section +
  `.tdd-swarm/LESSONS.md`): `ranked_search` is always OR-union semantics
  internally, so `op="AND"` post-filters its full ranked candidate list
  down to the conjunctive doc-id set (`boolean_search(index, q, "AND")`'s
  matches) before metadata filtering/truncation — preserving BM25's
  descending score order (op=OR is unmodified: it's exactly
  `ranked_search`'s own union). Result scores are always real positive
  BM25 floats once `ranked_search` is the active (feature-detected) path,
  never the boolean-fallback era's flat `0.0`.
- `/api/tickers` is registry-driven (`onrecord.registry.load()`), not
  corpus-driven, imported as `from onrecord import registry` and called
  fresh per-request (never cached) so tests can monkeypatch
  `api.registry.load`.
- `/api/metrics` reads a module-level `SCOREBOARD_PATH` constant fresh per
  request (mirrors `onrecord/eval/run.py`'s `DEFAULT_HISTORY_PATH`), so
  tests can monkeypatch it directly.
- CORS: allows `http://localhost:5173` (the commissioned UI's dev origin).

Run locally:
    uv run uvicorn onrecord.api:app --reload
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from onrecord import registry
from onrecord.index.inverted import InvertedIndex
from onrecord.ingest.build_corpus import load_corpus_snapshot
from onrecord.ingest.prices import api_payload
from onrecord.search.boolean import boolean_search
from onrecord.types import Doc

logger = logging.getLogger(__name__)

DEFAULT_INDEX_DIR = "artifacts/index"
DEFAULT_UI_DIR = "ui/"
DEFAULT_CORPUS_PATH = "corpus/v1/corpus.jsonl.gz"
DEFAULT_PRICES_CACHE_DIR = "artifacts/prices"
SCOREBOARD_PATH = "artifacts/scoreboard.jsonl"

# 9-key result shape pinned by tests/unit/test_api.py's module docstring:
# SearchResult's 3 fields (doc_id, score, snippet) + 6 of Doc's metadata
# fields (date, source_type, venue_type, jurisdiction, ticker, deep_link).
# `speaker` is deliberately excluded.
_RESULT_METADATA_FIELDS = (
    "date",
    "source_type",
    "venue_type",
    "jurisdiction",
    "ticker",
    "deep_link",
)

# --------------------------------------------------------------------------
# index lifecycle (AC-5): re-read ONRECORD_INDEX at startup *call* time, not
# module-import time, so per-test monkeypatch.setenv(...) + a fresh
# TestClient(app) context re-runs this and swaps the loaded index.
# --------------------------------------------------------------------------


def _bootstrap_index_from_corpus(index_dir: Path, corpus_path: Path) -> InvertedIndex | None:
    """Build (and, on success, `.save()` back to `index_dir` for a warm
    restart) an in-memory index from the corpus snapshot at `corpus_path`,
    used when `ONRECORD_INDEX` itself failed to load (missing dir, most
    commonly). Returns `None` if the snapshot has no docs either (missing
    path, empty file, all-malformed rows) — the caller then keeps
    `app.state.index` as `None`, preserving the existing 503 behavior
    (T-015 AC-3/AC-4)."""
    docs = load_corpus_snapshot(corpus_path)
    if not docs:
        return None

    index = InvertedIndex.build(docs)
    try:
        index.save(index_dir)
    except OSError:
        logger.warning(
            "failed to persist bootstrapped index to %s (serving from memory only)",
            index_dir,
            exc_info=True,
        )
    return index


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    index_dir = Path(os.environ.get("ONRECORD_INDEX", DEFAULT_INDEX_DIR))
    app.state.ui_dir = Path(os.environ.get("ONRECORD_UI_DIR", DEFAULT_UI_DIR))
    # `/api/prices` always has a default corpus path, per the ticket.
    app.state.corpus_path = os.environ.get("ONRECORD_CORPUS", DEFAULT_CORPUS_PATH)
    app.state.prices_cache_dir = os.environ.get("ONRECORD_PRICES_CACHE", DEFAULT_PRICES_CACHE_DIR)

    try:
        app.state.index = InvertedIndex.load(index_dir)
    except Exception:
        app.state.index = None
        # Index bootstrap (T-015 AC-3/AC-4): only when ONRECORD_CORPUS is
        # EXPLICITLY set in the environment -- deliberately NO implicit
        # fallback to DEFAULT_CORPUS_PATH here (unlike /api/prices above).
        # Both AC-3 and AC-4's own test text describe ONRECORD_CORPUS as
        # explicitly pointed at a specific path (valid or deliberately
        # missing), never an unset var; T-013's frozen AC-5 tests
        # (tests/unit/test_api.py) exercise exactly that unset case and
        # pin a 503 there. Since this worktree already has a real
        # corpus/v1/corpus.jsonl.gz snapshot committed, defaulting the
        # bootstrap trigger itself (as opposed to just the prices route's
        # corpus path) would silently flip those frozen tests from 503 to
        # 200 -- an unintended regression, not a sanctioned contract
        # change. Real deploys (Railway) must set ONRECORD_CORPUS
        # explicitly to opt into cold-start bootstrap (README Deploy
        # section documents this).
        explicit_corpus = os.environ.get("ONRECORD_CORPUS")
        if explicit_corpus is not None:
            app.state.index = _bootstrap_index_from_corpus(index_dir, Path(explicit_corpus))
    yield


app = FastAPI(title="onrecord API", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _require_index() -> InvertedIndex | None:
    return getattr(app.state, "index", None)


def _missing_index_response() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"error": "index not loaded — build one with `make ingest` or set ONRECORD_INDEX"},
    )


# --------------------------------------------------------------------------
# GET /health
# --------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# --------------------------------------------------------------------------
# GET /api/search
# --------------------------------------------------------------------------


def _resolve_search_fn():
    """Feature-detect the T-011 ranked-search path via import; fall back to
    the boolean-OR/AND pipeline (score always 0.0) when it isn't merged into
    this worktree yet."""
    try:
        from onrecord.search.ranked import ranked_search
    except ImportError:
        return None
    return ranked_search


def _doc_to_result_dict(doc: Doc, score: float, snippet: str) -> dict:
    result = {"doc_id": doc.id, "score": score, "snippet": snippet}
    for field in _RESULT_METADATA_FIELDS:
        result[field] = getattr(doc, field)
    return result


def _apply_filters(
    hits: list,
    index: InvertedIndex,
    *,
    source: str | None,
    venue: str | None,
    ticker: str | None,
    jurisdiction: str | None,
) -> list:
    def _matches(doc: Doc) -> bool:
        if source is not None and doc.source_type != source:
            return False
        if venue is not None and doc.venue_type != venue:
            return False
        if ticker is not None and doc.ticker != ticker:
            return False
        if jurisdiction is not None and doc.jurisdiction != jurisdiction:
            return False
        return True

    return [hit for hit in hits if _matches(index.get_doc(hit.doc_id))]


@app.get("/api/search")
async def search(
    q: str = "",
    mode: Literal["lexical", "semantic", "hybrid"] = "lexical",
    op: Literal["AND", "OR"] = "OR",
    k: int = Query(default=20, ge=1),
    source: str | None = None,
    venue: str | None = None,
    ticker: str | None = None,
    jurisdiction: str | None = None,
):
    if mode in ("semantic", "hybrid"):
        return {"error": "available_wednesday"}

    index = _require_index()
    if index is None:
        return _missing_index_response()

    ranked_search = _resolve_search_fn()
    if ranked_search is not None:
        # BM25 path (T-011 active). `ranked_search` itself always computes
        # OR-union semantics; per the wave-4 adjudication (see module
        # docstring + tests/unit/test_api.py's "Extension -- op=AND under
        # BM25"), op=AND narrows that union down to the conjunctive
        # candidate set (docs containing ALL analyzed query terms -- the
        # same doc-id set boolean_search(index, q, "AND") matches) BEFORE
        # truncation, keeping the same BM25 scores/ordering. Request every
        # ranked candidate (k=index.doc_count(), an upper bound) rather than
        # just the caller's k: ranked_search already scores its full union
        # candidate set internally regardless of `k` (only its own top-k
        # *selection* step is k-bounded), so this costs no extra scoring
        # work, and it keeps AND-narrowing + metadata filtering happening
        # before the final k-truncation below, per the pinned
        # filter-then-truncate order. Post-filtering a score-sorted sequence
        # preserves its descending order, so op=AND's results stay
        # correctly BM25-ranked.
        hits = ranked_search(index, q, k=index.doc_count())
        if op == "AND":
            and_ids = {r.doc_id for r in boolean_search(index, q, "AND")}
            hits = [hit for hit in hits if hit.doc_id in and_ids]
    else:
        hits = boolean_search(index, q, op)

    hits = _apply_filters(
        hits, index, source=source, venue=venue, ticker=ticker, jurisdiction=jurisdiction
    )
    hits = hits[:k]

    results = [
        _doc_to_result_dict(index.get_doc(hit.doc_id), hit.score, hit.snippet) for hit in hits
    ]
    return {"query": q, "mode": mode, "results": results}


# --------------------------------------------------------------------------
# POST /api/answer (stub — real grounded Q&A lands Thursday, see the ticket's
# module docstring "PINNED-FOR-THURSDAY" shape)
# --------------------------------------------------------------------------


class AnswerRequest(BaseModel):
    question: str
    mode: str = "lexical"
    k: int = 10


@app.post("/api/answer")
async def answer(_request: AnswerRequest):
    return {"error": "available_thursday"}


# --------------------------------------------------------------------------
# GET /api/tickers
# --------------------------------------------------------------------------


@app.get("/api/tickers")
async def tickers():
    index = _require_index()
    if index is None:
        return _missing_index_response()

    reg = registry.load()

    counts: dict[str, int] = {}
    last_receipt: dict[str, str] = {}
    for i in range(index.doc_count()):
        doc = index.get_doc(i)
        if not doc.ticker:
            continue
        counts[doc.ticker] = counts.get(doc.ticker, 0) + 1
        current_last = last_receipt.get(doc.ticker)
        if current_last is None or doc.date > current_last:
            last_receipt[doc.ticker] = doc.date

    by_sector: dict[str, list[dict]] = {}
    for entry in reg.get("tickers", []):
        symbol = entry["symbol"]
        sector = entry["sector"]
        by_sector.setdefault(sector, []).append(
            {
                "symbol": symbol,
                "receipt_count": counts.get(symbol, 0),
                "last_receipt": last_receipt.get(symbol),
            }
        )

    sectors = [
        {"sector": sector, "tickers": sorted(entries, key=lambda t: t["symbol"])}
        for sector, entries in sorted(by_sector.items())
    ]
    return {"sectors": sectors}


# --------------------------------------------------------------------------
# GET /api/metrics
# --------------------------------------------------------------------------


@app.get("/api/metrics")
async def metrics():
    path = Path(SCOREBOARD_PATH)
    if not path.exists():
        return []

    rows = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


# --------------------------------------------------------------------------
# GET /api/prices/{ticker} (T-015 AC-2) -- index-independent; degrades
# gracefully (empty series) via prices.py's own hostile-ticker/missing-
# corpus handling, never a 503.
# --------------------------------------------------------------------------


@app.get("/api/prices/{ticker}")
async def prices(ticker: str, range: int = 365, threshold: float = 5.0) -> dict:
    corpus_path = getattr(app.state, "corpus_path", DEFAULT_CORPUS_PATH)
    cache_dir = getattr(app.state, "prices_cache_dir", DEFAULT_PRICES_CACHE_DIR)
    return api_payload(
        ticker,
        corpus_path,
        range_days=range,
        threshold_pct=threshold,
        cache_dir=cache_dir,
    )


# --------------------------------------------------------------------------
# Static UI serving (T-015 AC-1): `GET /` serves ONRECORD_UI_DIR/index.html;
# a catch-all (registered LAST, after every /api/* route above, so it never
# shadows them) serves any other existing static asset under the UI dir
# with a guessed content type, falls back to index.html for an unmatched
# extension-less path (SPA-style), and 404s an unmatched path that either
# has an extension or starts with `api/`.
# --------------------------------------------------------------------------


def _ui_dir() -> Path:
    return getattr(app.state, "ui_dir", Path(DEFAULT_UI_DIR))


def _serve_index(ui_dir: Path) -> Response:
    try:
        content = (ui_dir / "index.html").read_bytes()
    except OSError as exc:
        raise HTTPException(status_code=404, detail="UI not built") from exc
    return Response(content=content, media_type="text/html")


@app.get("/")
async def root() -> Response:
    return _serve_index(_ui_dir())


@app.get("/{full_path:path}")
async def spa_catch_all(full_path: str) -> Response:
    if full_path == "api" or full_path.startswith("api/"):
        # Never SPA-fallback an unmatched /api/... path -- stay a clean 404
        # (every real /api/* route above already matched before this
        # catch-all is ever reached).
        raise HTTPException(status_code=404)

    ui_dir = _ui_dir()
    resolved_ui_dir = ui_dir.resolve()
    candidate = (ui_dir / full_path).resolve()
    if candidate.is_relative_to(resolved_ui_dir) and candidate.is_file():
        media_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        return Response(content=candidate.read_bytes(), media_type=media_type)

    if Path(full_path).suffix:
        # Has a file extension but no matching static asset -- 404, never
        # SPA-fallback (the ticket's explicit exception to the fallback).
        raise HTTPException(status_code=404)

    return _serve_index(ui_dir)

"""FastAPI layer — `/api/search`, `/api/tickers`, `/api/metrics`,
`/api/answer`, `/health` (T-013).

The commissioned UI (design studio, in flight) is built directly against
the JSON shapes pinned in `tests/unit/test_api.py`'s module docstring — that
file is the frozen, load-bearing contract for this module; read it in full
before touching this file. Summary of the seams it pins:

- Index lifecycle: `ONRECORD_INDEX` (default `artifacts/index`, mirrors
  `onrecord/cli.py`'s `DEFAULT_INDEX_DIR`) is re-read from `os.environ` at
  ASGI *startup* time (not baked in at module-import time), so
  `monkeypatch.setenv(...)` before `with TestClient(app) as client:` works
  per-test. A missing/unloadable index stores `None` on `app.state.index`;
  "data endpoints" (`/api/search`, `/api/tickers`) 503 in that case, via a
  flat `JSONResponse({"error": ...})` body (never `HTTPException`, which
  would wrap the body in `{"detail": ...}`). `/health`, `/api/metrics`, and
  `/api/answer` never depend on index state.
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
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from onrecord import registry
from onrecord.index.inverted import InvertedIndex
from onrecord.search.boolean import boolean_search
from onrecord.types import Doc

DEFAULT_INDEX_DIR = "artifacts/index"
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


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    index_dir = Path(os.environ.get("ONRECORD_INDEX", DEFAULT_INDEX_DIR))
    try:
        app.state.index = InvertedIndex.load(index_dir)
    except Exception:
        app.state.index = None
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
        hits = ranked_search(index, q, k=k)
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

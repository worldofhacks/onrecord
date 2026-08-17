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
- `/api/stats` (T-017): `{"documents", "jurisdictions", "tickers",
  "sources", "corpus_version"}` — computed once from the loaded index
  during ASGI *startup* (right after `app.state.index` is set) and cached
  on `app.state.stats_cache`; never recomputed per request. Missing index
  → the same flat 503 `_missing_index_response()` other data endpoints
  use. See `tests/unit/test_stats.py`'s module docstring for the frozen
  contract.
- `/api/metrics` reads a module-level `SCOREBOARD_PATH` constant fresh per
  request (mirrors `onrecord/eval/run.py`'s `DEFAULT_HISTORY_PATH`), so
  tests can monkeypatch it directly.
- CORS: allows `http://localhost:5173` (the commissioned UI's dev origin).

Extension — the T-024 RAG unlock (live `mode=semantic|hybrid`, the real
`POST /api/answer`, the degradation ladder)
--------------------------------------------------------------------------
`tests/unit/test_api_rag.py`'s module docstring is the frozen contract for
everything in this section — read it in full (especially "MODULE SEAMS
PINNED" and the ladder table) before touching the code below. Summary:

- Module seams: `answer_mod` / `embeddings` / `retrieve` are imported at
  module level and called through the module ATTRIBUTE, resolved fresh per
  request (`embeddings.get_provider()`, `answer_mod.default_generator()`,
  `answer_mod.answer(...)`) — the same monkeypatchable shape as the
  `registry.load` seam above. Per-request provider resolution is required,
  not stylistic: "store present but provider unconfigured" has to stay
  distinguishable from "store missing", which a startup-cached provider
  cannot do (it would send an operator hunting the wrong problem).
- Env vars consumed here: `ONRECORD_EMBED_STORE` (embedding-store dir;
  default `artifacts/embeddings/<resolved provider model>` — the same
  default `onrecord/rag/judge.py` computes, so the two agree by
  construction rather than by coincidence), `ONRECORD_ANSWER_MIN_CONF` (the
  retrieval-confidence threshold threaded into `answer(min_confidence=...)`;
  unset/blank → `None`, unparseable → a 503 naming the var, NEVER a silent
  fall-back to "no threshold"), plus `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`,
  which are read only inside the two library calls above, never here.
- Startup state: identity chunks (`chunk_corpus(docs, 1, 0)` over the
  loaded index's docs — T-020's locked invariant `len(doc_ids) == 1 <=>
  chunk_id == doc_ids[0]`), plus a best-effort WARM load of the embedding
  store into a DIRECTORY-KEYED cache (`app.state.embed_stores`). The cache
  is keyed by directory rather than held in a single `embed_store` slot
  because the default directory depends on the per-request resolved
  provider model; a store that fails to load (missing dir, `CorruptStore`,
  unresolvable provider) is simply absent from it and degrades to the
  ladder's store rung — startup itself never raises, so a corrupt store can
  never crash-loop the deploy (the T-015 bootstrap lesson).
- `GET /api/search?mode=semantic|hybrid` runs T-022's `semantic_search` /
  `hybrid_search` (hybrid at `ONRECORD_FUSION_DEPTH`, default 2000 — T-037;
  `0` restores full depth) — historically at FULL corpus depth, projects every hit's chunk_id
  through the EXPLICIT `chunk.doc_ids[0]` projection, and then takes the
  same filter-then-truncate tail as `mode=lexical`, so all three modes
  share one 9-key result shape and one filter order. `op` stays whitelisted
  (422 off-whitelist) but is ACCEPTED AND IGNORED for these modes: a
  boolean candidate-set rule has no meaning for a cosine ranking or an RRF
  fusion.
- `POST /api/answer` is a DATA endpoint at the unlock — a missing index is
  the same flat 503 `/api/search` and `/api/tickers` return. It retrieves
  per `mode` (default `"lexical"`: T-022 measured hybrid at ~1.3-1.4 s
  typical / ~3.5 s worst over 289K docs, so the lexical default is what
  keeps a bare API call fast AND keyless — the UI sends `mode` explicitly),
  threads the retrieval RANK ORDER and the REAL scores into
  `answer_mod.answer(...)`, and returns that dict VERBATIM as the 200 body.
  A refusal is a 200 with a populated `refusal` object, never an error.
  `k` is bounded ABOVE as well as below (`MAX_ANSWER_K`): every retrieved
  chunk's full text goes into the generator prompt, so an unbounded `k` is
  an unauthenticated spend amplifier once a key is provisioned.
- The degradation ladder: every rung is a flat `{"error": <str>}`
  `JSONResponse` (always `application/json`) NAMING ITS CONDITION with a
  token no other rung uses (`tests/unit/test_api_rag.py`'s `LADDER_TOKENS`
  is the frozen vocabulary — these strings are the only diagnosis a human
  ever sees, rendered verbatim by T-028's UI). Pinned on BOTH endpoints, in
  both embedding-backed modes. CONFIGURATION rungs, all detectable before
  any paid call: index missing → no embedding store (missing or corrupt) →
  provider unconfigured (`OPENAI_API_KEY`) → store/provider identity
  mismatch → partially embedded store (T-022 `MissingEmbeddings`) → stale
  store rows (T-022 `StoreMismatch`) → generator unconfigured
  (`ANTHROPIC_API_KEY`) → unparseable `ONRECORD_ANSWER_MIN_CONF`. RUNTIME
  rungs, for a correctly configured dependency that fails mid-request:
  `embedding request failed` (T-021 `EmbeddingRequestError` — a 429, 401,
  5xx or transport failure that survived its retries) and `generation
  failed` (ANY exception out of `generate_fn`, typed or not). Never an
  `HTTPException` (which would wrap the body in `{"detail": ...}`), never
  an uncaught 500 — an uncaught exception is a `text/plain` 500 with no
  `.error` at all, which is exactly how T-028's card loses its diagnosis
  on the most likely failure once keys are provisioned. Operator-, corpus-
  and library-supplied strings go through `_safe_echo` before entering a
  message (bounded, other rungs' tokens masked) so no echoed value can
  break the partition; the raw value goes to the log.
  `MinConfidenceWithoutScores` is the ladder's one 422 sibling: a
  server-side WIRING fault (a threshold configured with no scores to
  compare it against, which `answer()` would silently no-op), reported in
  the same flat shape.
- Handler shape: `search` and `answer` are plain `def`, so FastAPI runs
  them in its THREADPOOL. Their bodies are fully synchronous and now do
  seconds of blocking work — a blocking `httpx` embedding round trip with
  retries, a full-matrix cosine pass, corpus-wide hash verification, and on
  `/api/answer` a blocking LLM call (measured: 3179 ms for the
  `mode=hybrid, k=8` request T-028's Ask view sends, at 289K docs). On the
  event loop that stalls EVERY other request for the full duration
  (measured: `/health` 6 ms → 1968 ms behind one in-flight request), which
  is platform-health-check starvation arriving through a different door
  than the T-015 crash-loop. `/health` and the other constant-time
  handlers stay `async` — they belong on the loop and a threadpool hop
  would only cost them. This shape is coupled to the store cache's lock
  (see `_load_embed_store`): the cache was thread-safe only by accident
  while every handler serialised on the loop.
- The KEYLESS-LEXICAL guarantee: `mode=lexical` search AND answer work with
  no embedding store on disk and no key of any kind, and a lexical request
  never RESOLVES an embedding provider at all. The deployed corpus-v1
  service and every deterministic test in this repo depend on it.
- `/api/stats`'s `corpus_version` is T-018's `read_manifest` over the INDEX
  dir with the literal `"unversioned"` fallback — never a fabricated
  version string, and the same resolution `onrecord/eval/run.py` and
  `onrecord/rag/modes.py` use.

Run locally:
    uv run uvicorn onrecord.api:app --reload
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
import threading
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from datetime import time as dt_time
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from onrecord import registry
from onrecord.analysis import conduct as conduct_mod
from onrecord.analysis import dodge as dodge_mod
from onrecord.analysis import mentions as mentions_mod
from onrecord.index.inverted import InvertedIndex
from onrecord.ingest.build_corpus import load_corpus_snapshot, read_manifest
from onrecord.ingest.prices import api_payload
from onrecord.ingest.prices import fetch_eod as prices_fetch_eod
from onrecord.rag import answer as answer_mod
from onrecord.rag import embeddings, retrieve
from onrecord.rag.chunking import Chunk, chunk_corpus
from onrecord.search.boolean import boolean_search
from onrecord.types import Doc, SearchResult

logger = logging.getLogger(__name__)

DEFAULT_INDEX_DIR = "artifacts/index"
DEFAULT_UI_DIR = "ui/"
DEFAULT_CORPUS_PATH = "corpus/v1/corpus.jsonl.gz"
DEFAULT_PRICES_CACHE_DIR = "artifacts/prices"
SCOREBOARD_PATH = os.environ.get("ONRECORD_SCOREBOARD", "artifacts/scoreboard.jsonl")

# T-024. The store env var is canonically ONRECORD_EMBED_STORE (T-026 shipped
# it in onrecord/rag/judge.py; the ticket's own ONRECORD_EMBEDDINGS prose is
# superseded), and its default is spelled exactly as judge.py spells it, so a
# store built with one tool is found by the other.
EMBED_STORE_ENV = "ONRECORD_EMBED_STORE"
DEFAULT_EMBED_STORE_ROOT = "artifacts/embeddings"
MIN_CONFIDENCE_ENV = "ONRECORD_ANSWER_MIN_CONF"
# The honest fallback when the index dir carries no usable T-018 manifest --
# never a fabricated "v1" (orchestrator adjudication of plan-review I-12).
UNVERSIONED_CORPUS = "unversioned"

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
# T-024 degradation ladder (AC-3): one flat 503 per condition, each message
# NAMING its own condition in words no other rung uses -- these strings are
# the only diagnosis an operator (or T-028's UI) ever sees. The frozen
# vocabulary lives in tests/unit/test_api_rag.py's LADDER_TOKENS.
# --------------------------------------------------------------------------


class MinConfidenceWithoutScores(Exception):
    """A `min_confidence` threshold is configured but retrieval produced no
    scores to compare it against — `answer()` would silently no-op the gate,
    shipping ungrounded answers from a box whose operator believes the gate is
    on (T-023 review concern (c); AMENDMENT 2026-08-12). A NAMED type because
    `answer()` already raises a bare `ValueError` for its own scores/chunks
    length mismatch, and the two must stay distinguishable at the ladder.
    Mapped to a flat 422: it is a server-side WIRING fault, not a complaint
    about the request body."""


class _Degradation(Exception):
    """An internal ladder signal carrying the flat response body it becomes.

    Raised by the resolution helpers below (which sit several frames under a
    route handler) and converted at the route boundary, so no helper has to
    return a union of "value or response" and no rung can leak as an uncaught
    500."""

    def __init__(self, message: str, status_code: int = 503) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code

    def response(self) -> JSONResponse:
        return _flat_error(self.status_code, self.message)


def _flat_error(status_code: int, message: str) -> JSONResponse:
    """The frozen error shape: a FLAT `{"error": ...}` `JSONResponse`, never
    `HTTPException` (which wraps the body in `{"detail": ...}`), and always
    `application/json` — an uncaught exception becomes a `text/plain` 500
    whose body has no `.error` at all, which is exactly how T-028's cards
    lose their diagnosis."""
    return JSONResponse(status_code=status_code, content={"error": message})


# The ladder's condition vocabulary, restated here on purpose: it is the
# CONTRACT (tests/unit/test_api_rag.py's LADDER_TOKENS), and `_safe_echo`
# uses it to enforce the partition property structurally rather than leaving
# it to the discipline of whoever writes the next message.
_LADDER_TOKENS = (
    "index not loaded",
    "no embedding store",
    "OPENAI_API_KEY",
    "identity mismatch",
    "not embedded",
    "stale",
    "ANTHROPIC_API_KEY",
    "ONRECORD_ANSWER_MIN_CONF",
    "embedding request failed",
    "generation failed",
)

_ECHO_LIMIT = 120


def _safe_echo(value: object, *, limit: int = _ECHO_LIMIT) -> str:
    """Bound and neutralise an operator-, corpus- or library-supplied string
    before interpolating it into a ladder message.

    Two properties, both learned from the review:

    1. **The partition holds.** Every rung names exactly ONE condition, and
       every rung assertion in the frozen suite rests on that. An echoed
       value the ladder never accounted for silently breaks it — a store
       directory like `/srv/embeddings-stale-2025-01/`, a model id someone
       suffixed, a library message quoting corpus text. Each rung's own token
       comes from the CONSTANT part of its message, so masking every token
       inside the echo is always the right move.
    2. **The body is bounded.** A 4 KB environment value must not become a
       4 KB error body handed to an anonymous caller.

    The full, unmasked value always goes to the log, where the operator can
    read it and an anonymous caller cannot."""
    text = str(value)
    if len(text) > limit:
        text = text[:limit] + "…"
    for token in _LADDER_TOKENS:
        text = re.sub(re.escape(token), "…", text, flags=re.IGNORECASE)
    return text


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
    (T-015 AC-3/AC-4).

    Post-review fix (Critical-1, `.tdd-swarm/reports/T-015-review.md`):
    `load_corpus_snapshot` itself is NOT exception-safe — a corpus file
    that exists but is corrupt/unreadable (truncated gzip, not gzip at
    all, invalid UTF-8 inside a valid gzip stream) raises straight out of
    it (`EOFError` / `gzip.BadGzipFile` / `UnicodeDecodeError`
    respectively), which — uncaught — used to crash ASGI *startup* itself,
    not just this one request (a Railway crash-loop, reproduced live by
    the reviewer). Wrapped the same way `InvertedIndex.load` already is
    one line up in `_lifespan`: degrade to `None` (same missing-index 503
    path) with an ERROR-level log, never let it escape and take the
    process down."""
    try:
        docs = load_corpus_snapshot(corpus_path)
    except Exception:
        logger.error(
            "failed to load ONRECORD_CORPUS snapshot at %s for index bootstrap -- "
            "degrading to the missing-index 503 path instead of crashing ASGI startup",
            corpus_path,
            exc_info=True,
        )
        return None

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


def _corpus_version(index_dir: str | Path) -> str:
    """`corpus_version` from T-018's `read_manifest` over the INDEX dir — the
    same artifact the counts themselves come from, so the number and the
    version on the UI's hero strip always describe the same corpus (T-024
    re-pin #3).

    Every failure mode `read_manifest`'s tolerant contract collapses to `None`
    (no manifest, unreadable/corrupt JSON, JSON that is not an object), plus a
    manifest without the key, is the literal `"unversioned"` — never a
    fabricated `"v1"`. Spelled exactly as `onrecord/eval/run.py::
    _corpus_version` and `onrecord/rag/modes.py` spell it, so `/api/stats` and
    the scoreboard agree by construction (orchestrator adjudication of
    plan-review I-12)."""
    manifest = read_manifest(index_dir)
    if manifest is None:
        return UNVERSIONED_CORPUS
    return manifest.get("corpus_version", UNVERSIONED_CORPUS)


def _compute_stats(index: InvertedIndex, index_dir: str | Path) -> dict:
    """One-time stats computation (T-017) over every doc in `index`, mirroring
    `/api/tickers`'s existing `index.get_doc(i)` enumeration idiom. Called
    once at ASGI startup and cached on `app.state.stats_cache` — never
    per-request (AC-2)."""
    jurisdictions: set[str] = set()
    tickers: set[str] = set()
    sources: dict[str, int] = {}
    for i in range(index.doc_count()):
        doc = index.get_doc(i)
        if doc.jurisdiction:
            jurisdictions.add(doc.jurisdiction)
        if doc.ticker:
            tickers.add(doc.ticker)
        sources[doc.source_type] = sources.get(doc.source_type, 0) + 1
    return {
        "documents": index.doc_count(),
        "jurisdictions": len(jurisdictions),
        "tickers": len(tickers),
        "sources": sources,
        "corpus_version": _corpus_version(index_dir),
    }


def _identity_chunks(index: InvertedIndex | None) -> list[Chunk]:
    """The shipped chunking: identity chunks over the loaded index's docs
    (`chunk_corpus(docs, 1, 0)`, T-020's locked invariant `len(doc_ids) == 1
    <=> chunk_id == doc_ids[0]`), derived once at startup.

    Retrieval keys everything by chunk_id and this module projects back with
    `chunk.doc_ids[0]`, so these chunks are the only place the two id spaces
    meet. The invariant is not re-asserted here: `chunk_corpus(docs, 1, 0)`
    produces it by construction, and T-022's `hybrid_search` guards it
    corpus-wide (`NonIdentityChunking`, laddered below) for anything that
    ever changes the windowing."""
    if index is None:
        return []
    docs = [index.get_doc(i) for i in range(index.doc_count())]
    return chunk_corpus(docs, 1, 0)


def _warm_embed_store() -> None:
    """Best-effort startup preload of the embedding store into the
    directory-keyed cache, so the first semantic/hybrid request does not pay
    for a full matrix read.

    EVERY failure is swallowed: no store configured, an unresolvable provider
    on a keyless box, a missing directory, a `CorruptStore`. The per-request
    path re-resolves and reports the precise ladder rung; a startup that
    raised here would crash-loop the deploy instead (the T-015 corpus-snapshot
    lesson), and the keyless-lexical guarantee requires this box to keep
    serving regardless."""
    try:
        _load_embed_store(_embed_store_dir(embeddings.get_provider()))
    except Exception as exc:
        logger.info(
            "no embedding store warmed at startup (%s); lexical retrieval is unaffected", exc
        )


def _boot(app: FastAPI) -> None:
    index_dir = Path(os.environ.get("ONRECORD_INDEX", DEFAULT_INDEX_DIR))
    app.state.ui_dir = Path(os.environ.get("ONRECORD_UI_DIR", DEFAULT_UI_DIR))
    # `/api/prices` always has a default corpus path, per the ticket.
    app.state.corpus_path = os.environ.get("ONRECORD_CORPUS", DEFAULT_CORPUS_PATH)
    app.state.prices_cache_dir = os.environ.get("ONRECORD_PRICES_CACHE", DEFAULT_PRICES_CACHE_DIR)

    # Answer rate limiting (2026-08-13, gap-analysis B-4). Env-gated and OFF
    # by default: with neither cap set, `_answer_rate_limited` returns None
    # unconditionally and no state is ever touched. Caps are read at startup
    # (per-test env swapping via TestClient re-entry, same seam convention
    # as every other env read in this function); counters live here so each
    # ASGI startup begins at zero.
    def _cap(name: str) -> int | None:
        raw = os.environ.get(name, "").strip()
        return int(raw) if raw.isdigit() and int(raw) > 0 else None

    app.state.answer_rate = {
        "lock": threading.Lock(),
        "daily_cap": _cap("ONRECORD_ANSWER_DAILY_CAP"),
        "ip_hourly_cap": _cap("ONRECORD_ANSWER_IP_HOURLY_CAP"),
        "day": None,
        "day_count": 0,
        "ip_hits": {},
    }

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

    # T-017: computed once here (not per-request) and cached; `None` when
    # no index loaded, mirroring the existing missing-index 503 contract.
    app.state.stats_cache = (
        _compute_stats(app.state.index, index_dir) if app.state.index is not None else None
    )

    # T-039/T-041 (2026-08-14): insider-transaction rows (env seam
    # ONRECORD_FORM4; empty list when the artifact is absent -> the conduct
    # endpoint's flat 503) and the startup-computed Dodge Index (2.5s over
    # the full corpus, measured -- computed once here like stats, never per
    # request). Both best-effort: neither can fail startup.
    try:
        app.state.form4_rows = conduct_mod.load_transactions(
            os.environ.get("ONRECORD_FORM4", str(conduct_mod.DEFAULT_TRANSACTIONS_PATH))
        )
    except Exception:
        app.state.form4_rows = []
    # T-051: the live/upcoming hearings artifact (env seam
    # ONRECORD_LIVESTREAMS). Best-effort; absent -> None -> flat 503.
    try:
        live_path = Path(os.environ.get("ONRECORD_LIVESTREAMS", "artifacts/livestreams.json"))
        app.state.livestreams = (
            json.loads(live_path.read_text(encoding="utf-8")) if live_path.exists() else None
        )
    except Exception:
        app.state.livestreams = None

    # Hourly in-app refresh (env-gated ONRECORD_LIVE_REFRESH_MINUTES; unset
    # -> no thread, the frozen suite stays zero-network). Daemon thread per
    # the async-boot convention; requires yt-dlp in the image.
    app.state.live_refresh_thread = None
    _live_minutes = os.environ.get("ONRECORD_LIVE_REFRESH_MINUTES", "").strip()
    if _live_minutes.isdigit() and int(_live_minutes) > 0:
        import threading as _threading

        app.state.live_refresh_thread = _threading.Thread(
            target=_live_refresh_loop, args=(app, int(_live_minutes)), daemon=True
        )
        app.state.live_refresh_thread.start()

    # T-040: the Promise Ledger artifact (env seam ONRECORD_PROMISES).
    # Best-effort at startup; absent/unreadable -> empty list -> the
    # endpoint's flat 503.
    try:
        promises_path = Path(os.environ.get("ONRECORD_PROMISES", "evalsets/promises.jsonl"))
        app.state.promises = (
            [json.loads(line) for line in promises_path.open(encoding="utf-8") if line.strip()]
            if promises_path.exists()
            else []
        )
    except Exception:
        app.state.promises = []

    # T-056: quantify the ledger at boot. Deterministic (<1s over 1,527
    # quotes) and derived from promises.jsonl alone — computed rather than
    # shipped as an artifact so it can never go stale against the ledger
    # (the T-055 scoreboard lesson). Rows gain an additive `quantities`
    # field only when extractions fired; rollups are precomputed once (the
    # T-032 no-per-request-scans convention).
    from onrecord.analysis.quantities import aggregate_quantities, extract_quantities

    for _row in app.state.promises:
        _extracted = extract_quantities(str(_row.get("quote", "")))
        if _extracted:
            _row["quantities"] = _extracted
    app.state.promised_rollups = (
        {
            "jurisdiction": aggregate_quantities(app.state.promises, by="jurisdiction"),
            "ticker": aggregate_quantities(app.state.promises, by="ticker"),
        }
        if app.state.promises
        else {}
    )

    # T-057: the outcomes artifact (env seam ONRECORD_OUTCOMES; built by
    # `make refresh-outcomes` — a full-corpus scan too heavy for boot).
    # Absent/unreadable -> promises rows stay outcome-less and the summary
    # endpoint 503s; the ledger itself is never degraded by a missing
    # follow-up layer.
    try:
        outcomes_path = Path(os.environ.get("ONRECORD_OUTCOMES", "artifacts/promise_outcomes.json"))
        outcomes_doc = (
            json.loads(outcomes_path.read_text(encoding="utf-8"))
            if outcomes_path.exists()
            else {}
        )
    except Exception:
        outcomes_doc = {}
    outcome_rows = outcomes_doc.get("outcomes", {})
    app.state.outcomes_generated_at = outcomes_doc.get("generated_at", "")
    app.state.outcomes_by_jurisdiction = {}
    for _row in app.state.promises:
        outcome = outcome_rows.get(_row.get("promise_id"))
        if outcome is None:
            continue
        _row["outcome"] = outcome
        jur = _row.get("jurisdiction")
        if jur:
            bucket = app.state.outcomes_by_jurisdiction.setdefault(jur, {})
            bucket[outcome["status"]] = bucket.get(outcome["status"], 0) + 1
    app.state.outcomes_statuses = {}
    for _o in outcome_rows.values():
        status = _o.get("status", "")
        if status:
            app.state.outcomes_statuses[status] = app.state.outcomes_statuses.get(status, 0) + 1

    # T-059: the ISO-queue artifact (env seam ONRECORD_GRID; built by
    # `make refresh-grid`). Absent -> /api/grid 503s flat.
    try:
        grid_path = Path(os.environ.get("ONRECORD_GRID", "artifacts/iso_queues.json"))
        app.state.grid = (
            json.loads(grid_path.read_text(encoding="utf-8")) if grid_path.exists() else {}
        )
    except Exception:
        app.state.grid = {}

    # T-058: curated shell links, validated at load (verbatim receipts) —
    # a bad row is a boot failure, never a silently-dropped link. The table
    # legitimately ships empty until the owner curates rows.
    from onrecord.analysis.shells import load_shell_links

    try:
        _docs_by_id = (
            {app.state.index.get_doc(i).id: app.state.index.get_doc(i)
             for i in range(app.state.index.doc_count())}
            if app.state.index is not None
            else {}
        )
        app.state.shell_links = load_shell_links("data/shell_links.json", _docs_by_id)
    except FileNotFoundError:
        app.state.shell_links = []

    # T-033: mention-anchored performance cache. Env-gated
    # (ONRECORD_MENTIONS_BOOT) because building it fetches live price
    # series; the frozen suite stays zero-network with it unset. Prod sets
    # it and pays the cost inside the async boot thread.
    app.state.mentions_cache = None
    if os.environ.get("ONRECORD_MENTIONS_BOOT", "").strip() in ("1", "true", "yes"):
        try:
            idx = app.state.index
            if idx is not None:
                since = (datetime.now(UTC).date() - timedelta(days=365)).isoformat()
                docs = [idx.get_doc(i) for i in range(idx.doc_count())]
                mention_docs = [d for d in docs if d.ticker and d.date and d.date >= since]
                tickers = sorted({d.ticker for d in mention_docs})
                cache_dir = os.environ.get("ONRECORD_PRICES_CACHE") or None
                series_by_ticker = {}
                for tk in tickers:
                    series = prices_fetch_eod(tk, range_days=400, cache_dir=cache_dir) \
                        if cache_dir else prices_fetch_eod(tk, range_days=400)
                    if len(series) > 1:
                        series_by_ticker[tk] = series
                app.state.mentions_cache = mentions_mod.mention_rows(
                    mention_docs, series_by_ticker, since=since,
                    now_date=datetime.now(UTC).date().isoformat(),
                )
                logger.info("mentions cache: %d rows over %d tickers",
                            len(app.state.mentions_cache), len(series_by_ticker))
        except Exception:
            logger.exception("mentions cache build failed; endpoint degrades to 503")
            app.state.mentions_cache = None

    dodge_floor_raw = os.environ.get("ONRECORD_DODGE_MIN_DOCS", "").strip()
    app.state.dodge_min_docs = int(dodge_floor_raw) if dodge_floor_raw.isdigit() else 200
    try:
        app.state.dodge_cache = (
            dodge_mod.dodge_index(
                [app.state.index.get_doc(i) for i in range(app.state.index.doc_count())],
                min_docs=app.state.dodge_min_docs,
            )
            if app.state.index is not None
            else None
        )
    except Exception:
        app.state.dodge_cache = None

    # T-024: the RAG state. Chunks are derived from the index that was just
    # loaded (never from a separate corpus read), so the two can never
    # disagree about what is retrievable; the store cache starts empty and is
    # warmed below on a best-effort basis.
    app.state.chunks = _identity_chunks(app.state.index)
    app.state.chunks_by_id = {chunk.chunk_id: chunk for chunk in app.state.chunks}

    # T-060: the 8-K events feed, typed at boot from the loaded index's
    # filing docs (871 rows on corpus-v2; <1s). An unknown item code raises
    # in build_events — surfaced as a boot failure deliberately (a new SEC
    # item deserves a human, not a dropped row); guarded so a corpus
    # without filings just serves the endpoint's flat 503.
    from onrecord.analysis.events8k import ITEM_LABELS, build_events

    if app.state.index is not None:
        _docs = [app.state.index.get_doc(i) for i in range(app.state.index.doc_count())]
        _event_rows = build_events(_docs)
        for _event in _event_rows:
            _event["labels"] = [ITEM_LABELS[c] for c in _event["items"]]
        app.state.events8k = _event_rows
    else:
        app.state.events8k = []
    app.state.embed_stores = {}
    _warm_embed_store()


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """T-048 (2026-08-14): boot dispatch. Default (and every test):
    synchronous — behavior identical to the pre-T-048 lifespan, every env
    seam read at the same moment. With ONRECORD_ASYNC_BOOT set truthy
    (production), the port binds immediately and `_boot` runs in a daemon
    thread: `/` serves the UI at once, `/api/*` returns the ladder's
    honest warming 503s, and the UI's 15s auto-reprobe (PR #17) picks the
    moment readiness lands — a deploy never looks like an outage."""
    if os.environ.get("ONRECORD_ASYNC_BOOT", "").strip().lower() in ("1", "true", "yes"):
        app.state.warming = True
        app.state.index = None

        def _run() -> None:
            try:
                _boot(app)
            finally:
                app.state.warming = False

        threading.Thread(target=_run, name="onrecord-boot", daemon=True).start()
    else:
        app.state.warming = False
        _boot(app)
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
# T-024 embedding-side resolution: provider -> store -> identity, each step a
# ladder rung of its own. Resolved FRESH PER REQUEST through the module seams
# (see the module docstring): a provider folded into a startup-time
# `embed_store = None` would report "store missing" for a missing key.
# --------------------------------------------------------------------------


# Serialises the load-and-insert into `app.state.embed_stores` (see
# `_load_embed_store`). Module level, not per-app-instance: it guards the
# operation, and there is exactly one `app`.
_EMBED_STORE_LOCK = threading.Lock()


def _chunks() -> list[Chunk]:
    return getattr(app.state, "chunks", [])


def _chunks_by_id() -> dict[str, Chunk]:
    return getattr(app.state, "chunks_by_id", {})


def _embed_store_dir(provider: embeddings.EmbeddingProvider) -> Path:
    """`ONRECORD_EMBED_STORE`, else `artifacts/embeddings/<resolved model>` —
    byte-for-byte the default `onrecord/rag/judge.py` computes, so the API and
    the eval harness look in the same place for the same store."""
    configured = os.environ.get(EMBED_STORE_ENV)
    if configured:
        return Path(configured)
    return Path(DEFAULT_EMBED_STORE_ROOT) / provider.model


def _load_embed_store(directory: Path) -> embeddings.EmbeddingStore:
    """Load the T-021 store at `directory`, caching it BY DIRECTORY on
    `app.state`.

    Cached because a real store is a multi-hundred-megabyte matrix read (848
    MB at v2 scale), and keyed by directory rather than kept in one slot
    because the default directory depends on the per-request resolved
    provider model. Failures are never cached: a missing directory fails
    fast, and an operator who builds the store mid-flight should not have to
    restart the process. A store that LOADED, on the other hand, is held for
    the life of the process, exactly as the index is — re-embedding in place
    needs a restart. Every failure mode (missing dir, missing file,
    `CorruptStore`) is the SAME rung: a corrupt store degrades exactly like an
    absent one, so it never serves mis-mapped receipts and never crash-loops
    startup.

    THREAD SAFETY (code review I-1, coupled to the `def` handlers): the
    handlers run in FastAPI's threadpool, so a cold-cache burst arrives here
    genuinely concurrently. Without the lock, N workers each start their own
    multi-hundred-megabyte read of the same store; without the re-check
    INSIDE the lock, they merely do it one after another, which is no better.
    The fast path stays lock-free — the lock is held across a long read, and
    a warm request must never queue behind one."""
    key = str(directory)
    cache = getattr(app.state, "embed_stores", None)
    if cache is not None:
        store = cache.get(key)
        if store is not None:
            return store

    with _EMBED_STORE_LOCK:
        cache = getattr(app.state, "embed_stores", None)
        if cache is None:
            cache = {}
            app.state.embed_stores = cache
        # Re-check under the lock: every worker that missed the fast path is
        # queued here, and all but the first must take what the first loaded.
        store = cache.get(key)
        if store is not None:
            return store

        try:
            store = embeddings.EmbeddingStore.load(directory)
        except Exception as exc:
            logger.warning("embedding store at %s is unavailable: %s", directory, exc)
            raise _Degradation(
                f"no embedding store at {_safe_echo(directory)} — build one, or point "
                f"{EMBED_STORE_ENV} at an existing store"
            ) from exc

        cache[key] = store
        return store


def _require_store_identity(
    store: embeddings.EmbeddingStore, provider: embeddings.EmbeddingProvider
) -> None:
    """A store built by one model queried with another's vectors returns
    meaningless numbers, not weak matches — a WRONG receipt, the product's
    worst failure. The rung names BOTH sides so an operator can see which one
    to fix."""
    if store.model == provider.model and store.dim == provider.dim:
        return
    raise _Degradation(
        f"embedding store identity mismatch: the store was built with "
        f"model={_safe_echo(store.model)!r} (dim={store.dim}), but the resolved provider is "
        f"model={_safe_echo(provider.model)!r} (dim={provider.dim}) — re-embed the corpus "
        f"with this provider, or point {EMBED_STORE_ENV} at the store that matches it"
    )


def _embedding_context() -> tuple[embeddings.EmbeddingStore, embeddings.EmbeddingProvider]:
    """`(store, provider)` for the embedding-backed modes, or the first ladder
    rung that blocks them.

    Provider FIRST: resolving it is free (no network, no spend — construction
    only reads a key), and it is what the default store location is computed
    from, so a keyless box reports the key rather than a store it could never
    have located anyway."""
    try:
        provider = embeddings.get_provider()
    except embeddings.ProviderNotConfigured as exc:
        raise _Degradation(
            "the embedding provider is not configured — set OPENAI_API_KEY to enable "
            "mode=semantic and mode=hybrid (mode=lexical needs no key)"
        ) from exc

    store = _load_embed_store(_embed_store_dir(provider))
    _require_store_identity(store, provider)
    return store, provider


def _fusion_depth() -> int | None:
    """T-037: hybrid fusion depth. Default 2000 (differentially verified
    against full depth on the 100-query judgment set); `ONRECORD_FUSION_DEPTH=0`
    (or negative) restores the frozen full-depth behavior; junk falls back to
    the default rather than crashing a request."""
    raw = os.environ.get("ONRECORD_FUSION_DEPTH", "").strip()
    if not raw:
        return 2000
    try:
        value = int(raw)
    except ValueError:
        return 2000
    return value if value > 0 else None


def _embedding_hits(index: InvertedIndex, mode: str, query: str, k: int) -> list[SearchResult]:
    """T-022 retrieval for `mode`, with every typed error mapped onto its OWN
    rung (AMENDMENT per T-022's test review I-2, extended by code review I-2):
    a partially-embedded store, a stale store and a FAILED EMBEDDING REQUEST
    must each name their condition as a flat 503, never escape as an uncaught
    `text/plain` 500 — and the operator's fix differs in each case."""
    store, provider = _embedding_context()
    chunks = _chunks()
    try:
        if mode == "semantic":
            return retrieve.semantic_search(store, chunks, query, provider, k=k)
        return retrieve.hybrid_search(
            index, store, chunks, query, provider, k=k, fusion_depth=_fusion_depth()
        )
    except retrieve.MissingEmbeddings as exc:
        raise _Degradation(
            f"corpus chunks are not embedded in the configured store ({_safe_echo(exc)}) — "
            f"re-run the embedding build so every chunk has a row"
        ) from exc
    except retrieve.StoreMismatch as exc:
        raise _Degradation(
            f"the embedding store is stale ({_safe_echo(exc)}) — re-embed the chunks whose "
            f"text changed"
        ) from exc
    except retrieve.NonIdentityChunking as exc:
        raise _Degradation(
            f"retrieval requires identity chunking over the loaded corpus ({_safe_echo(exc)})"
        ) from exc
    except embeddings.EmbeddingRequestError as exc:
        # A CONFIGURATION-clean provider that failed MID-REQUEST: a 429, a
        # 401, a 5xx or a transport error that survived T-021's own retries.
        # Every rung above is detectable before any paid call; this one is
        # the most likely thing to happen once keys are provisioned, and it
        # was measured escaping as a text/plain 500 that stripped T-028's
        # card of its diagnosis.
        logger.warning("embedding request failed during %s retrieval: %s", mode, exc)
        raise _Degradation(
            f"embedding request failed ({_safe_echo(exc)}) — the embedding provider did not "
            f"answer; this is usually a rate limit or an expired key, and it is worth "
            f"retrying shortly"
        ) from exc


def _project_to_doc_ids(results: list[SearchResult]) -> list[SearchResult]:
    """Project retrieval's chunk_id-keyed hits into the corpus doc id space
    through the EXPLICIT `chunk.doc_ids[0]` projection (orchestrator
    adjudication of plan-review I-11), so the shared filter/serialise tail
    resolves every result through `index.get_doc` exactly as the lexical path
    does. Under the shipped identity chunking the two ids are equal — the
    projection is what keeps that an invariant rather than a coincidence."""
    chunks_by_id = _chunks_by_id()
    projected: list[SearchResult] = []
    for result in results:
        chunk = chunks_by_id.get(result.doc_id)
        if chunk is None:
            # A hit with no chunk cannot be projected onto a corpus doc, so it
            # cannot carry a receipt: dropping it is the conservative choice.
            # Unreachable while chunks and retrieval share one startup
            # snapshot, which they do.
            continue
        projected.append(
            SearchResult(doc_id=chunk.doc_ids[0], score=result.score, snippet=result.snippet)
        )
    return projected


# --------------------------------------------------------------------------
# GET /health
# --------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/ready")
def ready():  # NOT `async` -- trivial, but keeps the T-024 convention
    """Deploy readiness, distinct from `/health`'s frozen always-200
    liveness contract (T-015): 200 only once the index is actually loaded.

    Railway's healthcheck points here so traffic never cuts over to a
    container that is still booting. Measured 2026-08-16: uvicorn logged
    'Application startup complete' 41s before /api/* stopped 503ing,
    because the corpus/index load runs on the async-boot daemon thread —
    that window is what made post-deploy searches 503 or crawl, which the
    UI then reported as an unreachable engine.
    """
    index = getattr(app.state, "index", None)
    if index is None:
        return _flat_error(503, "index is still loading -- not ready for traffic")
    return {"status": "ready", "documents": index.doc_count()}


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
    date_from: str | None = None,
    date_to: str | None = None,
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
        # T-050: ISO-string comparison; a doc with a blank/malformed date
        # never matches a bounded query (absent evidence is not evidence).
        if date_from is not None and not (doc.date or "") >= date_from:
            return False
        if date_to is not None and not (doc.date or "\uffff") <= date_to:
            return False
        return True

    return [hit for hit in hits if _matches(index.get_doc(hit.doc_id))]


def _filtered_results(
    index: InvertedIndex,
    hits: list,
    *,
    query: str,
    mode: str,
    k: int,
    source: str | None,
    venue: str | None,
    ticker: str | None,
    jurisdiction: str | None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort: str = "score",
) -> dict:
    """The shared `/api/search` tail: AND-combined metadata filters, THEN
    truncation to `k`, then the locked 9-key result dicts. One tail for all
    three modes (T-024) — the filter-then-truncate order and the result shape
    are pinned identically for every mode, so they must not be re-implemented
    per mode."""
    hits = _apply_filters(
        hits, index, source=source, venue=venue, ticker=ticker, jurisdiction=jurisdiction,
        date_from=date_from, date_to=date_to,
    )
    if sort == "date_desc":
        # T-050: reorder the FILTERED set by doc date (stable on ties by the
        # incoming rank) before the same truncation every mode shares.
        hits = sorted(hits, key=lambda h: str(index.get_doc(h.doc_id).date or ""), reverse=True)
    hits = hits[:k]

    results = [
        _doc_to_result_dict(index.get_doc(hit.doc_id), hit.score, hit.snippet) for hit in hits
    ]
    return {"query": query, "mode": mode, "results": results}


@app.get("/api/search")
def search(  # NOT `async` -- see the module docstring's threadpool note
    q: str = "",
    mode: Literal["lexical", "semantic", "hybrid"] = "lexical",
    op: Literal["AND", "OR"] = "OR",
    k: int = Query(default=20, ge=1),
    source: str | None = None,
    venue: str | None = None,
    ticker: str | None = None,
    jurisdiction: str | None = None,
    date_from: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    sort: Literal["score", "date_desc"] = "score",
):
    index = _require_index()
    if index is None:
        return _missing_index_response()

    if mode in ("semantic", "hybrid"):
        # T-024. `op` is accepted and deliberately IGNORED on these modes (a
        # documented accept-and-ignore, not an oversight): it is a boolean
        # candidate-set rule, and neither a cosine ranking nor an RRF fusion
        # has a conjunctive candidate set to narrow. It stays VALIDATED
        # though -- a malformed request is still a malformed request (422).
        #
        # Ranking DEPTH follows the filters. With any metadata filter set,
        # retrieval runs at FULL corpus depth (as the BM25 path below does):
        # an unbounded number of higher-ranked docs can be filtered out, and
        # the pinned order is filter-THEN-truncate. With NO filter the served
        # results are just the first `k` of the ranking, and T-021's
        # `cosine_top_k` is documented to be bit-for-bit the full sort's
        # prefix (ties included), so asking for `k` is exactly equivalent --
        # and it keeps an unfiltered query from paying T-022's per-result
        # hash verification over the whole corpus, which is the cost the
        # orchestrator's result-scoped-verification ruling exists to avoid.
        # The hits are then projected out of the chunk_id space into the
        # corpus doc id space, so the tail below is literally shared.
        filtered = any(value is not None for value in (source, venue, ticker, jurisdiction))
        depth = max(len(_chunks()), 1) if filtered else k
        try:
            hits = _project_to_doc_ids(_embedding_hits(index, mode, q, depth))
        except _Degradation as exc:
            return exc.response()
        return _filtered_results(
            index,
            hits,
            query=q,
            mode=mode,
            k=k,
            source=source,
            venue=venue,
            ticker=ticker,
            jurisdiction=jurisdiction,
            date_from=date_from,
            date_to=date_to,
            sort=sort,
        )

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

    return _filtered_results(
        index,
        hits,
        query=q,
        mode=mode,
        k=k,
        source=source,
        venue=venue,
        ticker=ticker,
        jurisdiction=jurisdiction,
        date_from=date_from,
        date_to=date_to,
        sort=sort,
    )


# --------------------------------------------------------------------------
# POST /api/answer (T-024) -- the real grounded path: retrieve per mode, then
# T-023's answer() over the resolved generator. Its returned dict IS the 200
# body, verbatim (the PINNED-FOR-THURSDAY shape); a refusal is a 200 with a
# populated `refusal` object, because a refusal is an answer, not an error.
# --------------------------------------------------------------------------


MAX_ANSWER_K = 100


class AnswerRequest(BaseModel):
    question: str
    mode: Literal["lexical", "semantic", "hybrid"] = "lexical"
    # `ge=1` mirrors /api/search's frozen `k` convention (and onrecord/cli.py's
    # `--k`); the T-013-era stub accepted any int because it never retrieved.
    #
    # `le` is the code review's Minor-3: this endpoint is no longer a stub, and
    # `k` sizes the set whose FULL TEXT goes into the generator prompt —
    # measured at 1.96 M characters for `k=1000000000` on a 405-doc index, so
    # at corpus scale one unauthenticated request would hand a paid generator
    # something approaching the whole corpus. 100 is comfortably above every
    # real caller (T-028's Ask view sends 8; /api/search's own default depth
    # is 20). /api/search's unbounded `k` is T-013-frozen and spends CPU
    # rather than money — re-pinning it belongs to the wave-10 checklist.
    k: int = Field(default=10, ge=1, le=MAX_ANSWER_K)


def _min_confidence() -> float | None:
    """`ONRECORD_ANSWER_MIN_CONF` as a float; unset or blank → `None` (NO
    threshold — never an invented default, which would refuse real questions
    on a box whose operator never configured a gate).

    A value that does not parse is a 503 naming the var, never a silent
    fall-back to "no threshold": a configured grounding gate that quietly
    evaporates ships ungrounded answers from a box whose operator believes the
    gate is on. 503 rather than 422 because this is a SERVER
    misconfiguration, ladder-consistent with the two key rungs.

    The offending value is LOGGED, never echoed into the response (code
    review Minor-5): it reaches an anonymous caller, it is unbounded, and an
    operator string that happens to contain another rung's word would make
    this message name two conditions. The operator reads their own logs; the
    caller only needs to know which variable is wrong."""
    raw = os.environ.get(MIN_CONFIDENCE_ENV)
    if raw is None or not raw.strip():
        return None
    try:
        return float(raw)
    except ValueError as exc:
        logger.warning("%s is not a valid float: %r", MIN_CONFIDENCE_ENV, raw)
        raise _Degradation(
            f"{MIN_CONFIDENCE_ENV} is not a valid float — set it to a number such as 0.25, "
            f"or unset it to run without a retrieval-confidence gate (the value it is set to "
            f"is in the server log)"
        ) from exc


def _resolve_generator() -> Callable[[str], str]:
    """T-023's generator, resolved fresh per request through the module seam
    and wrapped so a RUNTIME failure is a rung rather than a 500.

    Resolution failure and call failure are two different conditions with two
    different fixes: the first means no key is configured (an operator sets
    one), the second means a configured generator did not complete — an
    Anthropic overload, a rate limit, a timeout, a transport reset — which is
    worth retrying. Both were measured escaping as `text/plain` 500s (code
    review I-2), which is precisely what T-028's Ask view cannot render.

    The wrapper catches EVERY exception, not just T-023's typed
    `GenerationError`: `generate_fn` is an injected seam, so an untyped
    `RuntimeError`/`TimeoutError` from deep in a transport is at least as
    likely, and from the caller's side both mean the same thing. Only the
    exception TYPE reaches the body — the one string here that a third party
    authored, and the one place a message could carry something we never
    audited."""
    try:
        generate_fn = answer_mod.default_generator()
    except answer_mod.GeneratorNotConfigured as exc:
        raise _Degradation(
            "no answer generator is configured — set ANTHROPIC_API_KEY to enable grounded "
            "answers (retrieval-only search needs no key)"
        ) from exc

    def generate(prompt: str) -> str:
        try:
            return generate_fn(prompt)
        except Exception as exc:
            logger.warning("answer generation failed", exc_info=True)
            raise _Degradation(
                f"generation failed ({_safe_echo(type(exc).__name__)}) — the answer generator "
                f"did not complete; the retrieval side is healthy, so this is worth retrying"
            ) from exc

    return generate


def _lexical_ranking(index: InvertedIndex, query: str, k: int) -> list:
    """BM25 hits at depth `k` through the same feature-detected seam
    `/api/search`'s lexical mode uses."""
    ranked_search = _resolve_search_fn()
    if ranked_search is None:
        # Unreachable in any worktree that can import `onrecord.rag.retrieve`
        # (it imports `ranked_search` unconditionally); kept so this path
        # degrades exactly like /api/search's lexical mode rather than raising.
        return boolean_search(index, query, "OR")[:k]
    return ranked_search(index, query, k=k)


def _retrieve_for_answer(
    index: InvertedIndex, mode: str, question: str, k: int
) -> tuple[list[Chunk], list[float] | None]:
    """The top `k` chunks for `question` under `mode`, in RETRIEVAL RANK ORDER,
    with the REAL retrieval scores positionally aligned.

    Both halves are load-bearing (AMENDMENT 2026-08-12, T-026 review — the CLI
    seam was found discarding both): citation `[n]` indexes the chunk list, so
    a reordering silently re-attributes every citation, and `answer()`
    substitutes `0.0` placeholders when the scores are dropped, which is
    invisible in the response shape but disables the confidence gate and lies
    in the UI's retrieved panel."""
    if mode == "lexical":
        hits = _lexical_ranking(index, question, k)
    else:
        hits = _embedding_hits(index, mode, question, k)

    chunks_by_id = _chunks_by_id()
    chunks: list[Chunk] = []
    scores: list[float] = []
    for hit in hits:
        chunk = chunks_by_id.get(hit.doc_id)
        if chunk is None:
            # See `_project_to_doc_ids`: a hit with no chunk cannot be
            # grounded, so it cannot be answered from.
            continue
        chunks.append(chunk)
        scores.append(float(hit.score))
    return chunks, scores


def _answer_rate_limited(http_request: Request) -> JSONResponse | None:
    """Return a flat 429 (with Retry-After) when a configured cap is
    exhausted, else record the hit and return None. Runs BEFORE the
    availability ladder: a rate-limited caller gets 429 even where an
    unkeyed deploy would 503 — the limiter protects the box and the owner's
    provider budget, not just successful generations. No caps configured
    (the default, and every keyless/test context) -> pure no-op."""
    state = getattr(app.state, "answer_rate", None)
    if state is None or (state["daily_cap"] is None and state["ip_hourly_cap"] is None):
        return None

    now = time.time()
    today = datetime.now(UTC).date()
    forwarded = http_request.headers.get("x-forwarded-for", "")
    client_ip = (
        forwarded.split(",")[0].strip()
        if forwarded.strip()
        else (http_request.client.host if http_request.client else "unknown")
    )

    with state["lock"]:
        if state["day"] != today:
            state["day"] = today
            state["day_count"] = 0

        if state["daily_cap"] is not None and state["day_count"] >= state["daily_cap"]:
            midnight = datetime.combine(
                today + timedelta(days=1), dt_time.min, tzinfo=UTC
            )
            retry_after = max(1, int((midnight - datetime.now(UTC)).total_seconds()))
            response = _flat_error(
                429, "rate limited: the daily answer budget is spent; resets at midnight UTC"
            )
            response.headers["Retry-After"] = str(retry_after)
            return response

        hits = state["ip_hits"].setdefault(client_ip, [])
        hits[:] = [t for t in hits if now - t < 3600.0]
        if state["ip_hourly_cap"] is not None and len(hits) >= state["ip_hourly_cap"]:
            retry_after = max(1, int(3600.0 - (now - hits[0])))
            response = _flat_error(
                429, "rate limited: hourly per-client answer budget reached; slow down"
            )
            response.headers["Retry-After"] = str(retry_after)
            return response

        state["day_count"] += 1
        hits.append(now)
    return None


@app.post("/api/answer")
def answer(request: AnswerRequest, http_request: Request):  # NOT `async` -- see module docstring
    limited = _answer_rate_limited(http_request)
    if limited is not None:
        return limited

    index = _require_index()
    if index is None:
        # Index BEFORE everything else (cheapest check, and the honest one):
        # a box with no index has nothing to answer from regardless of which
        # keys are missing, so this is the rung that points at the blocker.
        return _missing_index_response()

    try:
        min_confidence = _min_confidence()
        # Resolved BEFORE retrieval: an answer is not an answer without a
        # generator, and a box that cannot generate should not first pay a
        # provider to embed the question.
        generate_fn = _resolve_generator()
        chunks, scores = _retrieve_for_answer(index, request.mode, request.question, request.k)
        if min_confidence is not None and scores is None:
            # Unreachable through correct wiring (retrieval always produces
            # scores) -- which is the point: this is the tripwire that stops a
            # future regression from presenting as a normal 200 with a
            # threshold that was never enforced.
            raise MinConfidenceWithoutScores(
                f"{MIN_CONFIDENCE_ENV} is configured but retrieval produced no scores to "
                f"compare it against"
            )
        return answer_mod.answer(
            request.question,
            chunks,
            generate_fn,
            retrieval_scores=scores,
            min_confidence=min_confidence,
        )
    except MinConfidenceWithoutScores as exc:
        return _flat_error(422, str(exc))
    except _Degradation as exc:
        return exc.response()


# --------------------------------------------------------------------------
# GET /api/tickers
# --------------------------------------------------------------------------


@app.get("/api/live")
def live_endpoint():  # NOT `async` -- serves the startup-loaded artifact
    """T-051: live & upcoming hearings across the tracked jurisdictions.
    Tracked at refresh time (`make refresh-live`); `checked_at` says when."""
    payload = getattr(app.state, "livestreams", None)
    if payload is None:
        return _flat_error(
            503,
            "live hearing tracking is not refreshed -- run `make refresh-live` "
            "to produce artifacts/livestreams.json (ticket T-051)",
        )
    return {
        "checked_at": payload.get("checked_at", ""),
        "jurisdictions_resolved": payload.get("jurisdictions_resolved", 0),
        "live": payload.get("live", []),
        "upcoming": payload.get("upcoming", [])[:20],
    }


@app.get("/api/mentions")
def mentions_endpoint(  # NOT `async` -- serves the startup-computed cache
    window: int = Query(default=90, ge=1, le=365),
    k: int = Query(default=25, ge=1, le=200),
):
    """T-033: the record's calls. Mentions (ticker-attributed docs) with
    entry price anchored to the mention date's close, ranked by return
    since. Daily-close grain; `co_mentions` counts the trailing-365d set."""
    rows = getattr(app.state, "mentions_cache", None)
    if rows is None:
        return _flat_error(
            503,
            "mention performance is not computed -- set ONRECORD_MENTIONS_BOOT=1 "
            "(build happens at startup from the price cache)",
        )
    cutoff = (datetime.now(UTC).date() - timedelta(days=window)).isoformat()
    windowed = [r for r in rows if r["date"] >= cutoff]
    return {"rows": windowed[:k], "total": len(windowed), "window_days": window,
            "grain": "daily-close"}


@app.get("/api/promises")
def promises_endpoint(  # NOT `async` -- serves startup-loaded rows
    jurisdiction: str | None = None,
    ticker: str | None = None,
    category: str | None = None,
    k: int = Query(default=50, ge=1, le=500),
):
    """T-040: the Promise Ledger. Verbatim-pinned extracted commitments,
    date descending, filterable. `total`/`categories` describe the FILTERED
    set before the `k` truncation."""
    rows = getattr(app.state, "promises", [])
    if not rows:
        return _flat_error(
            503,
            "the promise ledger is not extracted -- run the T-040 extraction "
            "to produce evalsets/promises.jsonl",
        )
    if jurisdiction is not None:
        rows = [r for r in rows if r.get("jurisdiction") == jurisdiction]
    if ticker is not None:
        rows = [r for r in rows if r.get("ticker") == ticker]
    if category is not None:
        rows = [r for r in rows if r.get("category") == category]
    rows = sorted(rows, key=lambda r: str(r.get("date") or ""), reverse=True)
    categories: dict[str, int] = {}
    for row in rows:
        cat = row.get("category", "other")
        categories[cat] = categories.get(cat, 0) + 1
    return {"rows": rows[:k], "total": len(rows), "categories": dict(sorted(categories.items()))}


@app.get("/api/promised")
def promised_endpoint(  # NOT `async` -- serves boot-precomputed rollups
    by: str = Query(default="jurisdiction", pattern="^(jurisdiction|ticker)$"),
):
    """T-056: what the record promises, in numbers. Boot-precomputed
    rollups of extracted quantities (MW / GPD / jobs / dollars) keyed by
    jurisdiction or ticker."""
    rollups = getattr(app.state, "promised_rollups", {})
    if not rollups:
        return _flat_error(
            503,
            "the promise ledger is not extracted -- run the T-040 extraction "
            "to produce evalsets/promises.jsonl",
        )
    selected = rollups.get(by, {})
    return {
        "by": by,
        "rollups": selected,
        "n_quantified_total": sum(b["n_quantified"] for b in selected.values()),
    }


def _refresh_live_once(application, track_fn) -> None:
    """Swap the hearings-on-air payload from a tracker callable. Failures
    leave the previous payload serving (stale-with-checked_at beats empty)."""
    try:
        payload = track_fn()
        if payload and isinstance(payload.get("upcoming"), list):
            application.state.livestreams = payload
    except Exception:
        logger.warning("live refresh cycle failed; keeping previous payload", exc_info=True)


def _live_refresh_loop(application, interval_minutes: int) -> None:
    """Daemon loop: re-run the livestream tracker every interval. The
    hearings strip is the one surface where daily is not enough — liveness
    decays in hours, so it refreshes in-process (no commits, no deploys)."""
    import time as _time

    from onrecord.ingest.build_corpus import load_corpus_snapshot
    from onrecord.ingest.livestreams import track

    alive_path = Path("evalsets/linkhealth-2026-08-14.jsonl")
    while True:
        _time.sleep(max(interval_minutes, 5) * 60)

        def _run():
            docs = load_corpus_snapshot(
                os.environ.get("ONRECORD_CORPUS", "corpus/v3/corpus.jsonl.gz")
            )
            alive = {
                json.loads(line)["video_id"]
                for line in alive_path.open(encoding="utf-8")
                if line.strip() and json.loads(line)["status"] == "alive"
            }
            from datetime import UTC as _UTC
            from datetime import datetime as _dt
            return track(docs, alive,
                         checked_at=_dt.now(_UTC).isoformat(timespec="minutes"))

        _refresh_live_once(application, _run)


def _snaptrade_ready() -> tuple[str, str] | None:
    client_id = os.environ.get("SNAPTRADE_CLIENT_ID", "").strip()
    consumer_key = os.environ.get("SNAPTRADE_CONSUMER_KEY", "").strip()
    return (client_id, consumer_key) if client_id and consumer_key else None


_SNAPTRADE_503 = (
    "the portfolio lens is not configured -- set SNAPTRADE_CLIENT_ID and "
    "SNAPTRADE_CONSUMER_KEY (read-only scope; see tickets/T-065.md)"
)


@app.post("/api/portfolio/connect")
def portfolio_connect():  # NOT `async` -- short outbound POSTs, threadpool
    """T-065: create (or reuse) the deployment's single read-only SnapTrade
    connection and return the hosted portal URL. Credentials never touch
    this server; the portal handles brokerage auth."""
    from onrecord.act import portfolio as _portfolio

    creds = _snaptrade_ready()
    if creds is None:
        return _flat_error(503, _SNAPTRADE_503)
    client_id, consumer_key = creds
    transport = getattr(app.state, "snaptrade_transport", None)
    state_path = _portfolio.state_path()
    # userId is deployment-scoped (env seam) — the same SnapTrade account
    # serves local dev and prod, and userIds are globally unique per
    # partner, so each deployment registers its own.
    user_id = os.environ.get("ONRECORD_SNAPTRADE_USER", "onrecord")
    try:
        connection = _portfolio.load_connection(state_path)
        if connection is None:
            user_secret = _portfolio.register_user(
                client_id, consumer_key, user_id, transport=transport
            )
            _portfolio.save_connection(state_path, user_id, user_secret)
            connection = {"user_id": user_id, "user_secret": user_secret}
        portal = _portfolio.login_url(
            client_id, consumer_key, connection["user_id"], connection["user_secret"],
            connection_type="read", transport=transport,
        )
    except _portfolio.SnapTradeRequestError as exc:
        return _flat_error(502, f"snaptrade request failed: {exc}")
    return {"portal_url": portal, "scope": "read"}


@app.get("/api/portfolio")
def portfolio_view():  # NOT `async` -- threadpool; strictly factual join
    """T-065: the connected account's holdings crossed with the record.
    Facts only — what you hold, what the record shows. Never advice."""
    from onrecord.act import portfolio as _portfolio

    creds = _snaptrade_ready()
    if creds is None:
        return _flat_error(503, _SNAPTRADE_503)
    client_id, consumer_key = creds
    connection = _portfolio.load_connection(_portfolio.state_path())
    if connection is None:
        return {"connected": False}
    transport = getattr(app.state, "snaptrade_transport", None)
    try:
        positions = _portfolio.holdings(
            client_id, consumer_key, connection["user_id"], connection["user_secret"],
            transport=transport,
        )
    except _portfolio.SnapTradeRequestError:
        # Registered but no brokerage linked yet (the usual case between
        # /connect and the user finishing the portal), or an upstream blip.
        # This runs on EVERY page load — it must never be a 500.
        logger.info("snaptrade holdings unavailable; reporting pending link")
        return {"connected": False, "pending_link": True}
    from onrecord.analysis import conduct as conduct_mod

    held = {p["symbol"] for p in positions if p.get("symbol")}
    form4_rows = getattr(app.state, "form4_rows", [])
    since = (datetime.now(UTC).date() - timedelta(days=365)).isoformat()
    conduct_by_ticker = {
        t: conduct_mod.net_flow(form4_rows, t, since) for t in held
    } if form4_rows else {}
    promised = getattr(app.state, "promised_rollups", {}).get("ticker", {})
    mention_rows = (getattr(app.state, "mentions_cache", {}) or {}).get("rows", [])
    crossed = _portfolio.cross_with_record(
        positions,
        getattr(app.state, "events8k", []),
        conduct_by_ticker,
        promised,
        mention_rows,
    )
    # Additive per-ticker outcome counts (followed_up / quiet) — the API-
    # level join the module's frozen signature doesn't carry.
    outcome_counts: dict[str, dict[str, int]] = {}
    for _row in getattr(app.state, "promises", []):
        t = _row.get("ticker")
        o = _row.get("outcome")
        if t in held and o:
            bucket = outcome_counts.setdefault(t, {})
            bucket[o["status"]] = bucket.get(o["status"], 0) + 1
    for pos in crossed:
        if pos.get("record") is not None:
            pos["record"]["outcomes"] = outcome_counts.get(pos["symbol"], {})
    return {"connected": True, "positions": crossed,
            "disclosure": "read-only via SnapTrade; disconnect anytime in the portal"}


@app.get("/api/grid")
def grid_endpoint(jurisdiction: str | None = None):  # NOT `async` -- boot-loaded
    """T-059: what's actually FILED with grid operators, joined to our
    jurisdictions. Queued and withdrawn MW are separate figures, and this
    data is never summed with promised MW — filed and promised are
    different acts by different parties."""
    grid = getattr(app.state, "grid", {})
    rows = grid.get("rows", [])
    if not rows:
        return _flat_error(
            503,
            "the ISO queue artifact is not built -- run `make refresh-grid` "
            "to produce artifacts/iso_queues.json",
        )
    if jurisdiction is not None:
        rows = [r for r in rows if r.get("jurisdiction") == jurisdiction]
        return {"rows": rows, "total": len(rows), "fetched_at": grid.get("fetched_at", "")}
    by_jurisdiction: dict[str, dict] = {}
    for r in grid.get("rows", []):
        bucket = by_jurisdiction.setdefault(
            r["jurisdiction"], {"queued_mw": 0.0, "withdrawn_mw": 0.0, "n_projects": 0}
        )
        bucket["n_projects"] += 1
        if r.get("withdrawn"):
            bucket["withdrawn_mw"] += float(r.get("mw", 0.0))
        else:
            bucket["queued_mw"] += float(r.get("mw", 0.0))
    return {
        "by_jurisdiction": by_jurisdiction,
        "sources": grid.get("sources", []),
        "fetched_at": grid.get("fetched_at", ""),
        "misses_count": grid.get("misses_count", 0),
    }


@app.get("/api/shells")
def shells_endpoint():  # NOT `async` -- boot-validated curated table
    """T-058: who is actually behind the record's project names. Only
    curated, receipt-validated links resolve; an empty table is an honest
    state, not an error."""
    links = getattr(app.state, "shell_links", [])
    return {"resolved": links, "curated_total": len(links)}


@app.get("/api/events")
def events_endpoint(  # NOT `async` -- serves boot-typed rows
    ticker: str | None = None,
    k: int = Query(default=50, ge=1, le=500),
):
    """T-060: material events per ticker from 8-K item typing. Date
    descending; `total` counts the filtered set before truncation."""
    rows = getattr(app.state, "events8k", [])
    if not rows:
        return _flat_error(
            503,
            "no 8-K events are typed -- the loaded index carries no filing "
            "docs with Item headers",
        )
    if ticker is not None:
        rows = [r for r in rows if r.get("ticker") == ticker]
    return {"rows": rows[:k], "total": len(rows)}


@app.get("/api/outcomes/summary")
def outcomes_summary_endpoint():  # NOT `async` -- serves boot-loaded artifact
    """T-057: follow-up status counts over the ledger. The record shows
    followed-up or gone-quiet — it never adjudicates promises."""
    statuses = getattr(app.state, "outcomes_statuses", {})
    if not statuses:
        return _flat_error(
            503,
            "promise outcome trails are not built -- run `make refresh-outcomes` "
            "to produce artifacts/promise_outcomes.json",
        )
    return {
        "statuses": statuses,
        "generated_at": getattr(app.state, "outcomes_generated_at", ""),
        "by_jurisdiction": getattr(app.state, "outcomes_by_jurisdiction", {}),
    }


@app.get("/api/conduct/{ticker}")
def conduct_endpoint(ticker: str):  # NOT `async` -- T-024 convention
    """T-039: trailing-365d open-market insider net flow for `ticker`,
    from the T-038 Form 4 artifact. Juxtaposition data only."""
    rows = getattr(app.state, "form4_rows", [])
    if not rows:
        return _flat_error(
            503,
            "insider data is not ingested -- run the Form 4 pull "
            "(onrecord.ingest.form4.pull_form4, ticket T-038)",
        )
    since = (datetime.now(UTC) - timedelta(days=365)).date().isoformat()
    return conduct_mod.net_flow(rows, ticker.upper(), since)


@app.get("/api/dodge")
def dodge_endpoint():  # NOT `async` -- serves the startup-computed cache
    """T-041: deterministic per-jurisdiction evasion rows (computed once at
    startup over the loaded index; lexicon published for reproducibility)."""
    cache = getattr(app.state, "dodge_cache", None)
    if cache is None:
        return _missing_index_response()
    return {
        "rows": cache,
        "min_docs": getattr(app.state, "dodge_min_docs", 200),
        "markers": list(dodge_mod.DODGE_MARKERS),
    }


@app.get("/api/tickers")
def tickers():  # NOT `async` (T-032) -- CPU-bound index scan; threadpool dispatch
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
# GET /api/stats (T-017) -- hero-strip live corpus numbers, computed once
# at startup (see _compute_stats + _lifespan above) and cached.
# --------------------------------------------------------------------------


@app.get("/api/stats")
async def stats():
    cache = getattr(app.state, "stats_cache", None)
    if cache is None:
        return _missing_index_response()
    return cache


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
def prices(ticker: str, range: int = 365, threshold: float = 5.0) -> dict:
    # NOT `async` (T-032) -- api_payload does REAL network IO (yahoo, since
    # T-034) on a cache miss; on the event loop that starved every
    # concurrent request (observed live: search timeouts -> UI demo-data
    # fallback). Threadpool dispatch, same convention as search()/answer().
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

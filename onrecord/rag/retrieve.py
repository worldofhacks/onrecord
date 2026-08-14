"""Retrieval modes — semantic search, RRF hybrid fusion (T-022).

Pure retrieval functions consumed by T-024's API wiring; no FastAPI import
anywhere in this module. Consumes T-020's `Chunk`/`chunk_corpus` and T-021's
`EmbeddingStore`/`cosine_top_k`/`content_hash`. The authoritative contract
lives in `tests/unit/rag/test_retrieve.py`'s module docstring (frozen suite,
including its "PIN ROUND 2" section) — read it in full before touching this
file. Summary of what's implemented here:

`semantic_search(store, chunks, query, provider, k=10) -> list[SearchResult]`
  * Embeds ONLY the query (`provider.embed([query])`) — the corpus is
    embedded once, up front, by T-021's `EmbeddingStore.embed_corpus`.
  * Resolves rows CHUNK_ID-KEYED via `store.rows_for(chunk_ids)` — never
    positionally, and never via content hash (both are `str`; passing
    hashes would fail SILENTLY as a total miss).
  * A chunk with no store row raises `MissingEmbeddings` naming the COUNT —
    checked corpus-wide, before any ranking, at every `k` including `k=1`.
  * Store rows uncovered by `chunks` (prior embed runs, other corpus
    versions) never surface AND never consume a result slot: a bounded
    grow-k retry (score at `k`, double, retry) fills the cut past however
    deep a field of uncovered rows sits above it, without paying for a
    full-depth scan when the store is small. This pins the OBSERVABLE, not
    the strategy (a full-depth scan also satisfies every test here).
  * VERIFIES the recorded `content_hash` of every row it is about to
    RETURN against that chunk's current text — a disagreement (stale text)
    raises `StoreMismatch` naming the chunk_id and both hashes.
    Verification is RESULT-SCOPED (orchestrator ruling, locked): only rows
    that end up in the returned top-k are hashed, not the whole chunk set.
    Verification always goes through T-021's public `store.entry_for(...)`
    — never a private `store._entries` reach (review round 2: that saving
    belongs to a T-021 accessor, not here).
  * `SearchResult(doc_id=chunk.chunk_id, score=<cosine float>,
    snippet=chunk.text[:160])`; `score` is a builtin `float`.
  * `k <= 0` returns `[]` (ask for nothing, get nothing) — never an error,
    unlike `hybrid_search` below.
  * Receipt (`SearchResult`) construction scales with the number of
    results returned, never with the corpus or with `len(chunks)` — the
    ranking core (`_semantic_ranking`) verifies and returns `(chunk,
    score)` pairs, and only the caller-facing wrapper builds `SearchResult`
    objects, for exactly the pairs it is about to return. This is what
    lets `hybrid_search` consume a full `k=len(chunks)` semantic ranking
    (verifying every chunk, per the ruling above) without materializing a
    receipt per chunk (review round 2, Important-1).

`rrf_fuse(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]`
  * `score(id) = sum over rankings containing id of 1/(k + rank)`, rank
    1-based; sorted by score DESC, ties by id ASC. An id absent from a
    ranking contributes nothing (no penalty term). `k=60` is a standing
    locked decision.
  * `k <= 0` raises `ValueError` — `k` is RRF's smoothing constant, not a
    result count; `k=0` would silently degrade the formula to `1/rank` and
    a negative `k` hits `k + rank == 0` at some rank, a bare
    `ZeroDivisionError` from inside the fusion.

`hybrid_search(index, store, chunks, query, provider, k=10, rrf_k=60)`
  * GUARDS identity chunking FIRST, corpus-wide, over every chunk: each
    must satisfy `chunk.chunk_id == chunk.doc_ids[0] and len(chunk.doc_ids)
    == 1`, else `NonIdentityChunking` — fusion is defined over ONE id space
    (chunk_id), and the lexical ranking's ids are corpus doc ids, valid
    fusion input only under that identity invariant.
  * `k <= 0` or `rrf_k <= 0` raises `ValueError`, checked before any work —
    `fused[:k]` on a negative `k` is a negative slice (a wrong-LENGTH
    receipt with no error), which this ticket refuses to ship silently.
  * Lexical ranking at FULL DEPTH — `ranked_search(index, query,
    k=index.doc_count())` — RRF needs deep rankings.
    [T-037 AMENDMENT 2026-08-14: full depth is the DEFAULT, not the only
    mode. `fusion_depth=N` bounds both arms to their top max(k, N) — on the
    production corpus (289,536 chunks) full depth costs 7.8s/query on
    deploy hardware (full lexical materialization + a per-row hash
    verification for every returned semantic row + full-sort tail), which
    made hybrid time out in every interactive client. Bounded fusion at
    N=2000 was differentially verified against full depth on the 100-query
    judgment set before shipping (see tickets/T-037.md). `None` preserves
    the frozen behavior bit for bit.]
  * Semantic ranking = `_semantic_ranking(..., k=len(chunks))`, consumed as
    an ID SEQUENCE — every chunk is hash-verified (result-scoped
    verification at `k=len(chunks)` covers everything), but NO
    `SearchResult` is constructed for the ranking itself; only the final
    fused-and-truncated `k` results become `SearchResult`s.
  * Fuses, truncates to `k`, `score=<RRF score>`; snippet from the lexical
    hit when the id appeared lexically (positional snippets are strictly
    better), else `chunk.text[:160]`.

Errors: `StoreMismatch`, `MissingEmbeddings`, `NonIdentityChunking` are three
pairwise-distinct types, none a subclass of another, and none a subclass of
T-021's `StoreIdentityMismatch`/`CorruptStore` — T-024's degradation ladder
branches on them by name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from onrecord.rag.embeddings import EmbeddingStore, content_hash, cosine_top_k
from onrecord.search.ranked import ranked_search
from onrecord.types import SearchResult

if TYPE_CHECKING:
    from onrecord.index.inverted import InvertedIndex
    from onrecord.rag.chunking import Chunk
    from onrecord.rag.embeddings import EmbeddingProvider

SNIPPET_LEN = 160


class StoreMismatch(Exception):
    """A store row's recorded `content_hash` disagrees with the current
    chunk's text (stale text) — the message names the chunk_id and both
    the recorded and recomputed hashes."""


class MissingEmbeddings(Exception):
    """One or more chunks handed to `semantic_search`/`hybrid_search` have
    no row in the embedding store — the message names the count. Checked
    corpus-wide, at every `k`: a wrong receipt is the product's worst
    failure, never a silent skip."""


class NonIdentityChunking(Exception):
    """`hybrid_search` was handed a chunk that is not an identity chunk
    (`chunk_id != doc_ids[0]` or `len(doc_ids) != 1`) — fusion is defined
    over one id space (chunk_id) and cannot degrade into a no-overlap
    concatenation."""


def _resolve_covered_rows(store: EmbeddingStore, chunks: list[Chunk]) -> dict[int, Chunk]:
    """Chunk_id-keyed row resolution (never positional, never content-hash
    keyed). Raises `MissingEmbeddings` naming the count of chunks that have
    no row at all — a corpus-wide check, independent of any `k`."""
    chunk_ids = [chunk.chunk_id for chunk in chunks]
    rows = store.rows_for(chunk_ids)
    missing = sum(1 for row in rows if row is None)
    if missing:
        raise MissingEmbeddings(
            f"{missing} chunk(s) have no row in the embedding store (embed them before searching)"
        )
    return {row: chunk for chunk, row in zip(chunks, rows, strict=True)}


def _covered_top_k(
    store: EmbeddingStore,
    query_vec,
    k: int,
    row_to_chunk: dict[int, Chunk],
) -> list[tuple[int, float]]:
    """`cosine_top_k` restricted to rows covered by `row_to_chunk`, filling
    `k` covered results even when uncovered rows (prior embed runs) rank
    above every chunk — a bounded grow-k retry, doubling the underlying
    scan until either `k` covered rows are in hand or the whole store has
    been scanned. Pins the RESULT (a full-depth scan also satisfies it),
    not the strategy."""
    n_rows = store.matrix.shape[0]
    limit = max(k, 1)
    covered: list[tuple[int, float]] = []
    while True:
        candidates = cosine_top_k(store, query_vec, limit)
        covered = [(row, score) for row, score in candidates if row in row_to_chunk]
        if len(covered) >= k or limit >= n_rows:
            break
        limit = min(limit * 2, n_rows)
    return covered[:k]


def _verify_chunk(store: EmbeddingStore, chunk: Chunk) -> None:
    """Raise `StoreMismatch` (naming the chunk_id and both hashes) when the
    store's recorded `content_hash` for `chunk.chunk_id` disagrees with the
    chunk's current text. Always through T-021's public `entry_for` — never
    a private `store._entries` reach."""
    entry = store.entry_for(chunk.chunk_id)
    expected = content_hash(store.model, store.dim, chunk.text)
    recorded = entry["content_hash"]
    if recorded != expected:
        raise StoreMismatch(
            f"chunk {chunk.chunk_id!r}: store content_hash {recorded!r} does not match "
            f"the recomputed content_hash {expected!r} for the chunk's current text "
            f"(stale row)"
        )


def _semantic_ranking(
    store: EmbeddingStore,
    chunks: list[Chunk],
    query: str,
    provider: EmbeddingProvider,
    k: int,
) -> list[tuple[Chunk, float]]:
    """The verified core of `semantic_search`: cosine-ranked, result-scoped
    hash-verified `(chunk, score)` pairs, cosine order, top `k` covered
    rows — with NO `SearchResult` construction. `semantic_search` wraps
    this to build receipts for its own callers; `hybrid_search` consumes it
    directly as an id sequence (`k=len(chunks)`, so every chunk is verified)
    without paying to materialize a receipt per chunk (review round 2,
    Important-1)."""
    row_to_chunk = _resolve_covered_rows(store, chunks)

    query_vec = provider.embed([query])[0]

    covered = _covered_top_k(store, query_vec, k, row_to_chunk)

    ranking: list[tuple[Chunk, float]] = []
    for row, score in covered:
        chunk = row_to_chunk[row]
        _verify_chunk(store, chunk)
        ranking.append((chunk, float(score)))
    return ranking


def semantic_search(
    store: EmbeddingStore,
    chunks: list[Chunk],
    query: str,
    provider: EmbeddingProvider,
    k: int = 10,
) -> list[SearchResult]:
    """Embed `query`, rank `chunks` by cosine similarity over `store`, and
    return the top `k` as `SearchResult`s. See module docstring for the
    frozen contract (coverage/verification/uncovered-row rules)."""
    ranking = _semantic_ranking(store, chunks, query, provider, k)
    return [
        SearchResult(doc_id=chunk.chunk_id, score=score, snippet=chunk.text[:SNIPPET_LEN])
        for chunk, score in ranking
    ]


def rrf_fuse(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion: `score(id) = sum over rankings containing id
    of 1/(k + rank)`, rank 1-based. Sorted by score descending, ties broken
    by id ascending (byte-wise). An id absent from a ranking contributes
    nothing — no penalty term. `k <= 0` raises `ValueError` (see module
    docstring)."""
    if k <= 0:
        raise ValueError(f"rrf_fuse: k must be positive, got k={k!r}")
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def _guard_identity_chunking(chunks: list[Chunk]) -> None:
    for chunk in chunks:
        if not (chunk.chunk_id == chunk.doc_ids[0] and len(chunk.doc_ids) == 1):
            raise NonIdentityChunking(
                "hybrid_search requires identity chunking (chunk_id == doc_ids[0] and "
                "len(doc_ids) == 1) for every chunk — fusion is defined over one id "
                "space (chunk_id), and the lexical ranking's ids are corpus doc ids"
            )


def hybrid_search(
    index: InvertedIndex,
    store: EmbeddingStore,
    chunks: list[Chunk],
    query: str,
    provider: EmbeddingProvider,
    k: int = 10,
    rrf_k: int = 60,
    fusion_depth: int | None = None,
) -> list[SearchResult]:
    """RRF-fuse a lexical ranking with a semantic ranking over `chunks`,
    both keyed by chunk_id under the identity-chunking invariant.

    `fusion_depth=None` (the default, and every pre-T-037 caller) fuses at
    FULL depth — the frozen T-022 behavior, bit for bit. A positive
    `fusion_depth` bounds both arms to their top `max(k, fusion_depth)`
    entries, which bounds the semantic arm's per-row hash verification and
    the lexical materialization to the fused window instead of the whole
    corpus (T-037; measured 7.8s -> ~2s per query on the production
    corpus). See module docstring for the contract."""
    if k <= 0:
        raise ValueError(f"hybrid_search: k must be positive, got k={k!r}")
    if rrf_k <= 0:
        raise ValueError(f"hybrid_search: rrf_k must be positive, got rrf_k={rrf_k!r}")
    if fusion_depth is not None and fusion_depth <= 0:
        raise ValueError(
            f"hybrid_search: fusion_depth must be positive or None, got {fusion_depth!r}"
        )

    _guard_identity_chunking(chunks)

    if fusion_depth is None:
        lexical_depth = index.doc_count()
        semantic_depth = len(chunks)
    else:
        depth = max(k, fusion_depth)
        lexical_depth = min(depth, index.doc_count())
        semantic_depth = min(depth, len(chunks))

    lexical_results = ranked_search(index, query, k=lexical_depth)
    lexical_by_id = {result.doc_id: result for result in lexical_results}
    lexical_ranking = [result.doc_id for result in lexical_results]

    semantic_ranking_pairs = _semantic_ranking(store, chunks, query, provider, semantic_depth)
    semantic_ranking = [chunk.chunk_id for chunk, _score in semantic_ranking_pairs]

    fused = rrf_fuse([lexical_ranking, semantic_ranking], k=rrf_k)

    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}

    results: list[SearchResult] = []
    for doc_id, score in fused[:k]:
        lexical_hit = lexical_by_id.get(doc_id)
        snippet = (
            lexical_hit.snippet
            if lexical_hit is not None
            else chunks_by_id[doc_id].text[:SNIPPET_LEN]
        )
        results.append(SearchResult(doc_id=doc_id, score=float(score), snippet=snippet))
    return results

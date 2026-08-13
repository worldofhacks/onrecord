"""Retrieval modes — semantic search, RRF hybrid fusion (T-022).

Pure retrieval functions consumed by T-024's API wiring; no FastAPI import
anywhere in this module. Consumes T-020's `Chunk`/`chunk_corpus` and T-021's
`EmbeddingStore`/`cosine_top_k`/`content_hash`. The authoritative contract
lives in `tests/unit/rag/test_retrieve.py`'s module docstring (frozen suite)
— read it in full before touching this file. Summary of what's implemented
here:

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
    the strategy (a full-depth scan also satisfies every test here) — see
    the frozen suite's "Test Agent decisions" 1 for the measured rationale
    (full depth costs 24x more at 265K rows).
  * VERIFIES the recorded `content_hash` of every row it is about to
    RETURN against that chunk's current text — a disagreement (stale text)
    raises `StoreMismatch` naming the chunk_id and both hashes.
    Verification is RESULT-SCOPED (orchestrator ruling, locked): only rows
    that end up in the returned top-k are hashed, not the whole chunk set.
  * `SearchResult(doc_id=chunk.chunk_id, score=<cosine float>,
    snippet=chunk.text[:160])`; `score` is a builtin `float`.

`rrf_fuse(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]`
  * `score(id) = sum over rankings containing id of 1/(k + rank)`, rank
    1-based; sorted by score DESC, ties by id ASC. An id absent from a
    ranking contributes nothing (no penalty term). `k=60` is a standing
    locked decision.

`hybrid_search(index, store, chunks, query, provider, k=10, rrf_k=60)`
  * GUARDS identity chunking FIRST, corpus-wide, over every chunk: each
    must satisfy `chunk.chunk_id == chunk.doc_ids[0] and len(chunk.doc_ids)
    == 1`, else `NonIdentityChunking` — fusion is defined over ONE id space
    (chunk_id), and the lexical ranking's ids are corpus doc ids, valid
    fusion input only under that identity invariant.
  * Lexical ranking at FULL DEPTH — `ranked_search(index, query,
    k=index.doc_count())` — RRF needs deep rankings.
  * Semantic ranking = `semantic_search(..., k=len(chunks))` id sequence
    (so under hybrid every chunk is a result, and therefore every chunk is
    hash-verified).
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


def _verified_result(store: EmbeddingStore, chunk: Chunk, score: float) -> SearchResult:
    entry = store.entry_for(chunk.chunk_id)
    expected = content_hash(store.model, store.dim, chunk.text)
    recorded = entry["content_hash"]
    if recorded != expected:
        raise StoreMismatch(
            f"chunk {chunk.chunk_id!r}: store content_hash {recorded!r} does not match "
            f"the recomputed content_hash {expected!r} for the chunk's current text "
            f"(stale row)"
        )
    return SearchResult(doc_id=chunk.chunk_id, score=float(score), snippet=chunk.text[:SNIPPET_LEN])


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
    row_to_chunk = _resolve_covered_rows(store, chunks)

    query_vec = provider.embed([query])[0]

    covered = _covered_top_k(store, query_vec, k, row_to_chunk)

    return [_verified_result(store, row_to_chunk[row], score) for row, score in covered]


def rrf_fuse(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion: `score(id) = sum over rankings containing id
    of 1/(k + rank)`, rank 1-based. Sorted by score descending, ties broken
    by id ascending (byte-wise). An id absent from a ranking contributes
    nothing — no penalty term."""
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
) -> list[SearchResult]:
    """RRF-fuse a full-depth lexical ranking with a semantic ranking over
    `chunks`, both keyed by chunk_id under the identity-chunking invariant.
    See module docstring for the frozen contract."""
    _guard_identity_chunking(chunks)

    lexical_results = ranked_search(index, query, k=index.doc_count())
    lexical_by_id = {result.doc_id: result for result in lexical_results}
    lexical_ranking = [result.doc_id for result in lexical_results]

    semantic_results = semantic_search(store, chunks, query, provider, k=len(chunks))
    semantic_ranking = [result.doc_id for result in semantic_results]

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

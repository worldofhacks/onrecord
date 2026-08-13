"""Failing tests for T-022 — retrieval modes: semantic search, RRF hybrid
(k=60), and the lexical | semantic | hybrid side-by-side report.

Encodes `tickets/T-022.md` AC-1..AC-5, as amended post-freeze by the
orchestrator's T-021 C-1 id-space ruling (see "Post-freeze amendments"
below). These tests are FROZEN after the Test Agent hands off: do not edit
this file to make an implementation pass — fix the implementation (new files
`onrecord/rag/retrieve.py`, `onrecord/rag/modes.py`) instead.

Run with:
    uv run pytest tests/unit/rag/test_retrieve.py -v

MODULE-PRESENCE GUARD (why every test starts with `_retrieve_module()` /
`_modes_module()`)
----------------------------------------------------------------------
`onrecord.rag.retrieve` and `onrecord.rag.modes` are THIS ticket's target
modules and do not exist yet. A module-scope `import onrecord.rag.retrieve`
would blow the whole file up as a pytest COLLECTION ERROR, polluting other
in-flight tickets' regression baselines (`uv run pytest -q` is run by the
orchestrator at any time). So, mirroring `tests/unit/test_api.py`'s and
`tests/unit/rag/test_embeddings.py`'s established idiom,
`_require_module_spec(...)` + `pytest.fail(...)` turns "module missing" into
a clean per-test RED failure. Everything else this file imports —
`onrecord.types`, `onrecord.index.inverted`, `onrecord.rag.chunking`,
`onrecord.rag.embeddings`, `onrecord.search.ranked`, `onrecord.eval.*` — is
MERGED and real (wave 8), so those imports need no guard and the fixtures
exercise the real modules, never re-implementations of them.

ZERO NETWORK, ZERO KEYS
-----------------------
Every provider interaction goes through `ScriptedProvider` (the
`EmbeddingProvider` Protocol boundary — `model`, `dim`, `embed(texts)`).
No test reads a key, and `report_modes`' env-dependent `corpus_version`
lookup always `monkeypatch.delenv(..., raising=False)`s or `setenv`s first,
so neither branch is "environmentally lucky".

===========================================================================
POST-FREEZE AMENDMENTS TO THE TICKET (already applied below)
===========================================================================
`tickets/T-022.md:19` originally read "resolve rows via
`store.rows_for(hashes)`". The orchestrator's T-021 C-1 ruling made store
entries PER-CHUNK — `entries.json` maps `chunk_id -> {"row", "content_hash"}`
— so the argument is **chunk_ids, NOT content hashes**. Both id spaces are
`str`, so the wrong one fails SILENTLY as a total miss (every row `None`),
which is the LESSONS T-003/T-004 defect class; T-021's frozen suite carries
a tripwire for it
(`test_rows_for_is_chunk_id_keyed_not_content_hash_keyed`). Under this
suite, passing hashes surfaces as `MissingEmbeddings` naming every chunk —
loud, not silent.

Correspondence is therefore verified through the **content hash**: the store
entry's recorded `content_hash` must equal
`content_hash(store.model, store.dim, chunk.text)`, computed with T-021's
**frozen public helper** — imported, never re-derived
(`test_retrieve_never_re_derives_the_content_hash_formula` enforces both
halves statically, over the module AST rather than its text, so prose in a
docstring can never trip it).

===========================================================================
ORCHESTRATOR RULING — hash verification is RESULT-SCOPED (locked)
===========================================================================
Test review C-1 established that `tickets/T-022.md:19`'s "for every resolved
row" admits two implementations that both passed the first freeze while
behaving oppositely on this suite's own fixture: **corpus-wide** (hash every
chunk before ranking) and **result-scoped** (hash only the rows that end up
in the returned top-k). The orchestrator ruled **result-scoped**, and this
suite freezes it:

* the guarantee is that **no stale row is ever RETURNED**;
* rows that do not surface in the top-k are **not** verified on that query;
* global store integrity remains T-021's job — `EmbeddingStore.load`
  validates row counts, dtype/width, and row-index defects at load time.

The measured stakes behind the ruling: corpus-wide hashing costs ~211 ms per
query at 265K chunks x ~526 chars, on a request path T-021 tuned to
50-150 ms. Result-scoped costs ten hashes.

Consequence worth knowing: `hybrid_search` calls
`semantic_search(..., k=len(chunks))`, so under hybrid EVERY chunk is a
result and therefore every chunk IS verified
(`test_hybrid_search_verifies_every_chunk_because_all_of_them_are_results`).

===========================================================================
FROZEN CONTRACT — onrecord/rag/retrieve.py
===========================================================================

`semantic_search(store, chunks, query, provider, k=10) -> list[SearchResult]`
  * Embeds ONLY the query (`provider.embed([query])`) — the corpus was
    embedded once, by T-021's `embed_corpus`; re-embedding it here is a
    spend defect, pinned by `test_semantic_search_embeds_only_the_query`.
  * Scores via `cosine_top_k` over the store, maps rows to chunks
    **CHUNK_ID-KEYED, never positionally** (`store.rows_for(chunk_ids)` ->
    row->chunk map).
  * VERIFIES the recorded `content_hash` of every row it is about to RETURN
    against that chunk's text; a disagreement (stale text) raises typed
    `StoreMismatch`. **Verification is RESULT-SCOPED — orchestrator ruling,
    locked** (see "ORCHESTRATOR RULING" below): the guarantee is that no
    stale row is ever *served*, not that the whole chunk set is audited on
    every query. Both sides are pinned at small `k`
    (`test_semantic_search_raises_store_mismatch_when_a_stale_row_is_inside_the_cut`
    / `..._returns_cleanly_when_the_stale_row_is_below_the_cut`).
  * A chunk with no store row raises typed `MissingEmbeddings` naming the
    COUNT — this one IS corpus-wide, and fires at any `k` including `k=1`
    (a wrong receipt is the product's worst failure). The asymmetry with
    `StoreMismatch` is deliberate and is the ruling's whole point: coverage
    is one dict lookup per chunk, hashing is a sha256 over every chunk's
    text, and only the latter is unaffordable per query at 265K chunks.
  * The three error types are DISTINCT classes, none a subclass of another,
    and none a subclass of T-021's `StoreIdentityMismatch`/`CorruptStore` —
    T-024's degradation ladder branches on them by name.
  * Store rows not covered by `chunks` (prior embed runs, other corpus
    versions) are never surfaced AND never consume a result slot — see
    "Test Agent decisions" 1 below.
  * `SearchResult(doc_id=chunk.chunk_id, score=<cosine float>,
    snippet=chunk.text[:160])`; `score` is a builtin `float`, not a numpy
    scalar (T-024 serializes these to JSON).

`rrf_fuse(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]`
  * `score(id) = sum over rankings containing id of 1/(k + rank)`, rank
    **1-based**; sort by score DESC, ties by **id ASC**. An id absent from a
    ranking contributes nothing — no penalty term. `k=60` is a standing
    locked decision.

`hybrid_search(index, store, chunks, query, provider, k=10, rrf_k=60)`
  * GUARDS identity chunking first: every chunk must satisfy
    `chunk.chunk_id == chunk.doc_ids[0] and len(chunk.doc_ids) == 1`, else
    typed `NonIdentityChunking` — fusion is defined over ONE id space
    (chunk_id), and the lexical ranking's ids are CORPUS DOC ids.
  * Lexical ranking at FULL DEPTH — `ranked_search(index, query,
    k=index.doc_count())`. RRF needs deep rankings; a shallow `k=10` call
    silently changes fused scores for anything below lexical rank 10, which
    `test_hybrid_search_fuses_the_full_depth_lexical_ranking` measures
    exactly.
  * Semantic ranking = `semantic_search(..., k=len(chunks))` id sequence.
  * Fuse, truncate to `k`, `score=<RRF score>`; snippet from the LEXICAL hit
    when the id appeared lexically (positions-based snippets are strictly
    better) else `chunk.text[:160]`.

===========================================================================
FROZEN CONTRACT — onrecord/rag/modes.py
===========================================================================

`report_modes(index, store, chunks, judgments_path, provider,
history_path="artifacts/modes_scoreboard.jsonl") -> list[dict]`
  * For mode in **("lexical", "semantic", "hybrid")** — in that order —
    retrieves per judgment query and scores the SAME six labels as
    `eval/run.py` (`P@5, P@10, R@10, R@50, MRR, NDCG@10`, via
    `onrecord.eval.metrics`).
  * Appends ONE row per mode to its OWN artifact, each row exactly
    `{"timestamp", "git_sha", "corpus_version", "mode", "metrics"}` with
    `metrics` exactly `{"per_query", "mean"}`. `eval/run.py`'s history-row
    key set is frozen by `tests/unit/test_metrics.py` and MUST NOT gain a
    `mode` field — the sidecar is what sidesteps that frozen contract, and
    `test_the_mode_tag_never_leaks_into_eval_run_history_rows` pins both
    sides of the split.
  * `mean` divides by EVERY query, including ones that retrieved nothing
    (mirrors `eval/run.py::_mean_metrics`) — pinned with a deliberate
    zero-result lexical query in the fixture.
  * `corpus_version` via T-018's `read_manifest`, resolved exactly as
    `eval/run.py::_corpus_version` does: the `ONRECORD_INDEX` env var,
    falling back to `artifacts/index`, falling back to `"unversioned"`
    (see "Test Agent decisions" 3).
  * Also exposes a CLI `main`, mirroring `eval.run`'s pattern.

===========================================================================
TEST AGENT DECISIONS (NOT in the ticket — inventions this suite freezes)
===========================================================================
1. **Uncovered store rows never consume a result slot.** The ticket says
   rows not covered by `chunks` "are simply never surfaced". Taken as
   `cosine_top_k(store, q, k)` followed by a filter, a store carrying rows
   from a prior embed run returns FEWER than `k` results — a silently short
   receipt, the exact failure class this ticket's `MissingEmbeddings` rule
   exists to prevent. Frozen here as: `semantic_search(..., k=n)` returns
   `min(n, len(chunks))` results whenever every chunk is covered, however
   many uncovered rows outrank them.

   **This pins the OBSERVABLE, never the strategy** (test review I-3). A
   full-depth `cosine_top_k(store, q, <all rows>)` satisfies it, and so does
   a **bounded grow-k retry** — score at `k`, redo at `2k`, `4k`, … while
   fewer than `k` covered rows are in hand — and so does anything else that
   produces the pinned results. Nothing in this file forces full depth, and
   the implementer should know that full depth is the EXPENSIVE choice:
   *(measured, 265K rows)* the selection step alone is 2.7 ms at `k=10`
   versus 64.9 ms at `k=265000`, which reinstates the full-candidate sort
   T-021's re-review I-C removed after measuring it at 189 ms of a 220 ms
   query. The suite's own satisfiability reference deliberately implements
   the grow-k retry, not full depth, so "the tests permit it" is a measured
   fact rather than a claim.

   The retry must be a genuine loop, not a single doubling:
   `test_semantic_search_fills_k_past_a_deep_field_of_uncovered_rows` puts 24
   uncovered rows above every chunk, so a fixed one- or two-step widening
   still returns short. That is the one cheap pin available here — there is
   no observable that separates a correct grow-k retry from a correct
   full-depth scan, so *which* strategy is used stays deliberately unpinned.
2. **`StoreMismatch`'s message names the chunk_id and BOTH content hashes.**
   The ticket says "naming both ids"; under the per-chunk ruling the entry's
   key IS the chunk_id, so the two things being compared are the recorded
   and the recomputed hash. `NonIdentityChunking`'s message is deliberately
   NOT pinned (the ticket asks only for the type).
3. **`report_modes` resolves `corpus_version` from `ONRECORD_INDEX`.** The
   ticket freezes the signature, which takes an `index` OBJECT and no index
   path, so `read_manifest` has exactly one available source — the same env
   var `eval/run.py::_corpus_version` already reads (as do `onrecord/api.py`
   and `eval/run.py` today, for the same meaning). Same `"unversioned"`
   fallback. **`corpus_version` is therefore PROVENANCE FROM THE
   ENVIRONMENT, not a property of the `index` object that was scored** — the
   two can disagree, and nothing here detects it (test review M-4). A CLI
   `--index` flag would have to export `ONRECORD_INDEX` for the stamp to
   track the index it loaded.
4. **`semantic_search` does NOT guard identity chunking.** The ticket
   attaches that guard to `hybrid_search` specifically ("hybrid_search
   therefore GUARDS"), because only FUSION needs one id space; a
   semantic-only mode over `window>1` chunks is coherent and is where T-020's
   windowing sweep is headed. Pinned by
   `test_semantic_search_accepts_a_merged_chunk`.
5. **Retrieval depth inside `report_modes` is NOT pinned.** The fixture
   corpus is 4 docs and *(measured)* every depth **>= 3** reproduces the
   frozen numbers exactly — depth 2 does not, so the freedom granted is
   "anything from 3 up", not merely "at least the corpus size". Only the
   metric VALUES are frozen.

DELIBERATELY NOT PINNED (documented gaps, not oversights)
---------------------------------------------------------
* **A stale row that never reaches the top-k.** Direct consequence of the
  result-scoped ruling, and pinned as such: at `k=2` over this fixture the
  stale chunk sits at rank 3 and the call returns cleanly. A corpus-wide
  audit belongs to a maintenance path (or T-021's `load`), not the request
  path.
* **Which depth strategy `semantic_search` uses** (full scan vs grow-k
  retry) — no observable separates two correct implementations; see
  decision 1.
* `k <= 0` on any of the three functions (the ticket is silent, and
  `report_modes` never produces it).
* A repeated id **within one** ranking handed to `rrf_fuse` (first
  occurrence? last? summed? — all defensible), and `rrf_fuse` at `k <= 0`.
* `NonIdentityChunking`'s message text (the ticket asks only for the type;
  the other two messages ARE pinned because the ticket says "naming …").
* Whether the identity guard runs before or after the provider call.
* `hybrid_search`'s BM25 `k1`/`b` — it is pinned to `ranked_search`'s
  behaviour only through this fixture's resulting ORDER, and the ticket
  mentions neither parameter.
* `modes.main`'s argv contract — only that a callable `main` exists.

FIXTURE STANDARDS
-----------------
* Ids are REAL-shaped and MIXED-CASE (`yt:0Ij8OxBcnFc:seg000`,
  `yt:LviKZZXJb98:seg001`, `edgar:0000320193-24-000123:item1a` — several are
  verbatim from `evalsets/judgments.jsonl`). Never all-canonical
  placeholders: the RRF tie-break is a byte-order sort, so an implementation
  that casefolds ids, or that falls back to insertion order, is
  observationally identical on uniform-case fixtures. Both fused fixtures
  below contain a tie whose id-ascending winner is NOT the
  insertion-order winner.
* Embedding vectors are integer 8-vectors of norm exactly 4, so every
  normalized component is `n/4` — exactly representable in float16 AND
  float32 — and every cosine is `dot/16`. The store's fp16 packing is
  therefore lossless for these fixtures and the expected scores (1.0, 0.75,
  0.5, 0.25, 0.0) are exact, not approximate.
* Every RRF expected value was hand-computed twice: as an exact rational
  (e.g. `1/61 + 1/63`) and as an independently evaluated decimal literal.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib.util
import inspect
import json
import re
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from onrecord.index.inverted import InvertedIndex
from onrecord.rag.chunking import chunk_corpus
from onrecord.rag.embeddings import (
    CorruptStore,
    EmbeddingStore,
    StoreIdentityMismatch,
    content_hash,
)
from onrecord.search.ranked import ranked_search
from onrecord.types import Doc, SearchResult

# --------------------------------------------------------------------------
# Guards / module access
# --------------------------------------------------------------------------


def _require_module_spec(name: str, fail_message: str):
    """Return the module spec for `name`, or fail cleanly via pytest.fail.

    Mirrors tests/unit/test_api.py's and tests/unit/rag/test_embeddings.py's
    guard idiom: importlib.util.find_spec raises ModuleNotFoundError (rather
    than returning None) when a parent package in a dotted name is itself
    missing, so both "not found" cases normalize into one clean
    assertion-style failure, never an uncaught exception or a pytest
    collection error.
    """
    try:
        spec = importlib.util.find_spec(name)
    except ModuleNotFoundError:
        spec = None
    if spec is None:
        pytest.fail(fail_message)
    return spec


def _retrieve_module():
    _require_module_spec(
        "onrecord.rag.retrieve",
        "onrecord.rag.retrieve missing (T-022 target module — expected RED until "
        "the Implementation Agent lands it)",
    )
    import onrecord.rag.retrieve as retrieve

    return retrieve


def _modes_module():
    _require_module_spec(
        "onrecord.rag.modes",
        "onrecord.rag.modes missing (T-022 target module — expected RED until "
        "the Implementation Agent lands it)",
    )
    import onrecord.rag.modes as modes

    return modes


def _attr(module, name: str):
    if not hasattr(module, name):
        pytest.fail(f"{module.__name__}.{name} missing")
    return getattr(module, name)


def _retrieve_attr(name: str):
    return _attr(_retrieve_module(), name)


def _modes_attr(name: str):
    return _attr(_modes_module(), name)


# --------------------------------------------------------------------------
# Ids — real-shaped, mixed-case (see FIXTURE STANDARDS in the docstring)
# --------------------------------------------------------------------------

C_A = "yt:0Ij8OxBcnFc:seg000"
C_B = "yt:0Ij8OxBcnFc:seg001"
C_C = "edgar:0000320193-24-000123:item1a"
C_D = "yt:dQw4w9WgXcQ:seg000"
C_E = "yt:aB3dE5fG7hI:seg000"
# In the index but NOT among `chunks` — a doc found only lexically.
LEXONLY = "yt:LviKZZXJb98:seg001"
# Rows in the store from a PRIOR embed run — covered by no chunk.
X_1 = "yt:0V5-esiXrj8:seg093"
X_2 = "yt:821DuF--3dY:seg046"

QUERY = "substation"
NO_HIT_QUERY = "zzzqx nonexistent"

# --------------------------------------------------------------------------
# Hand-computed RRF constants (k=60, 1-based ranks)
#
# Each value was derived twice: once as an exact rational, once as an
# independently evaluated decimal. `repr` round-trips, so these literals are
# bit-identical to the arithmetic beside them.
# --------------------------------------------------------------------------

R_1 = 0.01639344262295082  # 1/61
R_2 = 0.016129032258064516  # 1/62
R_3 = 0.015873015873015872  # 1/63
R_4 = 0.015625  # 1/64
R_5 = 0.015384615384615385  # 1/65
R_12 = 0.013888888888888888  # 1/72
R_1_PLUS_3 = 0.032266458495966696  # 1/61 + 1/63
R_1_PLUS_2 = 0.03252247488101534  # 1/61 + 1/62
R_2_PLUS_3 = 0.03200204813108039  # 1/62 + 1/63
R_3_PLUS_4 = 0.03149801587301587  # 1/63 + 1/64
R_1_PLUS_1 = 0.03278688524590164  # 1/61 + 1/61
R_2_PLUS_12 = 0.030017921146953404  # 1/62 + 1/72

SIX_LABELS = ("P@5", "P@10", "R@10", "R@50", "MRR", "NDCG@10")

# --------------------------------------------------------------------------
# Corpus text builders — token counts drive BM25, markers keep texts (and so
# content hashes, and so store rows) distinct.
# --------------------------------------------------------------------------

_PAD_WORDS = ("county", "board", "hearing", "minutes", "record")


def _filler(n_tokens: int, marker: str, term_positions: tuple[int, ...] = ()) -> str:
    """`n_tokens` filler words with `marker` first and `QUERY` at each of
    `term_positions` (so term frequency and doc length are both explicit)."""
    words = [_PAD_WORDS[i % len(_PAD_WORDS)] for i in range(n_tokens)]
    words[0] = marker
    for position in term_positions:
        words[position] = QUERY
    return " ".join(words)


def _tf_text(marker: str, tf: int, n_tokens: int = 40) -> str:
    """Filler text carrying exactly `tf` occurrences of `QUERY`, spread out
    so no two land on the same slot."""
    return _filler(n_tokens, marker, tuple(3 + i * 3 for i in range(tf)))


TEXT_A = _filler(40, "alfa", (38,))  # tf 1, dl 40, term near the END
TEXT_B = _filler(30, "bravo")  # no query term
TEXT_C = _filler(30, "charlie")  # no query term
TEXT_D = _filler(120, "delta", (5,))  # tf 1, dl 120
TEXT_E = _filler(30, "echo")  # no query term
TEXT_LEXONLY = _filler(60, "foxtrot", (50, 55))  # tf 2, dl 60
TEXT_X1 = _filler(25, "golf")
TEXT_X2 = _filler(25, "hotel")
SHORT_TEXT = "a short caption about the substation"  # < 160 chars

# --------------------------------------------------------------------------
# Embedding vectors — integer 8-vectors of norm exactly 4 (sum of squares
# 16), so normalized components are n/4 (exact in fp16 AND fp32) and every
# cosine against QUERY_VEC is dot/16, exactly.
# --------------------------------------------------------------------------

QUERY_VEC = (4, 0, 0, 0, 0, 0, 0, 0)
NO_HIT_QUERY_VEC = (0, 4, 0, 0, 0, 0, 0, 0)

V_COS_100 = (4, 0, 0, 0, 0, 0, 0, 0)  # 16/16
V_COS_075 = (3, 2, 1, 1, 1, 0, 0, 0)  # 12/16
V_COS_050 = (2, 2, 2, 2, 0, 0, 0, 0)  # 8/16
V_COS_025 = (1, 2, 2, 2, 1, 1, 1, 0)  # 4/16
V_COS_000 = (0, 2, 2, 2, 2, 0, 0, 0)  # 0/16

RETRIEVAL_VECTORS = {
    TEXT_C: V_COS_100,
    TEXT_E: V_COS_075,
    TEXT_A: V_COS_050,
    TEXT_D: V_COS_025,
    TEXT_B: V_COS_000,
    TEXT_X1: V_COS_100,
    TEXT_X2: V_COS_075,
    QUERY: QUERY_VEC,
}

# Cosine order over the five chunks: C_C 1.0, C_E 0.75, C_A 0.5, C_D 0.25,
# C_B 0.0 — deliberately unrelated to both the chunks list order and the
# store's row order.
SEMANTIC_ORDER = (C_C, C_E, C_A, C_D, C_B)
SEMANTIC_SCORES = (1.0, 0.75, 0.5, 0.25, 0.0)

# The store is written in a DIFFERENT order than `chunks`, and carries two
# rows from a prior embed run (X_1 at row 0 outscores every chunk).
STORE_WRITE_ORDER = (
    (X_1, TEXT_X1),
    (C_C, TEXT_C),
    (C_E, TEXT_E),
    (X_2, TEXT_X2),
    (C_A, TEXT_A),
    (C_D, TEXT_D),
    (C_B, TEXT_B),
)

CHUNKS_ORDER = (C_A, C_B, C_C, C_D, C_E)


# --------------------------------------------------------------------------
# Test doubles for the EmbeddingProvider Protocol
# --------------------------------------------------------------------------


class ScriptedProvider:
    """Returns exactly the vector scripted for each text (hand-computable).

    Satisfies the `EmbeddingProvider` Protocol structurally (`model`, `dim`,
    `embed(texts) -> float32 (len(texts), dim)` in input order) and records
    every call, so "the corpus is never re-embedded at query time" is
    measurable rather than assumed.
    """

    def __init__(self, vectors: dict[str, tuple[int, ...]], model: str = "scripted-embed-v1"):
        self.vectors = {text: np.asarray(v, dtype=np.float32) for text, v in vectors.items()}
        self.dim = int(next(iter(self.vectors.values())).shape[0])
        self.model = model
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> np.ndarray:
        batch = list(texts)
        self.calls.append(batch)
        missing = [text for text in batch if text not in self.vectors]
        if missing:
            raise AssertionError(
                f"ScriptedProvider was asked to embed unscripted text {missing[0]!r} — "
                f"the fixture only scripts the query and the corpus texts"
            )
        return np.stack([self.vectors[text] for text in batch]).astype(np.float32)


# --------------------------------------------------------------------------
# Fixture builders (not tests)
# --------------------------------------------------------------------------


def _doc(doc_id: str, text: str) -> Doc:
    return Doc(
        id=doc_id,
        text=text,
        source_type="filing" if doc_id.startswith("edgar:") else "youtube",
        venue_type="written" if doc_id.startswith("edgar:") else "spoken",
        date="2024-03-01",
        deep_link=f"https://example.invalid/{doc_id}",
        ticker="AAPL" if doc_id.startswith("edgar:") else None,
        jurisdiction=None if doc_id.startswith("edgar:") else "loudoun-county-va",
        speaker=None if doc_id.startswith("edgar:") else "chair",
    )


def _chunk_map(docs: list[Doc], window: int = 1, overlap: int = 0) -> dict:
    """Real `chunk_corpus` output, keyed by chunk_id (its list ORDER is
    deliberately not relied on — chunk_corpus emits passthrough docs before
    windowed videos)."""
    return {chunk.chunk_id: chunk for chunk in chunk_corpus(docs, window=window, overlap=overlap)}


def _store_from(pairs, provider) -> EmbeddingStore:
    store = EmbeddingStore()
    store.embed_corpus([(chunk_id, text) for chunk_id, text in pairs], provider)
    provider.calls.clear()  # only query-time calls are interesting afterwards
    return store


RETRIEVAL_DOCS = (
    (C_A, TEXT_A),
    (C_B, TEXT_B),
    (C_C, TEXT_C),
    (C_D, TEXT_D),
    (C_E, TEXT_E),
    (LEXONLY, TEXT_LEXONLY),
)


def _fixture(store_pairs=STORE_WRITE_ORDER, chunk_ids=CHUNKS_ORDER):
    """The shared retrieval fixture.

    Six docs in the index; five of them are chunks (LEXONLY is an index doc
    with no chunk and no embedding — a corpus doc the chunk/embedding
    generation predates). Returns `(index, store, chunks, provider)`.
    """
    docs = [_doc(doc_id, text) for doc_id, text in RETRIEVAL_DOCS]
    index = InvertedIndex.build(docs)
    chunks_by_id = _chunk_map([doc for doc in docs if doc.id != LEXONLY])
    chunks = [chunks_by_id[chunk_id] for chunk_id in chunk_ids]
    provider = ScriptedProvider(RETRIEVAL_VECTORS)
    store = _store_from(store_pairs, provider)
    return index, store, chunks, provider


def _merged_fixture():
    """A `window=2` fixture: the two same-video segments merge into ONE chunk
    whose `chunk_id` is `...seg000+w2`, alongside an identity chunk.

    The merged chunk IS embedded, so `MissingEmbeddings`/`StoreMismatch` are
    both off the table and `NonIdentityChunking` is the only error a correct
    `hybrid_search` can raise.
    """
    docs = [_doc(C_A, TEXT_A), _doc(C_B, TEXT_B), _doc(C_C, TEXT_C)]
    index = InvertedIndex.build(docs)
    merged = _chunk_map([_doc(C_A, TEXT_A), _doc(C_B, TEXT_B)], window=2)
    identity = _chunk_map([_doc(C_C, TEXT_C)])
    merged_chunk = merged[f"{C_A}+w2"]
    chunks = [merged_chunk, identity[C_C]]
    vectors = {
        merged_chunk.text: V_COS_050,
        TEXT_C: V_COS_100,
        QUERY: QUERY_VEC,
    }
    provider = ScriptedProvider(vectors)
    store = _store_from(
        ((merged_chunk.chunk_id, merged_chunk.text), (C_C, TEXT_C)),
        provider,
    )
    return index, store, chunks, provider, merged_chunk


# Deep-uncovered-field fixture: three chunks buried under 24 rows from prior
# embed runs, every one of which outranks them. Exists to harden decision 1's
# observable without pinning a depth strategy (test review I-3).
DF_CHUNKS = ("yt:0Ij8OxBcnFc:seg000", "yt:dQw4w9WgXcQ:seg000", "edgar:0000320193-24-000123:item1a")
DF_UNCOVERED = tuple(f"yt:821DuF--3dY:seg{i:03d}" for i in range(100, 124))


def _deep_field_fixture():
    chunk_texts = {
        DF_CHUNKS[0]: _filler(30, "sierra"),
        DF_CHUNKS[1]: _filler(30, "tango"),
        DF_CHUNKS[2]: _filler(30, "uniform"),
    }
    uncovered = {chunk_id: _filler(14, f"prior{i:02d}") for i, chunk_id in enumerate(DF_UNCOVERED)}
    docs = [_doc(doc_id, text) for doc_id, text in chunk_texts.items()]
    index = InvertedIndex.build(docs)
    chunks_by_id = _chunk_map(docs)
    chunks = [chunks_by_id[chunk_id] for chunk_id in DF_CHUNKS]
    vectors = {
        chunk_texts[DF_CHUNKS[0]]: V_COS_075,
        chunk_texts[DF_CHUNKS[1]]: V_COS_050,
        chunk_texts[DF_CHUNKS[2]]: V_COS_025,
        QUERY: QUERY_VEC,
    }
    vectors.update(dict.fromkeys(uncovered.values(), V_COS_100))
    provider = ScriptedProvider(vectors)
    # Uncovered rows are written FIRST, so they occupy rows 0..23 and win
    # every tie as well as every score comparison.
    store = _store_from(tuple(uncovered.items()) + tuple(chunk_texts.items()), provider)
    return index, store, chunks, provider


# Full-depth fixture: 12 lexical candidates, only 2 of them chunks. The
# lexical ranking is [P, ten fillers by id asc, Q] — Q at rank 12, well past
# any default k=10 cut.
FD_P = "yt:0V5-esiXrj8:seg093"
FD_Q = "yt:LviKZZXJb98:seg001"
FD_FILLERS = tuple(f"yt:821DuF--3dY:seg{i:03d}" for i in range(1, 11))


def _full_depth_fixture():
    docs = [_doc(FD_P, _tf_text("papa", 5))]
    docs += [_doc(f, _tf_text(f"filler{i}", 2)) for i, f in enumerate(FD_FILLERS)]
    docs.append(_doc(FD_Q, _tf_text("quebec", 1)))
    index = InvertedIndex.build(docs)
    chunks_by_id = _chunk_map([doc for doc in docs if doc.id in (FD_P, FD_Q)])
    chunks = [chunks_by_id[FD_P], chunks_by_id[FD_Q]]
    text_of = {doc.id: doc.text for doc in docs}
    provider = ScriptedProvider(
        {text_of[FD_P]: V_COS_100, text_of[FD_Q]: V_COS_050, QUERY: QUERY_VEC}
    )
    store = _store_from(((FD_P, text_of[FD_P]), (FD_Q, text_of[FD_Q])), provider)
    return index, store, chunks, provider


# --------------------------------------------------------------------------
# report_modes fixture — 4 docs, 2 queries, one of which retrieves NOTHING
# lexically (the mean-denominator pin).
# --------------------------------------------------------------------------

M_1 = "yt:0Ij8OxBcnFc:seg000"
M_2 = "yt:0Ij8OxBcnFc:seg001"
M_3 = "edgar:0000320193-24-000123:item1a"
M_4 = "yt:dQw4w9WgXcQ:seg000"

M_TEXTS = {
    M_1: _tf_text("mike", 2, 30),  # tf 2, dl 30 -> lexical rank 1
    M_2: _tf_text("november", 1, 90),  # tf 1, dl 90 -> lexical rank 2
    M_3: _filler(30, "oscar"),  # no query term
    M_4: _filler(30, "papa"),  # no query term
}

# cos vs QUERY_VEC is v[0]/4; cos vs NO_HIT_QUERY_VEC is v[1]/4.
M_VECTORS = {
    M_TEXTS[M_1]: (1, 3, 1, 1, 1, 1, 1, 1),  # 0.25 / 0.75
    M_TEXTS[M_2]: (3, 1, 1, 1, 1, 1, 1, 1),  # 0.75 / 0.25
    M_TEXTS[M_3]: (2, 2, 2, 2, 0, 0, 0, 0),  # 0.50 / 0.50
    M_TEXTS[M_4]: (0, 0, 2, 2, 2, 2, 0, 0),  # 0.00 / 0.00
    QUERY: QUERY_VEC,
    NO_HIT_QUERY: NO_HIT_QUERY_VEC,
}

M_JUDGMENTS = (
    ("qa", QUERY, M_1, 1),
    ("qa", QUERY, M_2, 0),
    ("qa", QUERY, M_3, 2),
    ("qa", QUERY, M_4, 0),
    ("qb", NO_HIT_QUERY, M_1, 2),
    ("qb", NO_HIT_QUERY, M_2, 0),
    ("qb", NO_HIT_QUERY, M_3, 1),
    ("qb", NO_HIT_QUERY, M_4, 0),
)

# Hand-computed, mode by mode. Rankings:
#   lexical  qa [M_1, M_2]              qb []            (zero results)
#   semantic qa [M_2, M_3, M_1, M_4]    qb [M_1, M_3, M_2, M_4]
#   hybrid   qa [M_2, M_1, M_3, M_4]    qb [M_1, M_3, M_2, M_4]
# NDCG ideal gains are [2, 1, 0, 0] for both queries, so
# IDCG@10 = 2/log2(2) + 1/log2(3) = 2.6309297535714578.
EXPECTED_METRICS = {
    "lexical": {
        "per_query": {
            "qa": {
                "P@5": 0.2,
                "P@10": 0.1,
                "R@10": 0.5,
                "R@50": 0.5,
                "MRR": 1.0,
                # DCG = 1/log2(2) = 1.0 -> 1.0 / 2.6309297535714578
                "NDCG@10": 0.38009376671593426,
            },
            "qb": {
                "P@5": 0.0,
                "P@10": 0.0,
                "R@10": 0.0,
                "R@50": 0.0,
                "MRR": 0.0,
                "NDCG@10": 0.0,
            },
        },
        "mean": {
            "P@5": 0.1,
            "P@10": 0.05,
            "R@10": 0.25,
            "R@50": 0.25,
            "MRR": 0.5,
            "NDCG@10": 0.19004688335796713,
        },
    },
    "semantic": {
        "per_query": {
            "qa": {
                "P@5": 0.4,
                "P@10": 0.2,
                "R@10": 1.0,
                "R@50": 1.0,
                "MRR": 0.5,
                # DCG = 2/log2(3) + 1/log2(4) = 1.761859507142915
                "NDCG@10": 0.66967181649423,
            },
            "qb": {
                "P@5": 0.4,
                "P@10": 0.2,
                "R@10": 1.0,
                "R@50": 1.0,
                "MRR": 1.0,
                "NDCG@10": 1.0,
            },
        },
        "mean": {
            "P@5": 0.4,
            "P@10": 0.2,
            "R@10": 1.0,
            "R@50": 1.0,
            "MRR": 0.75,
            "NDCG@10": 0.8348359082471151,
        },
    },
    "hybrid": {
        "per_query": {
            "qa": {
                "P@5": 0.4,
                "P@10": 0.2,
                "R@10": 1.0,
                "R@50": 1.0,
                "MRR": 0.5,
                # DCG = 1/log2(3) + 2/log2(4) = 1.6309297535714575
                "NDCG@10": 0.6199062332840657,
            },
            "qb": {
                "P@5": 0.4,
                "P@10": 0.2,
                "R@10": 1.0,
                "R@50": 1.0,
                "MRR": 1.0,
                "NDCG@10": 1.0,
            },
        },
        "mean": {
            "P@5": 0.4,
            "P@10": 0.2,
            "R@10": 1.0,
            "R@50": 1.0,
            "MRR": 0.75,
            "NDCG@10": 0.8099531166420328,
        },
    },
}


def _write_judgments(tmp_path: Path) -> Path:
    path = tmp_path / "judgments.jsonl"
    lines = [
        json.dumps(
            {
                "query_id": query_id,
                "query": query,
                "criterion": "A document is relevant if it discusses the substation.",
                "doc_id": doc_id,
                "grade": grade,
            }
        )
        for query_id, query, doc_id, grade in M_JUDGMENTS
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _modes_fixture():
    docs = [_doc(doc_id, text) for doc_id, text in M_TEXTS.items()]
    index = InvertedIndex.build(docs)
    chunks_by_id = _chunk_map(docs)
    chunks = [chunks_by_id[doc_id] for doc_id in (M_1, M_2, M_3, M_4)]
    provider = ScriptedProvider(M_VECTORS)
    store = _store_from(tuple(M_TEXTS.items()), provider)
    return index, store, chunks, provider


def _isolate_environment(monkeypatch, tmp_path) -> None:
    """No test may be environmentally lucky: `ONRECORD_INDEX` is deleted
    (never assumed absent) and the CWD is moved off the checkout, so the
    `artifacts/index` fallback and `eval/run.py`'s default artifact path both
    resolve inside tmp."""
    monkeypatch.delenv("ONRECORD_INDEX", raising=False)
    monkeypatch.chdir(tmp_path)


def _rows_in(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _integer_tokens(text: str) -> list[str]:
    return re.findall(r"\d+", text)


def _assert_metrics(actual: dict, expected: dict) -> None:
    """Compare a `{"per_query", "mean"}` block value by value (pytest.approx
    does not recurse into nested mappings)."""
    assert set(actual["per_query"]) == set(expected["per_query"])
    for query_id, scores in expected["per_query"].items():
        assert actual["per_query"][query_id] == pytest.approx(scores, rel=1e-12)
    assert actual["mean"] == pytest.approx(expected["mean"], rel=1e-12)


# --------------------------------------------------------------------------
# AC-1 — rrf_fuse: hand-computed scores, 1-based ranks, k=60, id-asc ties
# --------------------------------------------------------------------------

# Four rankings, engineered so every tie in the fused output discriminates a
# different wrong tie-break:
#   * C_A / C_D both score 1/61 + 1/63 (AC-1's own worked example, reached
#     from opposite directions: ranks 1-and-3 vs 3-and-1).
#   * C_B / C_C / LEXONLY / C_E all score 1/62, each from ONE ranking only.
#     - id ASC puts C_C ("edgar:...") ahead of C_B, but C_B was encountered
#       FIRST -> an insertion-ordered tie-break gets this pair wrong.
#     - id ASC puts LEXONLY ("yt:LviKZZXJb98:...") ahead of C_E
#       ("yt:aB3dE5fG7hI:...") because 'L' < 'a' in byte order; CASEFOLDED
#       they swap ('a' < 'l') -> a normalizing tie-break gets this pair wrong.
#   * X_1 / X_2 both score 1/61 from rank 1 of their own ranking.
FUSE_RANKING_1 = [C_A, C_B, C_D]
FUSE_RANKING_2 = [C_D, C_C, C_A]
FUSE_RANKING_3 = [X_1, LEXONLY]
FUSE_RANKING_4 = [X_2, C_E]
FUSE_RANKINGS = [FUSE_RANKING_1, FUSE_RANKING_2, FUSE_RANKING_3, FUSE_RANKING_4]


def test_rrf_fuse_scores_match_the_hand_computed_reciprocal_rank_sums():
    # spec(T-022:AC-1)
    fuse = _retrieve_attr("rrf_fuse")

    scores = dict(fuse(FUSE_RANKINGS))

    assert scores == pytest.approx(
        {
            C_A: R_1_PLUS_3,  # ranks 1 and 3 -> 1/61 + 1/63
            C_D: R_1_PLUS_3,  # ranks 3 and 1 -> 1/63 + 1/61
            C_B: R_2,  # rank 2, one ranking only -> 1/62
            C_C: R_2,  # rank 2, one ranking only -> 1/62
            LEXONLY: R_2,  # rank 2, one ranking only -> 1/62
            C_E: R_2,  # rank 2, one ranking only -> 1/62
            X_1: R_1,  # rank 1, one ranking only -> 1/61
            X_2: R_1,  # rank 1, one ranking only -> 1/61
        },
        rel=1e-12,
    )


def test_rrf_fuse_orders_by_score_descending():
    # spec(T-022:AC-1)
    fuse = _retrieve_attr("rrf_fuse")

    fused = fuse(FUSE_RANKINGS)

    assert [score for _doc_id, score in fused] == sorted(
        (score for _doc_id, score in fused), reverse=True
    )


def test_rrf_fuse_breaks_ties_by_byte_wise_id_ascending():
    # spec(T-022:AC-1) — two ties, two different wrong answers: an
    # insertion-ordered tie-break yields [C_B, C_C]; a casefolding one yields
    # [C_E, LEXONLY]. Both are silent on all-canonical fixture ids.
    fuse = _retrieve_attr("rrf_fuse")

    fused = fuse(FUSE_RANKINGS)

    assert [doc_id for doc_id, _score in fused] == [
        C_A,
        C_D,
        X_1,
        X_2,
        C_C,
        C_B,
        LEXONLY,
        C_E,
    ]


def test_rrf_fuse_ranks_are_one_based():
    # spec(T-022:AC-1) — a 0-based implementation scores this 1/60.
    fuse = _retrieve_attr("rrf_fuse")

    assert dict(fuse([[C_A]])) == pytest.approx({C_A: R_1}, rel=1e-12)


def test_rrf_fuse_default_k_is_sixty():
    # spec(T-022:AC-1) — the standing locked decision, pinned against its
    # off-by-one neighbours rather than against itself.
    fuse = _retrieve_attr("rrf_fuse")

    default_scores = dict(fuse([[C_A, C_B]]))

    assert default_scores == pytest.approx(dict(fuse([[C_A, C_B]], k=60)), rel=1e-12)
    assert default_scores != pytest.approx(dict(fuse([[C_A, C_B]], k=59)), rel=1e-12)
    assert default_scores != pytest.approx(dict(fuse([[C_A, C_B]], k=61)), rel=1e-12)


def test_rrf_fuse_honours_an_explicit_k():
    # spec(T-022:AC-1) — k=10: 1/11 and 1/12.
    fuse = _retrieve_attr("rrf_fuse")

    assert dict(fuse([[C_A, C_B]], k=10)) == pytest.approx(
        {C_A: 0.09090909090909091, C_B: 0.08333333333333333}, rel=1e-12
    )


def test_rrf_fuse_absence_from_a_ranking_costs_nothing():
    # spec(T-022:AC-1) — C_B appears in exactly one of three rankings, at
    # rank 1; its score is 1/61 flat, with no penalty term for the two
    # rankings that omit it.
    fuse = _retrieve_attr("rrf_fuse")

    scores = dict(fuse([[C_A], [C_A], [C_B]]))

    assert scores[C_B] == pytest.approx(R_1, rel=1e-12)
    assert scores[C_A] == pytest.approx(R_1_PLUS_1, rel=1e-12)


def test_rrf_fuse_of_no_rankings_is_empty():
    # spec(T-022:AC-1)
    assert _retrieve_attr("rrf_fuse")([]) == []


def test_rrf_fuse_ignores_empty_rankings():
    # spec(T-022:AC-1) — the lexical ranking is empty for a query whose terms
    # are absent from the corpus (report_modes' qb); fusion must degrade to
    # the surviving ranking, not to nothing.
    fuse = _retrieve_attr("rrf_fuse")

    assert dict(fuse([[], [C_A, C_B], []])) == pytest.approx({C_A: R_1, C_B: R_2}, rel=1e-12)


def test_rrf_fuse_returns_each_id_exactly_once():
    # spec(T-022:AC-1)
    fuse = _retrieve_attr("rrf_fuse")

    ids = [doc_id for doc_id, _score in fuse([*FUSE_RANKINGS, [C_A, C_C]])]

    assert sorted(ids) == sorted({C_A, C_B, C_C, C_D, C_E, LEXONLY, X_1, X_2})


# --- properties (stress budgets far beyond hypothesis' default 100) --------

# A pool of real-shaped, mixed-case ids. Rankings are generated with
# `unique=True`: a REPEATED id within ONE ranking is behaviour the ticket
# leaves open (first occurrence? last? both summed?), so a correct
# implementation may legitimately treat it either way and the generator must
# never emit it — the same trap class as abbreviation collisions.
_ID_POOL = (
    C_A,
    C_B,
    C_C,
    C_D,
    C_E,
    LEXONLY,
    X_1,
    X_2,
)
_RANKING = st.lists(st.sampled_from(_ID_POOL), unique=True, max_size=len(_ID_POOL))
_RANKINGS = st.lists(_RANKING, min_size=1, max_size=4)
_RANKINGS_OF_PAIRS = st.lists(
    st.lists(st.sampled_from(_ID_POOL), unique=True, min_size=2, max_size=len(_ID_POOL)),
    min_size=1,
    max_size=4,
)
_K = st.integers(min_value=1, max_value=500)


@settings(max_examples=2000, deadline=None)
@given(_RANKINGS, _K)
def test_rrf_fuse_output_is_a_permutation_of_the_input_ids(rankings, k):
    # spec(T-022:AC-1)
    fuse = _retrieve_attr("rrf_fuse")

    fused_ids = [doc_id for doc_id, _score in fuse(rankings, k=k)]

    assert sorted(fused_ids) == sorted({doc_id for ranking in rankings for doc_id in ranking})


@settings(max_examples=2000, deadline=None)
@given(_RANKINGS, _K)
def test_rrf_fuse_output_is_totally_ordered_by_score_desc_then_id_asc(rankings, k):
    # spec(T-022:AC-1)
    fuse = _retrieve_attr("rrf_fuse")

    fused = fuse(rankings, k=k)

    assert fused == sorted(fused, key=lambda item: (-item[1], item[0]))


@settings(max_examples=2000, deadline=None)
@given(_RANKINGS, _K, st.data())
def test_rrf_fuse_does_not_depend_on_the_order_of_the_rankings(rankings, k, data):
    # spec(T-022:AC-1) — hybrid_search hands it [lexical, semantic]; the
    # fused result must not encode which one came first. Compared as a SCORE
    # MAPPING, not as an ordered list: with three or more rankings, float
    # addition is not associative, so a correct implementation may legitimately
    # break a mathematically exact tie differently once the summation order
    # changes. Pinning the list order here would be a generator-authored trap.
    fuse = _retrieve_attr("rrf_fuse")

    shuffled = data.draw(st.permutations(rankings))

    assert dict(fuse(rankings, k=k)) == pytest.approx(dict(fuse(list(shuffled), k=k)), rel=1e-12)


@settings(max_examples=2000, deadline=None)
@given(_RANKINGS, _K)
def test_rrf_fuse_scores_stay_within_their_reciprocal_rank_bounds(rankings, k):
    # spec(T-022:AC-1) — every id scores strictly positive, and no id can
    # exceed one 1/(k+1) contribution per ranking.
    fuse = _retrieve_attr("rrf_fuse")

    ceiling = len(rankings) / (k + 1)

    for _doc_id, score in fuse(rankings, k=k):
        assert 0.0 < score <= ceiling + 1e-12


@settings(max_examples=2000, deadline=None)
@given(_RANKINGS_OF_PAIRS, _K, st.data())
def test_rrf_fuse_promoting_an_id_never_lowers_its_score(rankings, k, data):
    # spec(T-022:AC-1) — swapping an id one place earlier in one ranking can
    # only help it (and can only hurt the id it displaced).
    fuse = _retrieve_attr("rrf_fuse")

    which = data.draw(st.integers(min_value=0, max_value=len(rankings) - 1))
    position = data.draw(st.integers(min_value=0, max_value=len(rankings[which]) - 2))
    promoted = rankings[which][position + 1]
    demoted = rankings[which][position]

    swapped = [list(ranking) for ranking in rankings]
    swapped[which][position], swapped[which][position + 1] = promoted, demoted

    before = dict(fuse(rankings, k=k))
    after = dict(fuse(swapped, k=k))

    assert after[promoted] >= before[promoted]
    assert after[demoted] <= before[demoted]


# --------------------------------------------------------------------------
# AC-2 — semantic_search
# --------------------------------------------------------------------------


def test_semantic_search_returns_the_hand_computed_cosine_order():
    # spec(T-022:AC-2) — cosines are dot/16 over norm-4 integer vectors, so
    # 1.0 / 0.75 / 0.5 / 0.25 / 0.0 are EXACT through the store's fp16 pack.
    _index, store, chunks, provider = _fixture()

    results = _retrieve_attr("semantic_search")(store, chunks, QUERY, provider)

    assert [(r.doc_id, r.score) for r in results] == list(
        zip(SEMANTIC_ORDER, SEMANTIC_SCORES, strict=True)
    )


def test_semantic_search_maps_store_rows_to_chunks_by_chunk_id_not_by_position():
    # spec(T-022:AC-2) — the permuted-store proof (plan-review C-3). The
    # store was written in a different order than `chunks` AND carries two
    # rows from a prior embed run, so `chunks[row]` mis-labels every hit.
    _index, store, chunks, provider = _fixture()
    # Covered rows in cosine order are 1 (C_C), 2 (C_E), 4 (C_A), 5 (C_D),
    # 6 (C_B). Liveness: indexing `chunks` by those rows is type-correct and
    # silently wrong, so the two mappings really do disagree here.
    assert [chunks[row].chunk_id for row in (1, 2, 4)] == [C_B, C_C, C_E]

    results = _retrieve_attr("semantic_search")(store, chunks, QUERY, provider)

    assert [r.doc_id for r in results] == list(SEMANTIC_ORDER)


def test_semantic_search_never_surfaces_store_rows_no_chunk_covers():
    # spec(T-022:AC-2) — X_1/X_2 are rows from a prior embed run; X_1
    # outscores every chunk and must still never appear.
    _index, store, chunks, provider = _fixture()

    results = _retrieve_attr("semantic_search")(store, chunks, QUERY, provider, k=99)

    assert [r.doc_id for r in results] == list(SEMANTIC_ORDER)


def test_semantic_search_uncovered_rows_do_not_consume_result_slots():
    # spec(T-022:AC-2) — Test Agent decision 1. `cosine_top_k(store, q, 3)`
    # followed by a filter returns only two chunks here, because X_1 and X_2
    # sit at rows 0 and 3 of the top four.
    _index, store, chunks, provider = _fixture()

    results = _retrieve_attr("semantic_search")(store, chunks, QUERY, provider, k=3)

    assert [(r.doc_id, r.score) for r in results] == [
        (C_C, 1.0),
        (C_E, 0.75),
        (C_A, 0.5),
    ]


def test_semantic_search_fills_k_past_a_deep_field_of_uncovered_rows():
    # spec(T-022:AC-2) — decision 1's observable, hardened (test review I-3).
    # 24 rows from prior embed runs all outscore every chunk, so a widening
    # strategy that gives up after one or two doublings (k=3 -> 6 -> 12)
    # still returns ZERO covered results. Only a genuine loop — or a
    # full-depth scan — fills k. This pins the RESULT, so both designs pass;
    # nothing here forces full depth.
    index, store, chunks, provider = _deep_field_fixture()
    del index

    results = _retrieve_attr("semantic_search")(store, chunks, QUERY, provider, k=3)

    assert [(r.doc_id, r.score) for r in results] == [
        (DF_CHUNKS[0], 0.75),
        (DF_CHUNKS[1], 0.5),
        (DF_CHUNKS[2], 0.25),
    ]


def test_semantic_search_doc_id_is_the_chunk_id():
    # spec(T-022:AC-2)
    _index, store, chunks, provider = _fixture()

    results = _retrieve_attr("semantic_search")(store, chunks, QUERY, provider)

    assert {r.doc_id for r in results} == {chunk.chunk_id for chunk in chunks}


def test_semantic_search_scores_are_builtin_floats():
    # spec(T-022:AC-2) — a numpy scalar type-checks as a float but breaks
    # json.dumps at T-024's API boundary.
    _index, store, chunks, provider = _fixture()

    results = _retrieve_attr("semantic_search")(store, chunks, QUERY, provider)

    assert [type(r.score) for r in results] == [float] * len(results)


def test_semantic_search_returns_search_result_objects():
    # spec(T-022:AC-2) — the frozen shared contract, not an ad-hoc tuple.
    _index, store, chunks, provider = _fixture()

    results = _retrieve_attr("semantic_search")(store, chunks, QUERY, provider)

    assert all(isinstance(result, SearchResult) for result in results)


def test_semantic_search_snippet_is_the_first_160_characters_of_the_chunk():
    # spec(T-022:AC-2) — SNIPPET_LEN=160, the boolean.py/T-014R convention.
    _index, store, chunks, provider = _fixture()
    assert len(TEXT_C) > 160  # liveness: the truncation is actually exercised

    results = _retrieve_attr("semantic_search")(store, chunks, QUERY, provider)

    assert results[0].snippet == TEXT_C[:160]
    assert all(len(r.snippet) <= 160 for r in results)


def test_semantic_search_snippet_of_a_short_chunk_is_its_whole_text():
    # spec(T-022:AC-2) — no padding, no ellipsis.
    docs = [_doc(C_A, SHORT_TEXT)]
    chunks = [_chunk_map(docs)[C_A]]
    provider = ScriptedProvider({SHORT_TEXT: V_COS_100, QUERY: QUERY_VEC})
    store = _store_from(((C_A, SHORT_TEXT),), provider)
    assert len(SHORT_TEXT) < 160

    results = _retrieve_attr("semantic_search")(store, chunks, QUERY, provider)

    assert results[0].snippet == SHORT_TEXT


def test_semantic_search_truncates_to_k():
    # spec(T-022:AC-2)
    _index, store, chunks, provider = _fixture()

    results = _retrieve_attr("semantic_search")(store, chunks, QUERY, provider, k=2)

    assert [r.doc_id for r in results] == [C_C, C_E]


def test_semantic_search_k_beyond_the_chunk_count_returns_every_chunk():
    # spec(T-022:AC-2)
    _index, store, chunks, provider = _fixture()

    results = _retrieve_attr("semantic_search")(store, chunks, QUERY, provider, k=500)

    assert len(results) == len(chunks)


def test_semantic_search_embeds_only_the_query():
    # spec(T-022:AC-2) — the corpus was embedded once, by embed_corpus;
    # re-embedding it per query is a spend defect.
    _index, store, chunks, provider = _fixture()

    _retrieve_attr("semantic_search")(store, chunks, QUERY, provider)

    assert provider.calls == [[QUERY]]


def _stale_chunks(chunks, stale_id=C_A, suffix=" (amended)"):
    """`chunks` with one member's TEXT edited — the operational path
    `embed_corpus` leaves behind, since it skips chunk_ids already present
    (`onrecord/rag/embeddings.py`), so the store keeps the pre-edit vector
    and the pre-edit content_hash."""
    return [
        dataclasses.replace(chunk, text=chunk.text + suffix)
        if chunk.chunk_id == stale_id
        else chunk
        for chunk in chunks
    ]


def test_semantic_search_raises_store_mismatch_when_the_chunk_text_is_stale():
    # spec(T-022:AC-2) — the default k=10 covers all five chunks, so the
    # stale one is served and must be caught.
    _index, store, chunks, provider = _fixture()

    with pytest.raises(_retrieve_attr("StoreMismatch")):
        _retrieve_attr("semantic_search")(store, _stale_chunks(chunks), QUERY, provider)


def test_semantic_search_raises_store_mismatch_when_a_stale_row_is_inside_the_cut():
    # spec(T-022:AC-2) — ORCHESTRATOR RULING, side one. C_A is the THIRD
    # chunk by cosine (1.0, 0.75, 0.5), so k=3 is the tightest cut that still
    # serves it. Pinned at the boundary rather than at the default k, so an
    # implementation that verifies only the first hit is caught too.
    _index, store, chunks, provider = _fixture()

    with pytest.raises(_retrieve_attr("StoreMismatch")):
        _retrieve_attr("semantic_search")(store, _stale_chunks(chunks), QUERY, provider, k=3)


def test_semantic_search_verifies_the_single_top_hit_at_k_one():
    # spec(T-022:AC-2) — ORCHESTRATOR RULING, the tightest case: C_C is the
    # cosine-1.0 chunk, so at k=1 it is the ONLY row served. Result-scoped
    # verification must still hash it. Without this, an implementation that
    # verifies every result EXCEPT the first passes the whole suite while
    # serving a stale rank-1 receipt — the highest-stakes row there is.
    _index, store, chunks, provider = _fixture()

    with pytest.raises(_retrieve_attr("StoreMismatch")):
        _retrieve_attr("semantic_search")(
            store, _stale_chunks(chunks, stale_id=C_C), QUERY, provider, k=1
        )


def test_semantic_search_returns_cleanly_when_the_stale_row_is_below_the_cut():
    # spec(T-022:AC-2) — ORCHESTRATOR RULING, side two, and the reason this
    # ruling is a RULING: at k=2 the stale C_A never reaches the results, so
    # it is never hashed and the call succeeds. Verification is
    # RESULT-SCOPED — no *served* receipt is ever wrong, and the whole chunk
    # set is not audited per query (T-021's load-time checks own that). A
    # corpus-wide implementation raises here and is wrong under the ruling.
    _index, store, chunks, provider = _fixture()

    results = _retrieve_attr("semantic_search")(store, _stale_chunks(chunks), QUERY, provider, k=2)

    assert [(r.doc_id, r.score) for r in results] == [(C_C, 1.0), (C_E, 0.75)]


def test_store_mismatch_names_the_chunk_and_both_content_hashes():
    # spec(T-022:AC-2) — Test Agent decision 2.
    _index, store, chunks, provider = _fixture()
    amended = TEXT_A + " (amended)"
    stale = _stale_chunks(chunks)

    with pytest.raises(_retrieve_attr("StoreMismatch")) as excinfo:
        _retrieve_attr("semantic_search")(store, stale, QUERY, provider)

    message = str(excinfo.value)
    assert C_A in message
    assert content_hash(store.model, store.dim, TEXT_A) in message
    assert content_hash(store.model, store.dim, amended) in message


def test_the_three_retrieval_errors_are_three_distinct_types():
    # spec(T-022:AC-2) — test review I-1: "typed" is not satisfied by three
    # names bound to ONE class. Aliasing all three to a single Exception
    # subclass passed the first freeze, because every `pytest.raises(X)` is
    # an isinstance check that an alias satisfies. T-024's degradation ladder
    # branches on these by name, so a merge would route a stale-text defect
    # into the wrong rung.
    module = _retrieve_module()
    errors = [
        _attr(module, "StoreMismatch"),
        _attr(module, "MissingEmbeddings"),
        _attr(module, "NonIdentityChunking"),
    ]

    assert len({id(error) for error in errors}) == 3, "the three error names are aliases"
    for error in errors:
        for other in errors:
            if error is not other:
                assert not issubclass(error, other), (
                    f"{error.__name__} is a subclass of {other.__name__}; catching one "
                    f"would swallow the other"
                )


def test_retrieval_errors_are_disjoint_from_t021s_store_error_hierarchy():
    # spec(T-022:AC-2) — test review I-1, second half. T-024 already branches
    # on T-021's StoreIdentityMismatch ("wrong store" -> 503); a
    # StoreMismatch that subclassed it would report a stale-text defect as a
    # wrong-store one. CorruptStore carries its own rung for the same reason.
    module = _retrieve_module()
    t021_errors = (StoreIdentityMismatch, CorruptStore)

    for name in ("StoreMismatch", "MissingEmbeddings", "NonIdentityChunking"):
        error = _attr(module, name)
        for t021_error in t021_errors:
            assert error is not t021_error
            assert not issubclass(error, t021_error), (
                f"onrecord.rag.retrieve.{name} must not subclass T-021's "
                f"{t021_error.__name__} — T-024's ladder branches on them separately"
            )


def test_semantic_search_raises_missing_embeddings_for_an_unembedded_chunk():
    # spec(T-022:AC-2)
    _index, store, chunks, provider = _fixture(
        store_pairs=((C_A, TEXT_A), (C_B, TEXT_B), (C_E, TEXT_E))
    )

    with pytest.raises(_retrieve_attr("MissingEmbeddings")):
        _retrieve_attr("semantic_search")(store, chunks, QUERY, provider)


def test_missing_embeddings_names_the_count_of_unembedded_chunks():
    # spec(T-022:AC-2) — two of five chunks are missing. No id in this
    # fixture contributes a bare "2" token, so an implementation naming the
    # total (5) or the covered count (3) instead is caught.
    _index, store, chunks, provider = _fixture(
        store_pairs=((C_A, TEXT_A), (C_B, TEXT_B), (C_E, TEXT_E))
    )

    with pytest.raises(_retrieve_attr("MissingEmbeddings")) as excinfo:
        _retrieve_attr("semantic_search")(store, chunks, QUERY, provider)

    assert "2" in _integer_tokens(str(excinfo.value))


def test_semantic_search_reports_missing_embeddings_even_when_k_is_tiny():
    # spec(T-022:AC-2) — never a silent skip: a wrong receipt is the
    # product's worst failure, and k=1 would otherwise hide it behind the
    # single hit that did resolve.
    _index, store, chunks, provider = _fixture(
        store_pairs=((C_A, TEXT_A), (C_B, TEXT_B), (C_E, TEXT_E))
    )

    with pytest.raises(_retrieve_attr("MissingEmbeddings")):
        _retrieve_attr("semantic_search")(store, chunks, QUERY, provider, k=1)


def test_semantic_search_accepts_a_merged_chunk():
    # spec(T-022:AC-2) — Test Agent decision 4: the identity guard belongs to
    # hybrid_search (fusion needs one id space); semantic-only retrieval over
    # a window>1 chunking is coherent and reports the chunk_id it was given.
    _index, store, chunks, provider, merged_chunk = _merged_fixture()

    results = _retrieve_attr("semantic_search")(store, chunks, QUERY, provider)

    assert merged_chunk.chunk_id in {r.doc_id for r in results}


# --------------------------------------------------------------------------
# AC-3 / AC-4 — hybrid_search
# --------------------------------------------------------------------------

# Preconditions the fused expectations rest on, asserted in-test so a change
# in BM25 fails HERE with a clear message instead of silently rewriting the
# fusion arithmetic:
#   lexical  [LEXONLY (tf 2, dl 60), C_A (tf 1, dl 40), C_D (tf 1, dl 120)]
#   semantic [C_C, C_E, C_A, C_D, C_B]
# RRF k=60:
#   C_A     1/62 + 1/63 = 0.03200204813108039
#   C_D     1/63 + 1/64 = 0.03149801587301587
#   C_C            1/61 = 0.01639344262295082   } tie, edgar: sorts first
#   LEXONLY        1/61 = 0.01639344262295082   }
#   C_E            1/62 = 0.016129032258064516
#   C_B            1/65 = 0.015384615384615385
EXPECTED_LEXICAL_ORDER = [LEXONLY, C_A, C_D]
EXPECTED_HYBRID_ORDER = [C_A, C_D, C_C, LEXONLY, C_E, C_B]
EXPECTED_HYBRID_SCORES = [R_2_PLUS_3, R_3_PLUS_4, R_1, R_1, R_2, R_5]


def _lexical_results(index):
    return ranked_search(index, QUERY, k=index.doc_count())


def test_hybrid_fixture_lexical_ranking_is_what_the_fusion_arithmetic_assumes():
    # spec(T-022:AC-3) — a precondition, not a contract on T-022: it pins the
    # fixture's BM25 order so the hand-computed RRF below cannot rot silently.
    index, _store, _chunks, _provider = _fixture()
    _retrieve_module()  # RED until the target module lands, like every test here

    assert [r.doc_id for r in _lexical_results(index)] == EXPECTED_LEXICAL_ORDER


def test_hybrid_search_fused_order_matches_the_hand_computed_rrf():
    # spec(T-022:AC-3) — lexical and semantic disagree sharply here; note the
    # 1/61 tie is broken toward C_C ("edgar:..."), which is the SEMANTIC-only
    # doc, while LEXONLY leads the lexical ranking.
    index, store, chunks, provider = _fixture()
    # In-test precondition (test review N-1): a T-011 BM25 change surfaces
    # HERE, named, instead of as a bare order mismatch blamed on T-022.
    assert [r.doc_id for r in _lexical_results(index)] == EXPECTED_LEXICAL_ORDER

    results = _retrieve_attr("hybrid_search")(index, store, chunks, QUERY, provider)

    assert [r.doc_id for r in results] == EXPECTED_HYBRID_ORDER


def test_hybrid_search_scores_are_the_rrf_scores():
    # spec(T-022:AC-3)
    index, store, chunks, provider = _fixture()
    assert [r.doc_id for r in _lexical_results(index)] == EXPECTED_LEXICAL_ORDER

    results = _retrieve_attr("hybrid_search")(index, store, chunks, QUERY, provider)

    assert [r.score for r in results] == pytest.approx(EXPECTED_HYBRID_SCORES, rel=1e-12)


def test_hybrid_search_returns_search_result_objects():
    # spec(T-022:AC-3) — test review M-2: `semantic_search` had this pin and
    # hybrid did not, the same asymmetry class as the score types.
    index, store, chunks, provider = _fixture()

    results = _retrieve_attr("hybrid_search")(index, store, chunks, QUERY, provider)

    assert all(isinstance(result, SearchResult) for result in results)


def test_hybrid_search_verifies_every_chunk_because_all_of_them_are_results():
    # spec(T-022:AC-3) — the reach of the result-scoped ruling under fusion:
    # hybrid calls semantic_search at k=len(chunks), so EVERY chunk is a
    # result and therefore every chunk is hashed. C_A is stale and would slip
    # past a k=2 semantic call (see the AC-2 pair), but never past hybrid.
    index, store, chunks, provider = _fixture()

    with pytest.raises(_retrieve_attr("StoreMismatch")):
        _retrieve_attr("hybrid_search")(index, store, _stale_chunks(chunks), QUERY, provider, k=1)


def test_hybrid_search_scores_are_builtin_floats():
    # spec(T-022:AC-3) — same JSON-serialisability constraint as the semantic
    # scores: T-024 hands these straight to a response body.
    index, store, chunks, provider = _fixture()

    results = _retrieve_attr("hybrid_search")(index, store, chunks, QUERY, provider)

    assert [type(r.score) for r in results] == [float] * len(results)


def test_hybrid_search_honours_an_explicit_rrf_k():
    # spec(T-022:AC-3) — rrf_k=10 recomputes every score off 1/(10+rank):
    # C_A is lexical rank 2 + semantic rank 3 -> 1/12 + 1/13; C_D is lexical
    # rank 3 + semantic rank 4 -> 1/13 + 1/14.
    index, store, chunks, provider = _fixture()

    results = _retrieve_attr("hybrid_search")(index, store, chunks, QUERY, provider, rrf_k=10)

    assert [r.score for r in results[:2]] == pytest.approx(
        [0.16025641025641027, 0.14835164835164835], rel=1e-12
    )


def test_hybrid_search_surfaces_a_semantically_only_doc_with_its_chunk_text_snippet():
    # spec(T-022:AC-3) — C_C carries no query term, so BM25 never nominates
    # it; RRF still floats it into the top three off its semantic rank 1.
    index, store, chunks, provider = _fixture()
    assert C_C not in {r.doc_id for r in _lexical_results(index)}

    results = _retrieve_attr("hybrid_search")(index, store, chunks, QUERY, provider)

    semantic_only = next(r for r in results if r.doc_id == C_C)
    assert semantic_only.snippet == TEXT_C[:160]


def test_hybrid_search_surfaces_a_lexically_only_doc_with_its_positional_snippet():
    # spec(T-022:AC-3) — LEXONLY is an index doc with no chunk (the chunk set
    # predates it), so its snippet can only come from the lexical hit; that
    # snippet is centred on the query term at token 50 and is NOT text[:160].
    index, store, chunks, provider = _fixture()
    lexical = {r.doc_id: r for r in _lexical_results(index)}
    assert LEXONLY not in {chunk.chunk_id for chunk in chunks}
    assert lexical[LEXONLY].snippet != TEXT_LEXONLY[:160]  # liveness

    results = _retrieve_attr("hybrid_search")(index, store, chunks, QUERY, provider)

    lexical_only = next(r for r in results if r.doc_id == LEXONLY)
    assert lexical_only.snippet == lexical[LEXONLY].snippet


def test_hybrid_search_prefers_the_lexical_snippet_for_a_chunk_found_both_ways():
    # spec(T-022:AC-3) — "positions-based snippets are strictly better": C_A
    # is both a chunk and a lexical hit, and its query term sits at token 38,
    # so the two candidate snippets are visibly different.
    index, store, chunks, provider = _fixture()
    lexical = {r.doc_id: r for r in _lexical_results(index)}
    assert lexical[C_A].snippet != TEXT_A[:160]  # liveness

    results = _retrieve_attr("hybrid_search")(index, store, chunks, QUERY, provider)

    both_ways = next(r for r in results if r.doc_id == C_A)
    assert both_ways.snippet == lexical[C_A].snippet


def test_hybrid_search_truncates_to_k_exactly():
    # spec(T-022:AC-3)
    index, store, chunks, provider = _fixture()

    results = _retrieve_attr("hybrid_search")(index, store, chunks, QUERY, provider, k=3)

    assert [r.doc_id for r in results] == EXPECTED_HYBRID_ORDER[:3]


def test_hybrid_search_fuses_the_full_depth_lexical_ranking():
    # spec(T-022:AC-3) — FD_Q sits at lexical rank 12, past any default k=10
    # cut. Full depth scores it 1/72 + 1/62 = 0.030017921146953404 and ranks
    # it second; a ranked_search(index, query, k=10) call scores it
    # 0.016129032258064516 and drops it to third, behind a filler.
    index, store, chunks, provider = _full_depth_fixture()
    lexical = [r.doc_id for r in ranked_search(index, QUERY, k=index.doc_count())]
    assert len(lexical) == 12 and lexical[-1] == FD_Q  # precondition

    results = _retrieve_attr("hybrid_search")(index, store, chunks, QUERY, provider, k=2)

    assert [r.doc_id for r in results] == [FD_P, FD_Q]
    assert [r.score for r in results] == pytest.approx([R_1_PLUS_1, R_2_PLUS_12], rel=1e-12)


def test_hybrid_search_raises_non_identity_chunking_for_a_merged_window_chunk():
    # spec(T-022:AC-4) — plan-review I-11: fail loud, never degenerate into a
    # no-overlap concatenation. The merged chunk IS embedded here, so
    # MissingEmbeddings cannot stand in for the guard.
    index, store, chunks, provider, merged_chunk = _merged_fixture()
    assert len(merged_chunk.doc_ids) == 2 and merged_chunk.chunk_id.endswith("+w2")

    with pytest.raises(_retrieve_attr("NonIdentityChunking")):
        _retrieve_attr("hybrid_search")(index, store, chunks, QUERY, provider)


def test_hybrid_search_raises_non_identity_chunking_for_a_chunk_covering_two_docs():
    # spec(T-022:AC-4) — test review M-1: the `len(chunk.doc_ids) == 1`
    # conjunct on its own. This chunk's id DOES equal doc_ids[0], so a guard
    # written as `chunk_id != doc_ids[0]` alone passes it through and fuses a
    # two-doc chunk into a single-doc id space. Unreachable from
    # `chunk_corpus` (T-020 pins the equivalence) but reachable from any
    # caller, which hybrid_search accepts.
    index, store, chunks, provider = _fixture()
    forged = [
        dataclasses.replace(chunk, doc_ids=[C_A, C_B]) if chunk.chunk_id == C_A else chunk
        for chunk in chunks
    ]
    assert forged[0].chunk_id == forged[0].doc_ids[0]  # liveness: only `len` is wrong

    with pytest.raises(_retrieve_attr("NonIdentityChunking")):
        _retrieve_attr("hybrid_search")(index, store, forged, QUERY, provider)


def test_hybrid_search_raises_non_identity_chunking_when_chunk_id_disagrees_with_its_doc_id():
    # spec(T-022:AC-4) — the other half of the guard: one doc id, but not the
    # chunk's own. Text and chunk_id are untouched, so the store still
    # resolves and verifies this chunk cleanly.
    index, store, chunks, provider = _fixture()
    forged = [
        dataclasses.replace(chunk, doc_ids=[C_B]) if chunk.chunk_id == C_A else chunk
        for chunk in chunks
    ]

    with pytest.raises(_retrieve_attr("NonIdentityChunking")):
        _retrieve_attr("hybrid_search")(index, store, forged, QUERY, provider)


def test_hybrid_search_guards_a_non_identity_chunk_that_would_never_be_returned():
    # spec(T-022:AC-4) — the guard is a corpus-wide precondition, not a
    # per-result filter: C_B scores last semantically, carries no query term,
    # and is cut by k=1, so a guard applied only to returned rows misses it.
    index, store, chunks, provider = _fixture()
    forged = [
        dataclasses.replace(chunk, doc_ids=[C_A, C_B]) if chunk.chunk_id == C_B else chunk
        for chunk in chunks
    ]

    with pytest.raises(_retrieve_attr("NonIdentityChunking")):
        _retrieve_attr("hybrid_search")(index, store, forged, QUERY, provider, k=1)


def test_hybrid_search_doc_ids_resolve_through_index_get_doc():
    # spec(T-022:AC-4) — the locked-invariant round trip that the frozen
    # 9-key /api/search shape rests on (T-024 projects chunk_id -> doc_id).
    index, store, chunks, provider = _fixture()

    results = _retrieve_attr("hybrid_search")(index, store, chunks, QUERY, provider)

    assert [index.get_doc(r.doc_id).id for r in results] == [r.doc_id for r in results]


def test_hybrid_search_propagates_missing_embeddings():
    # spec(T-022:AC-4) — the semantic half of the fusion cannot be silently
    # short either; a partial semantic ranking would skew every RRF score.
    index, store, chunks, provider = _fixture(
        store_pairs=((C_A, TEXT_A), (C_B, TEXT_B), (C_E, TEXT_E))
    )

    with pytest.raises(_retrieve_attr("MissingEmbeddings")):
        _retrieve_attr("hybrid_search")(index, store, chunks, QUERY, provider)


# --------------------------------------------------------------------------
# AC-5 — report_modes
# --------------------------------------------------------------------------


def _run_report_modes(tmp_path, monkeypatch, history_name="modes_scoreboard.jsonl"):
    _isolate_environment(monkeypatch, tmp_path)
    index, store, chunks, provider = _modes_fixture()
    judgments = _write_judgments(tmp_path)
    history = tmp_path / "sidecar" / history_name
    rows = _modes_attr("report_modes")(
        index, store, chunks, judgments, provider, history_path=history
    )
    return rows, history


def test_report_modes_appends_exactly_three_rows_one_per_mode(tmp_path, monkeypatch):
    # spec(T-022:AC-5)
    _rows, history = _run_report_modes(tmp_path, monkeypatch)

    assert [row["mode"] for row in _rows_in(history)] == ["lexical", "semantic", "hybrid"]


def test_report_modes_row_key_set_is_exactly_the_pinned_five(tmp_path, monkeypatch):
    # spec(T-022:AC-5)
    _rows, history = _run_report_modes(tmp_path, monkeypatch)

    for row in _rows_in(history):
        assert set(row) == {"timestamp", "git_sha", "corpus_version", "mode", "metrics"}
        assert set(row["metrics"]) == {"per_query", "mean"}


def test_report_modes_scores_the_six_eval_labels(tmp_path, monkeypatch):
    # spec(T-022:AC-5) — the SAME six labels as eval/run.py, verbatim.
    _rows, history = _run_report_modes(tmp_path, monkeypatch)

    for row in _rows_in(history):
        assert set(row["metrics"]["mean"]) == set(SIX_LABELS)
        for scores in row["metrics"]["per_query"].values():
            assert set(scores) == set(SIX_LABELS)


def test_report_modes_lexical_numbers_match_hand_computation(tmp_path, monkeypatch):
    # spec(T-022:AC-5) — lexical qa retrieves [M_1, M_2]; qb retrieves
    # NOTHING (its terms are absent from the corpus).
    _rows, history = _run_report_modes(tmp_path, monkeypatch)

    row = next(row for row in _rows_in(history) if row["mode"] == "lexical")
    _assert_metrics(row["metrics"], EXPECTED_METRICS["lexical"])


def test_report_modes_semantic_numbers_match_hand_computation(tmp_path, monkeypatch):
    # spec(T-022:AC-5) — semantic qa [M_2, M_3, M_1, M_4]; qb [M_1, M_3,
    # M_2, M_4].
    _rows, history = _run_report_modes(tmp_path, monkeypatch)

    row = next(row for row in _rows_in(history) if row["mode"] == "semantic")
    _assert_metrics(row["metrics"], EXPECTED_METRICS["semantic"])


def test_report_modes_hybrid_numbers_match_hand_computation(tmp_path, monkeypatch):
    # spec(T-022:AC-5) — hybrid qa fuses to [M_2, M_1, M_3, M_4], an order
    # neither single mode produces.
    _rows, history = _run_report_modes(tmp_path, monkeypatch)

    row = next(row for row in _rows_in(history) if row["mode"] == "hybrid")
    _assert_metrics(row["metrics"], EXPECTED_METRICS["hybrid"])


def test_report_modes_mean_denominator_counts_zero_result_queries(tmp_path, monkeypatch):
    # spec(T-022:AC-5) — qb retrieves nothing lexically and scores 0.0
    # across the board; the lexical mean must still divide by BOTH queries
    # (mirrors eval/run.py::_mean_metrics), halving qa's numbers rather than
    # quietly dropping the query.
    _rows, history = _run_report_modes(tmp_path, monkeypatch)

    row = next(row for row in _rows_in(history) if row["mode"] == "lexical")
    assert set(row["metrics"]["per_query"]) == {"qa", "qb"}
    assert row["metrics"]["per_query"]["qb"] == pytest.approx(dict.fromkeys(SIX_LABELS, 0.0))
    assert row["metrics"]["mean"]["MRR"] == pytest.approx(0.5, rel=1e-12)


def test_report_modes_returns_the_rows_it_appended(tmp_path, monkeypatch):
    # spec(T-022:AC-5)
    rows, history = _run_report_modes(tmp_path, monkeypatch)

    assert rows == _rows_in(history)


def test_report_modes_appends_without_disturbing_existing_history(tmp_path, monkeypatch):
    # spec(T-022:AC-5) — a scoreboard is an append-only audit trail.
    _isolate_environment(monkeypatch, tmp_path)
    index, store, chunks, provider = _modes_fixture()
    judgments = _write_judgments(tmp_path)
    history = tmp_path / "modes_scoreboard.jsonl"
    existing = json.dumps({"mode": "lexical", "note": "an earlier run"})
    history.write_text(existing + "\n", encoding="utf-8")

    _modes_attr("report_modes")(index, store, chunks, judgments, provider, history_path=history)

    lines = history.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4
    assert lines[0] == existing


def test_report_modes_creates_missing_history_directories(tmp_path, monkeypatch):
    # spec(T-022:AC-5) — mirrors eval/run.py's mkdir(parents=True).
    _rows, history = _run_report_modes(tmp_path, monkeypatch)

    assert history.exists()


def test_report_modes_reads_corpus_version_from_the_index_manifest(tmp_path, monkeypatch):
    # spec(T-022:AC-5) — Test Agent decision 3, via T-018's read_manifest.
    _isolate_environment(monkeypatch, tmp_path)
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    (index_dir / "manifest.json").write_text(
        json.dumps({"corpus_version": "corpus-v2-2026-08-12"}), encoding="utf-8"
    )
    monkeypatch.setenv("ONRECORD_INDEX", str(index_dir))
    index, store, chunks, provider = _modes_fixture()
    judgments = _write_judgments(tmp_path)
    history = tmp_path / "modes_scoreboard.jsonl"

    rows = _modes_attr("report_modes")(
        index, store, chunks, judgments, provider, history_path=history
    )

    assert {row["corpus_version"] for row in rows} == {"corpus-v2-2026-08-12"}


def test_report_modes_corpus_version_falls_back_to_unversioned(tmp_path, monkeypatch):
    # spec(T-022:AC-5) — delenv(raising=False) so the branch is exercised on
    # purpose rather than by an accident of the runner's environment.
    rows, _history = _run_report_modes(tmp_path, monkeypatch)

    assert {row["corpus_version"] for row in rows} == {"unversioned"}


def test_report_modes_stamps_a_string_timestamp_and_git_sha(tmp_path, monkeypatch):
    # spec(T-022:AC-5) — values are provenance, not contract; only the JSON
    # types are pinned (a datetime would not survive json.dumps).
    rows, _history = _run_report_modes(tmp_path, monkeypatch)

    assert all(isinstance(row["timestamp"], str) and row["timestamp"] for row in rows)
    assert all(isinstance(row["git_sha"], str) and row["git_sha"] for row in rows)


def test_the_mode_tag_never_leaks_into_eval_run_history_rows(tmp_path, monkeypatch):
    # spec(T-022:AC-5) — the locked constraint the sidecar exists to respect:
    # eval/run.py's history-row key set is frozen by test_metrics.py and must
    # NOT gain a mode field. The two artifacts differ by exactly that key.
    from onrecord.eval import run as eval_run

    modes_rows, _history = _run_report_modes(tmp_path, monkeypatch)
    run_history = tmp_path / "scoreboard.jsonl"
    eval_run.run(_write_judgments(tmp_path), retrieve_fn=lambda q: [], history_path=run_history)

    run_row = _rows_in(run_history)[0]
    assert set(run_row) == {"timestamp", "git_sha", "corpus_version", "metrics"}
    assert set(modes_rows[0]) - set(run_row) == {"mode"}


def test_report_modes_writes_only_its_own_artifact(tmp_path, monkeypatch):
    # spec(T-022:AC-5) — eval/run.py's default scoreboard is untouched.
    _rows, history = _run_report_modes(tmp_path, monkeypatch)

    assert not (tmp_path / "artifacts").exists()
    assert [path.name for path in history.parent.iterdir()] == ["modes_scoreboard.jsonl"]


# --------------------------------------------------------------------------
# Signatures + Definition of Done
# --------------------------------------------------------------------------


# Test review M-3: `kind` is part of the frozen signature. Without it,
# `def semantic_search(*, store, chunks, ...)` produces an identical
# (name, default) list while breaking the positional calls T-024 makes.
POS_OR_KW = inspect.Parameter.POSITIONAL_OR_KEYWORD


def _signature(func):
    return [
        (name, parameter.kind, parameter.default)
        for name, parameter in inspect.signature(func).parameters.items()
    ]


def test_semantic_search_signature_is_frozen():
    # spec(T-022:AC-2) — T-024 calls these positionally and by keyword.
    assert _signature(_retrieve_attr("semantic_search")) == [
        ("store", POS_OR_KW, inspect.Parameter.empty),
        ("chunks", POS_OR_KW, inspect.Parameter.empty),
        ("query", POS_OR_KW, inspect.Parameter.empty),
        ("provider", POS_OR_KW, inspect.Parameter.empty),
        ("k", POS_OR_KW, 10),
    ]


def test_rrf_fuse_signature_is_frozen():
    # spec(T-022:AC-1)
    assert _signature(_retrieve_attr("rrf_fuse")) == [
        ("rankings", POS_OR_KW, inspect.Parameter.empty),
        ("k", POS_OR_KW, 60),
    ]


def test_hybrid_search_signature_is_frozen():
    # spec(T-022:AC-3)
    assert _signature(_retrieve_attr("hybrid_search")) == [
        ("index", POS_OR_KW, inspect.Parameter.empty),
        ("store", POS_OR_KW, inspect.Parameter.empty),
        ("chunks", POS_OR_KW, inspect.Parameter.empty),
        ("query", POS_OR_KW, inspect.Parameter.empty),
        ("provider", POS_OR_KW, inspect.Parameter.empty),
        ("k", POS_OR_KW, 10),
        ("rrf_k", POS_OR_KW, 60),
    ]


def test_report_modes_signature_is_frozen():
    # spec(T-022:AC-5) — including the sidecar's default artifact path.
    assert _signature(_modes_attr("report_modes")) == [
        ("index", POS_OR_KW, inspect.Parameter.empty),
        ("store", POS_OR_KW, inspect.Parameter.empty),
        ("chunks", POS_OR_KW, inspect.Parameter.empty),
        ("judgments_path", POS_OR_KW, inspect.Parameter.empty),
        ("provider", POS_OR_KW, inspect.Parameter.empty),
        ("history_path", POS_OR_KW, "artifacts/modes_scoreboard.jsonl"),
    ]


def test_modes_exposes_a_cli_main():
    # spec(T-022:AC-5) — mirroring eval.run's pattern.
    assert callable(_modes_attr("main"))


def _module_ast(module) -> ast.Module:
    return ast.parse(Path(module.__file__).read_text(encoding="utf-8"))


def _imported_module_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_retrieve_never_re_derives_the_content_hash_formula():
    # spec(T-022:AC-2) — content_hash is T-021's frozen PUBLIC helper: import
    # it, never restate `sha256(f"{model}\n{dim}\n{text}")`. Two frozen
    # suites each encoding the same concatenation is the LESSONS T-003/T-004
    # recurrence in miniature, and any drift is a silent total miss. Checked
    # over the AST, so prose mentioning hashlib in a docstring is fine.
    tree = _module_ast(_retrieve_module())

    assert not any(name.split(".")[0] == "hashlib" for name in _imported_module_names(tree))
    assert not any(
        (isinstance(node, ast.Attribute) and node.attr == "sha256")
        or (isinstance(node, ast.Name) and node.id == "sha256")
        for node in ast.walk(tree)
    )
    assert any(
        (isinstance(node, ast.Attribute) and node.attr == "content_hash")
        or (isinstance(node, ast.Name) and node.id == "content_hash")
        or (isinstance(node, ast.alias) and node.name == "content_hash")
        for node in ast.walk(tree)
    )


def test_retrieve_imports_no_web_framework():
    # spec(T-022:AC-3) — Definition of Done: no FastAPI imports anywhere in
    # this ticket (API wiring is T-024's).
    imported = _imported_module_names(_module_ast(_retrieve_module()))

    assert not any(name.split(".")[0] in {"fastapi", "starlette", "uvicorn"} for name in imported)


def test_modes_imports_no_web_framework():
    # spec(T-022:AC-5) — Definition of Done, the modes half.
    imported = _imported_module_names(_module_ast(_modes_module()))

    assert not any(name.split(".")[0] in {"fastapi", "starlette", "uvicorn"} for name in imported)

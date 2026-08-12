"""Ranked (BM25) search over an InvertedIndex (T-011).

`ranked_search` runs an OR-semantics query: the candidate set is the union
of doc ids matching ANY analyzed query term (a doc matching zero query terms
is never a candidate, regardless of `k`). Each candidate's score is the SUM
of `onrecord.rank.bm25.bm25_score(...)` over every query term -- a term the
candidate doc lacks has `tf=0`, which the formula naturally scores as a 0
contribution, no special-casing required. Results are truncated to the
top-`k` via a heap, ties broken by ascending external `Doc.id` (never
internal id or insertion/heap-pop order) for determinism.

`k1`/`b` are exposed as keyword parameters here too (not just on
`bm25_score`) and threaded through every per-term score, per the ticket's
Definition of Done ("k1/b exposed as parameters everywhere").

Snippets are ~160 chars centered on the doc's first query-term occurrence
(the earliest token position, across all query terms, at which any query
term appears in that doc) -- not boolean.py's naive first-N-chars. Token
positions from `InvertedIndex.postings(term).positions` are 0-based indices
into the analyzer's token list, not character offsets, so a token-position
-> character-offset mapping is reconstructed locally by re-scanning the raw
doc text with the same word-token pattern `onrecord.analysis.analyzer`
uses; this lines up exactly with any analyzer (including the trivial
whitespace-split analyzer used in tests) whenever tokens contain no
internal punctuation, and degrades gracefully otherwise since the snippet
is a soft ~160-char window, not an exact-offset contract.

`boolean.py` is not touched or imported from here -- this module is
self-contained, per the ticket's file scope.
"""

from __future__ import annotations

import heapq
import re
from bisect import bisect_left
from typing import TYPE_CHECKING

from onrecord.types import SearchResult

if TYPE_CHECKING:
    from collections.abc import Callable

    from onrecord.index.inverted import InvertedIndex

SNIPPET_RADIUS = 80

# Word-token pattern mirroring onrecord.analysis.analyzer's tokenizer, used
# only to recover character spans for a known token *position* -- never to
# decide term matching (that's the index's job).
_WORD_RE = re.compile(r"[^\W_]+", flags=re.UNICODE)


def _resolve_analyzer(analyzer: Callable[[str], list[str]] | None) -> Callable[[str], list[str]]:
    if analyzer is not None:
        return analyzer
    from onrecord.analysis.analyzer import analyze

    return analyze


def _tf_in_doc(index: InvertedIndex, term: str, internal_id: int) -> int:
    postings = index.postings(term)
    doc_ids = postings.doc_ids
    i = bisect_left(doc_ids, internal_id)
    if i < len(doc_ids) and doc_ids[i] == internal_id:
        return postings.tfs[i]
    return 0


def _first_term_position_in_doc(
    index: InvertedIndex, terms: list[str], internal_id: int
) -> int | None:
    """Earliest token position, across all query terms, at which any query
    term occurs in `internal_id`; None if none of the terms occur there."""
    best: int | None = None
    for term in terms:
        postings = index.postings(term)
        doc_ids = postings.doc_ids
        i = bisect_left(doc_ids, internal_id)
        if i >= len(doc_ids) or doc_ids[i] != internal_id:
            continue
        positions = postings.positions[i]
        if not positions:
            continue
        term_first = min(positions)
        if best is None or term_first < best:
            best = term_first
    return best


def _char_span_for_token_position(text: str, token_position: int) -> tuple[int, int]:
    """(start, end) character offsets of the `token_position`-th word token
    in `text`; falls back to (0, 0) if `token_position` is out of range."""
    for i, match in enumerate(_WORD_RE.finditer(text)):
        if i == token_position:
            return match.start(), match.end()
    return 0, 0


def _snippet(text: str, token_position: int | None, radius: int = SNIPPET_RADIUS) -> str:
    if token_position is None:
        return text[: radius * 2]
    start_char, end_char = _char_span_for_token_position(text, token_position)
    start = max(0, start_char - radius)
    end = min(len(text), end_char + radius)
    return text[start:end]


def ranked_search(
    index: InvertedIndex,
    query: str,
    k: int = 10,
    k1: float = 1.5,
    b: float = 0.75,
    analyzer: Callable[[str], list[str]] | None = None,
) -> list[SearchResult]:
    """Run a BM25-ranked OR query against `index`, returning the top `k`
    `SearchResult`s sorted by score descending, ties broken by ascending
    external doc id."""
    from onrecord.rank.bm25 import bm25_score

    analyze = _resolve_analyzer(analyzer)
    terms = analyze(query)
    if not terms:
        return []

    candidate_ids: set[int] = set()
    for term in terms:
        candidate_ids.update(index.postings(term).doc_ids)
    if not candidate_ids:
        return []

    N = index.doc_count()
    avg_doc_len = index.avg_doc_length()

    scored: list[tuple[float, str, int]] = []  # (score, external_doc_id, internal_id)
    for internal_id in candidate_ids:
        doc_len = index.doc_length(internal_id)
        total = 0.0
        for term in terms:
            df = index.df(term)
            tf = _tf_in_doc(index, term, internal_id)
            total += bm25_score(tf, df, N, doc_len, avg_doc_len, k1=k1, b=b)
        doc_id = index.get_doc(internal_id).id
        scored.append((total, doc_id, internal_id))

    top = heapq.nsmallest(k, scored, key=lambda item: (-item[0], item[1]))

    results = []
    for score, doc_id, internal_id in top:
        doc = index.get_doc(internal_id)
        token_position = _first_term_position_in_doc(index, terms, internal_id)
        results.append(
            SearchResult(doc_id=doc_id, score=score, snippet=_snippet(doc.text, token_position))
        )
    return results

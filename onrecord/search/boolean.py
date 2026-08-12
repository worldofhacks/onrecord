"""Boolean/phrase search — AND/OR merges over postings, phrase adjacency (T-004).

`boolean_search` runs a single-op (AND/OR) boolean query: query text is
tokenized with the same analyzer used at index time (the analyzer invariant),
then AND performs a k-way sorted intersection of postings doc_ids and OR a
k-way union. `phrase_search` finds docs where the query's terms occur at
consecutive token positions.

Score is always 0.0 tonight (BM25 lands later); snippet is a naive first-160
chars of the doc text. Empty/absent-term/punctuation-only queries resolve to
`[]` without raising, per Spec §4.5 robustness.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from onrecord.types import SearchResult

if TYPE_CHECKING:
    from onrecord.index.inverted import InvertedIndex

SNIPPET_LEN = 160


def _resolve_analyzer(analyzer: Callable[[str], list[str]] | None) -> Callable[[str], list[str]]:
    if analyzer is not None:
        return analyzer
    from onrecord.analysis.analyzer import analyze

    return analyze


def _snippet(text: str) -> str:
    return text[:SNIPPET_LEN]


def _to_results(index: InvertedIndex, internal_ids: list[int]) -> list[SearchResult]:
    results = []
    for internal_id in internal_ids:
        doc = index.get_doc(internal_id)
        results.append(SearchResult(doc_id=doc.id, score=0.0, snippet=_snippet(doc.text)))
    return results


def _intersect_sorted(lists: list[list[int]]) -> list[int]:
    """K-way intersection of already-sorted lists of internal doc ids."""
    if not lists:
        return []
    result = list(lists[0])
    for other in lists[1:]:
        if not result:
            return []
        other_set = set(other)
        result = [doc_id for doc_id in result if doc_id in other_set]
    return result


def _union_sorted(lists: list[list[int]]) -> list[int]:
    """K-way union (deduplicated, sorted) of already-sorted lists of ids."""
    seen: set[int] = set()
    for lst in lists:
        seen.update(lst)
    return sorted(seen)


def boolean_search(
    index: InvertedIndex,
    query: str,
    op: str,
    analyzer: Callable[[str], list[str]] | None = None,
) -> list[SearchResult]:
    """Run a boolean AND/OR query (`op` in {"AND", "OR"}) against `index`."""
    analyze = _resolve_analyzer(analyzer)
    terms = analyze(query)
    if not terms:
        return []

    postings_lists = [list(index.postings(term).doc_ids) for term in terms]

    if op == "AND":
        matched_ids = _intersect_sorted(postings_lists)
    elif op == "OR":
        matched_ids = _union_sorted(postings_lists)
    else:
        raise ValueError(f"unknown boolean op: {op!r}")

    return _to_results(index, matched_ids)


def phrase_search(
    index: InvertedIndex,
    phrase: str,
    analyzer: Callable[[str], list[str]] | None = None,
) -> list[SearchResult]:
    """Run an exact phrase query against `index` via position adjacency."""
    analyze = _resolve_analyzer(analyzer)
    terms = analyze(phrase)
    if not terms:
        return []

    postings = [index.postings(term) for term in terms]

    # Candidate docs must contain ALL terms (AND); verify adjacency per doc.
    doc_id_sets = [set(p.doc_ids) for p in postings]
    if any(not s for s in doc_id_sets):
        return []
    candidate_doc_ids = set.intersection(*doc_id_sets)
    if not candidate_doc_ids:
        return []

    # Map term -> {doc_id: positions} for quick per-doc lookup.
    term_positions: list[dict[int, list[int]]] = []
    for p in postings:
        term_positions.append(dict(zip(p.doc_ids, p.positions)))

    matched_ids = []
    for doc_id in sorted(candidate_doc_ids):
        if _has_consecutive_run(term_positions, doc_id):
            matched_ids.append(doc_id)

    return _to_results(index, matched_ids)


def _has_consecutive_run(term_positions: list[dict[int, list[int]]], doc_id: int) -> bool:
    """True if there's a starting position for term_positions[0] in `doc_id`
    such that each subsequent term occurs at exactly one position higher,
    for the full length of the phrase (general N-word adjacency chase)."""
    first_positions = term_positions[0][doc_id]
    for start in first_positions:
        if _chase_from(term_positions, doc_id, start):
            return True
    return False


def _chase_from(term_positions: list[dict[int, list[int]]], doc_id: int, start: int) -> bool:
    expected = start
    for positions_by_doc in term_positions[1:]:
        expected += 1
        if expected not in positions_by_doc[doc_id]:
            return False
    return True

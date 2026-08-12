"""IR metrics — precision@k, recall@k, MRR, NDCG (T-005).

Conventions pinned by `tests/unit/test_metrics.py`'s module docstring (frozen
contract): binary relevance for precision/recall/MRR is `grade >= 1`; NDCG
uses graded relevance with linear gain and a `log2(rank + 1)` discount;
`k <= 0` and an empty `ranked` list never raise, they return `0.0`.
"""

from __future__ import annotations

import math


def precision_at_k(ranked: list[str], relevant: dict[str, int], k: int) -> float:
    """Precision@k: fraction of the top-k ranked doc ids that are relevant.

    Denominator is always `k` (not `min(k, len(ranked))`) — positions past
    the end of `ranked` are non-relevant padding, per AC-4.
    """
    if k <= 0:
        return 0.0
    hits = sum(1 for doc_id in ranked[:k] if relevant.get(doc_id, 0) >= 1)
    return hits / k


def recall_at_k(ranked: list[str], relevant: dict[str, int], k: int) -> float:
    """Recall@k: fraction of all relevant docs found in the top-k.

    Returns `0.0` (rather than raising) when `k <= 0` or when `relevant` has
    no doc with grade >= 1 (nothing to recall).
    """
    total_relevant = sum(1 for grade in relevant.values() if grade >= 1)
    if total_relevant == 0 or k <= 0:
        return 0.0
    hits = sum(1 for doc_id in ranked[:k] if relevant.get(doc_id, 0) >= 1)
    return hits / total_relevant


def mrr(ranked: list[str], relevant: dict[str, int]) -> float:
    """Reciprocal rank of the first relevant (grade >= 1) doc in `ranked`.

    `0.0` if no relevant doc appears anywhere in `ranked`.
    """
    for rank, doc_id in enumerate(ranked, start=1):
        if relevant.get(doc_id, 0) >= 1:
            return 1.0 / rank
    return 0.0


def _dcg(grades: list[int], k: int) -> float:
    """Sum of `grade_i / log2(i + 1)` for i in 1..min(k, len(grades))."""
    return sum(grade / math.log2(i + 1) for i, grade in enumerate(grades[:k], start=1))


def ndcg_at_k(ranked: list[str], relevant: dict[str, int], k: int) -> float:
    """Normalized DCG@k using 0/1/2 relevance grades (linear gain).

    `IDCG@k` is the DCG of `relevant`'s grades sorted descending (the ideal
    ordering), truncated at k. `NDCG@k = DCG@k / IDCG@k`, defined as `0.0`
    when `IDCG@k == 0` (no positive-grade doc in `relevant`), which also
    covers `k <= 0` (IDCG@0 is the empty-sum 0.0).
    """
    actual_grades = [relevant.get(doc_id, 0) for doc_id in ranked]
    ideal_grades = sorted(relevant.values(), reverse=True)

    idcg = _dcg(ideal_grades, k)
    if idcg == 0.0:
        return 0.0
    dcg = _dcg(actual_grades, k)
    return dcg / idcg

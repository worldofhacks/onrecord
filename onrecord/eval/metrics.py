"""IR metrics stubs — implemented by T-005 (red until ranking exists)."""

from __future__ import annotations


def precision_at_k(ranked: list[str], relevant: dict[str, int], k: int) -> float:
    """Precision@k: fraction of the top-k ranked doc ids that are relevant."""
    raise NotImplementedError


def recall_at_k(ranked: list[str], relevant: dict[str, int], k: int) -> float:
    """Recall@k: fraction of all relevant docs found in the top-k."""
    raise NotImplementedError


def mrr(ranked: list[str], relevant: dict[str, int]) -> float:
    """Mean reciprocal rank of the first relevant doc in `ranked`."""
    raise NotImplementedError


def ndcg_at_k(ranked: list[str], relevant: dict[str, int], k: int) -> float:
    """Normalized discounted cumulative gain@k, using 0/1/2 relevance grades."""
    raise NotImplementedError

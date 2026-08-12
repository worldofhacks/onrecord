"""BM25 scoring — probabilistic IDF + tf-saturation/length-norm (T-011).

Implements the ticket's frozen formula (`tickets/T-011.md`, pinned verbatim
in `tests/unit/test_bm25.py`'s module docstring):

    idf = ln(1 + (N - df + 0.5) / (df + 0.5))
    saturation = tf * (k1 + 1) / (tf + k1 * (1 - b + b * doc_len / avg_doc_len))
    bm25_score = idf * saturation

This is the probabilistic-variant IDF (Robertson/Sparck-Jones), not classic
IDF `ln(N/df)`: algebraically `1 + (N-df+0.5)/(df+0.5) == (N+1)/(df+0.5)`,
and since `N+1 > N+0.5 >= df+0.5` for any `0 <= df <= N`, that ratio is
always `> 1`, so the log is always strictly positive -- unlike classic IDF,
which goes negative once a term appears in more than half the corpus.

`k1` controls tf-saturation strength (higher k1 -> more reward for repeated
occurrences before diminishing returns kick in); `b` controls length
normalization (`b=0` disables it entirely, `b=1` fully normalizes by the
doc-length-to-average-length ratio). Both are exposed as keyword parameters
throughout the ranking layer, per the ticket's Definition of Done.
"""

from __future__ import annotations

import math


def bm25_score(
    tf: int,
    df: int,
    N: int,
    doc_len: float,
    avg_doc_len: float,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    """Okapi BM25 score for a single term against a single document.

    `tf` -- term frequency of the term in the document.
    `df` -- document frequency of the term across the corpus.
    `N` -- total document count in the corpus.
    `doc_len` -- token length of this document.
    `avg_doc_len` -- mean token length across the corpus.
    `k1`/`b` -- BM25 saturation/length-normalization parameters.
    """
    idf = math.log(1 + (N - df + 0.5) / (df + 0.5))
    denom = tf + k1 * (1 - b + b * (doc_len / avg_doc_len))
    saturation = tf * (k1 + 1) / denom
    return idf * saturation

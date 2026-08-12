"""Reference-BM25 differential -- our BM25 vs `rank_bm25.BM25Okapi` on the
IDENTICAL analyzed token stream (T-012, the assignment's core ranking-math
oracle). Isolates ranking math from tokenization: both systems are built
from the exact same per-doc token lists (the real `onrecord.analysis.
analyzer.analyze` by default).

--------------------------------------------------------------------------
IDF reconciliation -- what "agreement" means here (full derivation and
fixture-construction rationale lives in `tests/differential/
test_reference_bm25.py`'s module docstring; this is the load-bearing
summary the ticket's DoD requires in the implementation itself)
--------------------------------------------------------------------------

Ours (`onrecord.rank.bm25.bm25_score`, T-011, frozen):

    idf_ours(df) = ln(1 + (N - df + 0.5) / (df + 0.5))   -- always > 0.

`rank_bm25.BM25Okapi` (`BM25Okapi._calc_idf`/`get_scores`, read from the
installed package source):

    idf_theirs_raw(df) = ln((N - df + 0.5) / (df + 0.5))  -- classic
    probabilistic IDF, goes negative once df > N/2, at which point
    `BM25Okapi` floors the TERM's idf to `epsilon * average_idf`, a
    corpus-wide scalar unrelated to that term's own df. There is no analog
    to that flooring in our always-positive formula, so it is never
    reconciled -- only queries whose df stays comfortably below N/2 are
    ever assigned a `score_transform` below.

The saturation/length-norm factor `tf*(k1+1)/(tf+k1*(1-b+b*doc_len/
avg_doc_len))` is byte-for-byte identical between the two libraries given
matched tf/doc_len/avg_doc_len/k1/b. So the two total scores are
`idf_ours(df) * saturation` vs `idf_theirs_raw(df) * saturation` -- same
saturation, different idf -- and no universal exact-score-equality or
fixed-tolerance bound holds across arbitrary queries/corpora in general.

**What DOES hold, provably:** for any query whose analyzed terms all share
one document frequency `df` (every single-term query; any multi-term query
drawn from a single df-cohort), with that `df < N/2` (so
`idf_theirs_raw(df) > 0`, no epsilon floor): `idf_ours(df)` and
`idf_theirs_raw(df)` are each a single scalar, constant across every term
and candidate doc in that query, so `score_ours(doc) == c *
score_theirs(doc)` EXACTLY (to float precision) for every candidate, where
`c = idf_ours(df) / idf_theirs_raw(df)`. A positive-scalar rescale never
reorders, so top-k order agrees exactly too. This is the domain
`score_transform`/`max_rel_score_diff` below are computed in; tolerance is
`rel=1e-9` on the transform constant itself and `< 1e-6` max relative score
deviation after applying it (float noise only, empirically ~1e-16).

**What does NOT hold:** cross-df multi-term queries (terms with differing
document frequencies) -- `idf_ours(df)/idf_theirs_raw(df)` grows with `df`,
so the two systems can weigh a query's terms differently enough to flip
ranking even with every individual df < N/2. `score_transform`/
`max_rel_score_diff` are `None` for such queries (and for any query whose
shared df is not `< N/2`) rather than a bogus, misleading tolerance --
this divergence is mathematically real, never "fixed" or special-cased.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from rank_bm25 import BM25Okapi

from onrecord.index.inverted import InvertedIndex
from onrecord.rank.bm25 import bm25_score
from onrecord.types import Doc

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True)
class QueryDiff:
    """One query's our-vs-reference comparison."""

    query: str
    terms: list[str]
    our_ranking: list[str]
    reference_ranking: list[str]
    order_agrees: bool
    score_transform: float | None
    max_rel_score_diff: float | None


@dataclass(frozen=True)
class DifferentialReport:
    """Aggregate result of `run_differential` over a set of queries."""

    query_diffs: list[QueryDiff]
    all_orders_agree: bool


def _resolve_analyzer(
    analyzer: Callable[[str], list[str]] | None,
) -> Callable[[str], list[str]]:
    if analyzer is not None:
        return analyzer
    from onrecord.analysis.analyzer import analyze

    return analyze


def _tf_in_doc(index: InvertedIndex, term: str, internal_id: int) -> int:
    postings = index.postings(term)
    doc_ids = list(postings.doc_ids)
    if internal_id in doc_ids:
        return postings.tfs[doc_ids.index(internal_id)]
    return 0


def _our_candidate_scores(
    index: InvertedIndex, terms: list[str], k1: float, b: float
) -> dict[str, float]:
    """OR-semantics BM25 scores keyed by EXTERNAL doc id -- the union of
    docs matching >= 1 query term (mirrors `onrecord.search.ranked.
    ranked_search`'s own candidate-set semantics)."""
    N = index.doc_count()
    avg_len = index.avg_doc_length()
    candidate_ids: set[int] = set()
    for term in terms:
        candidate_ids.update(index.postings(term).doc_ids)

    scores: dict[str, float] = {}
    for internal_id in candidate_ids:
        doc_len = index.doc_length(internal_id)
        total = 0.0
        for term in terms:
            df = index.df(term)
            tf = _tf_in_doc(index, term, internal_id)
            total += bm25_score(tf, df, N, doc_len, avg_len, k1=k1, b=b)
        scores[index.get_doc(internal_id).id] = total
    return scores


def _score_transform_and_diff(
    terms: list[str],
    index: InvertedIndex,
    our_scores: dict[str, float],
    ref_scores: dict[str, float],
) -> tuple[float | None, float | None]:
    """`(c, max_rel_score_diff)` per the module docstring's IDF
    reconciliation, or `(None, None)` outside the provable same-df,
    df < N/2 agreement domain."""
    dfs = {index.df(t) for t in terms}
    if len(dfs) != 1:
        return None, None
    (df,) = dfs
    N = index.doc_count()
    idf_theirs_raw = math.log((N - df + 0.5) / (df + 0.5))
    if idf_theirs_raw <= 0:
        return None, None
    idf_ours = math.log(1 + (N - df + 0.5) / (df + 0.5))
    c = idf_ours / idf_theirs_raw

    max_rel = 0.0
    for doc_id, our in our_scores.items():
        transformed = c * ref_scores[doc_id]
        denom = abs(our) if our != 0 else 1.0
        rel = abs(our - transformed) / denom
        if rel > max_rel:
            max_rel = rel
    return c, max_rel


def run_differential(
    index_docs: list[Doc],
    queries: list[str],
    k1: float = 1.5,
    b: float = 0.75,
    k: int = 10,
    analyzer: Callable[[str], list[str]] | None = None,
) -> DifferentialReport:
    """Build our index AND `rank_bm25.BM25Okapi` from the identical
    per-doc token lists, then compare per-query top-k order + scores.

    `reference_ranking` is restricted to our own OR-semantics candidate set
    (docs matching >= 1 query term) -- `BM25Okapi.get_scores` scores every
    doc in the corpus, including 0-score docs our candidate set never
    considers, which would otherwise pad the reference ranking and
    spuriously mismatch a low-df query.
    """
    analyze = _resolve_analyzer(analyzer)
    index = InvertedIndex.build(index_docs, analyzer=analyze)

    token_lists = [analyze(d.text) for d in index_docs]
    reference = BM25Okapi(token_lists, k1=k1, b=b)

    query_diffs: list[QueryDiff] = []
    for query in queries:
        terms = analyze(query)

        our_scores = _our_candidate_scores(index, terms, k1, b)
        candidate_ids = set(our_scores)

        raw_ref_scores = reference.get_scores(terms)
        ref_scores_all = {
            index_docs[i].id: float(raw_ref_scores[i]) for i in range(len(index_docs))
        }
        ref_scores = {doc_id: ref_scores_all[doc_id] for doc_id in candidate_ids}

        our_ranking = sorted(candidate_ids, key=lambda d: (-our_scores[d], d))[:k]
        reference_ranking = sorted(candidate_ids, key=lambda d: (-ref_scores[d], d))[:k]

        score_transform, max_rel_score_diff = _score_transform_and_diff(
            terms, index, our_scores, ref_scores
        )

        query_diffs.append(
            QueryDiff(
                query=query,
                terms=terms,
                our_ranking=our_ranking,
                reference_ranking=reference_ranking,
                order_agrees=our_ranking == reference_ranking,
                score_transform=score_transform,
                max_rel_score_diff=max_rel_score_diff,
            )
        )

    return DifferentialReport(
        query_diffs=query_diffs,
        all_orders_agree=all(qd.order_agrees for qd in query_diffs),
    )


# --------------------------------------------------------------------------
# CLI -- `python -m onrecord.eval.differential`, same JSONL/corpus-loading
# convention as `onrecord.eval.pooling._load_corpus`.
# --------------------------------------------------------------------------


def _load_corpus(path: str | Path) -> list[Doc]:
    docs: list[Doc] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped:
                docs.append(Doc(**json.loads(stripped)))
    return docs


def _load_queries(path: str | Path) -> list[str]:
    with Path(path).open("r", encoding="utf-8") as fh:
        return [line.strip() for line in fh if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m onrecord.eval.differential",
        description=(
            "Reference-BM25 differential: our BM25 vs rank_bm25.BM25Okapi "
            "on the identical analyzed token stream."
        ),
    )
    parser.add_argument("--corpus", required=True, help="UTF-8 JSONL corpus, one Doc per line")
    parser.add_argument("--queries", required=True, help="UTF-8 text file, one query per line")
    parser.add_argument("--k1", type=float, default=1.5)
    parser.add_argument("--b", type=float, default=0.75)
    parser.add_argument("--k", type=int, default=10)
    args = parser.parse_args(argv)

    docs = _load_corpus(args.corpus)
    queries = _load_queries(args.queries)

    report = run_differential(docs, queries, k1=args.k1, b=args.b, k=args.k)

    for qd in report.query_diffs:
        status = "OK" if qd.order_agrees else "MISMATCH"
        print(f"{status}  {qd.query}")
        if not qd.order_agrees:
            print(f"  ours:      {qd.our_ranking}")
            print(f"  reference: {qd.reference_ranking}")

    return 0 if report.all_orders_agree else 1


if __name__ == "__main__":
    sys.exit(main())

"""Candidate pooling for judgment-set construction (T-009).

Pools judgment candidates for a query from three independent sources --
keyword/substring grep, BM25 (the reference oracle lib), and seeded random
sampling ("manual browsing" spice) -- dedupes by doc id, and shuffles with a
seeded RNG so no source attribution leaks into what a human judge sees.

`rank_bm25` is imported ONLY in this module -- never by `onrecord.rank` or
`onrecord.search` (ticket T-009 Definition of Done).

See `tests/unit/test_judgments.py`'s module docstring for the exact, frozen
algorithm this implements.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from rank_bm25 import BM25Okapi

from onrecord.types import Doc


def _load_corpus(corpus_path: str | Path) -> list[Doc]:
    """Load a UTF-8 JSONL corpus, preserving file line order; blanks skipped."""
    docs: list[Doc] = []
    with Path(corpus_path).open("r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            docs.append(Doc(**json.loads(stripped)))
    return docs


def pool_candidates(
    query: str,
    corpus_path: str | Path,
    k_per_source: int,
    seed: int,
) -> list[Doc]:
    """Pool judgment candidates for `query` from grep + bm25 + random sources.

    Sources (independent, then merged):
      (a) grep: docs whose `.text` contains `query` case-insensitively as a
          substring, in corpus file order, capped at `k_per_source`.
      (b) bm25: `rank_bm25.BM25Okapi` over whitespace-lowercased tokens,
          top `k_per_source` by score descending (ties by ascending index).
      (c) random: `min(3, len(corpus))` docs via `rng.sample`.

    A single `random.Random(seed)` is used first for the random source's
    `.sample(...)`, then -- after concatenating grep ++ bm25 ++ random and
    deduping by `.id` (first occurrence wins) -- to `.shuffle(...)` the
    deduped list in place, so a fixed seed is fully reproducible.
    """
    docs = _load_corpus(corpus_path)
    rng = random.Random(seed)

    query_lower = query.lower()
    grep_docs = [d for d in docs if query_lower in d.text.lower()][:k_per_source]

    tokenized_corpus = [d.text.lower().split() for d in docs]
    bm25 = BM25Okapi(tokenized_corpus)
    scores = bm25.get_scores(query_lower.split())
    order = sorted(range(len(docs)), key=lambda i: (-scores[i], i))
    bm25_docs = [docs[i] for i in order[:k_per_source]]

    random_docs = rng.sample(docs, min(3, len(docs)))

    seen: set[str] = set()
    combined: list[Doc] = []
    for d in grep_docs + bm25_docs + random_docs:
        if d.id not in seen:
            seen.add(d.id)
            combined.append(d)

    rng.shuffle(combined)
    return combined

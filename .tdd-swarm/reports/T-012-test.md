# T-012 Test Agent Report — Reference-BM25 differential (the oracle)

**Status:** DONE (frozen failing tests written; confirmed RED against the current
worktree, which has no `onrecord/eval/differential.py`; confirmed GREEN — all
31 tests — against a throwaway reference implementation built and run inside
the worktree, then deleted before commit; `git status` shows the implementation
file gone and only `tests/differential/**` added — zero diff outside the Test
Agent's file scope).

**Test file:** `tests/differential/test_reference_bm25.py` (+ `__init__.py`).
**Fixtures (committed):**
- `tests/differential/fixtures/corpus.jsonl` — 50-doc synthetic corpus (AC-1/AC-2).
- `tests/differential/fixtures/queries.txt` — the 10 fixture queries.
- `tests/differential/fixtures/divergence_corpus.jsonl` + `divergence_queries.txt`
  — 5-doc corpus deliberately engineered to disagree with the reference (AC-4's
  exit-1 path).

**Run command:**
```
uv run pytest tests/differential/ -v
```

## The homework (IDF reconciliation) — required before pinning tolerances

Read the installed `rank_bm25` source (`BM25Okapi._calc_idf`/`get_scores`).
Confirmed the two IDF formulas genuinely differ:

- Ours: `idf_ours(df) = ln(1 + (N-df+0.5)/(df+0.5))` — always strictly positive.
- `rank_bm25`: `idf_theirs_raw(df) = ln((N-df+0.5)/(df+0.5))` — classic
  probabilistic IDF, goes negative once `df > N/2`, at which point `BM25Okapi`
  floors it to `epsilon * average_idf` (a corpus-wide scalar, unrelated to
  that term's own `df`). No analog exists in our always-positive formula, so
  that regime is excluded from the comparison entirely (every fixture df stays
  well under `N/2`).

The saturation/length-norm factor **is** byte-for-byte identical between the
two libraries (verified against `rank_bm25`'s source) given matched
tf/doc_len/avg_doc_len/k1/b — so the two total scores are
`idf_ours(df) * saturation` vs `idf_theirs_raw(df) * saturation`: same
saturation, different idf. No universal score-equality holds.

**What I proved and pinned:** for any query whose analyzed terms all share
one document frequency (trivially every single-term query, and any
multi-term query drawn from one df-cohort), with that df `< N/2`, our score
is *exactly* `c = idf_ours(df)/idf_theirs_raw(df)` times the reference score
for every candidate — a single positive scalar shared across the whole
query. That proportionality guarantees (a) exact top-k order agreement and
(b) exact score agreement after the documented `c`-transform. Verified with a
throwaway implementation: max relative deviation after the transform was
~1e-16 (float noise) across all 10 fixture queries.

**What I explicitly did NOT pin as passing:** cross-df multi-term queries
(terms with differing document frequencies). `idf_ours/idf_theirs_raw` is not
constant across `df` — it grows with `df`, so the "+1" inflates common
(high-df) terms more than rare (low-df) ones, which can flip which candidate
ranks higher even with every individual df `< N/2`. This isn't hypothetical —
a hand-constructed 5-doc corpus (`divergence_corpus.jsonl`, query
`"rare common"`, df=1 vs df=2) produces a genuinely different top-1 doc
between the two systems, verified independently of the implementation. This
fixture drives AC-4's exit-1 path; `test_ac2_cross_df_query_reports_no_transform_not_a_false_equivalence`
pins that `score_transform`/`max_rel_score_diff` must be `None` for such a
query rather than a bogus tolerance.

## AC-1/AC-2 fixture design

50-doc corpus, 12 "signal" terms in four df-cohorts (df ∈ {3, 7, 12, 18}, all
`< N/2=25`), each term assigned to exactly that many docs at generation time
(asserted, not just intended). 10 queries: 6 single-term (spanning all four
cohorts) + 4 same-df multi-term (2–3 terms each, one term drawn per cohort).
Tokenized with the **real** `onrecord.analysis.analyzer.analyze` for both
systems (the entire point of a differential test — isolates ranking math from
tokenization, per the ticket's own Context).

## AC-3 — property vs OUR implementation, not the reference

Pinned as: "otherwise-identical" = **same total doc length** — `extra` filler
tokens are swapped for `extra` more occurrences of the query term (never
appended). This distinction matters and was discovered empirically before
freezing: an *append-only* (length-growing) formulation legitimately breaks
for multi-term queries once a companion term's length-normalization penalty
(`b>0`) outweighs the target term's own tf-saturation gain — real BM25
behavior, not a bug, and consistent with T-011's own tf-monotonicity property
(which also holds `doc_len` fixed). The fixed-length formulation was verified
over 1000+ hypothesis examples against the real `InvertedIndex` +
`ranked_search` stack (both single- and two-term OR queries) before freezing;
the frozen suite runs it at `max_examples=200`.

## AC-4 — `python -m onrecord.eval.differential` contract

`--corpus`/`--queries` are required args (production code never bakes a path
into `tests/`); `--k1`/`--b`/`--k` optional. Exit 0 on the main fixture, exit
1 with a per-query diff table on the divergence fixture (both verified via
subprocess against the throwaway implementation), exit 2 on missing required
args (argparse's own usage-error path). `main(argv)` also tested directly.

## Frozen contract (`onrecord/eval/differential.py`, not yet implemented)

```python
@dataclass(frozen=True)
class QueryDiff:
    query: str
    terms: list[str]
    our_ranking: list[str]
    reference_ranking: list[str]  # restricted to our OR-semantics candidate set
    order_agrees: bool
    score_transform: float | None       # None unless every term shares one df
    max_rel_score_diff: float | None

@dataclass(frozen=True)
class DifferentialReport:
    query_diffs: list[QueryDiff]
    all_orders_agree: bool

def run_differential(
    index_docs: list[Doc], queries: list[str],
    k1: float = 1.5, b: float = 0.75, k: int = 10,
    analyzer: Callable[[str], list[str]] | None = None,
) -> DifferentialReport: ...

def main(argv: list[str] | None = None) -> int: ...  # --corpus/--queries required
```

See the test file's module docstring for the full reconciliation write-up,
fixture construction details, and per-AC rationale.

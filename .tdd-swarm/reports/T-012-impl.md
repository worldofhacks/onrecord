# T-012 Implementation Agent Report — Reference-BM25 differential (the oracle)

**Status:** DONE — all 31 tests in `tests/differential/` pass; all local gates green.

**File scope:** `onrecord/eval/differential.py` (new file; `tests/`/fixtures untouched — `git status` shows exactly one new file).

## What was built

`onrecord/eval/differential.py` implements the frozen contract pinned by
`tests/differential/test_reference_bm25.py`'s module docstring and
`.tdd-swarm/reports/T-012-test.md`:

- `QueryDiff` / `DifferentialReport` frozen dataclasses, exact field set.
- `run_differential(index_docs, queries, k1=1.5, b=0.75, k=10, analyzer=None)`:
  - Builds `InvertedIndex` (T-003) AND `rank_bm25.BM25Okapi` from the
    IDENTICAL per-doc token lists (`analyzer` resolved once, defaulting to
    the real `onrecord.analysis.analyzer.analyze`, T-002).
  - Per query: OR-semantics candidate scoring via `onrecord.rank.bm25.
    bm25_score` (T-011) summed per term (mirrors `ranked_search`'s own
    candidate-set/tie-break semantics — ascending external `Doc.id`);
    reference scores pulled from `BM25Okapi.get_scores(terms)` and
    RESTRICTED to that same OR-semantics candidate set (never the full
    corpus `BM25Okapi` scores, which would pad in 0-score irrelevant docs
    and spuriously mismatch low-df queries).
  - `score_transform`/`max_rel_score_diff` computed only when every
    analyzed term in the query shares one document frequency AND that df's
    `idf_theirs_raw = ln((N-df+0.5)/(df+0.5))` is `> 0` (i.e. df < N/2, no
    epsilon-floor regime) — the provable-agreement domain derived in the
    module docstring; `None`/`None` otherwise (cross-df queries), never a
    misleading tolerance.
- `main(argv)` / CLI (`python -m onrecord.eval.differential`): argparse,
  `--corpus`/`--queries` required (JSONL/text, same loading convention as
  `onrecord.eval.pooling._load_corpus`), `--k1`/`--b`/`--k` optional.
  Prints one `OK`/`MISMATCH <query>` line per query, plus both rankings on
  any mismatch (the diff table). Returns/exits 0 iff
  `report.all_orders_agree`, else 1; argparse's own usage-error path
  (exit 2) on missing required args.

Manually verified against both fixtures: main fixture → exit 0, all 10
queries `OK`; divergence fixture (`"rare common"`, df=1 vs df=2) → exit 1
with a genuine per-query diff table (`ours: ['div_common', 'div_rare',
'div_common_pad']` vs `reference: ['div_rare', 'div_common',
'div_common_pad']`); missing `--corpus`/`--queries` → exit 2 with argparse
usage message.

## IDF reconciliation — documented in the module docstring

Summarized (full derivation lives in the test file's docstring, this repo's
source of truth): ours is always-positive probabilistic IDF with a `+1`;
`rank_bm25`'s raw IDF is classic probabilistic (no `+1`), goes negative past
`df > N/2` and gets epsilon-floored to a corpus-wide average — no analog on
our side, so that regime is never reconciled. Where every query term shares
one `df < N/2`, both idfs collapse to a single shared scalar per query, so
our score is exactly `c = idf_ours(df)/idf_theirs_raw(df)` times the
reference score for every candidate — proven, not just observed (confirmed
empirically too: `max_rel_score_diff` is float noise, ~1e-16, well under the
pinned `1e-6` gate, across all 10 fixture queries).

## Verification

```
uv run pytest tests/differential/ -v   → 31 passed
.tdd-swarm/run-local-gates.sh . tickets/T-012.md
  == format ==  48 files already formatted
  == lint ==    All checks passed!
  == unit ==    292 passed, 2 warnings (pre-existing, unrelated to T-012)
  == spec-lint == spec-lint OK: all ACs covered for T-012
  ALL LOCAL GATES GREEN
```

No test or fixture files were touched. No dispute raised — the frozen tests
matched the ticket's ACs and the Test Agent's handoff report exactly.

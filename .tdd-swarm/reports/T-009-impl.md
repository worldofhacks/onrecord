# T-009 Implementation Agent Report — Judgment-set tooling

**Status:** DONE — all 14 frozen tests in `tests/unit/test_judgments.py` pass; all local gates green.

**Files created (file scope, as ticketed):**
- `onrecord/eval/pooling.py`
- `onrecord/eval/judgments.py`

No other files touched (`onrecord/eval/metrics.py`, `onrecord/eval/run.py` untouched — parallel-ticket scope).

## Implementation summary

`pooling.py`: `pool_candidates(query, corpus_path, k_per_source, seed) -> list[Doc]`.
Loads the JSONL corpus preserving file order, then pools from three
independent sources exactly per the frozen contract in
`tests/unit/test_judgments.py`'s module docstring:
- (a) grep — case-insensitive substring match on `.text`, corpus order,
  capped at `k_per_source`.
- (b) bm25 — `rank_bm25.BM25Okapi` over `.lower().split()` tokens, top
  `k_per_source` by score desc / index asc tiebreak.
- (c) random — `min(3, len(corpus))` via `rng.sample`.

A single `random.Random(seed)` is created once, used first for the random
source's `.sample()`, then — after concatenating grep++bm25++random and
deduping by `.id` (first occurrence wins) — for `.shuffle()` on the deduped
list, matching the pinned ordering so a fixed seed is reproducible.
`rank_bm25` is imported only here (grepped repo-wide to confirm — see
Verification).

`judgments.py`: `main(argv) -> int` (argparse CLI) plus an internal
`run_judging_session(...)` helper implementing the session sequence:
1. `input("Relevance criterion: ")` captured before anything else is shown
   (AC-4).
2. `from onrecord.eval.pooling import pool_candidates` (module-level name,
   monkeypatchable) called to get the ordered candidate list; existing
   `--out` rows loaded to build the judged-pairs set; already-judged
   `(query_id, doc_id)` candidates dropped before display (AC-3).
3. Each remaining candidate's `.text` printed with no source/score/rank
   markers, graded via `input("Grade (0/1/2/s=skip): ")`; `0/1/2` appends a
   JSONL row `{query_id, query, criterion, doc_id, grade:int}` in append
   mode (parent dirs created if missing); `s`/`S` skips with no row written.
4. Returns 0.

`if __name__ == "__main__": sys.exit(main())` makes
`python -m onrecord.eval.judgments` work directly.

## Verification performed

1. `uv run pytest tests/unit/test_judgments.py -v` → **14/14 passed**.
2. `.tdd-swarm/run-local-gates.sh . tickets/T-009.md`:
   - format: clean (25 files already formatted)
   - lint: `All checks passed!`
   - unit: `28 passed` (14 pre-existing T-001 + 14 new, no regressions)
   - spec-lint: `spec-lint OK: all ACs covered for T-009`
   - **ALL LOCAL GATES GREEN**
3. `grep -rn "rank_bm25" onrecord/` → only hits in `onrecord/eval/pooling.py`
   (import + docstring mentions); confirms ticket DoD ("rank_bm25 used ONLY
   here — never imported by onrecord.rank or onrecord.search").
4. Manual end-to-end smoke test: ran
   `python -m onrecord.eval.judgments --query ... --query-id smoke1 --corpus ... --out ...`
   against a real 3-doc JSONL corpus with scripted stdin (criterion, grade
   `2`, skip `s`, grade `1`) — criterion prompt appeared first, candidate
   text appeared with no source/score markers, output JSONL had exactly the
   2 non-skipped rows with correct shape and int grades.
5. `git status --short` confirms only the two owned files are new/staged —
   no edits to `tests/`, `metrics.py`, or `run.py`.

## Notes / disputes

None. The frozen contract in the test module docstring was unambiguous and
implementable as specified; no `BLOCKED(TEST_DISPUTE)` needed.

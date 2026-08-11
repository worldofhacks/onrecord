# T-009 Implementation Agent Report — Judgment-set tooling

**Status:** DONE — all 16 frozen tests in `tests/unit/test_judgments.py` pass; all local gates green.

**Files created (file scope, as ticketed):**
- `onrecord/eval/pooling.py`
- `onrecord/eval/judgments.py`

No other files touched (`onrecord/eval/metrics.py`, `onrecord/eval/run.py` untouched — parallel-ticket scope).

## Update — criterion-drift guard on resume (Reviewer finding #1)

Review (`.tdd-swarm/reports/T-009-review.md`) flagged an Important finding:
resuming a `query_id` under a materially different criterion silently reused
stale grades and discarded the freshly typed criterion with no warning. The
Test Agent extended the frozen suite at `d720c97` (2 new tests + a documented
adjustment to `test_cli_resumability_does_not_represent_already_judged_doc`'s
fixture, whose `existing_row["criterion"]` now matches `_CLI_CRITERION` so it
cleanly tests "same-criterion resume" without overlapping the new
drift-guard tests). Fixed in `onrecord/eval/judgments.py`:

- Added `--amend-criterion` (argparse `store_true`, default `False`).
- Added `_find_stored_criterion(out_path, query_id)`: returns the criterion
  of the first file-order row matching `query_id`, or `None`.
- In `run_judging_session`, immediately after capturing `criterion` and
  before calling `pool_candidates` or touching any candidate: look up the
  stored criterion for `query_id`. If one exists, differs (plain string
  inequality) from the freshly typed criterion, and `--amend-criterion` was
  not passed → print a stderr message containing `"CRITERION MISMATCH"`,
  the stored criterion verbatim, the new criterion verbatim, and a mention
  of `--amend-criterion`; write nothing to `out_path`; display no candidate;
  return `1`. If `--amend-criterion` was passed, proceed normally — every
  row newly written this session already carries `criterion` (the freshly
  typed one), so no further change was needed there; already-judged rows
  are untouched (amending is not retroactive). If no stored criterion
  exists, or it's identical to the new one, proceed exactly as before.

## Implementation summary

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

1. `uv run pytest tests/unit/test_judgments.py -v` → **16/16 passed**
   (original 14 + `test_cli_refuses_resume_when_criterion_differs_and_writes_no_rows`
   + `test_cli_amend_criterion_flag_allows_resume_and_new_rows_carry_new_criterion`).
2. `.tdd-swarm/run-local-gates.sh . tickets/T-009.md`:
   - format: clean (25 files, after `ruff format .` auto-fixed one
     line-length wrap in the new guard clause)
   - lint: `All checks passed!`
   - unit: `30 passed` (14 pre-existing T-001 + 16 in this file, no regressions)
   - spec-lint: `spec-lint OK: all ACs covered for T-009`
   - **ALL LOCAL GATES GREEN**
3. `uv run pytest -q` (full repo suite) → `30 passed`.
4. `grep -rn "rank_bm25" onrecord/` → only hits in `onrecord/eval/pooling.py`
   (import + docstring mentions); confirms ticket DoD ("rank_bm25 used ONLY
   here — never imported by onrecord.rank or onrecord.search"); the drift-guard
   fix touched only `judgments.py`, so this is unchanged.
5. Manual end-to-end smoke test (original implementation, still valid): ran
   `python -m onrecord.eval.judgments --query ... --query-id smoke1 --corpus ... --out ...`
   against a real 3-doc JSONL corpus with scripted stdin (criterion, grade
   `2`, skip `s`, grade `1`) — criterion prompt appeared first, candidate
   text appeared with no source/score markers, output JSONL had exactly the
   2 non-skipped rows with correct shape and int grades.
6. `git status --short` confirms only `onrecord/eval/judgments.py` changed
   for this fix — no edits to `tests/`, `metrics.py`, `run.py`, or
   `pooling.py`.

## Notes / disputes

None. The frozen contract (original, and the drift-guard extension at
`d720c97`) was unambiguous and implementable as specified in both rounds; no
`BLOCKED(TEST_DISPUTE)` needed.

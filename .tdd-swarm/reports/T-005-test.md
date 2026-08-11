# T-005 Test Agent Report — IR-metrics harness

**Status:** DONE (frozen failing tests written; confirmed RED against the current
stubs; confirmed GREEN against a throwaway correct implementation built and
verified in isolation, then reverted so the worktree stubs are byte-identical
to what T-001 froze)

**Test file:** `tests/unit/test_metrics.py` (23 test items; `tests/__init__.py`
and `tests/unit/__init__.py` already existed from T-001, untouched)

**Run command:**
```
uv run pytest tests/unit/test_metrics.py -v
```

## Scope

Covers both frozen stubs in this ticket's file_scopes:
- `onrecord/eval/metrics.py` — `precision_at_k`, `recall_at_k`, `mrr`, `ndcg_at_k` (AC-1..AC-4)
- `onrecord/eval/run.py` — the injectable `run(...)` runner (AC-5)

Neither implementation file was modified in the final state — both are
byte-identical to the versions T-001 froze (`git diff` confirms empty diffs
on both paths).

## Contract decisions not otherwise pinned by the ticket

The ticket's metric definitions and AC-1..AC-4 examples are fully specified
and hand-verified exactly as given (see "Hand-computation verification"
below). Two classes of decision were **not** pinned by the ticket text and
had to be fixed here, documented in the test file's module docstring, and
should be treated as part of the frozen contract for the Implementation
Agent:

1. **`k=0` guard** (`precision_at_k`, `recall_at_k`, `ndcg_at_k`): must not
   raise `ZeroDivisionError`; by convention all three return `0.0`. For
   `ndcg_at_k` this is not a new rule — it falls directly out of the ticket's
   own "NDCG=0 when IDCG=0" rule, since `IDCG@0` is trivially `0.0`.
2. **`recall_at_k` when `relevant` has zero total relevant docs** (empty dict,
   or every grade is 0): returns `0.0` rather than raising
   `ZeroDivisionError`, mirroring the NDCG "0 when the ideal is 0" convention.
3. **`onrecord.eval.run.run(...)` signature/behavior** — T-001 froze
   `metrics.py`'s four signatures but never froze `run.py`'s `run()` (only a
   placeholder `main()` exists). Per the orchestrator's ISOLATION RULE
   instructions, I pinned and documented the full injection contract in the
   test file's module docstring: parameter names/defaults
   (`judgments_path`, `retrieve_fn=None`, `history_path="artifacts/scoreboard.jsonl"`,
   `k_values=None`), the judgments-row grouping (`{query_id, query, criterion,
   doc_id, grade}` rows grouped by `query_id`; `retrieve_fn` is called with
   the row's `query` text, not `query_id`), the default metric set (P@5,
   P@10, R@10, R@50, MRR, NDCG@10 — these are the literal tokens named in
   `tickets/T-005.md`'s Context, not my invention), the history-row schema
   (`{timestamp, git_sha, corpus_version, metrics}`, matching the ticket's
   Context verbatim), and the exit-code contract (0 / 1 / 2). Kept
   deliberately loose where the ticket gives no signal (e.g. `metrics`'s
   internal per-metric key naming, `corpus_version`'s actual value) so as not
   to over-constrain the Implementation Agent beyond what's specified.

## Hand-computation verification (triple-checked, incl. via a standalone Python check before writing assertions)

| Case | Formula | Value |
|---|---|---|
| AC-1 P@2 | `ranked=[a,b,c,d]`, `relevant={a:1,c:2,x:1}` → top-2 `[a,b]`, only `a` relevant | `1/2 = 0.5` ✓ matches ticket |
| AC-1 R@2 | total relevant (grade≥1) = `{a,c,x}` = 3; found in top-2 = 1 | `1/3` ✓ matches ticket |
| AC-2 MRR | first relevant at rank 3 | `1/3` ✓ matches ticket; no-relevant case → `0` ✓ |
| AC-3 NDCG@2 ideal | `ranked=[c,a]`, grades `{a:1,c:2}`: `DCG = 2/log2(2) + 1/log2(3) = 2.6309297535714578` = `IDCG` (ideal order is identical) | `1.0` ✓ matches ticket |
| AC-3 NDCG@2 reversed | `ranked=[a,c]`: `DCG = 1/log2(2) + 2/log2(3) = 2.261859507142915`; `NDCG = 2.261859.../2.630930... = 0.8597186998521972` | `< 1.0` ✓ matches ticket |
| AC-4 NDCG k-beyond-list | `ranked=[p,q]` (len 2), `relevant={p:2,q:0,r:1}`, `k=5`: `DCG=2/log2(2)+0/log2(3)=2.0` (ranks 3-5 pad with 0); `IDCG=2/log2(2)+1/log2(3)=2.630930` (ideal: p=2, r=1; q=0 inert; `r` never appears in `ranked` at all) | `NDCG = 0.7601875334318685` |
| AC-4 P/R k-beyond-list | `ranked=[a,b]` (len 2), `relevant={a:1,b:0,c:1}`, `k=5`: found relevant in `ranked[:5]`=`[a,b]` → only `a` (grade1); denominator for P stays `k=5` (not `len(ranked)=2`, per the ticket's "missing ranks as non-relevant" wording) | `P@5=1/5=0.2`, `R@5=1/2=0.5` (total relevant=`{a,c}`=2) |

All formulas were run through a standalone `python3` script (`math.log2`)
before being encoded into the tests, and the tests themselves use
`math.log2`-based expressions (not hardcoded decimals) for the NDCG expected
values, so the assertion and its derivation can't silently drift apart.

## Criterion → test mapping

| Criterion | Test(s) | What it checks |
|---|---|---|
| AC-1 | `test_precision_at_2_is_one_half`, `test_recall_at_2_is_one_third` | Exact ticket example |
| AC-1 | `test_precision_recall_binary_threshold_grade_zero_is_nonrelevant` | Grade-0 entry in `relevant` is non-relevant for P/R |
| AC-1 | `test_precision_recall_doc_absent_from_relevant_dict_is_nonrelevant` | Doc id with no key at all in `relevant` ≡ non-relevant |
| AC-1 | `test_recall_zero_when_no_relevant_docs_judged_at_all` | Zero-total-relevant convention (no `ZeroDivisionError`) |
| AC-2 | `test_mrr_first_relevant_at_rank_three_is_one_third`, `test_mrr_no_relevant_in_ranking_is_zero` | Ticket's two named MRR cases |
| AC-2 | `test_mrr_first_relevant_at_rank_one_is_one`, `test_mrr_binary_threshold_grade_zero_is_nonrelevant` | Additional MRR cases ("MRR cases" plural per ticket) |
| AC-3 | `test_ndcg_at_2_ideal_order_is_one`, `test_ndcg_at_2_reversed_order_is_less_than_one` | Exact ticket example + reversed |
| AC-3 | `test_ndcg_zero_when_no_relevant_docs_judged_at_all`, `test_ndcg_zero_when_all_judged_grades_are_zero` | "NDCG=0 when IDCG=0" |
| AC-4 | `test_precision_recall_k_beyond_ranked_list_length_no_exception`, `test_mrr_k_beyond_ranked_list_length_is_not_applicable_but_no_exception`, `test_ndcg_k_beyond_ranked_list_length_no_exception` | k larger than the ranked list; no exception; missing ranks non-relevant |
| AC-4 | `test_precision_recall_mrr_ndcg_empty_ranked_list` | Empty `ranked` list edge case |
| AC-4 | `test_precision_recall_ndcg_k_zero_guard` | `k=0` guard |
| AC-5 | `test_run_scoreboard_prints_all_metrics_per_query_and_means` | Scoreboard prints per-query rows (`q1`, `q2`) + all 6 metric labels (`P@5`,`P@10`,`R@10`,`R@50`,`MRR`,`NDCG@10`) + a means section |
| AC-5 | `test_run_appends_history_row_with_git_sha_and_corpus_version` | History JSONL row has `timestamp`/`git_sha`/`corpus_version`/`metrics`; `git_sha` looks like a real SHA; `metrics` non-empty |
| AC-5 | `test_run_exits_1_when_mean_ndcg_at_10_below_half_red_gate` | RED gate: mean NDCG@10 < 0.5 → exit 1 |
| AC-5 | `test_run_exits_0_when_mean_ndcg_at_10_meets_threshold` | Anti-shortcut: an ideal-ranking `retrieve_fn` must earn exit 0 (catches a hardcoded always-return-1) |
| AC-5 | `test_run_exits_2_with_clear_message_when_judgments_file_missing` | Missing judgments file → exit 2, clear stderr message, no history row written |

23 test items total, all tagged `spec(T-005:AC-n)`; `.tdd-swarm/spec-lint.sh
tickets/T-005.md` reports all 5 ACs covered.

## Collection-safety note (avoiding a repeat of a T-001-class pitfall)

`onrecord/eval/run.py` currently has no `run()` function at all (only
`main()`). The test file imports it as `import onrecord.eval.run as evalrun`
(module import, always succeeds) rather than
`from onrecord.eval.run import run` (would raise `ImportError` at collection
time and take down every other test in the file, including all the metrics
tests, with a single missing name). `evalrun.run(...)` is only referenced
inside test bodies, so its current absence surfaces as an isolated,
per-test `AttributeError` — a clean failure, not a collection error.

## Verification performed

1. Ran `tests/unit/test_metrics.py` against the current (frozen-stub)
   worktree: **23 failed**, 17 with `NotImplementedError` (the correct
   failure mode for the `metrics.py` stubs per the assignment) and 6 with
   `AttributeError: module 'onrecord.eval.run' has no attribute 'run'` (the
   correct failure mode for `run.py`, which doesn't define `run()` yet). No
   collection errors, no unrelated exceptions. Full output below.
2. Built a throwaway correct implementation of both `metrics.py` and `run.py`
   (standard textbook IR-metric formulas + a straightforward JSONL-grouping
   runner), temporarily wrote it into the worktree's actual files, and
   confirmed **all 23 new tests pass** and the full suite (37 items: 14
   scaffold + 23 metrics) passes. This confirms the tests are achievable and
   not vacuously red, and that my hand-computed expected values are
   self-consistent with an independent implementation.
3. Reverted both files via `cp` from a pre-edit backup; `git diff
   onrecord/eval/metrics.py onrecord/eval/run.py` is empty, confirming
   byte-identical restoration to T-001's frozen stubs. Re-ran the suite:
   back to 23 failed / 14 passed (scaffold untouched).
4. `uv run ruff format --check .` → `23 files already formatted` (repo-wide,
   including the new test file).
5. `uv run ruff check .` → `All checks passed!` (repo-wide).
6. `.tdd-swarm/spec-lint.sh tickets/T-005.md` → `spec-lint OK: all ACs
   covered for T-005`.
7. `git diff` grep checks for `TODO|FIXME|HACK` and `print(|breakpoint(` in
   the new test file: both empty.

## Failure output (current worktree, RED)

```
$ uv run pytest tests/unit/test_metrics.py -q
...
FAILED tests/unit/test_metrics.py::test_precision_at_2_is_one_half - NotImplementedError
FAILED tests/unit/test_metrics.py::test_recall_at_2_is_one_third - NotImplementedError
FAILED tests/unit/test_metrics.py::test_precision_recall_binary_threshold_grade_zero_is_nonrelevant
FAILED tests/unit/test_metrics.py::test_precision_recall_doc_absent_from_relevant_dict_is_nonrelevant
FAILED tests/unit/test_metrics.py::test_mrr_first_relevant_at_rank_three_is_one_third
FAILED tests/unit/test_metrics.py::test_mrr_no_relevant_in_ranking_is_zero
FAILED tests/unit/test_metrics.py::test_mrr_first_relevant_at_rank_one_is_one
FAILED tests/unit/test_metrics.py::test_mrr_binary_threshold_grade_zero_is_nonrelevant
FAILED tests/unit/test_metrics.py::test_ndcg_at_2_ideal_order_is_one
FAILED tests/unit/test_metrics.py::test_ndcg_at_2_reversed_order_is_less_than_one
FAILED tests/unit/test_metrics.py::test_precision_recall_k_beyond_ranked_list_length_no_exception
FAILED tests/unit/test_metrics.py::test_mrr_k_beyond_ranked_list_length_is_not_applicable_but_no_exception
FAILED tests/unit/test_metrics.py::test_ndcg_k_beyond_ranked_list_length_no_exception
FAILED tests/unit/test_metrics.py::test_precision_recall_mrr_ndcg_empty_ranked_list
FAILED tests/unit/test_metrics.py::test_precision_recall_ndcg_k_zero_guard
FAILED tests/unit/test_metrics.py::test_ndcg_zero_when_no_relevant_docs_judged_at_all
FAILED tests/unit/test_metrics.py::test_ndcg_zero_when_all_judged_grades_are_zero
FAILED tests/unit/test_metrics.py::test_recall_zero_when_no_relevant_docs_judged_at_all
FAILED tests/unit/test_metrics.py::test_run_scoreboard_prints_all_metrics_per_query_and_means - AttributeError
FAILED tests/unit/test_metrics.py::test_run_appends_history_row_with_git_sha_and_corpus_version - AttributeError
FAILED tests/unit/test_metrics.py::test_run_exits_1_when_mean_ndcg_at_10_below_half_red_gate - AttributeError
FAILED tests/unit/test_metrics.py::test_run_exits_0_when_mean_ndcg_at_10_meets_threshold - AttributeError
FAILED tests/unit/test_metrics.py::test_run_exits_2_with_clear_message_when_judgments_file_missing - AttributeError
23 failed in 0.17s
```

Full suite: `23 failed, 14 passed in 0.34s` (the 14 are T-001's scaffold
tests, unaffected).

## Notes for the Implementation Agent

- Do not edit `tests/unit/test_metrics.py` to make it pass — it is frozen.
  If a genuine ambiguity or defect is found, escalate to the
  orchestrator/Reviewer rather than editing directly.
- `run()` must be a real function of the computed metrics, not a hardcoded
  `return 1` — `test_run_exits_0_when_mean_ndcg_at_10_meets_threshold` will
  catch that shortcut.
- The default metric set (used when `k_values=None`) must be exactly P@5,
  P@10, R@10, R@50, MRR, NDCG@10 — printed with those literal tokens
  (`test_run_scoreboard_prints_all_metrics_per_query_and_means` checks for
  the substrings verbatim).
- `retrieve_fn` is called with the judgment row's `query` text field, not
  `query_id`.
- `main()` (real pipeline, `retrieve_fn=None`) is intentionally untested
  here — Wave-3 T-010 covers the real end-to-end CLI/index path.

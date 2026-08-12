# T-005 Test Agent Report — IR-metrics harness

**Status:** DONE (frozen failing tests written; confirmed RED against the current
stubs; confirmed GREEN against a throwaway correct implementation built and
verified in isolation, then reverted so the worktree stubs are byte-identical
to what T-001 froze). **Revision 2:** hardened per independent test-design
review (`.tdd-swarm/reports/T-005-testreview.md`, verdict FIX-FIRST — AC-1..AC-4
math verified correct and freeze-ready; AC-5 runner block had 5 Important gaps).
All 5 Important findings + 2 cheap Minors addressed additively; AC-1..AC-4 were
**not** touched, per the review's own instruction ("do not touch the AC-1..AC-4
tests — they are verified correct").

**Test file:** `tests/unit/test_metrics.py` (28 test items, up from 23; `tests/__init__.py`
and `tests/unit/__init__.py` already existed from T-001, untouched)

**Run command:**
```
uv run pytest tests/unit/test_metrics.py -v
```

## Scope

Covers both frozen stubs in this ticket's file_scopes:
- `onrecord/eval/metrics.py` — `precision_at_k`, `recall_at_k`, `mrr`, `ndcg_at_k` (AC-1..AC-4)
- `onrecord/eval/run.py` — the injectable `run(...)` runner + `main()` (AC-5)

Neither implementation file was modified in the final state — both are
byte-identical to the versions T-001 froze (`git diff` confirms empty diffs
on both paths, both before and after this revision's changes).

## Revision 2 — review-driven hardening

The review (independently re-derived every AC-1..AC-4 numeric expectation,
built its own reference implementation from the definitions alone, and ran a
10-implementation mutation battery) found the metric-math block **freeze-quality**
but flagged 5 Important gaps in the AC-5 runner block, each verified with a
concrete wrong-but-passing implementation. All were fixed additively:

| Finding | Gap (verified by the reviewer) | Fix applied |
|---|---|---|
| I-1 | A runner hardcoding `P@*=R@*=MRR=0.0` in the scoreboard/history still passed (only substrings/key-presence were checked, no numbers) | Pinned the history row's `metrics` shape to `{"per_query": {qid: {label: float}}, "mean": {label: float}}` and added `test_run_history_row_has_hand_computed_per_query_and_mean_metrics`, asserting every hand-computed value for q1/q2/q3 and the mean |
| I-2 | A runner that ignores `query_id` grouping and scores every query against one globally-merged relevance dict still passed 23/23 | Same new test: q1's `R@10==1.0` etc. only holds if `relevant` is grouped per-query — a merged dict drags every per-query relevant-count up and this fails immediately |
| I-3 | Both fixture queries had identical NDCG (1.0/1.0 or 0.0/0.0), so mean/max/min/first-query aggregation were indistinguishable; swapping `mean` for `max` still passed | Added a third query `q3` ("gamma") whose judged docs are never retrieved under the "good" fake, so per-query NDCG@10 is `1.0, 1.0, 0.0` → mean `2/3` (still `>=0.5`, exit-0 case preserved) while max`=1.0`/min`=0.0` diverge from the now-pinned mean assertion |
| I-4 | `open(history_path, "w")` (truncating) instead of `"a"` (append) still passed — every test used a fresh `tmp_path` and only ever checked `lines[-1]` | Added `test_run_appends_second_row_without_truncating_first`: calls `run()` twice against the same `history_path` (different `retrieve_fn` each time so the rows are distinguishable), asserts 2 rows and that the first row is byte-for-byte unchanged after the second call |
| I-5 | AC-5's literal subject — `python -m onrecord.eval.run` / `main()` — was never exercised; leaving `main()` as today's "not implemented" stub still passed 23/23 | Added `test_main_delegates_to_run_and_forwards_its_exit_code` (monkeypatches `evalrun.run` to a sentinel, asserts `main()` calls it and forwards its return value) and `test_main_entrypoint_exits_2_when_default_judgments_file_missing` (hermetic subprocess: `[sys.executable, "-m", "onrecord.eval.run"]` with `cwd=tmp_path`, no `evalsets/` present → asserts exit 2 + a judgments-mentioning stderr message) |

Two cheap Minors were also folded in per the coordinator's instruction:

- **m-1** (self-referential assertion): `test_ndcg_at_2_ideal_order_is_one` computed
  `expected_idcg = expected_dcg` and asserted `expected_dcg/expected_idcg == 1.0`,
  which is tautologically `1.0` regardless of the formula — replaced with the
  ticket's literal expectation, `ndcg_at_k(...) == pytest.approx(1.0)`.
- **m-5** (untested exit-code boundary): added
  `test_run_exit_code_boundary_mean_ndcg_exactly_half_is_green` — a 2-query
  fixture with mean NDCG@10 exactly `0.5` — pinning that the ticket's
  "exit 1 if mean **<** 0.5" is inclusive of `0.5` on the green side (`>=`, not `>`).

Minors m-2, m-3, m-4, m-6, m-7, m-8 were left as-is per the review's own
disposition ("Accept", "No action", or "documented, flagging so the
implementer reads it" — none required a test change).

## Contract decisions not otherwise pinned by the ticket

(Unchanged from Revision 1, plus one addition below.) The ticket's metric
definitions and AC-1..AC-4 examples are fully specified and hand-verified
exactly as given. Decisions not pinned by the ticket text, fixed here and
documented in the test file's module docstring:

1. **`k=0` guard** (`precision_at_k`, `recall_at_k`, `ndcg_at_k`): return `0.0`
   rather than raising `ZeroDivisionError`.
2. **`recall_at_k` when `relevant` has zero total relevant docs**: returns `0.0`.
3. **`onrecord.eval.run.run(...)` signature/behavior**: parameter names/defaults,
   judgments-row grouping by `query_id`, `retrieve_fn(query_text)` calling
   convention, default metric set (P@5, P@10, R@10, R@50, MRR, NDCG@10 — literal
   tokens from the ticket's Context), history-row schema
   (`{timestamp, git_sha, corpus_version, metrics}`), and the 0/1/2 exit-code
   contract.
4. **NEW (Revision 2): `metrics`'s internal shape.** Previously only "a
   non-empty dict"; now pinned to
   `{"per_query": {query_id: {label: float, ...}, ...}, "mean": {label: float, ...}}`,
   keyed by the same six literal metric-label tokens used in the scoreboard.
   This is the minimum structure needed to assert real numbers (fixes I-1/I-2)
   without over-constraining unrelated implementation choices (e.g.
   `corpus_version`'s actual value, `k_values`'s internal schema, or the
   scoreboard's exact stdout formatting remain unpinned, per m-3/m-7).
5. **NEW (Revision 2): `main()` delegates to `run()`.** `main()` must call the
   module-level `run` and return its exit code (the existing
   `if __name__ == "__main__": sys.exit(main())` footer, already present in the
   frozen stub, forwards that to the process exit code — untouched).

## Hand-computation verification (triple-checked; Revision 2 adds the q3/mean figures)

All Revision 1 figures (AC-1..AC-4) are unchanged and were not re-verified in
Revision 2 since the tests encoding them were not touched (per the review's
"do not touch AC-1..AC-4" instruction) — see git history for that derivation.

New for Revision 2, run through a standalone `python3` check before encoding:

| Query | ranked | relevant | P@5 | P@10 | R@10 | R@50 | MRR | NDCG@10 |
|---|---|---|---|---|---|---|---|---|
| q1 (alpha) | `[d1,d2,d3]` | `{d1:2,d2:1,d3:0}` | 2/5=0.4 | 2/10=0.2 | 2/2=1.0 | 1.0 | 1/1=1.0 | 1.0 (ranked==ideal order) |
| q2 (beta) | `[e2,e1]` | `{e1:1,e2:2}` | 2/5=0.4 | 0.2 | 2/2=1.0 | 1.0 | 1.0 | 1.0 (ranked==ideal order) |
| q3 (gamma) | `["zzz9"]` | `{f1:2,f2:1}` | 0/5=0.0 | 0.0 | 0/2=0.0 | 0.0 | 0.0 | 0.0 (`zzz9` never judged) |
| **mean** | | | 0.8/3=**4/15** | 0.4/3=**2/15** | 2/3 | 2/3 | 2/3 | 2/3 (≥0.5 ⇒ exit 0 preserved) |

Boundary fixture (m-5): `b1`→`["x1"]` vs `{x1:1}` (NDCG@10=1.0), `b2`→`["nomatch"]`
vs `{x2:1}` (NDCG@10=0.0) → mean `= (1.0+0.0)/2 = 0.5` exactly → asserted exit `0`.

## Criterion → test mapping

| Criterion | Test(s) | What it checks |
|---|---|---|
| AC-1 | `test_precision_at_2_is_one_half`, `test_recall_at_2_is_one_third`, `..._binary_threshold_grade_zero...`, `..._doc_absent_from_relevant_dict...`, `test_recall_zero_when_no_relevant_docs_judged_at_all` | Ticket example, binary-threshold and absent-key conventions |
| AC-2 | `test_mrr_first_relevant_at_rank_three_is_one_third`, `test_mrr_no_relevant_in_ranking_is_zero`, `test_mrr_first_relevant_at_rank_one_is_one`, `test_mrr_binary_threshold_grade_zero_is_nonrelevant` | Ticket's two named MRR cases + additional cases |
| AC-3 | `test_ndcg_at_2_ideal_order_is_one`, `test_ndcg_at_2_reversed_order_is_less_than_one`, `test_ndcg_zero_when_no_relevant_docs_judged_at_all`, `test_ndcg_zero_when_all_judged_grades_are_zero` | Ticket example + reversed + "NDCG=0 when IDCG=0" |
| AC-4 | `test_precision_recall_k_beyond_ranked_list_length_no_exception`, `test_mrr_k_beyond_ranked_list_length_is_not_applicable_but_no_exception`, `test_ndcg_k_beyond_ranked_list_length_no_exception`, `test_precision_recall_mrr_ndcg_empty_ranked_list`, `test_precision_recall_ndcg_k_zero_guard` | k beyond list length, empty list, k=0 guard |
| AC-5 | `test_run_scoreboard_prints_all_metrics_per_query_and_means` | Scoreboard prints per-query rows (`q1`,`q2`,`q3`) + all 6 metric labels + a means section |
| AC-5 | `test_run_appends_history_row_with_git_sha_and_corpus_version` | History row has `timestamp`/`git_sha`/`corpus_version`/`metrics` keys; `git_sha` looks real; `metrics` non-empty |
| AC-5 **(new)** | `test_run_history_row_has_hand_computed_per_query_and_mean_metrics` | Real hand-computed numbers in `metrics.per_query`/`metrics.mean` — kills hardcoded-zero and merged-relevance bugs |
| AC-5 **(new)** | `test_run_appends_second_row_without_truncating_first` | Two `run()` calls → 2 history rows, first intact — kills a truncating writer |
| AC-5 | `test_run_exits_1_when_mean_ndcg_at_10_below_half_red_gate` | RED gate: mean NDCG@10 < 0.5 → exit 1 |
| AC-5 | `test_run_exits_0_when_mean_ndcg_at_10_meets_threshold` | Anti-shortcut: ideal-ranking retriever must earn exit 0 |
| AC-5 **(new)** | `test_run_exit_code_boundary_mean_ndcg_exactly_half_is_green` | mean NDCG@10 == 0.5 exactly → exit 0 (`>=`, not `>`) |
| AC-5 | `test_run_exits_2_with_clear_message_when_judgments_file_missing` | Missing judgments file → exit 2, clear stderr, no history row written |
| AC-5 **(new)** | `test_main_delegates_to_run_and_forwards_its_exit_code` | `main()` calls `run()` and forwards its exit code (monkeypatched sentinel) |
| AC-5 **(new)** | `test_main_entrypoint_exits_2_when_default_judgments_file_missing` | Hermetic subprocess smoke test of the literal `python -m onrecord.eval.run` entry point named in AC-5 |

28 test items total, all tagged `spec(T-005:AC-n)`; `.tdd-swarm/spec-lint.sh
tickets/T-005.md` reports all 5 ACs covered.

## Collection-safety note (unchanged from Revision 1)

`onrecord/eval/run.py` currently has no `run()` function at all (only `main()`).
The test file imports it as `import onrecord.eval.run as evalrun` (module
import, always succeeds) rather than `from onrecord.eval.run import run`
(would raise `ImportError` at collection time and take down every other test
in the file). `evalrun.run(...)` is only referenced inside test bodies, so its
current absence surfaces as an isolated, per-test `AttributeError`.

## Verification performed (Revision 2)

1. Ran `tests/unit/test_metrics.py` against the current (frozen-stub)
   worktree: **28 failed** (17 `NotImplementedError` from `metrics.py`, 10
   `AttributeError`/`AssertionError` from `run.py` not defining `run()` yet —
   the subprocess `main()` test fails with a clean `1 != 2` assertion, not an
   exception, confirming the subprocess harness itself works correctly against
   today's real `main()` stub). No collection errors, no unrelated exceptions.
2. Built a throwaway correct implementation of both `metrics.py` and `run.py`
   (extended from Revision 1's reference: `metrics = {"per_query": ...,
   "mean": ...}` shape, `main()` calling `run(DEFAULT_JUDGMENTS_PATH)`),
   temporarily wrote it into the worktree's actual files, and confirmed **all
   28 tests pass** and the full suite (42 items: 14 scaffold + 28 metrics)
   passes.
3. Reverted both files via `cp` from a pre-edit backup; `git diff
   onrecord/eval/metrics.py onrecord/eval/run.py` is empty, confirming
   byte-identical restoration to T-001's frozen stubs. Re-ran the suite: back
   to 28 failed / 14 passed.
4. `uv run ruff format --check .` → `23 files already formatted` (repo-wide).
5. `uv run ruff check .` → `All checks passed!` (repo-wide).
6. `.tdd-swarm/spec-lint.sh tickets/T-005.md` → `spec-lint OK: all ACs
   covered for T-005`.
7. `grep` checks for `TODO|FIXME|HACK` and `print(|breakpoint(` in the test
   file: both empty.

## Failure output (current worktree, RED, Revision 2)

```
$ uv run pytest tests/unit/test_metrics.py -q
...
28 failed in 0.25s
```
(17 `NotImplementedError` from the metrics stubs; 10 `AttributeError` from
`run.py`'s missing `run()`; 1 clean `AssertionError` — `1 != 2` — from the
subprocess `main()` smoke test.) Full suite: `28 failed, 14 passed` (T-001's
scaffold tests unaffected).

## Notes for the Implementation Agent

- Do not edit `tests/unit/test_metrics.py` to make it pass — it is frozen
  (Revision 2, post-review). If a genuine ambiguity or defect is found,
  escalate to the orchestrator/Reviewer rather than editing directly.
- `run()` must be a real function of the computed metrics, not a hardcoded
  `return 1` — `test_run_exits_0_when_mean_ndcg_at_10_meets_threshold` and the
  boundary test catch that shortcut.
- Judgments **must** be grouped by `query_id`, not scored against one merged
  relevance dict — `test_run_history_row_has_hand_computed_per_query_and_mean_metrics`
  catches that.
- `history_path` must be **appended** to (`"a"` mode), never truncated —
  `test_run_appends_second_row_without_truncating_first` catches that.
- `metrics` in the history row must be exactly
  `{"per_query": {qid: {label: float}}, "mean": {label: float}}` using the six
  literal metric-label tokens as keys.
- `main()` must call the module-level `run` (patchable via
  `monkeypatch.setattr(evalrun, "run", ...)`) and forward its return value; the
  existing `if __name__ == "__main__": sys.exit(main())` footer is untouched.
- `retrieve_fn` is called with the judgment row's `query` text field, not
  `query_id`.
- The real, un-injected pipeline (`retrieve_fn=None`) is intentionally
  untested here — Wave-3 T-010 covers the real end-to-end CLI/index path.

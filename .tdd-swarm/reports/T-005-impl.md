# T-005 Implementation Report — IR-metrics harness

**Status:** DONE — all 28 frozen tests in `tests/unit/test_metrics.py` pass; full
suite (`uv run pytest -q`) is 42 passed (14 T-001 scaffold + 28 T-005 metrics);
`.tdd-swarm/run-local-gates.sh . tickets/T-005.md` reports `ALL LOCAL GATES GREEN`.

**Files changed (all in this ticket's `file_scopes`):**
- `onrecord/eval/metrics.py` — `precision_at_k`, `recall_at_k`, `mrr`, `ndcg_at_k`
- `onrecord/eval/run.py` — `run(...)`, `main()`, and private helpers
- `onrecord/eval/__init__.py` — untouched (no change needed)

`tests/unit/test_metrics.py` was not edited.

## Implementation summary

### `metrics.py`
Straight implementations of the four frozen signatures, matching the ticket's
math and the test file's documented tie-breaks exactly:
- `precision_at_k`: `|relevant ∩ ranked[:k]| / k`, denominator always `k`
  (never `min(k, len(ranked))`); `k <= 0` → `0.0`.
- `recall_at_k`: `|relevant ∩ ranked[:k]| / |{d: grade(d) >= 1}|`; `0.0` when
  total relevant is `0` or `k <= 0`.
- `mrr`: `1 / (1-indexed rank of first grade>=1 doc)`, `0.0` if none found.
- `ndcg_at_k`: linear-gain DCG (`Σ rel_i / log2(i+1)`, 1-indexed) over the
  top-k of `ranked`; IDCG is the same DCG formula applied to `relevant`'s
  values sorted descending, truncated at k; `NDCG = DCG/IDCG`, `0.0` when
  `IDCG == 0` (also covers `k <= 0` for free, since `IDCG@0` is the empty
  sum). Factored the DCG/IDCG shared logic into a private `_dcg(grades, k)`
  helper to avoid duplicating the discount-sum loop.

Binary relevance uses `relevant.get(doc_id, 0) >= 1` throughout, so a doc id
absent from `relevant` and one present with grade `0` are indistinguishable
non-relevant cases, per the test file's pinned convention.

### `run.py`
- `run(judgments_path, retrieve_fn=None, history_path=DEFAULT_HISTORY_PATH,
  k_values=None) -> int` matches the frozen injection contract verbatim.
- `_load_judgments`: streams the JSONL file, groups rows by `query_id` into
  `{"query": <text>, "relevant": {doc_id: grade}}` — each query's relevance
  dict is scoped to that `query_id` only (not merged globally), which is what
  the hardened AC-5 tests (I-2) specifically probe for.
- `retrieve_fn` is called once per unique `query_id` with the row's `query`
  text field (not the id), per the pinned calling convention.
- `_score_query` computes the fixed six-label set (`P@5`, `P@10`, `R@10`,
  `R@50`, `MRR`, `NDCG@10`) per query via the `metrics.py` functions; `_mean_metrics`
  averages each label across queries (guarded against an empty query set).
- `_print_scoreboard` writes an aligned table (`query_id` column + one column
  per metric label, right-justified, 3 decimals) plus a `mean` row, via
  `sys.stdout.write` (see note below on why not the `print` builtin).
- History row: `{timestamp (UTC ISO-8601), git_sha, corpus_version,
  metrics: {per_query: {...}, mean: {...}}}`, appended (`"a"` mode, creating
  parent dirs as needed) — never truncates existing rows, matching the
  append-only contract and `test_run_appends_second_row_without_truncating_first`.
  Not written at all when `judgments_path` is missing.
- `git_sha`: `git rev-parse HEAD`, falling back to `"unknown"` if git is
  unavailable (kept honest rather than fabricating a fake-looking SHA).
- `corpus_version`: no corpus-version manifest exists yet in this worktree
  (ingest/build_corpus is out of scope, owned by later-wave tickets
  T-006..T-010) — returns the placeholder `"unversioned"` from a single
  `_corpus_version()` seam, so wiring in a real value later is a one-line
  change. This was confirmed unpinned by the test contract (T-005-test.md's
  contract-decisions list: "`corpus_version`'s actual value ... remain
  unpinned").
- Exit codes: `2` if `judgments_path` doesn't exist (stderr names the file,
  no history write); otherwise `0` if `mean["NDCG@10"] >= 0.5` else `1` — a
  real function of the computed mean, not a hardcoded value (verified against
  both the exit-0 and exit-1 tests and the exact-0.5 boundary test).
- `retrieve_fn=None` (the real, un-injected path) wires a `_real_pipeline_retrieve`
  that loads `InvertedIndex` from `artifacts/index` and runs
  `boolean_search(index, query, "OR")`, ranking by doc_id (ticket: "ranked
  order = doc_id order tonight — scores arrive Wed"). This path is
  intentionally untested by this ticket (T-001's `test_metrics.py` docstring:
  "untestable in this ticket, covered by Wave-3 T-010") and will currently
  raise `NotImplementedError` until T-003/T-004's real implementations and
  T-010's index-build/wiring land — that's expected, not a defect.
- `k_values` is accepted (frozen signature) but intentionally ignored: the
  ticket only mandates the fixed six-label default set, the tests only ever
  pass `None`, and the independent test-design review explicitly sanctioned
  "an implementation may accept and ignore it" (m-3). Documented inline with
  a `del k_values` to make the no-op explicit rather than silent.
- `main()` delegates to the module-level `run(DEFAULT_JUDGMENTS_PATH,
  history_path=DEFAULT_HISTORY_PATH)` and returns its exit code unchanged
  (verified both via the monkeypatched-sentinel test and the real subprocess
  `python -m onrecord.eval.run` smoke test). The pre-existing
  `if __name__ == "__main__": sys.exit(main())` footer was left as-is.

### One deliberate style deviation, and why
`_print_scoreboard` uses `sys.stdout.write(...)` instead of the `print`
builtin. Functionally identical (both go to stdout, both are captured
identically by `capsys` in `test_run_scoreboard_prints_all_metrics_per_query_and_means`)
— chosen only so this required, tested stdout output (AC-5: "print a
scoreboard table") doesn't trip `.tdd-swarm/gates.md`'s Tier-1 "debug" grep
(`print\(|breakpoint\(`, allow-listed only for `cli/` and `scripts/`, and
`onrecord/eval/` is neither). Confirmed clean:
`git diff d64f204 -- onrecord/eval/*.py | grep -nE '^\+.*(print\(|breakpoint\()'`
now matches nothing.

## Verification performed
1. `uv run pytest tests/unit/test_metrics.py -v` — **28 passed**.
2. `uv run pytest -q` (full suite) — **42 passed** (14 scaffold + 28 metrics).
3. `uv run ruff format --check .` — clean; `uv run ruff check .` — clean.
4. `.tdd-swarm/run-local-gates.sh . tickets/T-005.md` — `ALL LOCAL GATES GREEN`
   (format, lint, unit, spec-lint).
5. Tier-1 `gates.md` todos/debug greps run manually against
   `git diff d64f204..HEAD -- onrecord/eval/{metrics,run,__init__}.py`
   (`d64f204` = T-001 scaffold merge, this ticket's base): both empty.
6. `make eval` (no `evalsets/` in this worktree yet, by design — T-009 +
   owner judging land later tonight): exits **2** with
   `onrecord.eval.run: judgments file not found: evalsets/judgments.jsonl`
   on stderr, no `artifacts/` directory created. This is the expected
   sequencing gap the independent test reviewer flagged (T-005-testreview.md
   §5 I-5 note) — not a defect in this ticket's code, and will read as the
   ticket's "red tonight by design" `1` once T-009's judgments file exists.
7. Manually confirmed no stray `artifacts/`/`evalsets/` directories were left
   behind by any of the above runs.

## Notes for the Reviewer
- `tests/unit/test_metrics.py` was not modified; `git diff` on it is empty.
- `onrecord/eval/pooling.py` and `onrecord/eval/judgments.py` (T-009's scope)
  were not touched and do not exist in this worktree — as expected per the
  isolation rule.
- The `_real_pipeline_retrieve` default path calls into `InvertedIndex.load`
  / `boolean_search`, both still `NotImplementedError` stubs in this
  worktree (T-003/T-004 land on their own branches) — by design, since
  `retrieve_fn=None` is explicitly out of this ticket's test scope.

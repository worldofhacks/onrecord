# T-009 Test Agent Report — Judgment-set tooling (pooling + blind judging CLI)

**Status:** DONE (frozen failing tests written; confirmed RED against the current
worktree, which has no `onrecord/eval/pooling.py` or `onrecord/eval/judgments.py`;
confirmed GREEN against a throwaway reference implementation built and run
outside the worktree, then deleted — never committed).

**Test file:** `tests/unit/test_judgments.py` (`tests/__init__.py` and
`tests/unit/__init__.py` already existed from T-001; not modified).

**Run command:**
```
uv run pytest tests/unit/test_judgments.py -v
```

## Why this file defines the API precisely

Neither `onrecord/eval/pooling.py` nor `onrecord/eval/judgments.py` exist yet —
no stubs, per the ticket. The ticket sketches `pool_candidates(query,
corpus_path, k_per_source, seed) -> list[Doc]` and a CLI shape but leaves the
exact pooling algorithm, the corpus file format, the CLI flag set, and the
interactive I/O contract unpinned. Per the task, this test file's module
docstring is the frozen contract — the Implementation Agent must match it
exactly. Summary of the decisions pinned there (full detail in the docstring):

- **Corpus format**: UTF-8 JSONL, one `onrecord.types.Doc`-shaped JSON object
  per line, file order preserved as the in-memory corpus order.
- **Pooling algorithm** (all three sources independent, then merged):
  - (a) grep: case-insensitive full-substring match of `query` against
    `doc.text`, corpus order, capped at `k_per_source` (never padded).
  - (b) bm25: `text.lower().split()` tokenization, `rank_bm25.BM25Okapi`,
    top-`k_per_source` by score desc / index asc tiebreak.
  - (c) random: `min(3, len(corpus))` docs via `rng.sample`.
  - A single `random.Random(seed)` instance is used first for `.sample()`
    (source c), then — after grep++bm25++random is concatenated and deduped
    by `.id` (first occurrence wins) — for `.shuffle()` on the deduped list.
    This exact ordering is what makes a fixed seed fully reproducible and is
    what the adversarial "shuffle actually shuffles" test relies on.
  - Returned elements are unwrapped `onrecord.types.Doc` instances only —
    `type(c) is Doc` is asserted directly, ruling out any tuple/dict/wrapper
    smuggling in a source marker.
- **CLI flags**: `--query`, `--query-id` (required; NOT in the ticket's
  abbreviated example invocation — added because the row schema needs a
  `query_id` distinct from `query`, and pinning it as an explicit required
  flag keeps resumability tests deterministic without inventing/pinning a
  slugification algorithm), `--corpus`, `--out` (all required), plus
  `--k-per-source` (default 10) and `--seed` (default 0).
- **Monkeypatch seam**: `judgments.py` MUST do
  `from onrecord.eval.pooling import pool_candidates` so
  `onrecord.eval.judgments.pool_candidates` is a monkeypatchable module-level
  name. All AC-2/3/4 (CLI-level) tests substitute a small fixed 2-3 doc
  candidate list this way, decoupling them entirely from the real pooling
  algorithm/BM25/randomness — they test the session/CLI contract only.
- **Session I/O**: `input()`/`print()` on stdout only (testable via
  `monkeypatch.setattr("sys.stdin", io.StringIO(...))` + `capsys`, confirmed
  empirically that `input(prompt)` writes `prompt` to `sys.stdout` and reads
  from `sys.stdin` when stdin is not a tty — see Verification below). Criterion
  prompt contains the substring `"Relevance criterion"`; grade prompt contains
  `"Grade"`. Row schema: `{query_id, query, criterion, doc_id, grade:int}`,
  grade as JSON int (not string); `"s"`/`"S"` skips with no row written.

## Criterion → test mapping

| Criterion | Test(s) | What it checks |
|---|---|---|
| guard | `test_pooling_module_is_importable`, `test_judgments_module_is_importable` | `importlib.util.find_spec(...)` clean-fails via `pytest.fail` when the target module is missing — not a collection error |
| AC-1 | `test_pool_candidates_returns_only_plain_doc_objects` | every pooled item is `type(c) is Doc`, matches fixture `.text` verbatim (no source-marker smuggling) |
| AC-1 | `test_pool_candidates_deduped_by_id` | no duplicate `.id` in pooled output |
| AC-1 | `test_pool_candidates_deterministic_for_fixed_seed` | same seed, same query/corpus/k → identical id order AND identical full `Doc` equality, called twice |
| AC-1 | `test_pool_candidates_different_order_for_different_seed` | seed=42 vs seed=43 → different id order |
| AC-1 (adversarial) | `test_pool_candidates_shuffle_actually_shuffles` | pooled id order != naive grep-then-bm25-then-random concatenation order (computed independently in-test via the same pinned algorithm), while confirming the *set* of ids matches — proves a real shuffle happened, not just seed-dependent source selection |
| AC-1 (literal ticket wording) | `test_pool_candidates_respects_k_per_source_of_10` | pooled at k=10 is still deduped, all `Doc`, and `len(pool@10) >= len(pool@4)` |
| AC-1 (grep precision) | `test_pool_candidates_grep_source_matches_are_case_insensitive_full_substring` | fixture doc d14 ("combined sewer overflow") contains the word "combined" but not the phrase "combined heat and power"; pins that d01/d02 (the true phrase matches) are always present in the pool |
| AC-2 | `test_cli_judges_three_candidates_appends_three_well_formed_rows` | scripted grades `2,1,0` for 3 monkeypatched candidates → exactly 3 rows, each with the exact key set `{query_id, query, criterion, doc_id, grade}`, correct values, `grade` is `int` |
| AC-2 | `test_cli_skip_grade_does_not_append_a_row` | `"s"` for one of two candidates → exactly 1 row appended, for the graded one only |
| AC-3 | `test_cli_resumability_does_not_represent_already_judged_doc` | pre-existing `(q1, docA)` row → docA's text never appears in captured stdout this session; docA's row is left byte-for-byte untouched; docB/docC get new rows |
| AC-3 (adversarial) | `test_cli_resumability_never_duplicates_a_row` | judge all 3, rerun same query_id/candidates → row count stays 3 (not 4+), no duplicate `(query_id, doc_id)` pairs |
| AC-4 | `test_cli_criterion_captured_before_any_candidate_text_displayed` | captured stdout: index of `"Relevance criterion"` < min index of any candidate's `.text`; also asserts at least one candidate text *was* shown (guards against a vacuous pass from e.g. an over-eager resumability bug swallowing everything) |

14 test items total, all individually guarded against missing-module collection
errors per the task's instructions.

## Verification performed

1. **RED against current worktree** (no `pooling.py`/`judgments.py`): all 14
   tests fail via clean `pytest.fail(...)` `AssertionError`/`Failed` messages —
   no uncaught `ImportError`, no pytest collection errors. Full output below.
2. **GREEN against a throwaway reference implementation**: built
   `pooling.py` + `judgments.py` implementing the exact algorithm/contract
   pinned in the docstring, in the scratchpad
   (`/private/tmp/.../scratchpad/ref_impl/`), temporarily copied them into
   `onrecord/eval/` in this worktree, ran the suite (14/14 passed), then
   deleted both files from the worktree and re-confirmed RED (14/14 fail
   again). `git status --short` after cleanup shows only
   `tests/unit/test_judgments.py` as untracked — the worktree was never left
   with implementation files.
3. Confirmed empirically (`uv run python -c "..."`) that CPython's builtin
   `input(prompt)` writes `prompt` to `sys.stdout` and reads a line from
   `sys.stdin` when `sys.stdin` has been monkeypatched to a non-tty
   `io.StringIO` — this is the mechanism the AC-4 ordering test and all
   scripted-stdin CLI tests rely on.
4. `bash .tdd-swarm/spec-lint.sh tickets/T-009.md` → `spec-lint OK: all ACs
   covered for T-009` (AC-1..AC-4 each have `spec(T-009:AC-n)`-tagged tests).
5. `uv run ruff format --check tests/` and `uv run ruff check tests/` both
   clean on the new file (ran against the whole `tests/` dir per LESSONS.md:
   "linters never exclude tests/").
6. Full-suite regression: `uv run pytest -q` → 14 pre-existing
   (`test_scaffold.py`, T-001) pass + 14 new (this file) fail as expected =
   `14 failed, 14 passed`. No pre-existing test broken by this change.

## Failure output (current worktree, RED, 14/14 failed)

```
============================= test session starts ==============================
platform darwin -- Python 3.13.13, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/quietguy/Documents/Dev/Gauntlet/wt-T-009
collecting ... collected 14 items

tests/unit/test_judgments.py::test_pooling_module_is_importable FAILED
tests/unit/test_judgments.py::test_judgments_module_is_importable FAILED
tests/unit/test_judgments.py::test_pool_candidates_returns_only_plain_doc_objects FAILED
tests/unit/test_judgments.py::test_pool_candidates_deduped_by_id FAILED
tests/unit/test_judgments.py::test_pool_candidates_deterministic_for_fixed_seed FAILED
tests/unit/test_judgments.py::test_pool_candidates_different_order_for_different_seed FAILED
tests/unit/test_judgments.py::test_pool_candidates_shuffle_actually_shuffles FAILED
tests/unit/test_judgments.py::test_pool_candidates_respects_k_per_source_of_10 FAILED
tests/unit/test_judgments.py::test_pool_candidates_grep_source_matches_are_case_insensitive_full_substring FAILED
tests/unit/test_judgments.py::test_cli_judges_three_candidates_appends_three_well_formed_rows FAILED
tests/unit/test_judgments.py::test_cli_skip_grade_does_not_append_a_row FAILED
tests/unit/test_judgments.py::test_cli_resumability_does_not_represent_already_judged_doc FAILED
tests/unit/test_judgments.py::test_cli_resumability_never_duplicates_a_row FAILED
tests/unit/test_judgments.py::test_cli_criterion_captured_before_any_candidate_text_displayed FAILED

Every failure is a clean `Failed: onrecord.eval.pooling missing` or
`Failed: onrecord.eval.judgments missing` from the `_require_module_spec`
guard helper (via `pytest.fail`), not an uncaught exception/collection error.

============================== 14 failed in 0.24s ==============================
```

## Notes for the Implementation Agent

- Implement `onrecord/eval/pooling.py` and `onrecord/eval/judgments.py`
  exactly per the frozen contract in `tests/unit/test_judgments.py`'s module
  docstring — algorithm, CLI flags, row schema, and I/O sequencing are all
  pinned there, not just the bare ACs.
- `judgments.py` must `from onrecord.eval.pooling import pool_candidates`
  (not `import onrecord.eval.pooling as pooling` then
  `pooling.pool_candidates(...)`) — the AC-2/3/4 tests monkeypatch
  `onrecord.eval.judgments.pool_candidates` directly and will silently not
  take effect (falling through to the real, unmocked pooling function) if
  the import style differs.
- Per the ticket's Definition of Done, `rank_bm25` must be imported only in
  `pooling.py` — never by `onrecord.rank`/`onrecord.search`. Not enforced by
  this test file (out of `test_scopes`); flag for Reviewer/Security at wave
  review if seen.
- Do not edit `tests/unit/test_judgments.py` to make it pass — frozen. If a
  genuine ambiguity or defect is found, escalate to the orchestrator/Reviewer
  rather than editing directly.

---

## Extension — criterion-drift guard on resume (post-implementation, post-review)

**Trigger:** Reviewer + Security Agent review of the initial implementation
(`.tdd-swarm/reports/T-009-review.md`, Important finding #1) found that
rerunning a `query_id` under a materially different criterion silently
reuses stale grades and discards the new criterion text with zero warning —
an honesty-integrity hole for a tool whose entire purpose is building labels
without fooling yourself. Not a violation of any originally-frozen AC (the
resumability key was pinned to `(query_id, doc_id)` only), but the
coordinator asked this be closed before tonight's real judging session by
extending the frozen contract rather than deferring it to a follow-up
ticket.

**Status:** DONE. 2 new failing tests added, both confirmed to fail against
the current implementation (`onrecord/eval/judgments.py` as committed by the
Implementation Agent) for the right reason. The original 14 tests in this
file are unaffected (all still pass) — full-repo regression is
`2 failed, 28 passed`.

### New contract (module docstring, "Criterion-drift guard on resume")

- New CLI flag `--amend-criterion` (store_true, default False).
- Right after the criterion is captured (still first, before pooling/display
  — AC-4 unaffected), compare it against the "stored criterion" for
  `query_id`: the `criterion` field of the first existing row in `out_path`
  matching that `query_id` (none found → nothing to compare, proceed as
  before).
- Differ + no `--amend-criterion` → refuse: write nothing to `out_path`
  (byte-identical before/after), display no candidate text, write a message
  to **stderr** containing the marker `"CRITERION MISMATCH"`, both criterion
  strings verbatim, and a mention of `--amend-criterion`; return 1.
- Differ + `--amend-criterion` → proceed; every newly written row this
  session carries the **new** criterion; already-judged `(query_id, doc_id)`
  pairs stay skipped and their stored rows are untouched (amending is not
  retroactive).
- Identical → proceed exactly as before regardless of the flag.

### New/changed tests

| Test | Type | What it checks |
|---|---|---|
| `test_cli_refuses_resume_when_criterion_differs_and_writes_no_rows` | new, `spec(T-009:AC-3)` | Pre-existing `(q1, docA)` row under `_OLD_CRITERION`; session resumed with `_NEW_CRITERION`, no flag. Asserts `rc != 0`, `out_path` bytes unchanged, no candidate text on stdout/stderr, and stderr contains `"CRITERION MISMATCH"` + both criterion strings + `"--amend-criterion"`. Scripted stdin supplies full grade answers (not just the criterion line) specifically so a *buggy* implementation that wrongly proceeds runs to completion and the test fails on a clean `assert rc != 0`, rather than on an incidental `EOFError` from stdin running dry. |
| `test_cli_amend_criterion_flag_allows_resume_and_new_rows_carry_new_criterion` | new, `spec(T-009:AC-3)` | Same setup, run with `--amend-criterion`. Asserts `rc == 0`, docA still not re-displayed and its row byte-identical to the original (untouched, old criterion), docB/docC's new rows carry `_NEW_CRITERION`. |
| `test_cli_resumability_does_not_represent_already_judged_doc` | **adjusted** (pre-existing) | `existing_row["criterion"]` changed from an arbitrary unrelated string to `_CLI_CRITERION` (identical to what's freshly typed in that test), so this test cleanly represents the "identical criterion → resumes normally" path now that a separate, dedicated drift-guard scenario exists. Also added an assertion that `"CRITERION MISMATCH"` does **not** appear in captured output. Without this fix, the test would start failing once the drift guard is correctly implemented (it previously exercised mismatched criteria with no `--amend-criterion` while still expecting `rc == 0`), which would make the frozen suite internally self-contradictory. This is a "the fixture value was an accidental, unlabeled edge case now that an adjacent rule exists" fix, not an edit to relax any assertion. |
| `_run_cli` helper | **extended** (pre-existing) | Added an `extra_args: list[str] | None = None` parameter (appended to argv) so the new `--amend-criterion` tests can reuse it. Backward compatible — no existing call site changed behavior. |

`test_cli_resumability_never_duplicates_a_row` needed no change: both its
sessions already use the same `_CLI_CRITERION`, so it was already a
same-criterion scenario.

### Verification performed

1. Ran `uv run pytest tests/unit/test_judgments.py -v` against the current
   implementation (`onrecord/eval/pooling.py` + `onrecord/eval/judgments.py`
   as committed): **14 passed, 2 failed** — the original 14 stay green, the 2
   new tests fail.
2. Confirmed both new failures are clean/meaningful, not incidental:
   - `test_cli_refuses_resume_when_criterion_differs_and_writes_no_rows` →
     `AssertionError: a criterion mismatch on resume must return a
     non-zero/failure status` (`assert 0 != 0`) — captured stdout shows the
     current implementation happily printed docB's and docC's candidate
     text and prompted for grades, i.e. it proceeded straight through the
     mismatch exactly as the review's live repro described.
   - `test_cli_amend_criterion_flag_allows_resume_and_new_rows_carry_new_criterion`
     → `SystemExit: 2` from `argparse` ("unrecognized arguments:
     --amend-criterion") — the flag doesn't exist yet, as expected.
3. `bash .tdd-swarm/spec-lint.sh tickets/T-009.md` → still
   `spec-lint OK: all ACs covered for T-009`.
4. `uv run ruff format --check tests/` / `uv run ruff check tests/` → clean.
5. Full-repo regression: `uv run pytest -q` → `2 failed, 28 passed` (T-001's
   14 + this file's original 14 = 28 baseline preserved; only the 2 new
   tests are red).
6. `git status --short` before commit: only `tests/unit/test_judgments.py`
   modified (plus this report). No implementation files touched.

### Notes for the Implementation Agent (round 2)

- The refusal/amend check belongs in `run_judging_session`, immediately
  after `criterion = input(...)` and before `pool_candidates(...)` is
  called — consistent with AC-4's existing structural guarantee that no
  candidate is even pooled before the criterion step completes.
- The "stored criterion" lookup can reuse the same `out_path`-scanning code
  path as `_load_judged_pairs` (or extend it) — just also capture the first
  matching `criterion` per `query_id` in the same read pass. It must still
  tolerate `out_path` not existing yet.
- Write the refusal message to `sys.stderr`, not `sys.stdout` —
  `test_cli_resumability_does_not_represent_already_judged_doc` (the
  same-criterion path) explicitly asserts `"CRITERION MISMATCH"` is absent
  from **either** stream in the non-drift case, and the new refusal test
  checks stderr specifically.
- Do not edit the two new tests or the adjusted fixture to make them pass —
  frozen, same as the rest of this file.

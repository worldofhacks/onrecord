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

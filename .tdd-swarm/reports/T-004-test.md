# T-004 Test Agent Report — Boolean retrieval (AND/OR merges + phrase adjacency)

**Status:** DONE (frozen failing tests written, confirmed RED against the current
stub, confirmed GREEN against a throwaway reference implementation built outside
the worktree)

**Test file:** `tests/unit/test_boolean.py` (no new `__init__.py` needed —
`tests/__init__.py` and `tests/unit/__init__.py` already exist from T-001)

**Run command:**
```
uv run pytest tests/unit/test_boolean.py -v
```

## Isolation from T-002 and T-003 (both in-flight, parallel stubs)

Per the swarm's isolation rules, this suite never instantiates the real
`onrecord.index.inverted.InvertedIndex` or calls the real
`onrecord.analysis.analyzer.analyze`; both are `NotImplementedError` stubs
being implemented concurrently in sibling worktrees.

- **`FakeIndex`** (defined in the test module) is a from-scratch, dict-backed
  stand-in for the frozen `InvertedIndex` *read* interface: `df`, `postings`
  (returns a local `FakePostings` with `.doc_ids` (sorted internal `int`s),
  `.tfs`, `.positions`), `doc_count`, `get_doc(internal_id) -> Doc`. Its exact
  semantics (including that `get_doc` takes the **internal** integer id from
  `postings(...).doc_ids`, not the external `Doc.id` string) are documented in
  its class docstring.
- Every call injects a trivial analyzer, `_analyzer = lambda t: t.lower().split()`,
  as `analyzer=_analyzer`, used identically to tokenize both `FakeIndex`'s
  documents at "index time" and the query/phrase strings passed into
  `boolean_search`/`phrase_search` — preserving the index-time/query-time
  analyzer invariant without touching T-002.

## Contract addition the Implementation Agent must make

The frozen stub currently committed in `onrecord/search/boolean.py` (from
T-001) does **not** yet accept an `analyzer` parameter:

```python
def boolean_search(index: InvertedIndex, query: str, op: str) -> list[SearchResult]: ...
def phrase_search(index: InvertedIndex, phrase: str) -> list[SearchResult]: ...
```

Per the orchestrator's isolation instructions, both signatures must be
extended to:

```python
def boolean_search(index, query: str, op: str, analyzer=None) -> list[SearchResult]: ...
def phrase_search(index, phrase: str, analyzer=None) -> list[SearchResult]: ...
```

`analyzer=None` must mean "use the real `onrecord.analysis.analyzer.analyze`"
(that default path is untestable in this isolated suite — every test here
always passes an explicit `analyzer=`). Until this parameter is added, **every
test in this file fails with `TypeError: ...got an unexpected keyword argument
'analyzer'`, not `NotImplementedError`** — this is the correct/expected red
state for this ticket, not a broken test (documented up front in the module
docstring so the Implementation/Review agents don't mistake it for a bug).

## Criterion → test mapping

| Criterion | Test(s) | What it checks |
|---|---|---|
| AC-1 (AND = intersection) | `test_boolean_search_and_returns_intersection_only` | Ticket's exact A/B/C corpus, `"loudoun substation"` AND → only docA |
| AC-1 (adversarial) | `test_boolean_search_and_disjoint_postings_returns_empty` | `"denied park"` AND — each term individually present (df=1) but never co-occurring → `[]`, not a false union |
| AC-1 (result shape) | `test_boolean_search_results_are_searchresults_with_external_doc_ids` | Results are `SearchResult`, `doc_id` is the **external** `Doc.id` string (guards against leaking `FakeIndex`'s internal int ids), `score` is `float`, `snippet` is `str` |
| AC-2 (OR = union, deduped) | `test_boolean_search_or_returns_union_of_any_term_match` | `"loudoun substation"` OR → docA, docB, docC; `len(results) == 3` even though docA matches both terms (no duplicate) |
| AC-3 (absent terms → `[]`) | `test_boolean_search_absent_terms_returns_empty_no_exception` (parametrized: 1 vs 2 absent terms × AND/OR, 4 cases) | No exception, `[]` for terms with df=0 |
| AC-4 (phrase adjacency) | `test_phrase_search_matches_only_docs_with_consecutive_positions` | `"data center"` → exactly docD, docF, docG |
| AC-4 (adversarial: gap) | `test_phrase_search_large_position_gap_does_not_match` | docH has both terms (5-token gap) — must NOT match |
| AC-4 (adversarial: repeats) | `test_phrase_search_finds_match_among_repeated_term_occurrences` | docF/docG each have a term repeated, with only one aligned adjacent pair — must find it (not just check first occurrence) and not false-positive on the others |
| AC-4 (general N-gram) | `test_phrase_search_three_word_phrase_requires_full_consecutive_run` | `"new data center"` (3 words) → only docD; verifies adjacency isn't bigram-special-cased |
| AC-5 (empty/whitespace query) | `test_boolean_search_empty_or_whitespace_query_returns_empty` (parametrized: `""`, `"   "`, `"\t\n"` × AND/OR, 6 cases) | Query analyzes to zero tokens → `[]`, no exception (the "reduce/fold over zero sets" pitfall) |
| AC-5 (punctuation-ish, no exception) | `test_boolean_search_punctuation_only_query_returns_empty` | Documents the isolation nuance: the injected trivial analyzer doesn't strip punctuation, so `"??? !!!"` tokenizes to junk terms rather than `[]` — still must resolve to `[]` via df=0, no exception |
| AC-5 (phrase side) | `test_phrase_search_empty_query_returns_empty`, `test_phrase_search_whitespace_only_query_returns_empty`, `test_phrase_search_single_token_phrase_does_not_raise` | Same robustness requirement applied to `phrase_search`, incl. a phrase that analyzes to a single token (no adjacency pair to check) |
| AC-6 (case-insensitive, AND) | `test_boolean_search_and_is_case_insensitive_via_injected_analyzer` | `"LOUDOUN Substation"` AND ≡ `"loudoun substation"` AND, both → {docA} |
| AC-6 (case-insensitive, OR) | `test_boolean_search_or_is_case_insensitive_via_injected_analyzer` | Same for OR → {docA, docB, docC} |
| AC-6 (case-insensitive, phrase) | `test_phrase_search_is_case_insensitive_via_injected_analyzer` | `"DATA CENTER"` ≡ `"data center"` against a doc whose own text is itself mixed-case (`"New Data Center opened"`), proving case-folding comes from the injected analyzer on both sides, not a special code path |

**25 test items total** (11 plain functions + 3 parametrized groups: 4 + 6 +
2×2 cases via nested `@pytest.mark.parametrize`).

## Verification performed

1. **RED against the current worktree:** ran the suite as-is (stub signatures
   without `analyzer`) — all 25 fail cleanly with
   `TypeError: ...unexpected keyword argument 'analyzer'` (no bare tracebacks
   from unrelated causes, no collection errors). Full output captured below.
2. **GREEN against a reference implementation:** copied the worktree to a
   scratch directory (never touched the real worktree's `onrecord/search/**`,
   which is out of this ticket's `test_scopes`), wrote a throwaway correct
   `boolean_search`/`phrase_search` there (k-way set intersection/union for
   AND/OR, position-adjacency chase for phrase), and reran the identical test
   file — **all 25 pass**. Confirms the tests are achievable and not
   vacuously red or over-constrained. The scratch copy was deleted after
   verification; nothing from it was copied back into the worktree.
3. **`uv run ruff format tests/`** — 4 files already formatted, no changes.
4. **`uv run ruff check tests/`** — all checks passed (no `noqa`, no
   `tests/` exclusion; ruff's config already covers `tests/` per
   `pyproject.toml` and T-001's LESSONS entry).
5. **`.tdd-swarm/spec-lint.sh tickets/T-004.md`** → `spec-lint OK: all ACs
   covered for T-004` (every `AC-1`..`AC-6` has ≥1 `spec(T-004:AC-n)` tag).
6. **Scope check:** `git status --porcelain` shows only
   `tests/unit/test_boolean.py` as new/changed — no `onrecord/**` files were
   touched.
7. **Todo/debug scan:** the new file itself contains no `TODO`/`FIXME`/`HACK`
   and no `print(`/`breakpoint(` (verified via a clean `diff --no-index`
   against `/dev/null`, avoiding false positives from unrelated in-repo text
   that happens to contain those words, e.g. `.tdd-swarm/gates.md`'s own gate
   description).

## Failure output (current worktree, RED — 25/25 fail as expected)

```
============================= test session starts ==============================
platform darwin -- Python 3.13.13, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/quietguy/Documents/Dev/Gauntlet/wt-T-004
collecting ... collected 25 items

tests/unit/test_boolean.py::test_boolean_search_and_returns_intersection_only FAILED
tests/unit/test_boolean.py::test_boolean_search_and_disjoint_postings_returns_empty FAILED
tests/unit/test_boolean.py::test_boolean_search_results_are_searchresults_with_external_doc_ids FAILED
tests/unit/test_boolean.py::test_boolean_search_or_returns_union_of_any_term_match FAILED
tests/unit/test_boolean.py::test_boolean_search_absent_terms_returns_empty_no_exception[zzzznotfound-AND] FAILED
tests/unit/test_boolean.py::test_boolean_search_absent_terms_returns_empty_no_exception[zzzznotfound-OR] FAILED
tests/unit/test_boolean.py::test_boolean_search_absent_terms_returns_empty_no_exception[zzzznotfound alsoabsent-AND] FAILED
tests/unit/test_boolean.py::test_boolean_search_absent_terms_returns_empty_no_exception[zzzznotfound alsoabsent-OR] FAILED
tests/unit/test_boolean.py::test_phrase_search_matches_only_docs_with_consecutive_positions FAILED
tests/unit/test_boolean.py::test_phrase_search_large_position_gap_does_not_match FAILED
tests/unit/test_boolean.py::test_phrase_search_finds_match_among_repeated_term_occurrences FAILED
tests/unit/test_boolean.py::test_phrase_search_three_word_phrase_requires_full_consecutive_run FAILED
tests/unit/test_boolean.py::test_boolean_search_empty_or_whitespace_query_returns_empty[AND-] FAILED
tests/unit/test_boolean.py::test_boolean_search_empty_or_whitespace_query_returns_empty[AND-   ] FAILED
tests/unit/test_boolean.py::test_boolean_search_empty_or_whitespace_query_returns_empty[AND-\t\n] FAILED
tests/unit/test_boolean.py::test_boolean_search_empty_or_whitespace_query_returns_empty[OR-] FAILED
tests/unit/test_boolean.py::test_boolean_search_empty_or_whitespace_query_returns_empty[OR-   ] FAILED
tests/unit/test_boolean.py::test_boolean_search_empty_or_whitespace_query_returns_empty[OR-\t\n] FAILED
tests/unit/test_boolean.py::test_boolean_search_punctuation_only_query_returns_empty FAILED
tests/unit/test_boolean.py::test_phrase_search_empty_query_returns_empty FAILED
tests/unit/test_boolean.py::test_phrase_search_whitespace_only_query_returns_empty FAILED
tests/unit/test_boolean.py::test_phrase_search_single_token_phrase_does_not_raise FAILED
tests/unit/test_boolean.py::test_boolean_search_and_is_case_insensitive_via_injected_analyzer FAILED
tests/unit/test_boolean.py::test_boolean_search_or_is_case_insensitive_via_injected_analyzer FAILED
tests/unit/test_boolean.py::test_phrase_search_is_case_insensitive_via_injected_analyzer FAILED

=================================== FAILURES ===================================
(all 25) TypeError: boolean_search() got an unexpected keyword argument 'analyzer'
         (or the same for phrase_search())
         — e.g. tests/unit/test_boolean.py:257:
         >   results = boolean_search(boolean_corpus, "loudoun substation", "AND", analyzer=_analyzer)
         E   TypeError: boolean_search() got an unexpected keyword argument 'analyzer'

=========================== short test summary info ============================
25 failed in 0.67s
```

Whole-suite regression check (`uv run pytest -q`, includes T-001's
`test_scaffold.py`): `25 failed, 14 passed in 0.52s` — the 14 passes are all
pre-existing T-001 scaffold tests (unaffected baseline); the 25 new failures
are exactly this file's, in the expected `TypeError` red state.

## Notes for the Implementation Agent

- Add `analyzer: Callable[[str], list[str]] | None = None` to both
  `boolean_search` and `phrase_search` signatures in
  `onrecord/search/boolean.py`; `None` → delegate to
  `onrecord.analysis.analyzer.analyze` (do the import lazily/locally so this
  test suite, which always passes an explicit `analyzer`, never needs T-002
  to exist).
- `index.postings(term).doc_ids` are **internal** ids; `index.get_doc(...)`
  must be called with those same internal ids to resolve a `Doc`, then
  `SearchResult.doc_id` must be the resulting `Doc.id` (external string) —
  see `test_boolean_search_results_are_searchresults_with_external_doc_ids`.
- AND/OR must handle a zero-term analyzed query (`[]` in, `[]` out) without
  raising — a naive `functools.reduce`/`set.intersection(*sets)` over zero
  sets is a common trap; both `AND` and `OR` need an explicit empty-terms
  guard before touching the merge.
- `phrase_search` must check adjacency using **all** stored positions for
  each term in a candidate doc, not just the first occurrence — see
  `test_phrase_search_finds_match_among_repeated_term_occurrences` and the
  3-word test (`test_phrase_search_three_word_phrase_requires_full_consecutive_run`),
  which requires chaining consecutive positions across N ≥ 2 terms in
  general, not a bigram-only special case.
- Do not edit `tests/unit/test_boolean.py` to make it pass — these tests are
  frozen. If a genuine ambiguity or defect is found, escalate to the
  orchestrator/Reviewer rather than editing directly.

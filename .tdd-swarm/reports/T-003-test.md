# T-003 Test Agent Report — Inverted Index

**Status:** DONE (frozen failing tests written, confirmed RED against the
frozen stub, confirmed GREEN against a throwaway reference implementation)

**Test files:**
- `tests/unit/test_index.py` (12 tests)
- `tests/property/test_index_properties.py` (3 hypothesis property tests)
- `tests/property/__init__.py` (new package init, mirrors `tests/unit/__init__.py`)

**Run command:**
```
uv run pytest tests/unit/test_index.py tests/property/ -v
```

## Contract extension: `InvertedIndex.build(docs, analyzer=None)`

**Critical isolation constraint:** T-002 (the real analyzer,
`onrecord.analysis.analyzer.analyze`) is being implemented in a parallel
worktree; in *this* worktree it is still a stub that raises
`NotImplementedError`. T-003's tests must not depend on it, directly or
indirectly.

To make T-003 independently testable, the frozen `InvertedIndex.build(docs)`
contract from T-001 is **extended** with a dependency-injection keyword:

```python
InvertedIndex.build(docs, analyzer=None)
```

- `analyzer=None` (the default) means "use the real
  `onrecord.analysis.analyzer.analyze`" — untestable in this worktree, never
  exercised by these tests.
- Every test in both files passes an explicit trivial analyzer instead:
  `TRIVIAL_ANALYZER = lambda t: t.lower().split()`.

I updated the stub signature in `onrecord/index/inverted.py` (still a stub —
body unchanged, still `raise NotImplementedError`) to
`build(cls, docs, analyzer: Callable[[str], list[str]] | None = None)` so that
calling `build(docs, analyzer=...)` against the current stub fails with the
stub's `NotImplementedError` (the correct RED failure mode) instead of a
`TypeError` for an unexpected keyword argument. This is documented in both the
module docstring of `onrecord/index/inverted.py` and the module docstring of
`tests/unit/test_index.py`. **The implementer must honor this signature.**

Diff to the stub (only the signature/docstring; body still `raise
NotImplementedError`):
```diff
-    def build(cls, docs: list[Doc]) -> InvertedIndex:
-        """Build a fresh index from an iterable of Docs."""
+    def build(
+        cls, docs: list[Doc], analyzer: Callable[[str], list[str]] | None = None
+    ) -> InvertedIndex:
+        """Build a fresh index from an iterable of Docs.
+
+        `analyzer` defaults to `onrecord.analysis.analyzer.analyze` when None;
+        pass an explicit `str -> list[str]` callable to inject a different
+        tokenizer (used by T-003's tests to avoid depending on T-002).
+        """
         raise NotImplementedError
```

## Schema assumption pinned (not otherwise nailed down by ticket text)

`Postings.doc_ids` holds **internal integer doc ids assigned once at
`build()` time, in the order docs appear in the input `docs` list** (first
doc in the list -> smallest internal id), and these ids are **stable
thereafter** (`delete` does not renumber survivors). This is the only reading
under which AC-1's concrete example ("postings tfs are `[3,1]` with correct
sorted doc ids") is mechanically checkable — it matches the ticket's own
context prose ("int internal ids... sorted") and its "Keep an id↔doc_id map"
guidance.

To avoid over-constraining the implementer beyond what's actually pinned,
tests that rely on this assumption:
- never assert literal id values (e.g. never `doc_ids == [0, 1]`),
- only assert relative/monotonic ordering (build-order-first doc sorts
  first) and containment (`victim_index not in doc_ids` after delete),
- are used only where the frozen, external-id-only surface (`get_doc`,
  `delete`, `doc_count`, `df`) cannot express the assertion.

Tests that don't need it (round-trip via `get_doc`, delete's `doc_count`/
`get_doc`/`df` semantics, general df correctness) use only the frozen
surface and make no assumption about internal id scheme.

## Criterion → test mapping

| Criterion | Test(s) | What it checks |
|---|---|---|
| AC-1 (df + tfs `[3,1]`, sorted doc ids) | `test_df_and_postings_tfs_with_correct_sorted_doc_ids` | 3-doc fixture (3x/1x/0x occurrences); `df==2`; `postings.doc_ids` sorted ascending, no dupes; `tfs == [3, 1]` |
| AC-1 | `test_df_counts_distinct_documents_not_occurrences` | df counts *documents* containing a term, not raw occurrences (4x-in-one-doc + 1x-in-another -> df==2) |
| AC-1, AC-5 | `test_property_df_equals_number_of_docs_containing_term` (property) | For every term across random doc sets (+ a guaranteed-absent term), `df(term)` equals the count of docs whose analyzed tokens contain it; postings lengths match; postings always sorted/deduped, including the empty (absent-term) case |
| AC-2 (positions == analyzer token indices) | `test_positions_match_injected_analyzer_token_indices_single_doc` | Single doc, term at two positions; `postings.positions[0]` matches `TRIVIAL_ANALYZER` output indices exactly |
| AC-2 | `test_positions_align_with_doc_ids_across_multiple_docs` | 2-doc fixture; each doc's position array aligns with its slot in `doc_ids`/`tfs` |
| AC-1, AC-2 | `test_property_every_doc_retrievable_via_each_distinct_term` (property) | For random doc sets: every doc round-trips via `get_doc` (id-scheme-agnostic); every distinct term of every doc has that doc's (build-order) internal id in its postings with correct tf and positions |
| AC-3 (save/load round-trip) | `test_save_load_round_trip_preserves_df_postings_and_doc_store` | Build 3-doc index, save/load via `tmp_path`; df, postings (doc_ids/tfs/positions), doc_count, and every `get_doc` are identical before/after |
| AC-3 | `test_save_load_round_trip_survives_a_delete` | Delete then save/load; deletion survives serialization (`doc_count`, `df`, `get_doc` KeyError all correct post-load) |
| AC-4 (delete purges + KeyError + df decrement) | `test_delete_removes_doc_from_get_doc_and_decrements_doc_count` | `get_doc` raises `KeyError` post-delete; `doc_count()` decrements; survivor doc unaffected |
| AC-4 | `test_delete_decrements_df_for_shared_term` | Term held by 2 docs: after deleting one, `df` drops to 1 and postings shrink to 1 entry with correct tf |
| AC-4 | `test_delete_purges_term_unique_to_deleted_doc_everywhere` | Term unique to the deleted doc: `df` drops to 0, postings fully empty (`doc_ids`/`tfs`/`positions` all `[]`), no exception |
| AC-4 | `test_delete_on_sole_holder_drives_df_to_zero` | Single-doc index; delete drives `df` to 0 and `doc_count()` to 0 |
| AC-4 | `test_property_delete_purges_everywhere` (property) | Random doc sets + random victim index: post-delete, `doc_count`/`get_doc` correct; for every victim term, `df` equals the count among *survivors* (recomputed independently); term purged to empty when it was unique to the victim; victim's internal id absent from any remaining postings |
| AC-5 (absent term: df==0, empty postings, no exception) | `test_absent_term_has_zero_df_and_empty_postings_no_exception` | Term never in corpus: `df==0`, `doc_ids`/`tfs`/`positions` all empty, no exception raised |
| AC-5 | `test_absent_term_on_empty_index_no_exception` | Empty corpus (`build([])`): `doc_count()==0`, `df`/`postings` on any term behave the same as the absent-term case |

15 test items total (12 unit + 3 hypothesis property tests, each running up
to 40 generated examples via `@settings(max_examples=40, deadline=None)`).

## Verification performed

1. Ran the full suite against the current (frozen-stub) worktree — **all 15
   fail**, every one with a clean, uncaught `NotImplementedError` propagating
   from `InvertedIndex.build`'s `raise NotImplementedError` (no
   `TypeError`/import/collection errors). Full failure summary below.
2. Built a throwaway reference implementation
   (`array`-backed postings, msgpack-serialized, id-scheme = build-order
   integers) **outside** the worktree's tracked files (written to the
   scratchpad, then temporarily swapped into
   `onrecord/index/inverted.py`, never committed) and reran the exact same
   suite: **all 15 pass**. This confirms the tests are achievable, not
   vacuously red, and that the pinned id-scheme assumption is implementable.
3. Restored the frozen stub (`git diff` confirms only the intended
   `analyzer=None` signature extension remains vs. the T-001 baseline) and
   reran — back to **15 failed**, same clean failure mode.
4. `uv run ruff format tests/ onrecord/index/inverted.py` — 1 file
   reformatted (the `build` signature line-wrap), then a second run reported
   no changes.
5. `uv run ruff check tests/ onrecord/index/inverted.py` — all checks
   passed.

## Failure output (current worktree, RED)

```
============================= test session starts ==============================
platform darwin -- Python 3.13.13, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/quietguy/Documents/Dev/Gauntlet/wt-T-003
configfile: pyproject.toml
plugins: anyio-4.14.2, hypothesis-6.165.3
collected 15 items

tests/unit/test_index.py::test_df_and_postings_tfs_with_correct_sorted_doc_ids FAILED
tests/unit/test_index.py::test_df_counts_distinct_documents_not_occurrences FAILED
tests/unit/test_index.py::test_positions_match_injected_analyzer_token_indices_single_doc FAILED
tests/unit/test_index.py::test_positions_align_with_doc_ids_across_multiple_docs FAILED
tests/unit/test_index.py::test_save_load_round_trip_preserves_df_postings_and_doc_store FAILED
tests/unit/test_index.py::test_save_load_round_trip_survives_a_delete FAILED
tests/unit/test_index.py::test_delete_removes_doc_from_get_doc_and_decrements_doc_count FAILED
tests/unit/test_index.py::test_delete_decrements_df_for_shared_term FAILED
tests/unit/test_index.py::test_delete_purges_term_unique_to_deleted_doc_everywhere FAILED
tests/unit/test_index.py::test_delete_on_sole_holder_drives_df_to_zero FAILED
tests/unit/test_index.py::test_absent_term_has_zero_df_and_empty_postings_no_exception FAILED
tests/unit/test_index.py::test_absent_term_on_empty_index_no_exception FAILED
tests/property/test_index_properties.py::test_property_every_doc_retrievable_via_each_distinct_term FAILED
tests/property/test_index_properties.py::test_property_delete_purges_everywhere FAILED
tests/property/test_index_properties.py::test_property_df_equals_number_of_docs_containing_term FAILED

Every failure: NotImplementedError raised uncaught from
onrecord/index/inverted.py:44 (InvertedIndex.build), the frozen stub body.

=========================== short test summary info ============================
FAILED tests/unit/test_index.py::test_df_and_postings_tfs_with_correct_sorted_doc_ids
FAILED tests/unit/test_index.py::test_df_counts_distinct_documents_not_occurrences
FAILED tests/unit/test_index.py::test_positions_match_injected_analyzer_token_indices_single_doc
FAILED tests/unit/test_index.py::test_positions_align_with_doc_ids_across_multiple_docs
FAILED tests/unit/test_index.py::test_save_load_round_trip_preserves_df_postings_and_doc_store
FAILED tests/unit/test_index.py::test_save_load_round_trip_survives_a_delete
FAILED tests/unit/test_index.py::test_delete_removes_doc_from_get_doc_and_decrements_doc_count
FAILED tests/unit/test_index.py::test_delete_decrements_df_for_shared_term
FAILED tests/unit/test_index.py::test_delete_purges_term_unique_to_deleted_doc_everywhere
FAILED tests/unit/test_index.py::test_delete_on_sole_holder_drives_df_to_zero
FAILED tests/unit/test_index.py::test_absent_term_has_zero_df_and_empty_postings_no_exception
FAILED tests/unit/test_index.py::test_absent_term_on_empty_index_no_exception
FAILED tests/property/test_index_properties.py::test_property_every_doc_retrievable_via_each_distinct_term
FAILED tests/property/test_index_properties.py::test_property_delete_purges_everywhere
FAILED tests/property/test_index_properties.py::test_property_df_equals_number_of_docs_containing_term
============================== 15 failed in 0.31s ==============================
```

## Notes for the Implementation Agent

- Do not edit `tests/unit/test_index.py` or `tests/property/test_index_properties.py`
  to make them pass — these tests are frozen. Escalate genuine ambiguities to
  the orchestrator/Reviewer instead.
- Honor `InvertedIndex.build(docs, analyzer=None)` exactly: when `analyzer`
  is `None`, call the real `onrecord.analysis.analyzer.analyze`; when a
  callable is passed, use it instead. Do not special-case the tests' trivial
  analyzer.
- Honor the pinned id scheme: internal ids assigned once, in `docs` list
  order, at `build()` time; stable across `delete` (no renumbering of
  survivors). `Postings.doc_ids` must be returned sorted ascending.
- `save`/`load` must round-trip `df`, `postings` (including `positions`,
  per-doc, aligned with `doc_ids`), `doc_count`, and every `get_doc` exactly,
  including across a prior `delete`.
- `delete` on an unknown id: behavior unspecified by the ticket/AC text and
  not tested here — pick something sane (e.g. `KeyError`) and document it if
  it matters for T-004+.

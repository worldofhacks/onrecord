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

---

# Addendum — frozen-contract extension per code review findings

**Trigger:** `.tdd-swarm/reports/T-003-review.md` (Reviewer + Security,
verdict APPROVED, 0 Critical / 3 Important / 4 Minor) flagged three
forward-compat gaps in "the core data structure of the whole engine" that
don't violate any T-003 AC today but block/complicate T-004 and the BM25
ticket. The orchestrator directed the Test Agent to extend the frozen suite
with failing tests for the API additions that resolve them. Same worktree,
same rules (`tests/` only, `spec()` tags, ruff-clean, no push).

**What changed:** `tests/unit/test_index.py` only — 9 new tests appended
(module docstring also extended with a new "FROZEN-CONTRACT EXTENSION"
section documenting the 3 additions below). The original 15 tests
(`tests/unit/test_index.py` + `tests/property/test_index_properties.py`)
are byte-for-byte unchanged and all still pass. No implementation files
touched this round.

## New contract surface (pinned, implementer must add)

1. **`get_doc(id)` accepts internal int ids** (review Important #1): in
   addition to the existing external `str` id lookup, `get_doc` must accept
   any `int` that appears in `postings(term).doc_ids` and resolve it to the
   correct `Doc`. The two id spaces are disjoint by Python type (`str` vs
   `int`) — dispatch on `isinstance(id, int)` rather than coercing. `KeyError`
   on an unrecognized id holds in both spaces.
2. **`doc_length(internal_id) -> int`** and **`avg_doc_length() -> float`**
   (review Important #2): public accessors for the already-tracked
   `_doc_lengths` data (token count under the build-time analyzer per doc,
   and the mean over currently-live docs). Both must round-trip through
   `save()`/`load()`.
3. **`postings()` for an absent term must not share mutable state** (review
   Important #3): either return immutable containers (mutation raises
   `TypeError`/`AttributeError`), or ensure a caller's mutation of a
   previously-returned `Postings` object is never visible to a later
   `postings()` call — not for the same absent term, a different absent
   term, or any real term. A shared, by-reference mutable "empty postings"
   singleton (the current `_EMPTY_POSTINGS` pattern) fails this.

## New criterion → test mapping

| Criterion | Test(s) | What it checks |
|---|---|---|
| AC-2 (get_doc, internal ids) | `test_get_doc_accepts_internal_int_id_and_returns_correct_doc` | 2-doc fixture; `get_doc(0)`/`get_doc(1)` (build-order internal ids) return the right `Doc`; external `str` lookups still work unchanged |
| AC-2 | `test_get_doc_resolves_every_id_in_a_terms_postings` | Every int in `postings("substation").doc_ids` resolves via `get_doc` to a doc whose external id is one of the two fixture docs |
| AC-2 | `test_get_doc_disjoint_id_spaces_survive_adversarial_numeric_looking_external_ids` | Adversarial: external ids `"1"`/`"0"` deliberately mismatched against build-order internal ids `0`/`1`; asserts `get_doc` dispatches on Python type rather than coercing/comparing across the two id spaces |
| AC-2 | `test_get_doc_key_error_holds_for_both_int_and_str_id_spaces` | Unknown `str` id and unknown `int` id both raise `KeyError`. **Note:** this one already passes against the current implementation — an unrecognized `int` happens to raise `KeyError` today too, since it's simply absent from the `str`-keyed external map. Kept because it's a genuine, permanent part of the pinned contract (regression guard once `get_doc` gains real int-space resolution), not because it's currently red. |
| AC-1 (doc lengths) | `test_doc_length_returns_token_count_under_injected_analyzer` | 2-doc fixture with known token counts (3, 1); `doc_length(0)==3`, `doc_length(1)==1` |
| AC-1 | `test_avg_doc_length_is_mean_token_count_over_live_docs` | 3-doc fixture with token counts (3, 1, 2); `avg_doc_length() == 2.0` |
| AC-1 | `test_doc_length_and_avg_doc_length_survive_save_load_round_trip` | Build, save, load via `tmp_path`; `doc_length`/`avg_doc_length` identical before/after |
| AC-5 (postings isolation) | `test_postings_absent_term_doc_ids_mutation_does_not_leak` | Attempts `postings(absent).doc_ids.append(999999)`; if it raises `TypeError`/`AttributeError`, immutable design accepted immediately; otherwise asserts the mutation is invisible to a later call for the same absent term, a different absent term, and a real term's postings. Reverts the mutation in a `finally` block regardless of outcome so a red result can't cascade into unrelated tests later in the same pytest session |
| AC-5 | `test_postings_absent_term_positions_mutation_does_not_leak` | Same pattern for `postings(absent).positions.append(...)` |

9 new test items (8 unit-level behavioral additions + 1 already-passing
regression guard), on top of the original 15 — **24 total** in
`tests/unit/test_index.py` + `tests/property/test_index_properties.py`.

## Verification performed (this round)

1. Ran the extended suite against the current worktree (post-T-003
   implementation, commit `db916f8`) — **8 of 9 new tests fail**, each for
   the expected reason (`AttributeError: 'InvertedIndex' object has no
   attribute 'doc_length'` / `'avg_doc_length'`; `KeyError: 0` for
   `get_doc(0)` not yet resolving internal ids; `AssertionError` on the two
   postings-isolation tests, demonstrating the actual singleton-sharing bug
   the review flagged). The 9th (`..._key_error_holds_for_both_...`) passes
   already — documented above, not vacuous, kept as a permanent regression
   guard. **The original 15 tests all still pass** — confirmed no
   regression/pollution from the new tests.
2. Cross-test-pollution fix: the two mutation tests initially DID cause the
   unrelated property tests (`test_property_delete_purges_everywhere`,
   `test_property_df_equals_number_of_docs_containing_term`) to fail too,
   because appending to the current implementation's shared
   `_EMPTY_POSTINGS` singleton corrupts it for the rest of the pytest
   process (a direct, reproduced demonstration of review Important #3).
   Fixed by wrapping each mutation test's assertions in `try`/`finally` that
   best-effort reverts the mutation (`.pop()`) after checking, regardless of
   pass/fail, so a red result stays localized to its own test.
3. Built a small patch on top of the current implementation (not committed;
   restored immediately after) adding: `get_doc` int-id dispatch,
   `doc_length`/`avg_doc_length` accessors over the existing
   `_doc_lengths`, and a `postings()` that constructs a fresh empty
   `Postings` per call instead of returning the shared `_EMPTY_POSTINGS`
   singleton. Reran the full extended suite: **all 24 pass**. Confirms the
   9 new tests are achievable, not vacuously red, with a minimal,
   review-aligned fix.
4. Restored `onrecord/index/inverted.py` to its exact committed state
   (`git diff --stat -- onrecord/index/inverted.py` empty) — this round
   touches tests only.
5. `uv run ruff format --check tests/` / `uv run ruff check tests/` — both
   clean.
6. `uv run pytest -q` (full repo suite) — **30 passed, 8 failed**, matching
   expectations (29 previously-passing + 1 newly-passing regression guard =
   30; the 8 new review-driven tests red).

## Failure output (current worktree, this round's RED)

```
tests/unit/test_index.py::test_get_doc_accepts_internal_int_id_and_returns_correct_doc FAILED
tests/unit/test_index.py::test_get_doc_resolves_every_id_in_a_terms_postings FAILED
tests/unit/test_index.py::test_get_doc_disjoint_id_spaces_survive_adversarial_numeric_looking_external_ids FAILED
tests/unit/test_index.py::test_get_doc_key_error_holds_for_both_int_and_str_id_spaces PASSED
tests/unit/test_index.py::test_doc_length_returns_token_count_under_injected_analyzer FAILED
tests/unit/test_index.py::test_avg_doc_length_is_mean_token_count_over_live_docs FAILED
tests/unit/test_index.py::test_doc_length_and_avg_doc_length_survive_save_load_round_trip FAILED
tests/unit/test_index.py::test_postings_absent_term_doc_ids_mutation_does_not_leak FAILED
tests/unit/test_index.py::test_postings_absent_term_positions_mutation_does_not_leak FAILED

Representative failure reasons (uv run pytest tests/unit/test_index.py tests/property/ -v):
  AttributeError: 'InvertedIndex' object has no attribute 'avg_doc_length'
  AttributeError: 'InvertedIndex' object has no attribute 'doc_length'
  KeyError: 0                                    (get_doc(0) not yet resolving internal ids)
  AssertionError: mutating postings(absent_term).doc_ids leaked into a later
    postings() call for the SAME absent term — shared mutable state
  AssertionError: mutating postings(absent_term).positions leaked into a later
    postings() call for the SAME absent term — shared mutable state

========================= 8 failed, 16 passed in 0.74s =========================
(16 passed = 15 original T-003 unit tests + the 1 already-satisfying new test;
 tests/property/test_index_properties.py's 3 tests are unaffected/still green.)
```

## Notes for the (next) Implementation Agent

- The 3 additions above are new frozen contract surface, same status as the
  original AC-1..AC-5 tests: do not edit the tests to make them pass.
- `get_doc`'s type-dispatch must not coerce — an external id that happens to
  look numeric as a string (e.g. `Doc.id == "0"`) must never resolve via the
  internal-int path, and vice versa. Dispatch on `isinstance(id, int)` (or
  equivalent), not on stringifying/parsing.
- `doc_length`/`avg_doc_length` should read from the existing `_doc_lengths`
  data already maintained at `build()`/`delete()`/`save()`/`load()` — no new
  serialization format needed, just accessors.
- For postings isolation, the minimal fix is to stop returning one shared
  module-level "empty postings" object for absent terms — construct a fresh
  one per call (or freeze the containers). Either satisfies the tests.

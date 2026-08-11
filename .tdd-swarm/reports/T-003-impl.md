# T-003 Implementation Agent Report — Inverted Index

**Status:** DONE (initial impl `db916f8` + reconciled-contract fix round, this commit)

**File touched:** `onrecord/index/inverted.py` only (in-scope: `onrecord/index/**`).
No edits to `tests/`, `onrecord/analysis/`, or anywhere outside file scope.

## Fix round — reconciled contract (review findings + orchestrator adjudication)

Review (`.tdd-swarm/reports/T-003-review.md`) APPROVED the initial impl
(`db916f8`) with 0 Critical / 3 Important forward-compat findings. The
orchestrator additionally adjudicated a real id-space collision between
T-003's stub and T-004's frozen `FakeIndex` contract (`.tdd-swarm/LESSONS.md`,
2026-08-11 T-003/T-004 entry): canonical `get_doc` must accept **both**
internal int ids and external str ids. The Test Agent froze all of this as
8 new failing tests (+1 pre-existing-pass regression guard) at `17af676`,
extending `tests/unit/test_index.py`. Fixed as follows:

1. **`get_doc(id: str | int)`** — dispatches on Python type: `int` looks up
   `self._docs` directly (the internal-id space, same ints as
   `postings(term).doc_ids`); `str` looks up via `self._id_to_internal` as
   before (external-id space). `KeyError` on an unknown id in either space.
   The two spaces are genuinely disjoint by type, so a numeric-looking
   external id (e.g. `"0"`) can never collide with an internal id.
2. **`doc_length(internal_id: int) -> int`** and
   **`avg_doc_length() -> float`** — public accessors over the
   already-stored `_doc_lengths` map (populated at `build()`, maintained at
   `delete()`, already round-tripping through `meta.msgpack`); no new
   storage or serialization logic needed, just the getters. `doc_length` on
   an unknown internal id raises `KeyError`; `avg_doc_length()` on an empty
   index returns `0.0`.
3. **Postings isolation for absent terms** — replaced the module-level
   `_EMPTY_POSTINGS` mutable singleton with a `_empty_postings()` factory
   that allocates a fresh `Postings(array("q"), array("q"), [])` on every
   call. `postings()` for a real term still returns the live internal object
   by reference (unchanged; not required by any test, called out as a
   residual forward-looking note below, same as review's Important #3
   caveat for real terms).

All 3 fixes are additive/local to `onrecord/index/inverted.py`; no change to
`build()`'s tokenization, `save`/`load`'s on-disk layout, or `delete()`'s
purge logic (delete already maintained `_doc_lengths` correctly for the new
getters to expose).

## What was implemented

`InvertedIndex` fully implements the T-001/T-003 contract as extended by the
Test Agent (`build(cls, docs, analyzer=None)`):

- **Postings**: a small `__slots__` class holding `doc_ids` (`array('q')`,
  sorted ascending, deduped), `tfs` (`array('q')`, aligned with `doc_ids`),
  and `positions` (`list[array('q')]`, one per `doc_ids` entry, values =
  analyzer token indices). Structural `__eq__`/`__repr__` added for
  convenience (not required by tests, harmless).
- **Internal id scheme**: assigned once at `build()` time in input-list order
  (`docs[i]` -> internal id `i`), stable across `delete` (no renumbering of
  survivors) — matches the Test Agent's pinned schema assumption.
- **build()**: when `analyzer is None`, lazily imports and calls
  `onrecord.analysis.analyzer.analyze` (not exercised by any test tonight,
  per the isolation note — T-002 is still a stub in this worktree); otherwise
  uses the injected callable. Tokenizes each doc once, groups token indices
  by term, and bulk-converts to sorted parallel arrays (input order already
  yields ascending internal ids per term, so no extra sort needed).
- **df/postings**: O(1) dict lookups; absent terms return `0` / a shared
  empty `Postings` singleton — no exceptions (AC-5).
- **get_doc/doc_count**: backed by an external-id -> internal-id map and an
  internal-id -> `Doc` map; `get_doc` on an unknown/deleted id raises
  `KeyError` (also what `delete` raises for an unknown id — undocumented by
  the ticket, picked `KeyError` per the Test Agent's suggestion).
- **delete()**: removes the doc from both id maps and `_doc_lengths`, then
  scans every term's postings, binary-searches (`bisect_left`, arrays are
  sorted) for the victim's internal id, and splices it out of `doc_ids`/
  `tfs`/`positions` together; a term whose postings become empty is dropped
  entirely from `_postings` and its `df` set to `0` (AC-4, including the
  "purged everywhere" empty-postings case).
- **doc lengths**: stored at build time (`_doc_lengths: dict[int, int]`,
  token count per internal id) per the ticket's "BM25 needs them Wednesday —
  store, don't compute elsewhere" instruction. Not yet exposed via a public
  accessor since no AC/test calls for one — flagging for whoever picks up
  BM25 to add a getter rather than re-deriving lengths.
- **save/load**: directory-based. `postings.npy` holds one flat `int64`
  numpy array with every term's `doc_ids` + `tfs` + per-doc `positions`
  concatenated back-to-back; `meta.msgpack` records per-term offsets/lengths
  into that array plus `df`, doc-length map, id maps, and the next-internal-id
  counter; `docs.msgpack` holds every live `Doc`'s fields keyed by internal
  id. `load()` reconstructs `Postings` by slicing the npy array at the
  recorded offsets. Round-trips df/postings(doc_ids/tfs/positions)/doc
  store/doc_count exactly, including across a prior `delete` (AC-3).

No `rank_bm25` import anywhere in `onrecord/index/`. `onrecord/analysis/`
untouched.

## Test results

```
uv run pytest tests/unit/test_index.py tests/property/ -v
```
**24 passed** (21 unit + 3 hypothesis property, 40 examples each) — 0 failed.
(Initial impl: 15/15. Fix round added 9 new unit tests, 24/24 total.)

Full-suite regression check (`uv run pytest -q`): **38 passed** (24 T-003 +
14 pre-existing scaffold tests), 0 failed, 0 skipped.

## DoD sanity: 10K synthetic docs build time

Ad hoc script (200-word vocab, 20-60 whitespace tokens/doc, trivial
analyzer, outside `tests/`, not committed): **build 10,000 docs in 0.421s**
(well under the 30s sanity bound). Save/load of the resulting index: save
0.101s, load 0.173s (not a DoD requirement, included for context).

## Gates

`.tdd-swarm/run-local-gates.sh . tickets/T-003.md` (re-run after fix round):
```
== format ==  25 files already formatted
== lint ==    All checks passed!
== unit ==    38 passed in 0.84s
== spec-lint == spec-lint OK: all ACs covered for T-003
ALL LOCAL GATES GREEN
```
Manual todos/debug-statement gates (per `.tdd-swarm/gates.md`, not wrapped by
the script): `git diff | grep -E '(TODO|FIXME|HACK)'` and
`git diff | grep -E '(print\(|breakpoint\()'` both empty (checked against
the fix-round diff).

## Notes / things the next ticket should know

- `delete()` on an unknown external id raises `KeyError(id)` — undocumented
  by the ticket/ACs, chosen for symmetry with `get_doc`'s behavior. `delete`
  itself was NOT extended to accept internal int ids (not part of the
  reconciled contract / not requested by review or the Test Agent's
  extension — only `get_doc` needed dual-space dispatch, since T-004
  resolves postings matches via `get_doc`, not `delete`).
- Residual, not-yet-fixed forward-looking item from the review (Important
  #3, only partially addressed): `postings()` for a **real** (present) term
  still returns the live internal `Postings` object by reference, not a
  defensive copy — only the absent-term case was required to stop being a
  shared singleton, and that's what the reconciled test contract covers.
  Worth a follow-up if T-004/BM25 ever need to safely mutate a returned
  `Postings` in place (nothing today does).
- Review's Minor #1 (stale `df=0` dict entries left behind after a full
  purge in `delete()`) and Minor #3/#4 (save()'s double-materialization;
  `np.load` not pinning `allow_pickle=False` explicitly) were Minor, not
  Important, and out of scope for this fix round — not touched.
- No test disputes in either round; the frozen tests (including the
  reconciled-contract extension) and the pinned build-order id scheme were
  directly implementable with no ambiguity encountered.

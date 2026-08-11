# T-003 Implementation Agent Report — Inverted Index

**Status:** DONE

**File touched:** `onrecord/index/inverted.py` only (in-scope: `onrecord/index/**`).
No edits to `tests/`, `onrecord/analysis/`, or anywhere outside file scope.

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
**15 passed** (12 unit + 3 hypothesis property, 40 examples each) — 0 failed.

Full-suite regression check (`uv run pytest -q`): **29 passed** (15 T-003 +
14 pre-existing scaffold tests), 0 failed, 0 skipped.

## DoD sanity: 10K synthetic docs build time

Ad hoc script (200-word vocab, 20-60 whitespace tokens/doc, trivial
analyzer, outside `tests/`, not committed): **build 10,000 docs in 0.421s**
(well under the 30s sanity bound). Save/load of the resulting index: save
0.101s, load 0.173s (not a DoD requirement, included for context).

## Gates

`.tdd-swarm/run-local-gates.sh . tickets/T-003.md`:
```
== format ==  25 files already formatted
== lint ==    All checks passed!
== unit ==    29 passed in 0.93s
== spec-lint == spec-lint OK: all ACs covered for T-003
ALL LOCAL GATES GREEN
```
Manual todos/debug-statement gates (per `.tdd-swarm/gates.md`, not wrapped by
the script): `git diff | grep -E '(TODO|FIXME|HACK)'` and
`git diff | grep -E '(print\(|breakpoint\()'` both empty.

## Notes / things the next ticket should know

- `_doc_lengths` exists and is correct but has no public getter yet — add
  one (e.g. `doc_length(internal_id_or_doc_id)`) when BM25 lands rather than
  recomputing lengths from `Doc.text`.
- `delete()` on an unknown external id raises `KeyError(id)` — undocumented
  by the ticket/ACs, chosen for symmetry with `get_doc`'s behavior.
- No test disputes; the frozen tests and the Test Agent's pinned build-order
  id scheme were directly implementable with no ambiguity encountered.

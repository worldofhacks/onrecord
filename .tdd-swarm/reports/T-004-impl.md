# T-004 Implementation Agent Report — Boolean retrieval (AND/OR + phrase adjacency)

**Status:** DONE

## What was built

`onrecord/search/boolean.py` — only file touched (file_scope `onrecord/search/**`
honored; `onrecord/index/**` and `onrecord/analysis/**` untouched).

- Added the `analyzer: Callable[[str], list[str]] | None = None` keyword to
  both `boolean_search` and `phrase_search`, per the Test Agent's contract
  note in `.tdd-swarm/reports/T-004-test.md`. `None` lazily imports
  `onrecord.analysis.analyzer.analyze` inside `_resolve_analyzer` (deferred
  import, so this module never touches T-002's still-in-flight stub unless
  a caller actually omits `analyzer`).
- `boolean_search`: tokenizes `query` with the resolved analyzer; empty
  token list -> `[]` immediately (guards the "reduce over zero sets" trap
  called out in the test notes). Otherwise pulls `index.postings(term).doc_ids`
  per term and does a k-way sorted intersection (`AND`) or k-way union,
  deduplicated (`OR`), over the internal ids. Unknown `op` raises
  `ValueError` (not exercised by the frozen suite, but keeps the function
  honest rather than silently mis-behaving).
- `phrase_search`: tokenizes `phrase`; empty/single-token -> `[]`/no-op-safe
  return. For multi-term phrases, intersects postings doc_id sets to find
  AND-candidates, then for each candidate chases every occurrence of the
  first term's positions, requiring each subsequent term to appear at
  exactly `start + i`. This checks **all** stored positions per term (not
  just the first occurrence), satisfying the repeated-term and 3-word
  N-gram adversarial tests.
- Both functions resolve internal ids to `Doc`s via `index.get_doc(...)`
  and return `SearchResult(doc_id=doc.id, score=0.0, snippet=doc.text[:160])`
  — external string ids only, per AC guard on leaking internal ints.

## Verification

```
uv run pytest tests/unit/test_boolean.py -v   → 25 passed
.tdd-swarm/run-local-gates.sh . tickets/T-004.md → ALL LOCAL GATES GREEN
  == format ==  23 files already formatted
  == lint ==    All checks passed!
  == unit ==    39 passed (25 new + 14 baseline T-001 scaffold)
  == spec-lint ==  spec-lint OK: all ACs covered for T-004
```

Scope check: `git status --porcelain` shows only `onrecord/search/boolean.py`
modified. `tests/` untouched. Todo/debug scan on the diff
(`git diff -- onrecord/search/boolean.py | grep -nE '^\+.*(TODO|FIXME|HACK)'`
and the `print(`/`breakpoint(` equivalent) both empty.

## Notes / deviations

- One lint fixup needed after first pass: ruff's `UP035` wanted
  `Callable` imported from `collections.abc` instead of `typing` — fixed,
  no behavior change.
- No dispute with the frozen tests; the `analyzer=None` contract addition
  documented by the Test Agent was applied exactly as specified.

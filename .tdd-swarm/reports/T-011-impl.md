# T-011 Implementation Report — BM25 ranking (bm25_score + ranked_search)

**Status:** DONE — all 25 frozen tests in `tests/unit/test_bm25.py` pass; local gates green.

## Update (post-review fix — Important finding I-1)

Review flagged: `bm25_score(..., k1=0, ...)` raised `ZeroDivisionError` when
`tf=0` (denominator collapses to `tf` at `k1=0`, and `tf=0` is the ORDINARY
case for any OR-semantics `ranked_search` candidate that matches only a
subset of the query's terms — not a contrived direct-call-only edge case).
Test Agent extended `tests/unit/test_bm25.py` at commit `90cf5cc` with 4 new
tests pinning: `tf=0` → `0.0` at any `k1` (never raises); `tf>0` at `k1=0` →
pure IDF (saturation collapses to exactly `1.0`, independent of `tf`
magnitude and `b`); `avg_doc_len=0` → `0.0` (adjacent guard, same
division-by-zero shape); `ranked_search(k1=0)` on a partial-match
multi-term query completes and ranks by summed IDF of only the
actually-matched terms (tf=1 and tf=3 for the same term now tie).

Fix — a single guard clause at the top of `bm25_score`
(`onrecord/rank/bm25.py`), before the formula ever divides by anything
involving `tf`:

```python
if tf <= 0 or avg_doc_len <= 0:
    return 0.0
```

No changes to `onrecord/search/ranked.py` were needed — it already routes
every score through `bm25_score`, so the guard covers `ranked_search`'s
`k1=0` partial-match path automatically. All 25 tests pass (21 original +
4 new); local gates green (`208 passed` = prior `204` + 4 new).

## Files added (within ticket file_scopes)

- `onrecord/rank/__init__.py` — new package.
- `onrecord/rank/bm25.py` — `bm25_score(tf, df, N, doc_len, avg_doc_len, k1=1.5, b=0.75) -> float`,
  the ticket's exact probabilistic-IDF + tf-saturation/length-norm formula, no
  deviation:
  - `idf = ln(1 + (N - df + 0.5) / (df + 0.5))`
  - `saturation = tf * (k1 + 1) / (tf + k1 * (1 - b + b * doc_len / avg_doc_len))`
  - `bm25_score = idf * saturation`
- `onrecord/search/ranked.py` — new file (boolean.py and index code untouched):
  `ranked_search(index, query, k=10, k1=1.5, b=0.75, analyzer=None) -> list[SearchResult]`.

No other files modified. `git status` shows only the two new paths above.

## Implementation notes

- **Candidate set**: plain set union of `index.postings(term).doc_ids` across
  every analyzed query term (OR semantics) — a doc matching zero query terms
  never becomes a candidate, regardless of `k`.
- **Scoring**: per candidate, sum `bm25_score(tf, df, N, doc_len, avg_doc_len,
  k1=k1, b=b)` over every query term; `tf` for a term the doc lacks is looked
  up via `bisect_left` over the term's sorted `doc_ids` (0 if absent), so
  "term absent" naturally contributes 0 via the formula — no special-casing.
- **Top-k + tie-break**: `heapq.nsmallest(k, scored, key=lambda item: (-score,
  external_doc_id))` — ties broken by ascending external `Doc.id` string,
  never internal id or insertion/heap-pop order (matches the Test Agent's
  pinned convention in the test module docstring).
- **k1/b threading**: both are keyword parameters on `ranked_search` and are
  passed through to every `bm25_score` call — never silently defaulted
  internally (`test_ranked_search_k1_and_b_are_actually_threaded_through`
  exercises this directly).
- **Snippet**: token position -> character offset is reconstructed by
  re-scanning the doc's raw text with a word-token regex
  (`[^\W_]+`, mirroring `onrecord.analysis.analyzer`'s own tokenizer pattern)
  and taking the `token_position`-th match's span; this lines up exactly with
  both the trivial test analyzer (`text.lower().split()`, since the fixture
  text has no internal punctuation) and the real analyzer's tokenization.
  Window is `[match.start() - 80, match.end() + 80]`, clamped to
  `[0, len(text)]` — the clamp is what keeps the near-doc-start case a
  genuine prefix of `doc.text` rather than wrapping to the tail (Python's
  negative-index slicing footgun the Test Agent's docstring calls out
  explicitly). "First query-term position" is the minimum token position
  across *all* query terms present in that doc, not just the first term in
  the query string.
- `boolean.py` and `onrecord/index/inverted.py` were read for their public
  contracts (`postings`, `df`, `doc_count`, `doc_length`, `avg_doc_length`,
  `get_doc`) but not imported from or edited — `ranked.py` is self-contained,
  per the ticket's file scope.

## Gate results (final, post-fix)

```
$ uv run pytest tests/unit/test_bm25.py -v
25 passed in 0.29s

$ .tdd-swarm/run-local-gates.sh . tickets/T-011.md
== format ==  41 files already formatted
== lint ==    All checks passed!
== unit ==    208 passed, 1 warning in 3.96s
== spec-lint == spec-lint OK: all ACs covered for T-011
ALL LOCAL GATES GREEN
```

208 = the prior 204 (baseline through the initial T-011 implementation) + 4
new k1=0/avg_doc_len=0 boundary tests; no prior test regressed.

## Disputes

None. Both original ambiguities the Test Agent flagged (tie-break direction,
snippet char-offset mapping) were already resolved and pinned in the frozen
test file/docstring before this agent started; implementation followed
those pinned conventions directly. The post-review k1=0 boundary semantics
were likewise pinned by the Test Agent (commit `90cf5cc`) before this fix
was made — implementation followed the pinned semantics directly. No
`BLOCKED(TEST_DISPUTE)`.

## Out of scope (per ticket, not touched)

Differential vs `rank_bm25` (T-012), CLI/API wiring (T-013), k1/b sweep
tooling.

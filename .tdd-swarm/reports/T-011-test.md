# T-011 Test Agent Report — BM25 ranking (bm25_score + ranked_search)

**Status:** DONE (frozen failing tests written; confirmed RED against the current
worktree, which has no `onrecord/rank/bm25.py` or `onrecord/search/ranked.py`;
confirmed GREEN against a throwaway reference implementation built and run
outside the worktree, then deleted — never committed; `git status` shows zero
diff outside `tests/`).

**Test file:** `tests/unit/test_bm25.py` (new; `tests/unit/__init__.py` already
existed from T-001, not modified).

**Run command:**
```
uv run pytest tests/unit/test_bm25.py -v
```

## Isolation approach

Per the ticket's own framing, T-010's merged engine (analyzer, `InvertedIndex`
with df/positions/doc_length/avg_doc_length dual-space `get_doc`, boolean
search) is all real. Every test here builds real `InvertedIndex` instances via
`InvertedIndex.build(docs, analyzer=TRIVIAL_ANALYZER)` — only tokenization is
swapped for a trivial `text.lower().split()` (same convention as T-003/T-004's
suites), so every df/tf/doc_length/avg_doc_length stat consumed by the
formula-level assertions comes from the real, merged index, not a fake.

Only `onrecord.rank.bm25` and `onrecord.search.ranked` (this ticket's targets,
which don't exist yet — no stubs) are import-guarded via
`_require_module_spec` + `pytest.fail`, the established pattern from
`tests/unit/test_judgments.py` / `tests/unit/test_scaffold.py`: a missing
module fails cleanly per-test, never as a collection error for the whole file.

## Contracts pinned (module docstring of test_bm25.py — authoritative for the
implementer)

Signatures pinned verbatim from the ticket:
```
bm25_score(tf, df, N, doc_len, avg_doc_len, k1=1.5, b=0.75) -> float
ranked_search(index, query, k=10, k1=1.5, b=0.75, analyzer=None) -> list[SearchResult]
```
`idf = ln(1 + (N-df+0.5)/(df+0.5))`; `saturation = tf*(k1+1)/(tf+k1*(1-b+b*doc_len/avg_doc_len))`;
`bm25_score = idf * saturation`.

Two ambiguous details the ticket leaves unpinned, resolved here (both verified
against the throwaway reference implementation before freezing):

1. **Tie-break direction** ("ties broken by doc id for determinism" — no
   direction given): pinned to **ascending external `Doc.id`** (the string on
   `SearchResult.doc_id`), never the internal integer id. AC-5's tie corpus
   (`doc_a`/`doc_m`/`doc_z`, three docs with byte-identical stats) is built in
   a **deliberately scrambled insertion order** (`doc_f, doc_d, doc_z, doc_a,
   doc_e, doc_m, doc_c, doc_b`) so internal ids for the tied group are `z=2,
   a=3, m=5` — NOT already ascending in external-id order — specifically to
   catch an implementation that ties-break on internal id or heap-pop/
   insertion order instead of the external id string. A top-k truncation test
   (`k=5`) additionally proves the tie-break is honored *through* truncation
   (only `doc_a` survives the cut among the three ties), guarding against a
   heap keyed on score alone.

2. **Snippet char-offset mapping** (`postings(term).positions` are token
   indices, not character offsets — some mapping is an unavoidable
   implementation detail the ticket doesn't specify byte-exactly): rather than
   pinning an exact slice formula, the snippet tests use marker words placed
   at generously-separated, verified distances from the query term (~33–49
   chars away — comfortably inside any reasonable ±80 window; ~289–305 chars
   away — comfortably outside it), so the tests are robust to small boundary-
   math differences while still failing hard on a naive "first N chars of the
   doc" snippet (boolean.py's pre-BM25 behavior) or a negative-index
   wraparound bug (`text[pos-80:...]` without clamping to 0, which in Python
   silently splices in tail-of-string content when `pos < 80`). A dedicated
   adversarial test puts the match at char offset 0 and asserts the snippet is
   a literal prefix of `doc.text`.

## Hand-computed values — never hardcoded decimals

Every expected score is computed at test time via a shared `_bm25_ref(...)`
helper (`math.log`, no magic decimal literals) and compared with
`pytest.approx`. For AC-5 (`ranked_search`), `_ref_doc_score(idx, ...)` reads
`N`/`df`/`doc_length`/`avg_doc_length`/`tf` straight off the **real**
`InvertedIndex` built for that test, so the "hand computation" is anchored to
the merged engine's own real stats, not values invented separately in the
test.

AC-5's 8-doc fixture corpus (all docs exactly 10 tokens ⇒ `avg_doc_len == 10.0`
exactly for every doc, isolating this AC to df/tf/OR-sum/top-k/tie-break
effects rather than length normalization) verified by hand:
`doc_d(1.814) > doc_c(1.270) > doc_e(0.944) > doc_b(0.542) > doc_a(0.325) ==
doc_m(0.325) == doc_z(0.325)`; `doc_f` (matches neither query term) is never a
candidate.

## Criterion → test mapping

| AC | Test(s) |
|---|---|
| guard | `test_bm25_module_is_importable`, `test_ranked_module_is_importable` |
| AC-1 (IDF ordering) | `test_bm25_score_lower_df_scores_strictly_higher`, `test_bm25_score_idf_component_matches_hand_computed_formula_exactly` |
| AC-2 (saturation) | `test_bm25_score_higher_tf_scores_higher`, `test_bm25_score_marginal_gain_shrinks_with_tf_saturation` |
| AC-3 (length norm / b knob) | `test_bm25_score_shorter_doc_scores_higher_with_default_b`, `test_bm25_score_b_zero_disables_length_normalization` |
| AC-4 (IDF positivity) | `test_bm25_score_stays_positive_when_df_exceeds_half_corpus[6,9,10]`, `test_bm25_score_idf_positive_even_when_term_in_every_document` (df==N boundary) |
| AC-5 (ranked_search order/top-k/tie-break) | `test_ranked_search_exact_score_order_matches_hand_computation`, `test_ranked_search_excludes_docs_matching_zero_query_terms`, `test_ranked_search_topk_truncation_respects_tiebreak`, `test_ranked_search_ties_broken_by_ascending_external_doc_id_not_insertion_order`, `test_ranked_search_k1_and_b_are_actually_threaded_through` (DoD: "k1/b exposed as parameters everywhere") |
| AC-6 (snippet) | `test_ranked_search_snippet_is_centered_on_first_query_term_occurrence`, `test_ranked_search_snippet_does_not_wrap_around_when_term_near_doc_start` (adversarial boundary case) |
| Property (ticket Test Plan) | `test_property_idf_strictly_decreases_as_df_rises` (hypothesis, tagged AC-1) |
| Property (ticket Test Plan) | `test_property_adding_a_query_term_occurrence_never_lowers_the_score` (hypothesis, tagged AC-2) |

21 test items total (12 deterministic bm25_score tests incl. 3 parametrized
cases, 7 ranked_search tests, 2 hypothesis properties), all individually
guarded against missing-module collection errors.

## Achievability verification (throwaway reference implementation)

Built a minimal reference `onrecord/rank/bm25.py` (the exact formula) and
`onrecord/search/ranked.py` (OR-candidate union, sum-of-per-term score,
`heapq.nsmallest` keyed on `(-score, external_doc_id)` for the top-k+tie-break,
token→char-offset mapping for the snippet) directly in the worktree, ran
`uv run pytest tests/unit/test_bm25.py -v` → **21 passed**, confirming every AC
and both properties are achievable exactly as specified. Then deleted
`onrecord/rank/` and `onrecord/search/ranked.py` entirely (`git status`
confirms zero diff outside `tests/`) and re-ran to confirm the RED state
returned.

## Run output

```
$ uv run pytest tests/unit/test_bm25.py -v
... 21 failed (all `Failed: onrecord.rank.bm25 missing` / `onrecord.search.ranked missing`
    via pytest.fail — never an ImportError/collection error) ...

$ uv run pytest -q -m "not slow"    # full repo suite
21 failed, 182 passed, 1 deselected in 3.49s
```

182 previously-passing tests stay green; only the 21 new T-011 tests fail,
cleanly, all via `pytest.fail` in the module-guard helper (confirmed by
re-running against the throwaway reference implementation, which flips all 21
to PASSED with zero other changes).

`.tdd-swarm/spec-lint.sh tickets/T-011.md` → `spec-lint OK: all ACs covered
for T-011`.

`uv run ruff format tests/` / `uv run ruff check tests/` both clean (ruff
format reformatted one line-length wrap in the new file on first pass; both
commands clean on the committed version).

## Notes / decisions for the Implementation Agent

- `ranked_search`'s candidate set is a **plain set union** of
  `postings(term).doc_ids` across all query terms (OR semantics) — a doc
  matching zero query terms must never appear in the output, confirmed via
  `test_ranked_search_excludes_docs_matching_zero_query_terms` (doc_f, k=10).
- The AC-5 fixture corpus deliberately holds every doc's length at exactly the
  corpus average (`doc_len == avg_doc_len == 10.0` for all 8 docs) so `b`
  contributes an identical constant factor to every candidate — this isolates
  AC-5 to df/tf/OR-sum/top-k/tie-break correctness without conflating it with
  AC-3's length-normalization concern (which is tested separately, directly
  against `bm25_score`).
- `test_ranked_search_k1_and_b_are_actually_threaded_through` guards
  specifically against an implementation that accepts the `k1`/`b` keywords
  (to satisfy the signature) but silently ignores them internally in favor of
  the 1.5/0.75 defaults — a plausible corner-cutting bug given the DoD's
  explicit "k1/b exposed as parameters everywhere" requirement.
- No `BLOCKED(TEST_DISPUTE)` — both ticket ambiguities (tie-break direction,
  snippet char-offset mapping) were resolvable by picking a reasonable,
  well-documented convention and verifying it against a throwaway reference
  implementation, rather than requiring escalation.

# OnRecord — Metrics Report

*Final-checkpoint consolidation (2026-08-14). Every number below is
reproducible from committed artifacts; provenance sidecars are cited
inline. Nothing here is estimated — where a number was estimated earlier
in the project, the measured replacement and the delta are both shown.*

## 1. Corpus

| Version | Documents | Jurisdictions | Sources | Snapshot |
|---|---|---|---|---|
| v1 (MVP, 2026-08-11) | 24,115 | 28 | 958 filings + 23,157 meeting segments | `corpus/v1/corpus.jsonl.gz` (tracked) |
| v2 (Early, 2026-08-13) | **289,536** | **51** | 958 filings + 288,578 meeting segments | `v2-artifacts` release asset, sha256 in `corpus/v2/manifest.json` |

## 2. The judgment set — and what it taught us

| Session | Queries | Rows | Labeler | Notes |
|---|---|---|---|---|
| 1 (hand) | 5 | 65 | owner | criterion-first, blind pooled |
| 2 | +10 (=15) | +190 | gpt-5.2 (owner-directed) | q1–q5 re-pooled against v2 |
| 3 | +85 (=100) | +1,105 | gpt-5.6-sol (owner-directed) | zero parse failures; session pack committed pre-pooling |
| 4 (repair) | =100 | +886 (=2,246) | gpt-5.6-sol | the semantic pooling arm (below) |
| 5 (T-054) | =100 | +1,390 (=**3,636**) | gpt-5.6-sol | the 3-large arm; zero parse failures |

Provenance: `evalsets/judgment-session-{2,3}-provenance.json`,
`judgment-session-4-provenance.json`. Grade distribution: 519×2, 413×1,
1,314×0.

**Finding 1 — pooling bias by corpus size.** When corpus-v2 (12×) first
replaced v1, BM25 *read* 0.171 against v1-pooled judgments: unjudged
documents flooded the top ranks and scored as non-relevant. Re-pooling
against v2 recovered the honest number. Both readings preserved in
`evalsets/scoreboard.jsonl`.

**Finding 2 — pooling bias by method.** The pool drew from grep + BM25 +
random; semantic retrieval's unique finds were never judged, so semantic
*read* 0.135 — a slander, not a measurement. Session 4 added a semantic
arm (`pool_candidates(semantic_fn=...)`, additive, frozen path pinned
bit-identical) and judged its 886 previously-unseen pairs. The repaired
numbers reordered the leaderboard (below).

## 3. Retrieval

| Configuration (corpus-v2) | P@5 | P@10 | R@10 | R@50 | MRR | NDCG@10 |
|---|---|---|---|---|---|---|
| Boolean OR (Day-1 baseline, 15q) | 0.000 | 0.000 | 0.000 | 0.000 | 0.001 | 0.000 |
| BM25 (15q, three-arm pool) | 0.840 | 0.693 | 0.710 | 0.929 | 0.956 | 0.751 |
| BM25 (100q, three-arm pool) | 0.470 | 0.392 | 0.689 | 0.846 | 0.618 | 0.558 |
| BM25 (100q, **four-arm pool**) | 0.488 | 0.409 | 0.425 | 0.602 | 0.644 | 0.449 |
| Semantic (100q, four-arm) | — | — | — | 0.644 | 0.670 | **0.538** |
| Hybrid RRF (100q, four-arm) | — | — | — | **0.928** | 0.644 | 0.431 |

- **Defended k1/b**: 121-cell sweep (k1∈[0,2.5], b∈[0,1]) is a plateau
  around the default; kept 1.5/0.75. Artifact:
  `artifacts/sweeps/k1b_ndcg10.json` (+curve PNG).
- **Reference differential**: 31 frozen tests, our BM25 vs `rank_bm25` on
  the identical analyzed token stream.
- **Bounded fusion (T-037)**: hybrid's frozen full-depth fusion cost
  7.8s/query on deploy hardware. `fusion_depth=2000` was differentially
  verified before shipping: **99.5% mean top-20 overlap (min 90%), 98/100
  identical top-10, NDCG@10 0.4309 vs 0.4315, 4.1× latency win**
  (`evalsets/t037-differential.json`).
- The `make eval` ≥0.5 lexical gate reads red (0.449) post-repair while
  semantic clears it — the gate was calibrated against the BM25-biased
  pool; its re-scope is an open owner decision (T-047), deliberately not
  made silently.
- **Embedding upgrade eval (T-054, 2026-08-14)**: `text-embedding-3-large`
  @ 3072 re-embed ($≈9.50) scored against a fifth pooling arm (its own
  semantic top-20, 1,390 novel pairs labeled by gpt-5.6-sol, zero
  failures; pool 2,246 → 3,636 rows). Same-pool comparison: semantic
  NDCG@10 **0.4614 → 0.5505 (+19.3%)**, hybrid **0.4245 → 0.4708
  (+10.9%)**, semantic R@50 0.574 → 0.752. The old-pool reading of
  3-large was 0.330 — Finding 2's mechanism, a +0.22 swing from judging
  the model's own arm. **Deployed 2026-08-14 (T-055, owner go)**: prod now
  serves the 3-large store; its rows were promoted to the deployed history
  and the deployed-scope gate reads **PASS at 0.5505**. Measured prod
  latency after the swap: semantic ~5.5s, hybrid ~6.0–6.5s (up from
  ~3–4s — the 2× wider matrix; within the 8s UI budget; Matryoshka
  truncation to 1536 is the documented latency lever if ever needed).
  Full table: `tickets/T-054.md`; histories:
  `evalsets/modes-scoreboard{,-3large}.jsonl`.

## 4. Grounding and the judge

- **Judge validation** (gpt-5-mini vs 36 gpt-5.6-sol-labeled claims over
  12 real answers; owner-directed labeler): **agreement 0.944**, gate 0.8
  — `evalsets/judge-validation-2026-08-13.json`. Validation *found two
  latent defects that had made the judge nonfunctional against the live
  API since it was built*: the gpt-5 family rejects the legacy
  `max_tokens` spelling (HTTP 400 on every call), and the 64-token output
  cap was fully consumed by hidden reasoning (every verdict empty). The
  judge had never produced a real verdict until validation forced it to.
- **Judged eval headline** (deployed retrieval config, hybrid k=8,
  fusion_depth=2000; claude-opus-5 generation; validated judge):
  **faithfulness 0.930 mean** across 12 answers, **12/12 unanswerable
  correctly refused, 0/12 false refusals**
  (`evalsets/judged-eval-2026-08-14.json`).

## 5. Mechanics-layer data (final checkpoint)

- **Form 4**: 3,832 filings → 8,307 insider transactions across 100
  tickers (`artifacts/form4/insider_transactions.jsonl`; parser pins the
  EDGAR XSL-wrapper gotcha).
- **Promise Ledger**: 1,527 commitments from 954 promise-dense docs;
  quotes enforced verbatim in code — 14 model outputs (0.9%) dropped for
  violating the substring pin (`evalsets/promises.jsonl` +
  `promises-provenance.json`). Measured spend ≈ $11.25.
- **Dodge Index**: 43 jurisdictions scored deterministically (frozen
  lexicon, per-1,000-docs rate, min 200 docs), full corpus scan 2.5s.

## 6. Costs

Measured, not estimated — see `docs/cost-analysis.md`. Total external AI
spend through the final checkpoint ≈ **$35–40** (embedding $1.47; labeling
sessions ≈ $4; promise extraction $11.25; answers/judging/evals the rest).
The Day-1 estimate was $20–50 for dev; landed inside it.

## 7. Honest limits

- The judgment set is ~97% LLM-labeled (owner-directed at each step,
  cross-family from the generator, full provenance) with the 65 hand
  labels as the human anchor. An owner spot-check remains open (OQ-6).
- The faithfulness validation labels are model-labeled (gpt-5.6-sol, same
  provider family as the judge, different tier) per owner directive —
  disclosed here and in the artifact.
- Verbatim promise quotes inherit caption dysfluencies ("the the the
  bonds…") — by design: the ledger quotes what the record says, exactly.
- Prices are daily closes (stooq/yahoo keyless chain).
- Receipt link-rot, measured by full census (11,004 videos, 2026-08-14):
  **0.98%** (108 dead links; `evalsets/linkhealth-2026-08-14.jsonl`). The
  captions remain in the corpus regardless; a 'source removed' UI
  treatment is the documented follow-up (T-036).

## 8. Corpus-v3 (2026-08-15, T-053 swap)

309,662 docs (+20,126: Legistar 18,337 — a new document type; captions
delta 1,304; filings 485 incl. 759 FTS-discovered accessions). Judgment
session 6: 1,037 novel v3 pairs (lexical+semantic arms), gpt-5.6-sol,
zero parse failures — pool 3,636 → 4,673 rows across six sessions.
Deployed-scope gate on v3: **PASS — semantic 0.521, hybrid 0.500,
lexical 0.444**. Numbers are not comparable to §3's v2-pool rows (pool
and corpus both changed; the honest pairing is same-pool-same-corpus).
Delta-embed cost $0.39; labeling ≈ $2. Provenance:
`evalsets/judgment-session-6-provenance.json`, build evidence:
`artifacts/v3/BUILD-REPORT.json`.

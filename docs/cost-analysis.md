# AI Cost Analysis — OnRecord

*Living document; actuals tracked from Day 1, projections finalized before submission.*

## Actual dev spend (running)

| Item | Cost | Notes |
|---|---|---|
| Claude Code (orchestrator + subagent dispatches, Days 1–3) | subscription | no per-token API billing |
| Corpus embedding (text-embedding-3-small, 289,536 chunks ≈ 74M tokens) | ~$1.47 at completion | MEASURED at $0.02/MTok from a 64-chunk sample, not estimated. The Day-1 "$3–8 for 24–40K chunks" guess was doubly wrong: the corpus grew 10.6× (v2) *and* the price-per-token guess was ~25× high. Includes the partial spend from three failed runs (input-limit 400, aggregate-cap 400, rate-limit 429 — see `tickets/T-030.md`/`T-031.md`); those died early, so waste was cents. |
| Answer generation (claude-opus-5) | ~$0.10 to date | ~$0.03/grounded answer measured live (≈2.5K input + ≈600 output tokens at $5/$25 per MTok); 3 live answers during smoke + browser pass. |
| Judgment labeling, session 2 (gpt-5.2, owner-directed) | ~$1–2 | 205 relevance calls (~1.2K input tokens each + reasoning output). Session 1 was hand-labeled ($0). Provenance: `evalsets/judgment-session-2-provenance.json`. |
| Judgment labeling, session 3 (gpt-5.6-sol, owner-directed) | ~$1–2 | 1,105 relevance calls, MEASURED 386K prompt + 27K completion tokens (terse grader, zero parse failures) — the 100-query expansion. Provenance: `evalsets/judgment-session-3-provenance.json`. |
| Faithfulness judge (gpt-5-mini) | <$0.01 | wire smoke only; real judged-eval runs pending owner hand labels (validation gate). |
| Data acquisition | $0.00 | EDGAR public domain; yt-dlp captions free; FMP free tier; stooq free |
| Hosting/infra | $0.00 | Railway free-tier service; local-first by design |

**Total external AI spend to date: ≈ $3–4** — the deterministic core stayed free by design; paid AI entered with the RAG extension exactly as planned, at roughly 1/10th of the original headline estimate because the estimate was reconciled against live pricing before the big run.

## Measured per-query unit costs (fills the projection method below)

| Query type | Tokens (measured) | Cost |
|---|---|---|
| Lexical search | 0 LLM tokens | $0 (pure index) |
| Semantic/hybrid search | 1 embedding call (~50–200 tokens) | ≈$0.000004 |
| Grounded answer (lexical retrieval) | ≈2.5K in / ≈600 out, claude-opus-5 | ≈$0.028 |
| Judged answer (adds gpt-5-mini per-claim verdicts) | +≈1.5K in / ≈100 out | +≈$0.0006 |
| Corpus re-embed (only on corpus version bump) | ≈74M tokens | ≈$1.47, amortized by content-hash cache (unchanged text is never re-billed) |

## Projection model (to finalize Thursday with measured token counts)
Assumptions to measure, not guess: avg AI questions/user/session, sessions/user/month, tokens per question type (retrieval-only vs grounded answer vs judged answer). Cost drivers at scale: generation tokens (dominant), embedding refresh on corpus updates (minor, cached by content hash), judge sampling rate (tunable — judge a %, not all).

| Scale | 100 users | 1K users | 10K users | 100K users |
|---|---|---|---|---|
| $/month (est.) | TBD | TBD | TBD | TBD |

Method: measure real per-query token costs on the finished RAG pipeline Thursday night, then fill this table with the assumption block above it.

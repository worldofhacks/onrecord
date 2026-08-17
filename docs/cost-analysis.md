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
| Judgment labeling, session 4 (gpt-5.6-sol) | ~$1–2 | 886 pairs — the pooling-bias repair (semantic arm). Provenance: `evalsets/judgment-session-4-provenance.json`. |
| Judgment labeling, session 5 (gpt-5.6-sol) | ~$2 | 1,390 pairs — the text-embedding-3-large arm (T-054). Provenance: `evalsets/judgment-session-5-provenance.json`. |
| Judgment labeling, session 6 (gpt-5.6-sol) | ~$2 | 1,037 pairs — the corpus-v3 arm (T-053). Provenance: `evalsets/judgment-session-6-provenance.json`. |
| Promise extraction (claude, 954 promise-dense docs → 1,527 verbatim commitments) | $11.25 | MEASURED; the single largest line item. See `evalsets/promises-provenance.json` and `tickets/T-040.md`. |
| Corpus re-embed (text-embedding-3-large @ 3072, 289,536 chunks) | ≈$9.50 | T-054 embedding upgrade; ≈73.5M tokens at $0.13/MTok. |
| Corpus-v3 delta embed (20,126 new chunks) | $0.39 | T-053; only new text billed — the content-hash cache copied 1,394 duplicate rows free. Evidence: `artifacts/v3/BUILD-REPORT.json`. |
| Faithfulness judge (gpt-5-mini) + judged eval | <$0.50 | judge validation (36 labeled claims, 0.944 agreement) plus the 12-answer judged eval. `evalsets/judge-validation-2026-08-13.json`, `evalsets/judged-eval-2026-08-14.json`. |
| Data acquisition | $0.00 | EDGAR public domain; yt-dlp captions free; ISO queues, EIA, EPA ECHO, Legistar all keyless; stooq/yahoo free |
| Hosting/infra | $0.00 | Railway free-tier service; local-first by design |

**Total external AI spend through final submission: ≈ $33** (itemized above;
±$3 on the four "~" rows). This document is the authority for spend —
`docs/metrics.md` §6 and `docs/self-eval.md` cite this table rather than
carrying their own figures.

The shape of the bill is worth stating plainly: embeddings and one extraction
pass account for ≈$22.6 of it, labeling ≈$9, and everything user-facing
(answers, judging) under $1. The deterministic core — ingest, index, BM25,
Dodge Index, promise quantities, outcome trails, 8-K typing, ISO joins — cost
$0 in API spend by design, which is why the paid surface stayed this small
across 66 tickets. The Day-1 headline estimate of $20–50 for development
held; the early "$3–4" reading in this file was simply written before the
promise-extraction and re-embed waves landed.

## Measured per-query unit costs (fills the projection method below)

| Query type | Tokens (measured) | Cost |
|---|---|---|
| Lexical search | 0 LLM tokens | $0 (pure index) |
| Semantic/hybrid search | 1 embedding call (~50–200 tokens) | ≈$0.000004 |
| Grounded answer (lexical retrieval) | ≈2.5K in / ≈600 out, claude-opus-5 | ≈$0.028 |
| Judged answer (adds gpt-5-mini per-claim verdicts) | +≈1.5K in / ≈100 out | +≈$0.0006 |
| Corpus re-embed (only on corpus version bump) | ≈74M tokens | ≈$1.47, amortized by content-hash cache (unchanged text is never re-billed) |

## Projection model (filled 2026-08-13 from measured per-query costs)

Assumptions (stated, not hidden): 5 grounded answers/user/month (demo-stage
engagement), 20 searches/user/month (lexical $0, semantic ≈$0.000004), judge
sampling on 10% of answers, one corpus re-embed per quarter amortized. The
dominant driver is generation ($0.028/answer measured); everything else is
noise until ~100K users. The env-gated rate limiter
(`ONRECORD_ANSWER_DAILY_CAP`, `ONRECORD_ANSWER_IP_HOURLY_CAP`) hard-caps the
worst case regardless of traffic.

| Scale | 100 users | 1K users | 10K users | 100K users |
|---|---|---|---|---|
| Grounded answers (5/user/mo × $0.028) | $14 | $140 | $1,400 | $14,000 |
| Searches + judge sampling + embed refresh | <$1 | ~$2 | ~$20 | ~$200 |
| **$/month (est.)** | **~$15** | **~$142** | **~$1.4K** | **~$14.2K** |

Levers at scale, in order of impact: cheaper generator tier for routine
questions (haiku-class ≈ 1/10th the cost), answer caching by
question-hash (civic questions repeat), judge sampling rate, and prompt-
cache reuse on the shared system/context prefix.

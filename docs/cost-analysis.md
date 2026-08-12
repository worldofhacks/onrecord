# AI Cost Analysis — OnRecord

*Living document; actuals tracked from Day 1, projections finalized before submission.*

## Actual dev spend (running)

| Item | Cost | Notes |
|---|---|---|
| Claude Code (orchestrator + ~30 subagent dispatches, Day 1) | subscription | ~4M subagent tokens Day 1; no per-token API billing |
| External LLM API calls | $0.00 | none yet — generation/judge arrive with RAG (Thu-Fri) |
| Embeddings | $0.00 | pending Extension; est. $3-8 for ~24-40K chunks (text-embedding-3-small class) |
| Data acquisition | $0.00 | EDGAR public domain; yt-dlp captions free; FMP free tier; stooq free |
| Hosting/infra | $0.00 | local-first by design |

**Total external AI spend to date: $0.00** (by design — the Day-1/2 core is deterministic engineering; paid AI enters with the RAG Extension).

## Projection model (to finalize Thursday with measured token counts)
Assumptions to measure, not guess: avg AI questions/user/session, sessions/user/month, tokens per question type (retrieval-only vs grounded answer vs judged answer). Cost drivers at scale: generation tokens (dominant), embedding refresh on corpus updates (minor, cached by content hash), judge sampling rate (tunable — judge a %, not all).

| Scale | 100 users | 1K users | 10K users | 100K users |
|---|---|---|---|---|
| $/month (est.) | TBD | TBD | TBD | TBD |

Method: measure real per-query token costs on the finished RAG pipeline Thursday night, then fill this table with the assumption block above it.

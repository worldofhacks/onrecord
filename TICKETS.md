# Tickets — onrecord-mvp (tonight, 23:59)

Posture: mvp · Issues mirroring: deferred (posture.md) · Branch: swarm/onrecord-mvp

## Wave 1
| id | title | status | deps | model |
|----|-------|--------|------|-------|
| T-001 | Scaffold: package, frozen interfaces, registry, Makefile | backlog | — | standard |

## Wave 2 (8 parallel — disjoint file scopes)
| id | title | status | deps | model |
|----|-------|--------|------|-------|
| T-002 | Analyzer (tokenize+normalize, shared index/query) | backlog | T-001 | cheap |
| T-003 | Inverted index (df, tf, positions; save/load/delete) | backlog | T-001 | standard |
| T-004 | Boolean retrieval (AND/OR + phrase) | backlog | T-001 | standard |
| T-005 | IR-metrics harness (P@k, R@k, MRR, NDCG; red) | backlog | T-001 | standard |
| T-006 | YouTube captions adapter (VTT→Doc, timestamps) | backlog | T-001 | standard |
| T-007 | EDGAR adapter (10-K/Q/8-K → sections) | backlog | T-001 | standard |
| T-008 | FMP transcripts adapter (timeboxed, fallback-safe) | backlog | T-001 | cheap |
| T-009 | Judgment tooling (pooling + blind judging CLI) | backlog | T-001 | standard |

## Wave 3
| id | title | status | deps | model |
|----|-------|--------|------|-------|
| T-010 | Integration: CLI e2e, corpus-v1 snapshot, clean-clone one-command | backlog | T-002..T-009 | standard |

## Non-ticket orchestrator/owner actions tonight
- After T-006/T-007 land: orchestrator launches full-breadth background pulls (captions all registry channels; EDGAR all registry tickers)
- ~22:00: corpus-v1 snapshot cutoff → build index → owner judges ≥5 queries via T-009 CLI (~30-40 min) → `make eval` prints RED scoreboard → commit
- MVP traceability: T-001→MVP-1 · pulls+T-006/7/8+T-010→MVP-2 · T-009+owner→MVP-3 · T-003→MVP-4 · T-004+T-010→MVP-5 · T-005→MVP-6 · T-010→MVP-7

## Blocked
| id | reason | attempts | needs |
(none)

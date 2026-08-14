# Tickets — onrecord

Issues mirroring: deferred (posture.md). Status transitions are orchestrator-owned; full audit trail in `.tdd-swarm/progress.md`.

---

## Epic 1 — onrecord-mvp (COMPLETE 2026-08-12; tag `mvp-checkpoint`) · Branch: swarm/onrecord-mvp

Posture: mvp · Tables below preserved as history. Waves 1-3 kept verbatim from the original plan (statuses were never regenerated post-run); waves 4-7 reconstructed from `.tdd-swarm/progress.md` — all done/merged, 314 tests green at handoff.

### Wave 1
| id | title | status | deps | model |
|----|-------|--------|------|-------|
| T-001 | Scaffold: package, frozen interfaces, registry, Makefile | backlog | — | standard |

### Wave 2 (8 parallel — disjoint file scopes)
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

### Wave 3
| id | title | status | deps | model |
|----|-------|--------|------|-------|
| T-010 | Integration: CLI e2e, corpus-v1 snapshot, clean-clone one-command | backlog | T-002..T-009 | standard |

### Waves 4-7 (history, reconstructed from progress.md — all merged)
| id | title | status | wave | deps | model |
|----|-------|--------|------|------|-------|
| T-011 | BM25 ranking — probabilistic IDF, ranked search + snippets | done | 4 | T-010 | standard |
| T-013 | FastAPI layer — /api/search, /api/tickers, /api/metrics (+T-013R re-pin) | done | 4 | T-010 | standard |
| T-014 | Prices layer — EOD cache, significant moves, /api/prices payload (+T-014R amendment) | done | 4 | T-010 | standard |
| T-012 | Differential vs rank_bm25 (identical token stream) | done | 5 | T-011 | standard |
| T-015 | Serve UI + /api/prices route + index bootstrap (Railway) | done | 6 | T-013, T-014 | standard |
| T-016 | Wire the design app to the live API | done | 6 | T-013, T-014 | capable |
| T-017 | GET /api/stats + hero strip live numbers | done | 7 | T-015, T-016 | cheap |

### Non-ticket orchestrator/owner actions (MVP, history)
- After T-006/T-007 land: orchestrator launches full-breadth background pulls (captions all registry channels; EDGAR all registry tickers)
- ~22:00: corpus-v1 snapshot cutoff → build index → owner judges ≥5 queries via T-009 CLI (~30-40 min) → `make eval` prints RED scoreboard → commit
- MVP traceability: T-001→MVP-1 · pulls+T-006/7/8+T-010→MVP-2 · T-009+owner→MVP-3 · T-003→MVP-4 · T-004+T-010→MVP-5 · T-005→MVP-6 · T-010→MVP-7

---

## Epic 2 — early-checkpoint + RAG extension · Branch: swarm/onrecord-early-rag (proposed)

Plan: `.tdd-swarm/reports/EPIC2-planner.md` (Revision 2 incorporates the adversarial review `.tdd-swarm/reports/EPIC2-plan-review.md` + orchestrator adjudications). Wave numbering continues globally. Only T-024 touches `onrecord/api.py` (api surface serialized — every RAG capability lands as a library first, T-014 precedent). **Deploy posture (adjudicated): this epic does NOT promote corpus-v2 or RAG to prod — prod stays corpus-v1 lexical; Dockerfile/.dockerignore untouched.**

### Wave 8 (5 parallel — disjoint file scopes; shared empty `onrecord/rag/__init__.py` across T-020/T-021/T-027 per the wave-2 auto-merge precedent)
| id | title | status | deps | model |
|----|-------|--------|------|-------|
| T-018 | Corpus-version manifest — `make ingest V=2 [RAW=…]`, checksummed manifest, versioned scoreboard rows | done | — | cheap |
| T-019 | k1/b sweep — NDCG@10 grid, curve artifact, defended-params docs | done | — | standard |
| T-020 | RAG chunking — alternate windowings + window/overlap recall sweep | done | — | standard |
| T-021 | Embeddings — provider adapter, id-keyed content-hash cache, fp16 store, cosine | done | — | standard |
| T-027 | Claim segmentation authority — rag/claims.py (grounding + judge) | done | — | cheap |

### Wave 9 (4 parallel)
| id | title | status | deps | model |
|----|-------|--------|------|-------|
| T-022 | Retrieval modes — semantic, hybrid RRF k=60, side-by-side report | done | T-018, T-020, T-021 | standard |
| T-023 | Grounded answer pipeline — citations, grounding, refusal (library) | done | T-020, T-027 | capable |
| T-025 | QA + unanswerable eval sets, refusal/false-refusal runner | done | T-018 | standard |
| T-026 | Cross-family faithfulness judge + hand-label validation gate | done | T-018, T-027 | standard |

### Wave 10 (2 parallel — disjoint: onrecord/api.py vs ui/**)
| id | title | status | deps | model |
|----|-------|--------|------|-------|
| T-024 | API unlock — live semantic\|hybrid, full /api/answer, 3 transitional re-pins | done | T-018, T-020, T-021, T-022, T-023 | capable |
| T-028 | Ask view wired to the real /api/answer — citations, grounding, refusal, 503 states | done | — (builds to the pinned contract; verified post-merge) | standard |

### Non-ticket orchestrator/owner actions (epic 2)
- **Judgment repair FIRST (adjudicated, plan-review C-4)**: re-pool + re-judge q1–q5 against corpus-v2 per `evalsets/judgment-session-2.md` §"FIRST: top up q1–q5" (already prepped, drift-guard-compatible resume) — HARD PRECONDITION for the official k1/b sweep run and every "Defended k1/b"/metrics README number. Measured context: BM25 NDCG@10 on v2 with v1-pooled judgments = 0.173 (pooling bias). The 0.5 NDCG gate stays as-is — still-red after re-judging is honest data, not a gate to weaken. Until then, ledger notes `make eval` exit-1 as EXPECTED on v2.
- **Corpus-v2 rebuild** (orchestrator, after T-018 merges): recreate the re-parse script from the old-scratchpad pattern (registry-slug matching; exclude `Loudoun_County_Board_of_Supervisors` dir) → `make ingest V=2 RAW=<parsed-raw-dir>` → re-run harness (rows tagged v2). Judged doc ids survive v2 verbatim — verified.
- **Owner labeling sessions**: ~10 more judged queries (Thursday gate, `python -m onrecord.eval.judgments`); ~10 faithfulness hand labels (T-026 schema); review T-025's unanswerable set + judgment-derived QA labels (OQ-6).
- **Post-provisioning eval runs** (blocked on keys — open questions 1-3): corpus-v2 embed with checkpointing (T-021, cost actuals → docs/cost-analysis.md), side-by-side modes report (T-022), refusal/false-refusal (T-025), judge validation then faithfulness (T-026), LOCAL uvicorn smoke + one measured full-depth lexical latency number (T-024, plan-review M-12), Ask-view browser checklist (T-028).
- **Sweep runs + docs fill** (orchestrator, after v2 rebuild AND the judgment repair above): k1/b sweep → README "Defended k1/b" numbers; chunking sweep → published curve (caption notes the identity-ships/window>1-deferred scope-cut, plan-review I-11).
- **Robustness-v2 verification** (orchestrator-operational, deliberately NOT a ticket — see planner report §D; measured 30/30 green on the real v2 index already): README "Robustness" section lands in the wave-10 integration commit.
- **Wave-10 integration checklist** (orchestrator-owned doc edits — plan-review I-2 resolution; ledger note per M-13: these are docs, not code fixes, hence Integration-Agent-legal): README API section (ONRECORD_EMBEDDINGS / ONRECORD_ANSWER_MIN_CONF / key env vars + T-024's env inventory); README overrides for running locally against v2 (`ONRECORD_CORPUS`/`ONRECORD_INDEX` — adjudicated I-3: defaults stay v1 this epic, fix is documentation); README stale teaser copy removed at unlock; README Deploy runbook 5-liner (adjudicated I-14): `railway up --service onrecord` from the repo root (service NOT git-connected), smoke `/health` + `/api/search?mode=lexical` + `POST /api/answer` mode=lexical, rollback = redeploy from a checkout of the previous known-good commit (`mvp-checkpoint` tag); "Defended k1/b" + robustness number fills.

### Deferred items (recorded decisions, not silent skips)
- **RAG-to-prod deploy — owner-gated, post-epic** (adjudicated C-1/C-2; tied to OQ-5): prod stays corpus-v1 lexical this epic. Measured facts for the owner's decision: v2 in-process bootstrap = 103 s / 8.1 GB peak RSS (exceeds normal healthcheck windows and plausible plan memory); the image would also need the embedding store (~0.78 GB fp16), which `.dockerignore` currently excludes. Options: (a) prebuilt index + store shipped in the image (kills the 103 s / 8.1 GB spike; needs a size budget + .dockerignore change), (b) bigger Railway plan + volume, (c) stay-v1 live demo with RAG demoed locally/CLI in the video.
- **Snapshot distribution >100 MB / git-lfs absent** (adjudicated I-4 → open question #7): recommendation attached — corpus/v1 stays committed (offline clean-clone guarantee, test_e2e.py pins it); corpus/v2 ships as a GitHub Release asset; manifest + sha256 checksums ARE committed (T-018's `snapshot_sha256`); `make ingest V=2 RAW=…` rebuilds locally from raw. LFS risk noted for the labs.gauntletai.com mirror (owner-managed).
- **corpus-v3 (Thu-Fri) / corpus-v4 (Sat freeze — final reported metrics run on v4 per spec §2.4/§8.2)** (adjudicated I-13): operational, owner+orchestrator, NOT tickets this epic. v4 freeze obliges: re-run k1/b + chunking sweeps, incremental re-embed (content-hash cache makes it delta-cost — count against OQ-3's budget), re-run modes/faithfulness numbers. Recording this here is the drift-gate answer for spec §2.4.

### Blocked
| id | reason | attempts | needs |
(none)

## Repairs & backlog (epic 2 close-out, 2026-08-13)
| id | title | status | origin |
|----|-------|--------|--------|
| T-029 | qa_eval real-seam test full-suite order dependence | done (merged wave-9 repair) | wave-9 integration |
| T-030 | embed input-limit guard (33 filing sections > 8K tokens) | done (merged wave-9 repair) | operational embed run 1 |
| T-031 | token-aware embedding request packing + Retry-After honoring | done | operational embed runs 2–3 |
| T-032 | /api/prices + /api/tickers async-def-sync-body (T-024 I-1 class) | done | T-024 fix round |
| T-033 | Mention-anchored ticker performance (paste.trade reference) | done | — | T-032, T-034 | standard |
| T-034 | Price source repair — yahoo keyless primary (stooq bot-walled) | done | repair | — | standard |
| T-035 | Remove ALL demo data from UI (search corpus + Ask illustrative) | done | repair | T-032 | standard |
| T-037 | Bounded fusion depth — hybrid 4x, differential evidence | done | repair | — | capable |
| T-038 | Form 4 ingestion (EDGAR insider transactions) | done | final-A | — | standard |
| T-039 | Confidence-vs-Conduct (insider net-flow join + UI) | done | final-A | T-038 | standard |
| T-040 | Promise Ledger (LLM-extracted commitments, Ledger tab live) | done | final-A | — | capable |
| T-041 | Dodge Index (deterministic evasion scoring) | done | final-A | — | cheap |
| T-042 | Judged-eval headline run (faithfulness + refusal rates) | done | final-A | — | standard |
| T-043 | Metrics report consolidation | done | final-B | T-042 | capable |
| T-044 | Self-eval vs rubric | done | final-B | T-043 | capable |
| T-045 | AI-LOG final pass | done | final-B | — | capable |
| T-046 | Pre-Search transcript re-export | done | final-B | — | cheap |
| T-047 | Eval-gate re-scope (owner decision) | done | final-B | — | cheap |
| T-048 | UX: warming page + rate-limit messaging | done | final-C | — | standard |
| T-049 | Chart polish: ranges + insider dots | done | final-C | T-038 | standard |
| T-050 | Search date filter + sort | done | final-C | — | standard |
| T-051 | Hearings on air: live/upcoming stream tracking | done | living | T-036 | standard |
| T-052 | Filings delta: EDGAR Atom poller | done | living | T-038 | standard |
| T-053 | Refresh lanes + corpus-v3 runbook (swap on owner go) | done | living | T-051, T-052 | standard |
| T-054 | Embedding upgrade eval: 3-large @ 3072 vs baseline | done | living | T-047 | standard |
| T-055 | Deploy 3-large store to production (owner go) | done | living | T-054 | standard |
| T-056 | Quantified promises (MW/gallons/jobs/$ extraction) | done | enrich-A | T-040 | standard |
| T-057 | Promise -> outcome tracking (follow-up trails) | done | enrich-A | T-056 | standard |
| T-058 | LLC shell resolution v1 (curated, receipted) | planned | enrich-B | T-033 | capable |
| T-059 | Grid interconnection queues (iso_queue source) | planned | enrich-B | T-057, research | standard |
| T-060 | 8-K event typing (material-events feed) | done | enrich-A | T-052 | standard |

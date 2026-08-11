# Pre-Search Document — OnRecord (RelevanceEngine, Assignment 02)

**Date:** 2026-08-11 · **Author:** Alexander Miller · **Method:** AI-interview per the assignment's Pre-Search methodology (Claude Code / Opus). The full AI conversation is saved in-repo as the reference document required by the assignment: [`docs/presearch-transcript.md`](presearch-transcript.md) (re-exportable via `scripts/export_presearch_transcript.py`).

**Product in one line:** *OnRecord* — a from-scratch search engine + RAG system over the AI-infrastructure buildout's public paper trail (county permitting meetings, utility earnings calls, regulatory dockets), where every answer carries a clickable receipt: a YouTube timestamp, an EDGAR anchor, or a docket page.

---

## Phase 1: Define Your Constraints

### 1. Scale & Load Profile
- **Users at launch / 6 months:** Solo research tool + public demo. Design point: 1-10 concurrent users; cost projections modeled at 100/1K/10K/100K users for the required AI Cost Analysis.
- **Traffic pattern:** Interactive, bursty, low volume. Retrieval must feel instant (target: lexical query p50 < 50ms, p99 < 200ms on ~0.5-1M retrieval units, in-process).
- **Real-time vs. batch:** Ingestion is batch (scripted pulls, run per corpus version). Search/QA is interactive. No streaming requirements.
- **Cold-start tolerance:** High. Index deserializes from disk at startup (seconds); acceptable for a CLI/local API.

### 2. Budget & Cost Ceiling
- **Monthly spend limit (dev week):** ≤ $100 total AI spend.
  - Embeddings: ~0.5-1M chunks × ~250 tokens ≈ 125-250M tokens ≈ $3-30 one-time per corpus freeze (model-dependent; content-hash cache makes re-freezes incremental).
  - Generation + LLM-judge during dev/eval: ~$20-50.
  - Infra: $0 (local-first; in-memory index; no vector DB, no hosted search).
- **Pay-per-use vs. fixed:** Pay-per-use APIs. No fixed-cost services.
- **Money-for-time trades:** Use hosted embedding/LLM APIs instead of local models; use free-tier transcript sources with documented fallbacks rather than paid data vendors.

### 3. Time to Ship
- **MVP timeline:** Tonight, 2026-08-11 23:59 (Day-1 checklist: design doc, corpus-v1 loaded, ≥5 labeled queries, inverted index, boolean retrieval, red metrics harness, one-command run).
- **Checkpoints:** Early Submission Thu 2026-08-13 23:59 (BM25 + full IR metrics + reference differential). Final Sun 2026-08-16 **11:59 AM** (tuning, robustness, RAG, reports).
- **Speed vs. maintainability:** Speed-to-checkpoint wins all ties, protected by the eval harness (the harness is what makes fast iteration safe).
- **Iteration cadence:** Daily: change → `make eval` → compare scoreboard → commit with metrics in the message.

### 4. Compliance & Regulatory Needs
- **HIPAA / health data:** N/A — no health data.
- **GDPR / EU users:** N/A — no accounts, no PII collected; corpus is public-record content.
- **SOC 2 / enterprise:** N/A — course project.
- **Data residency:** N/A.
- **Data-source posture (the real compliance surface):** Government meeting recordings and regulatory filings are public records; EDGAR is public domain. YouTube captions are fetched via yt-dlp for research use — the repo stores derived artifacts (index, chunk snippets with deep links, metadata), not wholesale redistributed transcripts; every retrieval unit links back to its source. Earnings-call transcripts come from free public sources with per-source attribution; if a source's terms are restrictive, the fallback is SEC 8-K prepared-remarks exhibits + fewer tickers (documented in the adapter).

### 5. Team & Skill Constraints
- **Solo or team:** Solo + AI agents (AI-first development is an explicit assignment requirement).
- **Languages known well:** TypeScript/Node (strongest), Python (working), Rust (working).
- **Choice & learning appetite:** **Python** — deliberately, as a career investment in RAG pipelines: the pipeline layer (embeddings, rerankers, eval tooling, judge loops) lives in Python across industry and research. Rust was considered for the performance flex and rejected: this assignment is 80% pipeline-and-evals by weight, and Rust's payoff is in engine infrastructure, not pipelines. TypeScript remains available for an optional demo UI only.

## Phase 2: Architecture Discovery

### 6. Hosting & Deployment
- **Model:** Local-first. CLI + thin FastAPI wrapper on localhost. Optional deploy (Fly.io/Railway single container) only if the weekend has slack; the assignment's "deployed link" requirement applies to web products, and the graded surface here is CLI + harness.
- **CI/CD:** GitHub Actions runs `make test` and `make eval` on push — the metrics harness in CI is the regression gate.
- **Scaling characteristics:** Single process, in-memory index. Documented scale path (not built): memory-mapped postings, sharding by source-type, ANN index past ~1M vectors.

### 7. Authentication & Authorization
- N/A — read-only public-data demo; no accounts, no RBAC, no multi-tenancy. (Assignment scope: search quality, not user management.)

### 8. Database & Data Layer
- **Database:** None. Filesystem is the store:
  - `corpus/vN/` — immutable versioned snapshots: raw pulls + normalized JSONL (one retrieval unit per line with `{id, text, ticker?, jurisdiction?, speaker?, venue_type, date, source_type, deep_link}`).
  - `artifacts/` — serialized inverted index (JSON/msgpack), embedding matrix (`.npy`), eval scoreboard history (JSONL).
- **Full-text search:** Hand-built — that *is* the product (inverted index + BM25 from scratch; reference library used only as a test oracle).
- **Vector storage:** numpy matrix + brute-force cosine — exact, fp16, fast to ~300K chunks. Past that threshold, a lightweight ANN (hnswlib) with a measured recall-vs-exact check — a documented, measured choice either way, never a default.
- **Caching:** Embedding cache keyed by content hash (never re-embed unchanged chunks across corpus versions).
- **Read/write ratio:** Read-heavy; writes are batch ingestion only.

### 9. Backend / API Architecture
- **Shape:** Monolith — single Python package `onrecord/` with modules `ingest / analysis / index / search / rank / eval / rag`.
- **API style:** CLI first (graded surface), FastAPI thin wrapper second (demo surface). REST, three endpoints max (`/search`, `/answer`, `/health`). No GraphQL/tRPC/gRPC.
- **Background jobs / queues:** None — ingestion is idempotent scripts run per corpus version.

### 10. Frontend Framework & Rendering
- **Required:** None — CLI + API is the graded surface.
- **Optional (Saturday, time-permitting):** one static HTML/JS page over the API for the demo video: search box, mode toggle (lexical/semantic/hybrid), results with highlighted snippets + deep links, answer pane with citations.
- **SEO / SSR / PWA / offline:** N/A.

### 11. Third-Party Integrations
| Service | Role | Pricing cliff / rate limits | Fallback / lock-in |
|---|---|---|---|
| yt-dlp | County-meeting + investor-day captions | Free; polite pacing, pinned version | Channel RSS + manual caption pulls; adapter-isolated |
| SEC EDGAR | 10-K/10-Q/8-K, Form 4, full-text search | Free, public domain; 10 req/s guideline | None needed |
| Motley Fool / FMP | Earnings-call transcripts | Free tier caps | 8-K prepared-remarks exhibits + reduced ticker list |
| State PUC / FERC / ERCOT / PJM portals | Dockets, testimony, interconnection queues | Free public records; scrapers are per-portal | Reduce jurisdictions; corpus tiers absorb variance |
| Embedding API (OpenAI text-embedding-3-small or Voyage) | Semantic retrieval | ~$0.02-0.13 / 1M tokens | Adapter interface; matrix rebuildable |
| Anthropic Claude (generation) + OpenAI (judge) | RAG answers; faithfulness judging | Per-token; judge from a **different model family** than generator per assignment | Swappable via adapter |

- **Vendor lock-in risk:** Low everywhere — every external touchpoint sits behind a small adapter; corpus artifacts are plain JSONL/npy.

## Phase 3: Post-Stack Refinement

### 12. Security Vulnerabilities
- **Known pitfalls for this stack:** injection via scraped text into LLM prompts (treat all corpus text as untrusted data; instruct-and-delimit in RAG prompts; never execute corpus content); yt-dlp supply chain (pin version, hash-lock); malformed PDFs (parse in-process with defensive limits, no shelling out to untrusted args).
- **Secrets:** `.env` only, never committed; keys are per-provider.
- **Misconfigurations to avoid:** FastAPI bound to localhost by default; no dynamic eval of query strings (boolean parser is a hand-rolled tokenizer, not `eval`).

### 13. File Structure & Project Organization
```
onrecord/            # single package (monorepo, single project)
  analysis/          # tokenizer/normalizer — ONE function used at index AND query time
  ingest/            # per-source adapters: youtube.py, edgar.py, transcripts.py, dockets.py
  index/             # inverted index: postings (doc_id, tf, positions), df, serialization
  search/            # boolean AND/OR + phrase/proximity via positions
  rank/              # BM25 (probabilistic IDF), top-k heap, snippets
  eval/              # judgment sets, precision@k/recall@k/MRR/NDCG, differential, properties, robustness
  rag/               # chunking, embeddings, lexical|semantic|hybrid retrieve, answer, faithful, refusal
corpus/v1..vN/       # immutable versioned snapshots (JSONL)
evalsets/            # judgments.jsonl, qa.jsonl, unanswerable.jsonl, judge_handlabels.jsonl
scripts/             # ingest_v1.sh … one script per corpus version
docs/                # presearch.md, this design's spec, metrics reports, AI-LOG.md
tests/               # unit, property (hypothesis), differential, robustness
Makefile             # make setup / test / eval / ingest / demo — one command each
```

### 14. Naming Conventions & Code Style
- Python: `snake_case`, type hints throughout, dataclasses for records.
- Tooling: `ruff` (lint + format), `uv` (env + deps), Python 3.12.
- Commits: conventional-ish, with the eval scoreboard delta pasted into any commit that touches ranking.

### 15. Testing Strategy
- **Unit (pytest):** analyzer, postings merge, BM25 components, RRF.
- **Property (hypothesis):** IDF strictly decreases as df rises; index→search round-trip returns the doc; delete removes the doc from every posting list; a doc gaining a query term never ranks below an otherwise-identical doc lacking it.
- **Differential / oracle-diffing (the assignment's core discipline):** our BM25 vs. `rank_bm25` on the identical analyzed token stream — same tokens in, scores within tolerance, top-k ranking agreement. Feeding the reference the *same tokens* is what isolates the ranking math from tokenizer differences.
- **Robustness suite:** empty query, stopword-only, unicode/emoji/CJK, very long docs, absent terms — zero crashes, index integrity preserved.
- **IR-metrics harness:** precision@k, recall@k, MRR, NDCG against the hand-labeled judgment set (≥5 queries Day 1 → ≥15 by Early), built **red on Day 1, before ranking exists**. One command: `make eval`. Scoreboard history in JSONL.
- **RAG evals:** recall@k of labeled answer-chunks (lexical vs. semantic vs. hybrid), faithfulness via cross-family LLM judge validated against ~10 hand labels, refusal rate on a deliberate unanswerable set.
- **Coverage target (MVP):** ~90% on `analysis/index/rank`, ~75% overall. Coverage is secondary to the oracle suites above.

### 16. Recommended Tooling & DX
- **AI tools (assignment requires ≥2):** Claude Code (primary build agent) + MCP integrations (context7 for library docs, browser tooling for source scouting); Cursor/Codex available as needed. AI-LOG.md and cost tracking start Day 1.
- **CLI/dev:** `uv`, `ruff`, `pytest`, `hypothesis`, `yt-dlp`, `make`.
- **Debugging:** the eval harness is the debugger of record — every retrieval bug should manifest as a metric or property-test failure first.

---

## Decisions Summary

| Decision | Choice | Rationale (alternatives considered) |
|---|---|---|
| Language | Python | RAG-pipeline career investment; `rank_bm25` oracle; numpy/hypothesis. (Rust: engine-flex, wrong layer for the goal. TS: kept for optional UI only.) |
| Corpus | AI-infrastructure permitting & power paper trail, 4 tiers, ~12-25K primary docs → 0.4-1M retrieval units | Asymmetric information lives in attention deserts; unique; multi-modal (YouTube/audio/text) with clickable receipts. (Considered & rejected: generic Wikipedia/docs corpora; podcast RAG; loud-CEO earnings universe — Times Square, not a desert.) |
| Index | Hand-built inverted index, in-memory, positions + df, compact array-based postings | Assignment core; positions power phrase queries + snippets; int-array postings keep Python memory sane at ~1M units. |
| Ranking | BM25, probabilistic IDF (`ln(1+(N−df+0.5)/(df+0.5))`), k1/b swept vs. NDCG | The IDF variant that survives differential testing; "defended k1/b" per rubric. |
| Vectors | Brute-force cosine, numpy | Exact + milliseconds at this scale; ANN is a measured future decision. |
| Hybrid | Reciprocal Rank Fusion | Score-normalization-free; report all three modes side by side. |
| Judge | Cross-family LLM judge + ~10 hand labels | Assignment requirement; guards self-preference bias. |
| Oracles | Judgment set · `rank_bm25` differential · property invariants · validated judge | "Measured, not vibed" — every layer has an independent source of truth. |

## Paths Not Taken (exploration record)

The corpus decision was iterated deliberately: general corpora (Wikipedia/arXiv/docs) → "citation you can experience" media corpora (podcasts, SCOTUS oral arguments, educator YouTube) → market-receipts engines over loud-CEO venues (earnings calls + podcast appearances) → **rejected as over-analyzed** → final: the same receipts mechanics pointed at an attention desert (county permitting meetings, PUC dockets, neocloud promises) where public data is materially under-indexed. Mechanics preserved across the pivot: Promise Ledger, Confidence-vs-Conduct, Dodge Index.

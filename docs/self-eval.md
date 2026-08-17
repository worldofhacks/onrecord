# OnRecord — Self-Evaluation Report

*Harness pass rates against the RelevanceEngine rubric (Assignment 02),
2026-08-14. Every claim links to committed evidence; honest gaps are named
in §4. Reproduce the harness with one command: `make harness`.*

## 1. Submission deliverables

| Deliverable | Status | Evidence |
|---|---|---|
| GitHub repository (setup, architecture, deployed link) | ✅ | README (setup + deploy runbook); live: onrecord-production-842c.up.railway.app; mirrored to labs GitLab |
| Demo video (3–5 min) | 🟡 owner recording | script prepared; platform verified demo-ready |
| Pre-Search document | ✅ | `docs/presearch.md` + full transcript `docs/presearch-transcript.md` (re-exported from the original session) |
| AI Development Log | ✅ | `docs/AI-LOG.md` — all 7 template sections + final-week addendum (11 oracle-catch entries) |
| AI Cost Analysis | ✅ | `docs/cost-analysis.md` — measured spend (≈$33, itemized) + 100/1K/10K/100K projections with stated assumptions |
| Evaluation harness, one command | ✅ | `make harness`: 1,472 tests (incl. 31 differential, 89 property/robustness) + IR scoreboard + deployed-scope gate |
| Metrics report | ✅ | `docs/metrics.md` (consolidated) + README tables — reproducible commands inline |
| Self-eval report | ✅ | this document |
| RAG pipeline (QA set + faithfulness/relevancy/refusal scripts, reported numbers) | ✅ | `evalsets/qa.jsonl` + `unanswerable.jsonl`; `scripts/judged_eval.py`; numbers below |
| AI-LOG.md (where AI misled, how the oracle caught it) | ✅ | same file as the Dev Log — Oracle Catches is its largest section |
| Social post | 🟡 owner posting | draft: `docs/social-post.md` |

## 2. Rubric dimensions — measured results

**Core engine (MVP/Early bars, all exceeded):**

| Rubric line | Requirement | Delivered |
|---|---|---|
| Judgment set | ≥15 queries | **100 queries / 4,673 blind pooled judgments**, 6 sessions, provenance sidecars |
| IR metrics | P@k, R@k, MRR, NDCG | full harness + 8-row committed history; honest pooling-bias story documented |
| BM25 + defended k1/b | required | 121-cell sweep artifact; plateau; kept 1.5/0.75 |
| Differential | match reference within tolerance | 31 frozen tests vs `rank_bm25`, identical token stream — green |
| Property invariants | IDF monotonicity, round-trip, deletion | hypothesis suite — green (89 property/robustness tests) |
| Robustness | empty/stopword/unicode/absent/long — 0 crashes | frozen suite — green |
| Retrieval gate | "strong, honestly measured" | deployed-scope gate **PASS** (best mode semantic NDCG@10 0.538 ≥ 0.5); legacy lexical-only gate reads 0.449 and is preserved red with the full explanation (`onrecord/eval/gate.py` docstring) |

**RAG extension:**

| Rubric line | Requirement | Delivered |
|---|---|---|
| retrieve(query, k, mode) | lexical \| semantic \| hybrid | `onrecord/rag/retrieve.py` + live `/api/search?mode=` |
| answer → {text, citations[]} | grounded + cited | `onrecord/rag/answer.py` + live `/api/answer` (pinned contract) |
| faithful(answer, chunks) | judge verdict | `onrecord/rag/judge.py`, cross-family (gpt-5-mini vs claude generator) |
| Judge validated vs ~10 hand labels, different family | required | validated at **0.944 agreement** on 36 labels (owner-directed gpt-5.6-sol labeler — disclosed; the validation also exposed and fixed two latent judge defects) |
| Faithfulness, honestly measured | central metric | **0.930 mean** over 12 real answers, per-claim (`evalsets/judged-eval-2026-08-14.json`) |
| Refusal on unanswerable set | high, honest | **12/12 correctly refused; 0/12 false refusals** |
| Recall@k reported for all three modes | required | R@50: lexical 0.602 / semantic 0.644 / hybrid **0.928** (100q, repaired pool) |
| Chunking tuned, measured | required | window sweep vs recall (T-020 artifact); identity chunking adopted, documented |
| ≥4 distinct behaviours | required | grounded answer · citation popovers · refusal · three retrieval modes · grounding badge (claims-checked count) |

**Beyond the rubric (the product thesis):** Promise Ledger (1,527
verbatim-pinned commitments), Confidence-vs-Conduct (8,307 Form 4
transactions joined per ticker), Dodge Index (deterministic, 43
jurisdictions), receipt-joined price moves, chart hover, rate limiting,
CI, 26 merged PRs across 5 days.

## 3. Harness pass rates

- Test suite: **1,472 / 1,472** (unit + integration + property + robustness + differential), `make test`
- Differential: 31/31 · Property/robustness: 89/89
- IR gate (deployed scope): **PASS** · legacy lexical gate: red, documented
- Judged eval: faithfulness 0.930 · refusal 1.00 · false-refusal 0.00
- CI: GitHub Actions green on `main` (blocking test job; scoreboard artifact job)

## 4. Honest gaps

1. ~97% of relevance judgments are LLM-labeled (owner-directed, cross-family,
   provenanced); the 65 session-1 hand labels are the human anchor. An owner
   spot-check of sessions 3–4 remains open.
2. Faithfulness-judge validation labels are model-labeled (same provider
   family as the judge, different tier) per owner directive — disclosed in
   the artifact and metrics report.
3. The corpus is ~12× the assignment's "few thousand documents" — scale
   surfaced real engineering (pooling bias, fusion latency) that smaller
   corpora would have hidden; those findings are documented as features of
   the work, but cold starts (~2–4 min) remain a rough edge.
4. Mention-anchored ticker performance (T-033) and assorted UX polish
   (T-048–T-050) are ticketed but not shipped at self-eval time.

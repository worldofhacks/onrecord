# Session handoff — post-MVP state (2026-08-12, ~04:00)

## Where everything stands
- **MVP: submitted.** All 7 requirements done; main @ GitHub (`1fe7528`+, tag `mvp-checkpoint`), mirrored to labs.gauntletai.com (owner-managed), demo video recorded.
- **Live:** https://onrecord-production-842c.up.railway.app (Railway service `onrecord`, project 438233ee; deploys via `railway up --service onrecord` from the repo root — NOT git-connected).
- **Tests:** 314 green. Process: tdd-swarm (read `.tdd-swarm/progress.md` for the full audit trail, `.tdd-swarm/LESSONS.md` before writing any ticket).
- **Metrics (5 queries, 65 judgments):** boolean 0.000 / BM25 P@5 0.520, R@50 0.949, MRR 1.000, NDCG@10 0.622. History: `evalsets/scoreboard.jsonl` (prod reads it via `ONRECORD_SCOREBOARD` env).

## Long-running processes (this machine)
- **Depth caption pull** (full channel archives → corpus-v2): may still be running. Check: `tail -2 /Users/quietguy/Documents/Dev/Gauntlet/corpus-raw/youtube/pull.log`. Restart (fully resumable, safe to re-run): the orchestrator script lives in the OLD session's scratchpad — recreate trivially: yt-dlp per channel with `--download-archive corpus-raw/youtube/archive.txt --write-auto-subs --skip-download`, channels from `scratchpad resolved_channels.json` equivalent; or re-resolve via ytsearch voting (see LESSONS: fabricated handles 404).
- **Owner side-session**: nearby_receipts venue_type+snippet amendment (task chip) — check if its branch landed before touching `onrecord/ingest/prices.py`.

## Thursday (Early checkpoint) — remaining work, in priority order
1. **Corpus-v2**: re-parse ALL pulled captions (incl. depth-pass videos) with the merged parser → rebuild snapshot + index → re-run harness (tag corpus_version=v2). Parse script pattern: see old scratchpad `parse_captions_to_jsonl.py` — registry-slug matching, EXCLUDE `Loudoun_County_Board_of_Supervisors` dir (multi-city mislabel).
2. **15+ queries**: owner labels ~10 more via `python -m onrecord.eval.judgments` (criterion-first, blind). Then re-run both harness rows.
3. **k1/b sweep**: new ticket — grid k1∈[0,2.5], b∈[0,1] against NDCG@10 on the judgment set; report curve in docs; "defended k1/b" is a rubric line. (k1=0 boundary already guarded.)
4. **Robustness**: suite exists (empty/unicode/absent/long) — verify against corpus-v2, document in README.

## Thursday-Friday (RAG extension) — spec §5, contracts already pinned
- `/api/answer` full implementation: embeddings (content-hash cached), semantic + hybrid (RRF) retrieval modes, grounded answers with citations, refusal. Response contract PINNED in tests/unit/test_api.py docstring (Thursday section).
- QA eval set + unanswerable set; faithfulness LLM-judge from a DIFFERENT model family than the generator, validated against ~10 hand labels; chunking swept against recall@k (75s windows are the current chunk unit).
- UI Ask view is already wired to the contract — it lights up when the endpoint ships.

## Weekend (Final, Sun 11:59 AM)
Mechanics layer (Promise Ledger / Confidence-vs-Conduct via Form 4 join / Dodge Index), metrics report finalization, self-eval vs rubric, cost analysis numbers (measure real per-query tokens), AI-LOG final pass, social post (@GauntletAI), re-export Pre-Search transcript (`scripts/export_presearch_transcript.py` — note: it's pinned to the OLD session's id; update SESSION path or sweep all *.jsonl in the project dir).

## Standing decisions (don't relitigate)
Python/uv; corpus = AI-infra paper trail; probabilistic IDF; RRF for hybrid; cross-family judge; mvp posture deferrals in `.tdd-swarm/posture.md`; merges happen ONLY from the main checkout (see ledger: three directory-trap incidents); frozen tests ship ruff-clean; secret-leak checks capture ALL loggers.

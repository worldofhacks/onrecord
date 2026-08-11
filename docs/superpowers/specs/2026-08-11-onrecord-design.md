# OnRecord — Design Spec

**Date:** 2026-08-11 · **Status:** awaiting user approval · **Companion:** [`docs/presearch.md`](../../presearch.md) (constraints, stack decisions, testing strategy)

## 1. Product identity

**OnRecord** (alt name: *Groundwork*) — a from-scratch search engine + RAG system over the AI-infrastructure buildout's public paper trail. One-liner: *every megawatt promised, permitted, and powered — searchable, with a clickable receipt: the council-meeting timestamp, the EDGAR anchor, or the sworn-testimony page.*

- **Assignment core** (graded): hand-built inverted index → boolean retrieval → BM25 → IR-metrics harness → differential/property/robustness suites.
- **Extension** (graded): embeddings, lexical|semantic|hybrid retrieval, grounded answers with citations, refusal, faithfulness/relevancy/refusal evals.
- **Mechanic layer** (demo, weekend): Promise Ledger, Confidence-vs-Conduct, Dodge Index — query patterns + comparison prompts over the same engine. Never blocks a checkpoint.
- **Thesis:** asymmetric information lives in attention deserts. The buildout's earliest, most honest signals appear in venues almost nobody indexes: county permitting meetings, PUC dockets, interconnection queues, neocloud earnings calls.

## 2. Corpus — registry-driven, versioned, large

Single source of truth: `corpus/registry.yaml` — every channel, ticker, and docket the adapters iterate over. Adding scale = adding registry lines, never code.

### 2.1 Scale targets

| Tier | Source | Universe | Primary docs |
|---|---|---|---|
| T1 | County/city meeting videos (yt-dlp captions) | ~60 channels, full archives | 5,000-15,000 |
| T2 | Earnings-call transcripts | ~100 tickers × 8-12 quarters | 800-1,200 |
| T3 | Regulatory dockets + queues | ~18 regulators + FERC + 6 RTOs | 3,000-5,000 |
| T4 | Corporate & public paper | 10-K/10-Q/8-K, sustainability/water reports, investor days, MOUs, agenda packets/staff reports | 3,500-7,500 |
| | | **Total** | **~12,000-25,000 primary docs → 0.4-1M retrieval units** |

The assignment's "few thousand documents" is exceeded at the primary-document level by corpus-v2 (Wednesday); later versions keep growing through the week.

### 2.2 Registry v1 enumeration

**T1 jurisdictions (~60 channels, by state):**
- **VA (16):** Loudoun, Prince William, Fairfax, Spotsylvania, Stafford, Fauquier, Culpeper, Henrico, Chesterfield, Hanover, Louisa, Caroline, Orange, Pittsylvania, Mecklenburg, Frederick Co
- **TX (6):** Abilene (Stargate), San Antonio council + CPS Energy board, Ellis Co, Temple, Fort Worth, Lancaster
- **GA (6):** Douglas, Newton, Fayette, Bartow, Coweta, Walton
- **OH (4):** New Albany, Licking Co, Columbus, Union Co
- **AZ (6):** Maricopa BOS, Chandler, Mesa, Goodyear, Buckeye, Peoria
- **Midwest (10):** Council Bluffs / Altoona / West Des Moines / Cedar Rapids IA, Sarpy Co NE + OPPD board, DeKalb IL, Mount Pleasant + Port Washington WI, St. Joseph Co IN, Kansas City MO
- **South (7):** Memphis council + MLGW board TN (xAI), Richland Parish LA (Meta), Madison Co MS (AWS), Bessemer + Huntsville AL, Berkeley Co SC, Wake Co NC
- **West (10):** The Dalles + Morrow Co OR, Grant Co PUD + Quincy WA, Storey Co + Reno NV, Cheyenne WY, Eagle Mountain UT, Pryor/Mayes Co + Stillwater OK, Ellendale/Stark Co ND (Applied Digital)

*Best-effort by channel availability; registry records each channel's YouTube ID + archive depth. Target ≥45 live adapters by Friday.*

**T2 tickers (~100, by sector):**
- **Utilities/IPPs (24):** VST CEG NRG TLN NEE SO D DUK AEP ETR EXC PPL EVRG WEC OGE AES PNW IDA POR ES FE CNP XEL SRE
- **Hyperscalers/AI (10):** MSFT GOOGL AMZN META ORCL NVDA AMD INTC TSM MU
- **Neoclouds & miner-pivots (12):** CRWV NBIS IREN APLD WULF CIFR HUT CORZ GLXY HIVE BTDR BITF
- **DC REITs & land (5):** DLR EQIX IRM TPL VMC
- **Builders/E&C (9):** PWR EME MTZ FIX IESC STRL ACM J DY
- **Power equipment/cooling (13):** VRT ETN GEV POWL HUBB NVT MOD ROK TT JCI CARR GNRC CAT
- **Gas midstream & fuel (5):** KMI WMB ET BE PLUG
- **Nuclear/SMR/uranium (8):** OKLO SMR LEU CCJ UEC DNN BWXT NNE
- **Grid/copper/fiber/materials (8):** ITRI FCX SCCO GLW LUMN CCOI MLM AWK
- **Servers/networking (8):** SMCI DELL HPE ANET CIEN COHR ALAB MRVL

**T3 regulatory (~18 + FERC + RTOs):** VA SCC · GA PSC (Georgia Power load-growth) · OH PUCO (AEP data-center tariff) · TX PUCT + ERCOT large-load queue · AZ ACC · PA PUC · NV PUCN · SC PSC · NC UC · MO PSC · OK CC · LA PSC · MS PSC · WI PSC · MN PUC · IN URC · WY PSC · ND PSC · TVA board (Memphis) · **FERC** (Talen/AWS co-location docket, large-load & interconnection-reform dockets) · RTO interconnection/large-load queues: PJM, MISO, ERCOT, SPP, CAISO, NYISO.

**T4 corporate/public paper:** 10-K/10-Q risk factors + MD&A capex for all T2 tickers; 8-K stream via EDGAR full-text search ("data center", "hyperscale", "large load"); hyperscaler sustainability/water reports; investor-day and conference-keynote videos (timestamped); public incentive MOUs/economic-development agreements; county agenda packets + planning-commission staff reports (Granicus/Legistar bulk).

### 2.3 Document schema & retrieval unit

```jsonc
{ "id": "yt:loudoun:2025-11-05:seg042",
  "text": "…the applicant is requesting 240 megawatts of additional capacity…",
  "source_type": "county_meeting | earnings_call | docket | filing | corporate",
  "venue_type": "sworn | coached | candid",     // testimony/docket | call/filing | podcast/interview
  "jurisdiction": "Loudoun County, VA",           // when applicable
  "ticker": "VST",                                // when applicable
  "speaker": "…", "date": "2025-11-05",
  "deep_link": "https://youtube.com/watch?v=…&t=2732s" }
```

Retrieval units: speaker-turn groups (transcripts), ~60-90s caption windows (video), section-level (filings/dockets). Every unit carries a working deep link — the receipts guarantee.

### 2.4 Ingestion schedule (deadline-protected)

| Version | When | Contents |
|---|---|---|
| corpus-v1 | **tonight (MVP)** | **≥2,500 primary docs** (MVP requires "a few thousand documents" loaded Day 1): 6-10 county channels' full caption archives (Loudoun, Prince William, Spotsylvania, Fairfax, Maricopa, New Albany, Memphis, Mount Pleasant…) + EDGAR 10-K/10-Q/8-K pulls for top ~40 tickers + sample earnings transcripts + 1 PUC docket — all three adapter families proven at thousands-scale |
| corpus-v2 | Wed | ~20 T1 channels + top 40 T2 tickers with full transcript depth |
| corpus-v3 | Thu-Fri | full T1+T2, core T3 dockets + queues |
| corpus-v4 | Sat freeze | T4 + stragglers; **final reported metrics run on this freeze** |

Snapshots are immutable; the harness re-runs per version and the scoreboard is tagged with the corpus version, so metrics stay comparable. Form 4 + interconnection-queue tables ingest as *structured joins* (not indexed text) for the mechanic layer.

## 3. Core engine (Python, from scratch)

- **Analyzer** — one function used at index AND query time: lowercase, Unicode NFKC, punctuation strip; no stemming in v1 (an A/B against the metrics later — a documented, measured choice). Stopwords retained (phrase queries need them).
- **Inverted index** — `term → postings` where postings are compact parallel int arrays `(doc_ids[], tfs[], position_offsets[] → positions[])`, plus df per term and doc lengths. Python-dict object overhead is the scale killer at ~1M units; `array`/numpy-backed postings keep it in low GBs. Serialization: msgpack + npy to `artifacts/`.
- **Boolean search** — AND (galloping intersection on sorted arrays), OR (k-way merge), phrase/proximity via position adjacency.
- **BM25** — probabilistic IDF `ln(1 + (N−df+0.5)/(df+0.5))` (the variant that survives differential testing), k1/b defended by sweep against NDCG; top-k via heap; snippets from positions with term highlighting.
- **Interfaces** — CLI: `onrecord search "spotsylvania rezoning" --source county_meeting --venue sworn --k 10`; FastAPI wrapper (`/search`, `/answer`) for the demo UI.

## 4. Eval harness — built red, tonight, before ranking exists

1. **Judgment set** (`evalsets/judgments.jsonl`): ≥5 queries tonight → ≥15 by Thursday, graded 0/1/2. Protocol: relevance criterion written *before* looking at candidates; candidates pooled from grep + `rank_bm25` + manual browsing; judged shuffled and blind to source system.
2. **IR metrics**: precision@k, recall@k, MRR, NDCG. `make eval` prints the scoreboard and appends JSONL history (corpus version + git SHA tagged).
3. **Differential**: our BM25 vs `rank_bm25` **on the identical analyzed token stream** (isolates ranking math from tokenization); score tolerance + top-k agreement.
4. **Properties** (hypothesis): IDF strictly decreases as df rises; index→search round-trip; delete purges every posting; adding a query term to a doc never lowers its rank vs. an otherwise-identical doc.
5. **Robustness**: empty query, stopword-only, unicode/emoji/CJK, very long docs, absent terms — zero crashes, index integrity intact.

## 5. RAG extension (Thu-Fri)

- **Chunking = tuned parameter:** sweep window/overlap against recall@k of labeled answer chunks; publish the curve.
- **Embeddings:** hosted API, content-hash cached; fp16 numpy matrix; brute-force cosine to ~300K chunks, hnswlib past that **with a measured recall-vs-exact check** (either way, documented with numbers).
- **Modes:** `lexical | semantic | hybrid` (RRF, k=60) — all three reported side by side on the same queries.
- **Grounded answers:** `answer(query, chunks) → {text, citations[]}`; every citation is a deep link. Claim-level: each sentence must trace to ≥1 retrieved chunk.
- **Refusal:** deliberate `evalsets/unanswerable.jsonl` (e.g., "what does Loudoun County think about Solana?"); decline on low retrieval confidence; measure refusal on unanswerable AND false-refusal on answerable.
- **Judging:** faithfulness via LLM judge from a different model family than the generator (Claude generates ↔ GPT judges), validated against ~10 hand labels before its verdicts count.

## 6. Mechanic layer (weekend; demo-video material)

- **Promise Ledger** — forward-looking claims (megawatts, jobs, tax revenue, dates) by company/jurisdiction, each paired with later-quarter outcome evidence already in the corpus. Hero: Foxconn→Mount Pleasant; neocloud GW promises.
- **Confidence-vs-Conduct** — claims joined against structured tables (Form 4; interconnection-queue status) in date windows.
- **Dodge Index** — Q&A pairs from call/hearing segmentation + the faithfulness-judge muscle: "was the question answered?" Hero: water-usage evasion in permitting hearings.

## 7. Repo layout, commands, deliverables

Layout and testing strategy: see `docs/presearch.md` §13/§15. Commands: `make setup | test | eval | ingest V=2 | demo` — clean-clone-to-running is one command (`make setup && make demo`), verified by actually cloning fresh. The frozen corpus snapshot ships in-repo compressed (gzipped JSONL; LFS if >100MB) so a clean clone runs **offline** — no network, no API keys required for the graded core path.

**Deliverables map:** GitHub repo (this) · demo video (mechanics + harness run) · Pre-Search doc (`docs/presearch.md`) · AI Development Log (`docs/AI-LOG.md`, started tonight) · AI Cost Analysis (`docs/cost-analysis.md`, tracked from first API call) · eval harness (`make eval`) · metrics report (README, reproducible) · self-eval report · RAG eval scripts + numbers · social post (@GauntletAI).

## 8. Timeline

### 8.1 MVP checklist — exact 1:1 mapping (all seven, none skipped)

| # | Assignment MVP requirement (verbatim intent) | Where it's met tonight |
|---|---|---|
| 1 | Day-1 design doc committed (analysis pipeline, index representation, ranking, judgment set) | This spec: §3 analyzer, §3 index representation, §3 BM25 ranking plan, §4 judgment-set protocol — committed `fa09ead`+ |
| 2 | Corpus chosen and loaded (a few thousand documents) | corpus-v1 = **≥2,500 primary docs** loaded + normalized (§2.4) |
| 3 | Hand-built relevance-judgment set started (≥5 queries with labeled relevant docs) | `evalsets/judgments.jsonl`, ≥5 queries, pooled + blind-judged (§4.1) |
| 4 | Inverted index with document frequencies and term positions | §3: postings carry df, tf, AND positions |
| 5 | Boolean retrieval (AND/OR) returning documents end-to-end | §3: query → analyzer → postings merge → ranked doc list w/ metadata, via CLI |
| 6 | Metrics harness stubbed with precision@k / recall on labeled queries (red) | `make eval` prints precision@k + recall@k (plus MRR/NDCG stubs), failing/red tonight by design (§4.2) |
| 7 | Runnable from a clean clone with one command | `make setup && make demo`, verified by an actual fresh clone; corpus snapshot in-repo, offline (§7) |

### 8.2 Week timeline

| When | Checkpoint | Contents |
|---|---|---|
| **Tue night** | **MVP** | all seven items in §8.1 |
| Wed | — | corpus-v2, BM25 + full metrics + differential green |
| **Thu night** | **Early** | ≥15 queries, k1/b sweep, property + robustness suites, corpus-v3 |
| Fri | — | RAG: chunking sweep, 3 modes, grounded answers + refusal |
| Sat | — | corpus-v4 freeze, faithfulness/refusal evals, mechanics, demo UI |
| **Sun 11:59 AM** | **Final** | metrics + self-eval reports, AI-LOG, cost analysis, video, social post |

## 9. Risks & fallbacks

| Risk | Mitigation |
|---|---|
| Transcript source paywalls (T2) | 8-K prepared-remarks exhibits + reduced ticker list; adapter-isolated |
| County caption quality (T1) | Prefer channels with decent auto-captions; noisy text is honest IR reality — metrics measure through it; drop-worst-channels documented in registry |
| Docket portal scraper variance (T3) | Per-portal adapters; tier system absorbs shortfall — checkpoints never depend on T3 |
| Scale vs. Python memory | Array-backed postings; fp16 vectors; measured ANN threshold |
| Deadline vs. corpus ambition | Corpus versioning: every checkpoint runs on whatever version is frozen that day; ambition lands in v3/v4, never blocks v1/v2 |
| LLM judge unreliability | Cross-family judge + ~10 hand-label validation gate before verdicts count |

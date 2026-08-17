# OnRecord

- **Live demo — https://onrecord-production-842c.up.railway.app**
- **Source — https://github.com/worldofhacks/onrecord**

A from-scratch search engine (+ RAG extension) over the AI-infrastructure
buildout's public paper trail — county permitting meetings, municipal
legislative records, and SEC filings. Every result carries a clickable
receipt: a YouTube timestamp, an EDGAR anchor, or a docket page.

The index, the analyzer, BM25, and the fusion are written here, not
imported. `rank_bm25` is a dependency of the *eval* harness only — a
differential reference the tests score against (`onrecord/eval/differential.py`)
and one arm of the judgment pool (`onrecord/eval/pooling.py`) — and is
imported by neither `onrecord.rank` nor `onrecord.search`.

See [`docs/superpowers/specs/2026-08-11-onrecord-design.md`](docs/superpowers/specs/2026-08-11-onrecord-design.md)
for the full design (analyzer, index representation, ranking, eval
protocol), [`docs/presearch.md`](docs/presearch.md) for constraints and
stack decisions, and **[`docs/metrics.md`](docs/metrics.md) — the authority
for every metric in this project.** Where this README and `docs/metrics.md`
disagree, `docs/metrics.md` wins.

## What the live demo is serving

Ask the deployment itself — `GET /api/stats` is the number that cannot go
stale:

```sh
curl -s https://onrecord-production-842c.up.railway.app/api/stats
```

Reading at the time of writing (2026-08-17), matching
`corpus/v3/manifest.json`:

| | |
|---|---|
| Corpus version | **v3** |
| Documents | **309,662** |
| Sources | county_meeting **289,882** · legistar **18,337** · filing **1,443** |
| Jurisdictions | 51 |
| Registered tickers | 295 |

Three document types, not two. **Legistar** (municipal agendas, minutes and
matters — 18,337 docs) joined at the corpus-v3 swap and is a first-class
`source_type` alongside `county_meeting` and `filing`.

**All three retrieval modes are live in production**: `lexical` (BM25),
`semantic` (cosine over `text-embedding-3-large` @ 3072 dims), and `hybrid`
(RRF fusion). So is grounded Q&A at `POST /api/answer`. Measured warm
against the live service on 2026-08-17: lexical 0.2–2.9s depending on how
broad the query is, semantic ~4–6s, hybrid ~4.5s.

Nothing about the deployed configuration is gated or pending: it is the
image the `Dockerfile` builds, described in [Deploy](#deploy-railway-single-service).

## Quickstart

Clean clone to a running demo, offline, in one command:

```sh
git clone https://github.com/worldofhacks/onrecord.git
cd onrecord
make setup && make demo
```

`make setup` (`uv sync`) installs dependencies. `make demo` needs no network
access and no API keys: it loads `artifacts/index` if one exists, and
otherwise builds an in-memory index straight from the committed
`corpus/v1/corpus.jsonl.gz` snapshot, then runs 3 canned queries and prints
ranked results with deep links.

**Be clear about what that gets you.** On a clean clone `artifacts/` does
not exist, so `make demo` runs against **corpus-v1: 24,115 documents** (958
filings + 23,157 meeting segments) — the small, git-committed snapshot that
guarantees the offline clean-clone path and that `tests/integration/test_e2e.py`
pins.
That is roughly 1/13th of the 309,662-document corpus-v3 the live demo
serves, and it is lexical-only (no embedding store ships in the repo). The
big corpus is distributed as a GitHub release asset, not in git — see
[Running the deployed configuration locally](#running-the-deployed-configuration-locally).

## Commands

| Command | What it does |
|---|---|
| `make setup` | Install dependencies (`uv sync`). |
| `make test` | Run the test suite (`uv run pytest -q`) — 1,472 tests as of this writing. |
| `make demo` | Load/build the index and run 3 canned queries end-to-end (see Quickstart). |
| `make ingest` | Merge raw adapter output (`corpus/raw/**/*.jsonl`) into `corpus/v$(V)/corpus.jsonl.gz` and build + save the index to `artifacts/index` (`onrecord.ingest.build_corpus`). `V` defaults to 1; pass `V=3 RAW=<parsed-raw-dir>`. |
| `make eval` | The IR-metrics harness (P@k, R@k, MRR, NDCG) against `evalsets/judgments.jsonl`, appending to the scoreboard (`onrecord.eval.run`). Its default arm is the **Day-1 boolean baseline, red by design** (exit 1) — that is the honest starting line, not a broken build. |
| `make gate` | The deployed-scope retrieval gate (`onrecord.eval.gate`): scores the best NDCG@10 among the modes the product actually ships against the 0.5 floor. |
| `make harness` | The assignment's one-command harness: full frozen suite (unit + differential + property + robustness) → `make eval` → `make gate`. |
| `make refresh-live` / `refresh-form4` / `refresh-outcomes` / `refresh-grid` / `refresh-corpus` / `refresh-all` | The living-platform delta lanes (T-051/T-052/T-053): livestream tracking, Form 4 pulls, promise-outcome trails, ISO queues, fast-moving artifact refresh. Also wired as a daily review-PR workflow in `.github/workflows/refresh-data.yml` — nothing auto-merges. The corpus/index/embedding swap is deliberately **not** in these lanes; it is a versioned runbook in `tickets/T-053.md` that runs on owner go, because it carries re-pooling and re-billing obligations. |

## Searching directly

Once an index exists (via `make ingest` or the `make demo` fallback), query
it from the CLI:

```sh
uv run python -m onrecord.cli search "substation" --op AND --k 10
uv run python -m onrecord.cli search "rezoning" --source county_meeting
uv run python -m onrecord.cli search "data center" --phrase
```

`search` flags: `--op {AND,OR}` (default `AND`), `--phrase` (exact-phrase
query, overrides `--op`), `--k N` (max results, default 10), `--source
TYPE` (filter to a `Doc.source_type` — `county_meeting`, `legistar`,
`filing`), `--index DIR` (index directory, default `artifacts/index`). An
empty query, a query whose terms are all absent from the index, or
unicode/punctuation-only junk all resolve to a graceful "No results"
message and exit 0 — never a crash. The CLI is boolean/phrase retrieval
only; ranked and semantic retrieval live behind the API.

## API

FastAPI (`onrecord/api.py`) serves the JSON API *and* the static UI from
one process. Run it locally with:

```sh
uv run uvicorn onrecord.api:app --reload
```

A missing/unbuilt index is not fatal — `/health` still returns 200, and the
data endpoints degrade to a `503` naming the missing condition rather than
a 500. CORS is open to `http://localhost:5173` (the UI's dev origin).

### Core

| Endpoint | What it does |
|---|---|
| `GET /health` | Liveness. Always `200 {"status": "ok"}` (frozen contract). |
| `GET /ready` | Deploy readiness — `200` only once the index is actually loaded. Railway's healthcheck points here so traffic never cuts over to a container that is still booting (measured: startup logs "complete" ~41s before `/api/*` stops 503ing, because the corpus load runs on the async-boot thread). |
| `GET /api/stats` | Corpus version, document count, per-source counts, jurisdictions, tickers. The canonical answer to "what is this instance serving?". |
| `GET /api/search?q=&mode=lexical&op=OR&k=20&source=&venue=&ticker=&jurisdiction=&date_from=&date_to=&sort=` | Retrieval. `mode=lexical` is BM25-ranked with AND-combined metadata filters and needs no API key at all (the keyless-lexical guarantee). `mode=semantic`/`hybrid` do cosine / RRF retrieval over the embedding store, and `503` naming the missing condition (`OPENAI_API_KEY`, an unbuilt store, a store/model identity mismatch) when unconfigured. An unknown `mode` is `422`. |
| `POST /api/answer` | Grounded Q&A ("Ask") — body `{"question", "mode", "k"}` (`question` is the field name; `k` is bounded `1..100` — it sizes the set whose full text goes into a paid generator prompt). Retrieves per mode, then generates a cited answer. A refusal is a populated `refusal` object in a `200`, not an error. `503` when the index is missing, or naming `ANTHROPIC_API_KEY` / the semantic retrieval condition; `422` when `question` is missing. |
| `GET /api/metrics` | The eval history the UI's Score view renders, read from `ONRECORD_SCOREBOARD`. |
| `GET /api/tickers` | Registered tickers (`corpus/registry.yaml`) grouped by sector, each with a live `receipt_count` and `last_receipt` computed off the loaded index. |

### Feature surfaces

These are the product surfaces built on top of retrieval. Every row they
return carries a receipt link back to the source document. Counts and
rollups are whatever the deployment currently holds — hit the endpoint
rather than trusting a number written here; where a surface has an
unconfigured or genuinely empty state, that is noted below rather than
papered over.

| Endpoint | What it does |
|---|---|
| `GET /api/promises` | **Promise Ledger** — verbatim-pinned public commitments extracted from the record (1,527 as served), filterable by jurisdiction/ticker/category. Quotes are enforced as exact substrings of the source doc in code. |
| `GET /api/promised?by=jurisdiction\|ticker` | The Ledger's quantities rolled up — megawatts, gallons/day, jobs, dollars. |
| `GET /api/outcomes/summary` | Outcome trails: which promises were followed up on in a later meeting and which went quiet. |
| `GET /api/dodge` | **Dodge Index** — a deterministic, frozen-lexicon score of evasive answering per jurisdiction (per-1,000-docs rate, min-doc floor). |
| `GET /api/conduct/{ticker}` | Insider conduct from Form 4 filings. |
| `GET /api/events` | Typed 8-K material events with item codes and labels. |
| `GET /api/mentions?window=90&k=25` | Mention-anchored ticker performance: ticker-attributed docs with entry price anchored to the mention date's close, ranked by return since (daily-close grain). Needs `ONRECORD_MENTIONS_BOOT=1` and a warm price cache, else a named `503`. |
| `GET /api/prices/{ticker}?range=365&threshold=5.0` | EOD price series + significant-move timeline joined to nearby receipts. Index-independent; an unknown ticker `200`s with an empty series rather than erroring. |
| `GET /api/live` | **Hearings on Air** — livestream/upcoming-meeting tracking across the resolved jurisdictions. |
| `GET /api/grid` | ISO interconnection queues (MISO / SPP / ERCOT / CAISO) joined to jurisdictions. |
| `GET /api/shells` | Shell-entity resolution — who is behind the record's project names. Only curated, receipt-validated links resolve, so an empty table is an honest state rather than an error (and is what the deployment currently returns). |
| `POST /api/portfolio/connect`, `GET /api/portfolio` | Read-only SnapTrade portfolio lens (opt-in; requires `SNAPTRADE_*` credentials, absent by default). |

### Static UI

| Endpoint | What it does |
|---|---|
| `GET /` | Serves `<ONRECORD_UI_DIR>/index.html` (default `ui/`). |
| `GET /<any-other-path>` | Serves a matching static asset under `ONRECORD_UI_DIR`; an unmatched extension-less path SPA-falls-back to `index.html`; an unmatched path with an extension `404`s. `/api/*` is never shadowed by this fallback. |

See `tests/unit/test_api.py`'s module docstring for the exact frozen JSON
contracts (the UI parses these directly), and `ui/WIRING.md` for how each
view maps onto them.

## Robustness

Both retrieval paths — boolean AND/OR and BM25 — are exercised against the
canonical edge-case query inventory: **empty**, **stopword-only**,
**unicode** (punctuation/junk), **emoji-only**, **CJK**, **absent-terms**,
and **very-long** queries, crossed with boolean AND/OR and BM25 ranking.
Every case resolves gracefully (a clean empty/no-results response, never an
uncaught exception or a 500) rather than merely being assumed safe.

**Real-index verification**: the same case matrix, run against the fully
built index on 2026-08-12 — **24/24 passed**. That run was against the
corpus-v2 index (289,536 docs), the deployed corpus at the time; the probe
is the same frozen matrix as the unit suites, so re-running it against any
built `artifacts/index` reproduces it.

**Honest caveat**: county-meeting text is sourced from YouTube
auto-captions, which are noisy by construction (misheard terms, missed
punctuation). Per the design spec's Risks & fallbacks (§9): "noisy text is
honest IR reality — metrics measure through it." Every number in this
README is measured through that noise, not smoothed around it.

## Metrics

**`docs/metrics.md` is the authority**; its §8 covers the deployed
corpus-v3 configuration. Reproduce with `make harness` (full suite +
scoreboard + gate).

**Judgment set**: 4,673 pooled rows across **100 queries**, built over six
labeling sessions (`evalsets/judgments.jsonl`) — 65 hand labels as the
human anchor, the rest owner-directed LLM labeling, criterion-first (session
packs committed before pooling runs), pooled blind, with a provenance
sidecar per session (`evalsets/judgment-session-{2,3,4,5,6}-provenance.json`).

### Deployed configuration (corpus-v3, `text-embedding-3-large`)

`make gate` scores what the product actually ships. Current reading:

| Mode | NDCG@10 | Gate (≥0.50) |
|---|---|---|
| **semantic** | **0.521** | PASS |
| hybrid | 0.500 | — |
| lexical (BM25) | 0.444 | — |

Full per-mode metrics live in `evalsets/modes-scoreboard.jsonl`; the
lineage the UI's Score view renders is `evalsets/scoreboard-ui.jsonl`,
served at `/api/metrics` — seven curated rows from the Day-1 boolean
baseline (NDCG@10 **0.000**) to the deployed v3·3-large row:

| Row | P@5 | P@10 | R@10 | R@50 | MRR | NDCG@10 |
|---|---|---|---|---|---|---|
| v1·bool (Day-1 baseline) | 0.000 | 0.000 | 0.000 | 0.000 | 0.003 | 0.000 |
| **v3·3L (deployed)** | **0.620** | **0.584** | 0.299 | 0.657 | 0.706 | **0.521** |

### Earlier readings — measured on corpus-v2, not on what the demo serves

These rows are kept because the *deltas* between them are the story. **Every
number in this table was measured against corpus-v2 (289,536 docs) and its
pool**, which is not the corpus the live demo runs. They are not comparable
to the v3 numbers above: pool and corpus both changed, and the only honest
pairing is same-pool-same-corpus.

| Retrieval (**corpus-v2**) | P@5 | P@10 | R@10 | R@50 | MRR | NDCG@10 |
|---|---|---|---|---|---|---|
| Boolean OR (unranked, Day-1 baseline, 15q) | 0.000 | 0.000 | 0.000 | 0.000 | 0.001 | 0.000 |
| BM25 (15q, three-arm pool) | 0.840 | 0.693 | 0.710 | 0.929 | 0.956 | 0.751 |
| BM25 (100q, three-arm pool) | 0.470 | 0.392 | 0.689 | 0.846 | 0.618 | 0.558 |
| BM25 (100q, **four-arm pool**) | 0.488 | 0.409 | 0.425 | 0.602 | 0.644 | 0.449 |
| Semantic (100q, four-arm pool) | — | — | — | 0.644 | 0.670 | 0.538 |
| Hybrid RRF (100q, four-arm pool) | — | — | — | 0.928 | 0.644 | 0.431 |

The identical labels produce each pool-generation's rows — the deltas are
the ranking functions, measured, not vibed. Three methodology notes worth
reading before comparing anything:

1. **15q→100q drop**: the 85 session-3 queries are deliberately narrower
   (single-ordinance, single-disclosure topics), so fewer pooled documents
   clear their grade-2 bars.
2. **Pooling bias by corpus size**: when corpus-v2 first replaced corpus-v1
   (10.6× larger), BM25's NDCG@10 *read* 0.171 against the v1-pooled
   judgments — not a regression but unjudged documents flooding the top
   ranks, and unjudged scores as non-relevant. Re-pooling against v2
   recovered the honest number. Both readings are preserved in
   `evalsets/scoreboard.jsonl`, `corpus_version`-tagged.
3. **Pooling bias by method, found and repaired**: the original pool drew
   candidates from grep + BM25 + random — no semantic arm — so semantic
   retrieval's unique finds were never judged and scored as non-relevant
   (semantic *read* 0.135; a slander, not a measurement). Adding a semantic
   arm and judging its 886 new pairs moved semantic to the top, pulled BM25
   down (its old numbers were flattered by its own pooling arm), and forced
   the gate question. Consequence, decided in T-047: retrieval quality is
   gated on what the product deploys (`make gate`). The legacy lexical-only
   `make eval` gate is preserved unchanged and reads red — nothing was
   retuned silently; the full history is in `onrecord/eval/gate.py`'s
   docstring.

### Grounding

Measured on the deployed retrieval config (hybrid, `fusion_depth=2000`),
`claude-opus-5` generation, validated judge — see `docs/metrics.md` §4 and
`evalsets/judged-eval-2026-08-14.json`:

- **faithfulness 0.930** mean across 12 answers
- **12/12 unanswerable questions correctly refused, 0/12 false refusals**
- the judge itself was validated at **0.944 agreement** against labeled
  claims before any of its verdicts were reported
  (`evalsets/judge-validation-2026-08-13.json`)

### Bounded fusion

Hybrid's full-depth fusion cost 7.8s/query on deploy hardware.
`fusion_depth=2000` (`ONRECORD_FUSION_DEPTH`) was differentially verified
before shipping: **99.5% mean top-20 overlap (min 90%), 98/100 identical
top-10, NDCG@10 0.4309 vs 0.4315, 4.1× latency win**
(`evalsets/t037-differential.json`).

## Defended k1/b

BM25's `k1` (tf-saturation strength) and `b` (length-normalization
strength) are not picked by convention — they're swept over a grid and
defended against the judgment set's mean NDCG@10, via
`onrecord/eval/sweep.py`:

```sh
uv run python -m onrecord.eval.sweep \
    --index artifacts/index \
    --judgments evalsets/judgments.jsonl \
    --out artifacts/sweeps/k1b_ndcg10.json \
    [--plot]
```

The sweep scores every cell of `k1 ∈ {0.0, 0.25, …, 2.5}` ×
`b ∈ {0.0, 0.1, …, 1.0}` (121 cells) as the mean NDCG@10 across every
judgment query — a query that retrieves nothing still counts (as a 0.0)
toward the mean, so the number below cannot be inflated by silently
dropping hard queries. `--plot` additionally renders a heatmap PNG next to
the JSON artifact.

**Chosen (k1, b): 1.5, 0.75 — the shipped default, kept deliberately.**

| k1 | b | Mean NDCG@10 |
|---|---|---|
| 1.25 | 0.8 | 0.7617 (grid best) |
| 1.5 | 0.8 | 0.7611 |
| 1.5 | 0.7 | 0.7425 |
| **1.5** | **0.75 (shipped)** | **≈0.752 (between its grid neighbors)** |
| 0.0 | any | 0.2937 (degenerate floor) |

*Grid summary — **measured on corpus-v2 (289,536 docs)**, 15-query judgment
set, run 2026-08-12, 121 cells in 4.0 min. The artifact records
`corpus_version: v2` (`artifacts/sweeps/k1b_ndcg10.json` + heatmap PNG);
it has **not** been re-swept against corpus-v3, so read it as a statement
about the parameter surface's shape, not as a v3 measurement. The top of
the surface is a broad plateau — the best five cells span
`k1 ∈ [0.75, 1.75]` × `b ∈ [0.5, 0.9]` within 0.006 NDCG of each other.*

**Defense:** the shipped default sits on the same plateau as the grid best —
0.752 vs 0.7617, a gap of ~0.01 that is well within noise on a 15-query set —
so changing frozen-tested defaults would be noise-chasing, not tuning. What
the sweep *does* establish is that the parameters are load-bearing: every
`k1 = 0` cell collapses to 0.294 (tf-saturation off means term frequency
stops discriminating), and low-`b` cells lag because this corpus mixes
75-second caption windows with filing sections a hundred times longer, so
length normalization has real work to do. The defense of (1.5, 0.75) is
therefore measured, not conventional: it is statistically indistinguishable
from the best cell on that judgment set, and the sweep artifact regenerates
in ~4 minutes against whatever index it is pointed at.

## Deploy (Railway, single service)

One FastAPI process serves the JSON API and the static UI, so the whole app
deploys as a single Railway service built from the repo's `Dockerfile`
(`python:3.12-slim` + `uv`).

```sh
# One-time: install the Railway CLI, then from the repo root:
railway login
railway init          # create/link a Railway project for this repo
railway up            # build the Dockerfile and deploy
```

`railway.json` pins `"builder": "DOCKERFILE"` and points the healthcheck at
**`/ready`** (600s timeout), so Railway holds traffic on the old container
until the new one has its index loaded — `/health` is liveness only and
would cut traffic over too early.

### What the image contains

The `Dockerfile` **fetches the corpus-v3 deploy artifacts at build time**
from the repo's public `v3-artifacts` GitHub release — the corpus snapshot,
the prebuilt index, and the `text-embedding-3-large` embedding store
(~2.4 GB together). They are not baked from the working tree: the snapshot
exceeds GitHub's 100 MB file limit, `railway up`'s upload path chokes on
that much build context, and the embedding store cannot be rebuilt
in-container without keys and a re-embedding bill. Each fetch is a single
`RUN` layer with a resume-capable `curl` (a mid-stream reset killed the
first deploy attempt), so only the extracted tree lands in the image.

`corpus/v1/corpus.jsonl.gz` remains git-tracked and also lands in the image
via `COPY . .`, as the small fallback snapshot.

Because those artifacts are present at fixed paths, the image sets its own
container-scoped defaults and **a deploy needs no additional Railway env
vars**:

```
ONRECORD_CORPUS=corpus/v3/corpus.jsonl.gz
ONRECORD_INDEX=artifacts/index
ONRECORD_EMBED_STORE=artifacts/embeddings-3large
ONRECORD_EMBED_MODEL=text-embedding-3-large
ONRECORD_SCOREBOARD=evalsets/scoreboard-ui.jsonl
```

These are **image-local only**. `onrecord/api.py` has no built-in default
for `ONRECORD_CORPUS` (index bootstrap requires the env var explicitly
present), so local runs and the frozen test suite are unaffected — this was
the post-review fix for the "deployer trap" where the obvious deploy path
silently 503s (`.tdd-swarm/reports/T-015-review.md` Important-1).

`ONRECORD_EMBED_MODEL` is not optional decoration: it must match the store's
identity, or query-time embeddings arrive at the wrong dimensionality and
`semantic_search` rejects the store rather than serving mismatched vectors.

Keyless deploys stay green — lexical search and the whole UI work with no
API keys at all; semantic/hybrid and Ask degrade to clean `503`s naming the
missing key.

### Environment variables

| Env var | Default (code) | Set in image | Purpose |
|---|---|---|---|
| `ONRECORD_INDEX` | `artifacts/index` | `artifacts/index` | Saved `InvertedIndex` directory. If missing, startup bootstraps an in-memory index from `ONRECORD_CORPUS` and saves it back here for a warm restart. |
| `ONRECORD_CORPUS` | *(unset; `/api/prices` falls back to `corpus/v1/corpus.jsonl.gz`)* | `corpus/v3/corpus.jsonl.gz` | Corpus snapshot (gzip newline-JSON). Powers the `/api/prices` receipt join and, when present, cold-start index bootstrap. A corrupt/unreadable snapshot degrades to a `503`, never a crash-loop. |
| `ONRECORD_EMBED_STORE` | `artifacts/embeddings/<resolved model>` | `artifacts/embeddings-3large` | Embedding store backing `mode=semantic`/`hybrid`. Must be built for the same corpus **and** the same model — the identity check `503`s on a mismatch rather than silently serving stale vectors. |
| `ONRECORD_EMBED_MODEL` | `text-embedding-3-small` (provider default) | `text-embedding-3-large` | Query-time embedding model. Must match the store (3072 dims for 3-large). |
| `ONRECORD_EMBED_PROVIDER` | `openai` | *(unset)* | Embedding provider name. |
| `ONRECORD_SCOREBOARD` | `artifacts/scoreboard.jsonl` | `evalsets/scoreboard-ui.jsonl` | The eval history `/api/metrics` serves. The image points at the curated, git-tracked lineage; the legacy artifact copy went stale the moment the embedding store swapped. |
| `ONRECORD_UI_DIR` | `ui/` | *(unset)* | Static UI asset directory. |
| `ONRECORD_FUSION_DEPTH` | `2000` | *(unset)* | Hybrid RRF fusion depth (`0` = full depth). See [Bounded fusion](#bounded-fusion). |
| `ONRECORD_ANSWER_MIN_CONF` | *(unset — no gate)* | *(unset)* | Optional refusal gate for `/api/answer`: minimum top retrieval confidence below which the pipeline refuses *before* calling the generator. A malformed value surfaces as its own named `503` condition rather than being echoed. |
| `ONRECORD_ANSWER_DAILY_CAP`, `ONRECORD_ANSWER_IP_HOURLY_CAP` | *(unset)* | *(unset)* | Rate caps on `/api/answer` — the dominant paid user-facing surface (a semantic query's embedding call is ~$0.000004; a grounded answer is ~$0.03). |
| `ONRECORD_GENERATOR_MODEL` | pinned in `onrecord/rag/answer.py` | *(unset)* | Overrides the answer generator model id. |
| `ONRECORD_JUDGE_MODEL` | `DEFAULT_JUDGE_MODEL` in `onrecord/rag/judge.py` | *(unset)* | Overrides the eval-harness judge model id. |
| `ONRECORD_PRICES_CACHE` | `artifacts/prices` | *(unset)* | On-disk cache for fetched EOD price series. |
| `OPENAI_API_KEY` | *(unset)* | *(runtime)* | Query embedding for `mode=semantic`/`hybrid`. Absent → those modes `503`; lexical is unaffected. |
| `ANTHROPIC_API_KEY` | *(unset)* | *(runtime)* | Answer generation for `/api/answer`. Absent → `503` naming it. |
| `FMP_API_KEY` | *(unset)* | *(runtime)* | Optional price-source fallback when stooq fails. |
| `EDGAR_USER_AGENT` | *(unset)* | *(runtime)* | Required by SEC fair-access policy for EDGAR ingest adapters. |
| `SNAPTRADE_CLIENT_ID`, `SNAPTRADE_CONSUMER_KEY` | *(unset)* | *(runtime)* | Optional read-only portfolio lens. |
| `PORT` | `8000` | Railway-injected | Bind port; never set manually in Railway. |

See `.env.example` for the ingest-side keys.

### Redeploy / rollback runbook

```sh
railway up --service onrecord   # from the repo root; the Railway service is
                                # NOT git-connected, so this is the only deploy trigger
```

Smoke-test after every deploy:

```sh
B=https://onrecord-production-842c.up.railway.app
curl -s $B/ready                                  # 200 once the index is loaded
curl -s "$B/api/stats"                            # corpus_version + doc count
curl -s "$B/api/search?q=substation&mode=lexical" # 200
curl -s "$B/api/search?q=substation&mode=hybrid"  # 200
curl -s -X POST $B/api/answer -H 'content-type: application/json' \
     -d '{"question":"What did the county say about the substation?","mode":"hybrid"}'
```

`/api/answer` should return `200` (a refusal counts) or a `503` naming the
missing condition — never a 500.

Rollback: check out the previous good commit and `railway up --service
onrecord`. Note that the image fetches its data artifacts from a **release
tag**, so a code rollback does not roll the corpus back; swapping corpus
versions is the separate `tickets/T-053.md` runbook.

### Running the deployed configuration locally

corpus-v3 (309,662 docs) is distributed as the `v3-artifacts` GitHub
release, not in git — the snapshot exceeds GitHub's 100 MB file limit.
`corpus/v3/manifest.json` **is** committed and carries the doc count, the
source breakdown, and the snapshot's sha256 for verification.

Fetch the three artifacts from the same release the `Dockerfile` fetches
from (`.github/workflows/refresh-data.yml` pulls the corpus snapshot the
same way):

```sh
mkdir -p artifacts corpus/v3
BASE=https://github.com/worldofhacks/onrecord/releases/download/v3-artifacts
curl -fSL -C - -o /tmp/a.tgz $BASE/index-v3.tar.gz            && tar -xzf /tmp/a.tgz -C artifacts && rm /tmp/a.tgz
curl -fSL -C - -o /tmp/a.tgz $BASE/embeddings-3large-v3.tar.gz && tar -xzf /tmp/a.tgz -C artifacts && rm /tmp/a.tgz
curl -fSL -C - -o corpus/v3/corpus.jsonl.gz $BASE/corpus-v3.jsonl.gz

ONRECORD_CORPUS=corpus/v3/corpus.jsonl.gz \
ONRECORD_INDEX=artifacts/index \
ONRECORD_EMBED_STORE=artifacts/embeddings-3large \
ONRECORD_EMBED_MODEL=text-embedding-3-large \
ONRECORD_SCOREBOARD=evalsets/scoreboard-ui.jsonl \
OPENAI_API_KEY=... ANTHROPIC_API_KEY=... \
uv run uvicorn onrecord.api:app
```

`/api/stats` should then report `corpus_version: v3` — the manifest travels
with the index, so the reported version is the artifact's own claim, not a
config guess.

To rebuild a corpus from raw adapter output instead:
`make ingest V=3 RAW=<parsed-raw-dir>` (writes `corpus/v3/corpus.jsonl.gz` +
manifest and the index into the default `artifacts/index`; pass
`--index-out` to `onrecord.ingest.build_corpus` directly if you need to keep
an existing index around).

## Costs

`docs/cost-analysis.md` is the authority for spend — itemized measured
actuals (embeddings, six labeling sessions, promise extraction,
answers/judging), measured per-query unit costs, and 100/1K/10K/100K
projections with the assumptions stated rather than hidden. The
deterministic core — ingest, index, BM25, Dodge Index, promise quantities,
outcome trails, 8-K typing, ISO joins — cost $0 in API spend by design.

## Honest limits

- The judgment set is overwhelmingly LLM-labeled (owner-directed at each
  step, cross-family from the generator, full per-session provenance), with
  65 hand labels as the human anchor. An owner spot-check remains open.
- The faithfulness validation labels are model-labeled (same provider
  family as the judge, different tier) per owner directive — disclosed here
  and in the artifact.
- The judge was nonfunctional until validation forced it to produce real
  verdicts (two latent defects: a rejected `max_tokens` spelling and an
  output cap fully consumed by hidden reasoning). That is written up in
  `docs/AI-LOG.md` rather than quietly fixed.
- Verbatim promise quotes inherit caption dysfluencies ("the the the
  bonds…") — by design: the ledger quotes what the record says, exactly.
- Prices are daily closes from a keyless source chain.
- Receipt link-rot, measured by full census (11,004 videos, 2026-08-14):
  **0.98%** (108 dead links, `evalsets/linkhealth-2026-08-14.jsonl`). The
  captions remain in the corpus regardless; a "source removed" UI treatment
  is a documented follow-up.
- The k1/b sweep and the earlier metric tables were measured on corpus-v2
  and have not been re-run on corpus-v3; they are labelled as such above
  rather than relabelled to the deployed corpus.
- `make demo` runs on corpus-v1 (24,115 docs), not the corpus the live demo
  serves. See [Quickstart](#quickstart).

## Docs

| Document | What it is |
|---|---|
| [`docs/metrics.md`](docs/metrics.md) | **The metric authority.** Corpus, judgments, retrieval, grounding, costs, honest limits; §8 covers deployed corpus-v3. |
| [`docs/cost-analysis.md`](docs/cost-analysis.md) | Measured AI spend, per-query unit costs, scale projections. |
| [`docs/self-eval.md`](docs/self-eval.md) | Rubric-by-rubric self-evaluation with evidence links and named gaps. |
| [`docs/AI-LOG.md`](docs/AI-LOG.md) | AI development log — including every place AI misled the build and how the oracle caught it. |
| [`docs/presearch.md`](docs/presearch.md) | Pre-search: constraints, stack decisions, risks (full transcript in `docs/presearch-transcript.md`). |
| [`docs/superpowers/specs/2026-08-11-onrecord-design.md`](docs/superpowers/specs/2026-08-11-onrecord-design.md) | The design spec — analyzer, index representation, ranking, eval protocol. |
| [`TICKETS.md`](TICKETS.md) + [`tickets/`](tickets/) | 66 tickets, with recorded decisions and deferrals rather than silent skips. |
| [`ui/WIRING.md`](ui/WIRING.md) | How each UI view maps onto the API contracts. |

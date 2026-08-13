# OnRecord

A from-scratch search engine (+ RAG extension) over the AI-infrastructure
buildout's public paper trail — county permitting meetings, utility
earnings calls, and SEC filings. Every result carries a clickable receipt:
a YouTube timestamp, an EDGAR anchor, or a docket page.

See [`docs/superpowers/specs/2026-08-11-onrecord-design.md`](docs/superpowers/specs/2026-08-11-onrecord-design.md)
for the full design (analyzer, index representation, ranking, eval
protocol) and [`docs/presearch.md`](docs/presearch.md) for constraints and
stack decisions.

## Quickstart

Clean clone to a running demo, offline, in one command:

```sh
git clone <this-repo-url>
cd onrecord
make setup && make demo
```

`make setup` (`uv sync`) installs dependencies; no network access or API
keys are required for `make demo` — it loads the `artifacts/index` build if
one exists, and otherwise builds an in-memory index straight from the
committed `corpus/v1/corpus.jsonl.gz` snapshot, then runs 3 canned queries
and prints ranked results with deep links.

## Commands

| Command | What it does |
|---|---|
| `make setup` | Install dependencies (`uv sync`). |
| `make test` | Run the test suite (`uv run pytest -q`). |
| `make demo` | Load/build the index and run 3 canned queries end-to-end (see Quickstart). |
| `make ingest` | Merge raw adapter output (`corpus/raw/**/*.jsonl`) into `corpus/v1/corpus.jsonl.gz` and build + save the index to `artifacts/index` (`onrecord.ingest.build_corpus`). |
| `make eval` | Run the IR-metrics harness (precision@k, recall@k, MRR, NDCG) against `evalsets/judgments.jsonl` and print the scoreboard (`onrecord.eval.run`); red tonight by design, before ranking exists. |

## Searching directly

Once an index exists (via `make ingest` or the `make demo` fallback), query
it directly:

```sh
uv run python -m onrecord.cli search "substation" --op AND --k 10
uv run python -m onrecord.cli search "rezoning" --source county_meeting
uv run python -m onrecord.cli search "data center" --phrase
```

`search` flags: `--op {AND,OR}` (default `AND`), `--phrase` (exact-phrase
query, overrides `--op`), `--k N` (max results, default 10), `--source
TYPE` (filter to a `Doc.source_type`, e.g. `county_meeting`,
`earnings_call`, `filing`), `--index DIR` (index directory, default
`artifacts/index`). An empty query, a query whose terms are all absent
from the index, or unicode/punctuation-only junk all resolve to a graceful
"No results" message and exit 0 — never a crash.

## API

The commissioned UI (design studio, in flight) is built against a FastAPI
layer (`onrecord/api.py`). Run it locally with:

```sh
uv run uvicorn onrecord.api:app --reload
```

The index directory it loads is configurable via `ONRECORD_INDEX` (default
`artifacts/index`); a missing/unbuilt index is not fatal — `/health` still
returns 200, only the data endpoints degrade to a 503 with an actionable
message. CORS is open to `http://localhost:5173` (the UI's dev origin).

| Endpoint | What it does |
|---|---|
| `GET /health` | Liveness check, always `200 {"status": "ok"}`. |
| `GET /api/search?q=&mode=lexical&op=OR&k=20&source=&venue=&ticker=&jurisdiction=` | Lexical search is BM25-ranked with metadata filters, AND-combined when more than one is given. `mode=semantic`/`hybrid` (T-024) are LIVE: cosine/RRF retrieval over an embedding store, `503` naming the missing condition (`OPENAI_API_KEY`, an unbuilt store, a store/provider identity mismatch) when unconfigured — `mode=lexical` needs no key. An unknown `mode` is `422`. |
| `POST /api/answer` | Grounded Q&A ("Ask", T-024) — body `{"question", "mode", "k"}`; retrieves per mode then generates a cited answer, `200` with the full T-023 answer shape (a refusal is a populated `refusal` object, not an error). `503` when the index is missing, or naming `ANTHROPIC_API_KEY` (no generator configured) or the semantic/hybrid retrieval condition; `mode=lexical` answers need no key at all (the keyless-lexical guarantee). `422` when `question` is missing. |
| `GET /api/tickers` | Registered tickers (`corpus/registry.yaml`) grouped by sector, each with a live `receipt_count` and `last_receipt` date computed off the loaded index. |
| `GET /api/metrics` | Parsed `artifacts/scoreboard.jsonl` eval history as a JSON array (`[]` when it doesn't exist yet). |

See `tests/unit/test_api.py`'s module docstring for the exact frozen JSON
contracts (the UI parses these directly).

The same FastAPI app also serves the static UI and a prices endpoint
(T-015, single-service Railway deployment):

| Endpoint | What it does |
|---|---|
| `GET /` | Serves `<ONRECORD_UI_DIR>/index.html` (default `ui/`). |
| `GET /<any-other-path>` | Serves a matching static asset under `ONRECORD_UI_DIR` if one exists (e.g. `/support.js`, guessed content type); an unmatched extension-less path SPA-falls-back to `index.html`; an unmatched path with an extension `404`s. `/api/*` paths are never shadowed by this fallback. |
| `GET /api/prices/{ticker}?range=365&threshold=5.0` | EOD price series + significant-move timeline joined to nearby receipts, via `onrecord.ingest.prices.api_payload`. Index-independent; an unsafe/unknown ticker `200`s with an empty series rather than erroring. |

## Robustness

Both retrieval paths — boolean AND/OR and BM25 — are exercised against the
canonical edge-case query inventory: **empty**, **stopword-only**,
**unicode** (punctuation/junk), **emoji-only**, **CJK**, **absent-terms**,
and **very-long** queries, crossed with boolean AND/OR and BM25 ranking.
Every case resolves gracefully (a clean empty/no-results response, never an
uncaught exception or a 500) rather than merely being assumed safe.

**Real-index verification**: run against the fully-built corpus-v2 index
(289,536 docs: 288,578 county-meeting segments + 958 filings) on
2026-08-12 — **24/24 cases passed** (`.tdd-swarm/progress.md`, "CORPUS-V2
OFFICIAL" entry: "Robustness on final index 24/24 PASS").

**Honest caveat**: county-meeting text is sourced from YouTube
auto-captions, which are noisy by construction (misheard terms, missed
punctuation). Per the design spec's Risks & fallbacks (§9): "noisy text is
honest IR reality — metrics measure through it." Every number in this
README, including the 24/24 above, is measured through that noise, not
smoothed around it.

## Deploy (Railway, single service)

FastAPI (`onrecord/api.py`) serves both the JSON API and the static UI from
one process, so the whole app deploys as a single Railway service built
from the repo's `Dockerfile` (`python:3.12-slim` + `uv`, `uv sync
--no-dev`, `CMD` binds `0.0.0.0:$PORT`).

```sh
# One-time: install the Railway CLI, then from the repo root:
railway login
railway init          # create/link a Railway project for this repo
railway up            # build the Dockerfile and deploy
```

`railway.json` pins `"builder": "DOCKERFILE"` and the start command
(`uv run uvicorn onrecord.api:app --host 0.0.0.0 --port $PORT`) — Railway
injects `$PORT` automatically, no manual configuration needed for that
one.

**Cold start "just works" out of the box — no extra env vars required.**
The `Dockerfile` bakes `ENV ONRECORD_CORPUS=corpus/v1/corpus.jsonl.gz`
(the committed corpus snapshot lands in the image via `COPY . .`, at
exactly that path), so a fresh `railway up` with zero configured env vars
already bootstraps an in-memory index from it on first startup — no
"deployer trap" where the obvious deploy path silently 503s (post-review
fix; see `.tdd-swarm/reports/T-015-review.md` Important-1). This default
is **image-local only** — `onrecord/api.py` itself still has no built-in
default for `ONRECORD_CORPUS` (only `/api/prices`' corpus path defaults;
index bootstrap requires the env var explicitly present), so local runs
and the test suite are unaffected; it only takes effect inside the
container, where the `Dockerfile`'s `ENV` sets it for you.

Optionally override any of these in the Railway project's environment
variables (`railway variables set NAME=value`, or the dashboard) — e.g. to
point at a different/updated corpus snapshot without rebuilding the image:

| Env var | Default | Purpose |
|---|---|---|
| `ONRECORD_INDEX` | `artifacts/index` | Saved `InvertedIndex` directory. `artifacts/` isn't committed, so on a fresh deploy this won't exist yet — startup bootstraps an in-memory index from `ONRECORD_CORPUS` instead of 503ing (the `Dockerfile` already sets this for you — see above), then saves it back to this path for a warm restart. A corrupt/unreadable corpus snapshot degrades to the same 503 rather than crashing startup (never a Railway crash-loop). |
| `ONRECORD_CORPUS` | *(unset in code; `corpus/v1/corpus.jsonl.gz` in the `Dockerfile`)* | Corpus snapshot path (gzip newline-JSON). Powers `/api/prices`' receipt join (defaults to `corpus/v1/corpus.jsonl.gz` there even if unset) **and**, when present in the environment, cold-start index bootstrap when `ONRECORD_INDEX` is missing/unbuilt. |
| `ONRECORD_UI_DIR` | `ui/` | Static UI asset directory (`index.html`, `support.js`, ...). |
| `ONRECORD_PRICES_CACHE` | `artifacts/prices` | On-disk cache dir for fetched EOD price series (`onrecord.ingest.prices`). |
| `FMP_API_KEY` | *(unset)* | Optional Financial Modeling Prep API key, used as a fallback price source when the primary (stooq) source fails. |
| `PORT` | *(Railway-injected)* | Bind port; never set this manually in Railway — the platform provides it. |

Both the index-missing and corpus-missing/corrupt cases degrade gracefully
rather than crashing the deploy: with neither a usable index nor a usable
corpus snapshot, `/api/search` and `/api/tickers` return a `503` with an
actionable message while `/` (the UI) and `/health` keep serving normally.

### Redeploy / rollback runbook

```sh
railway up --service onrecord   # from the repo root; the Railway service is
                                 # NOT git-connected, so this is the only deploy trigger
```

Smoke-test after every deploy: `GET /health` (200), `GET
/api/search?q=test&mode=lexical` (200), `POST /api/answer
{"question": "...", "mode": "lexical"}` (200 or a 503 naming the missing
condition — never a 500).

Rollback: `git checkout <previous-good-commit-or-the-mvp-checkpoint-tag> &&
railway up --service onrecord`.

**Prod stays pinned to corpus/v1, lexical-only, for this epic.** Promoting
corpus-v2 or the RAG surface (semantic/hybrid search, Ask) to production is
a deliberate, owner-gated decision, not something this wave ships
automatically — see `TICKETS.md`'s "Deferred items" section ("RAG-to-prod
deploy — owner-gated, post-epic") for the measured cost/memory facts behind
that call.

### Running against corpus-v2 locally

corpus-v2 (289,536 docs) is bigger than corpus-v1 and isn't shipped in the
repo (its snapshot exceeds GitHub's 100 MB file limit — see `TICKETS.md`'s
deferred items — so `corpus/v2/corpus.jsonl.gz` is gitignored; only
`corpus/v2/manifest.json` is committed) and is never the default anywhere
in `onrecord/api.py`. To rebuild it and point a local `uvicorn` at it:

```sh
make ingest V=2 RAW=<parsed-raw-dir>   # rebuilds corpus/v2/ + artifacts/index locally

ONRECORD_CORPUS=corpus/v2/corpus.jsonl.gz \
ONRECORD_INDEX=artifacts/index-v2 \
ONRECORD_EMBED_STORE=artifacts/embeddings/<model> \
ONRECORD_GENERATOR_MODEL=<generator-model-id> \
ONRECORD_JUDGE_MODEL=<judge-model-id> \
uv run uvicorn onrecord.api:app --reload
```

| Env var | Purpose |
|---|---|
| `ONRECORD_CORPUS` | Corpus snapshot path; point at `corpus/v2/corpus.jsonl.gz` to bootstrap/answer from v2 instead of the v1 default. |
| `ONRECORD_INDEX` | Saved `InvertedIndex` directory; use a v2-specific path (e.g. `artifacts/index-v2`) so it never collides with the v1 index already saved at the default `artifacts/index`. |
| `ONRECORD_EMBED_STORE` | Embedding-store directory backing `mode=semantic`/`hybrid`; must be built for the SAME corpus version being served — T-021's store/provider identity check `503`s on a mismatch rather than silently serving stale vectors. |
| `ONRECORD_GENERATOR_MODEL` | Overrides the Claude generator model id `onrecord/rag/answer.py` resolves for `/api/answer` (its own pinned default otherwise). |
| `ONRECORD_JUDGE_MODEL` | Overrides `onrecord/rag/judge.py`'s eval-harness judge model id (`DEFAULT_JUDGE_MODEL` otherwise). |

## Metrics report (reproducible)

Judgment set: 15 queries, 255 blind pooled judgments (`evalsets/judgments.jsonl`), criteria written before candidates were seen. Session 1 (5 queries, 65 rows) was hand-labeled at the MVP checkpoint against corpus-v1; session 2 (q1–q5 re-pooled against corpus-v2 + 10 new queries, 190 rows) was labeled by an LLM judge (`gpt-5.2` — a different model family from the answer generator; provenance in `evalsets/judgment-session-2-provenance.json`) under the same protocol: criterion-first, pooled grep+BM25+random, shuffled, blind to source. Reproduce with `make eval` (boolean baseline, exits 1 — red by design) and the BM25 run in `docs/metrics.md`.

| Retrieval (corpus-v2, 15 queries) | P@5 | P@10 | R@10 | R@50 | MRR | NDCG@10 |
|---|---|---|---|---|---|---|
| Boolean OR (unranked, Day-1 baseline) | 0.000 | 0.000 | 0.000 | 0.000 | 0.001 | 0.000 |
| BM25 (k1=1.5, b=0.75) | 0.840 | 0.693 | 0.710 | 0.929 | 0.956 | 0.751 |

The identical labels produce both rows — the delta is the ranking function, measured, not vibed. A methodological note worth reading before comparing across corpus versions: when corpus-v2 (289,536 docs) first replaced corpus-v1 (24,115 docs), BM25's NDCG@10 *read* 0.171 against the v1-pooled judgments — not a retrieval regression but pooling bias (the 10.6×-larger corpus pushed unjudged documents into the top ranks, and unjudged scores as non-relevant). Re-pooling the judgment set against v2 recovered the honest number above. Both readings are preserved in `evalsets/scoreboard.jsonl`, `corpus_version`-tagged.

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

*Grid summary (corpus-v2, 289,536 docs, 15-query judgment set with q1–q5
re-pooled against v2 per `tickets/T-019.md`'s hard precondition; run
2026-08-12, 121 cells in 4.0 min, artifact + heatmap in
`artifacts/sweeps/`, `corpus_version: v2` recorded in the artifact):
the top of the surface is a broad plateau — the best five cells span
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
from the best cell on this corpus's judgment set, and the sweep artifact
regenerates in ~4 minutes whenever the judgment set grows.

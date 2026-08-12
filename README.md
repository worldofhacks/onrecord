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
| `GET /api/search?q=&mode=lexical&op=OR&k=20&source=&venue=&ticker=&jurisdiction=` | Lexical search (boolean OR/AND today; upgrades transparently to BM25 once T-011's `ranked_search` lands) with metadata filters, AND-combined when more than one is given. `mode=semantic`/`hybrid` return a `{"error": "available_wednesday"}` teaser; an unknown `mode` is `422`. |
| `POST /api/answer` | Grounded Q&A ("Ask") stub — body `{"question", "mode", "k"}`; currently `200 {"error": "available_thursday"}`, `422` when `question` is missing. |
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

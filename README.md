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

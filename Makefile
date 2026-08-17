.PHONY: setup test eval ingest demo

V ?= 1

setup:
	uv sync

test:
	uv run pytest -q

eval:
	uv run python -m onrecord.eval.run

ingest:
	uv run python -m onrecord.ingest.build_corpus --version $(V) $(if $(RAW),--raw-dir $(RAW))

demo:
	uv run python -m onrecord.cli demo

# The assignment's one-command evaluation harness: judgment set + IR metrics
# + differential + property + robustness (the full frozen suite), then the
# metrics scoreboard. The boolean baseline gate is red by design; the
# deployed-scope gate (T-047) is `make gate`.
harness:
	uv run pytest -q
	-uv run python -m onrecord.eval.run
	uv run python -m onrecord.eval.gate

gate:
	uv run python -m onrecord.eval.gate

# The living platform (T-051/T-052/T-053): delta refresh lanes. The corpus
# swap itself (corpus-v3) is a documented runbook in tickets/T-053.md and
# runs only on owner go (it invalidates the demo-verified state).
refresh-live:
	uv run python -c "import json, os; from onrecord.ingest.build_corpus import load_corpus_snapshot; from onrecord.ingest.livestreams import track; from datetime import datetime, UTC; alive = {json.loads(l)['video_id'] for l in open('evalsets/linkhealth-2026-08-14.jsonl') if json.loads(l)['status']=='alive'}; track(load_corpus_snapshot(os.environ.get('ONRECORD_CORPUS','corpus/v3/corpus.jsonl.gz')), alive, checked_at=datetime.now(UTC).isoformat(timespec='minutes'))"

refresh-form4:
	uv run python -c "from onrecord import registry; from onrecord.ingest.form4 import pull_form4; pull_form4([t['symbol'] for t in registry.load()['tickers']])"

refresh: refresh-live refresh-form4
	@echo "deltas refreshed; filings delta + corpus-v3 swap: see tickets/T-053.md"
refresh-outcomes:
	uv run python scripts/build_outcomes.py

refresh-grid:
	uv run python scripts/build_grid.py

# Living-data refresh automation (daily lane; .github/workflows/refresh-data.yml).
# refresh-corpus freshens fast-moving artifacts only — the corpus/index/embedding
# swap stays the T-053 versioned runbook and is never run from here.
.PHONY: refresh-corpus refresh-all
refresh-corpus:
	uv run python scripts/refresh_corpus.py

refresh-all: refresh-corpus refresh-outcomes


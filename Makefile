.PHONY: setup test eval ingest demo

setup:
	uv sync

test:
	uv run pytest -q

eval:
	uv run python -m onrecord.eval.run

ingest:
	uv run python -m onrecord.ingest.build_corpus

demo:
	uv run python -m onrecord.cli demo

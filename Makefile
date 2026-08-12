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

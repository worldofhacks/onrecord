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

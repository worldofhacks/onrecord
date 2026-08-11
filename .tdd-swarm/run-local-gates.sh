#!/bin/bash
# Tier-1 local gates. Usage: .tdd-swarm/run-local-gates.sh [worktree-dir] [ticket-file]
set -e
cd "${1:-.}"
echo "== format ==" && uv run ruff format --check .
echo "== lint ==" && uv run ruff check .
echo "== unit ==" && uv run pytest -q
if [ -n "$2" ]; then echo "== spec-lint ==" && "$(git rev-parse --show-toplevel)/.tdd-swarm/spec-lint.sh" "$2"; fi
echo "ALL LOCAL GATES GREEN"

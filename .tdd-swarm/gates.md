# Gate Commands — onrecord (Python 3.14 / uv)

## Tier 1 — local (per ticket loop; wrapped in run-local-gates.sh)
```
format:    uv run ruff format --check .
lint:      uv run ruff check .
typecheck: SKIPPED (posture deferral — ruff only tonight)
unit:      uv run pytest -q
spec-lint: .tdd-swarm/spec-lint.sh <ticket-file>
todos:     git diff <base>..HEAD | grep -nE '^\+.*(TODO|FIXME|HACK)' → must be empty
debug:     git diff <base>..HEAD | grep -nE '^\+.*(print\(|breakpoint\()' → must be empty (print allowed in cli/ and scripts/)
```

## Tier 2 — repo (wave review)
```
build:     uv sync && uv run python -c "import onrecord"
regression: uv run pytest -q  (>= baseline pass count; baseline: 0 at Phase 0)
eval:      make eval  (must run end-to-end; RED metrics are expected tonight)
secrets:   manual diff review by Security Agent (no gitleaks; posture)
perf:      DEFERRED (posture)
drift:     diff vs docs/superpowers/specs/2026-08-11-onrecord-design.md
```

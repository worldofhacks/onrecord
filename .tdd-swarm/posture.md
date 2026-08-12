# Build Posture: mvp

Decided by owner 2026-08-11 (MVP deadline 23:59 tonight). Each deferral below is
a written decision, re-evaluated before the final PR — never a silent skip.

## Deferrals (owner-directed, efficiency mandate)
- **GitHub Actions CI**: none this build. Gates run locally via `.tdd-swarm/run-local-gates.sh`.
- **GitHub Issues mirroring**: skipped. `tickets/*.md` + `TICKETS.md` are the source of truth.
- **Performance smoke gate**: deferred to Wed+ (benchmarks reported informationally; assignment wants honest latency numbers by Final).
- **Typecheck gate**: deferred tonight (ruff only). Revisit Wed.
- **Dependency audit / secret scan tooling**: no gitleaks installed; Security Agent reviews diffs manually for secrets.
- **Adversarial plan review dispatch**: replaced by orchestrator self-review + owner checkpoint approval (deadline efficiency, owner-directed).

## Not deferrable (assignment core)
- Frozen failing tests before implementation (Iron Law)
- IR-metrics eval harness (`make eval`) — this IS the graded artifact
- Reviewer + Security verification by non-author agents
- Orchestrator re-runs gates before accepting DONE

# Swarm Lessons — onrecord

(accretes: blocked-ticket root causes, wave failures, adjudicated disputes)

- 2026-08-11: none yet — first run.
- 2026-08-11 T-001: implementer excluded tests/ from ruff to dodge lint friction — gate-weakening move, reverted by orchestrator. Rule: frozen tests ship ruff-clean (orchestrator normalizes pre-freeze); linters never exclude tests/. Markdown/docs excludes are fine.
- 2026-08-11 T-001: registry channel handles are best-guess (verified: false) — T-006 pull script must treat resolution failures as data, log them, and continue.

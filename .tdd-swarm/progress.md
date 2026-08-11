# Swarm Ledger — onrecord-mvp

Baseline (Phase 0, 2026-08-11): 0 tests, vacuously green. Branch swarm/onrecord-mvp off main@4f01918.
Posture: mvp (see posture.md). Deadline: MVP checkpoint tonight 23:59.
- T-001: tests-written (14 failing cleanly; orchestrator pre-freeze review + format/lint normalization — recorded deviation: no separate test-review dispatch for trivial scaffold)
- T-001: done (merged into swarm; review APPROVED after 1 fix round — unpinned deps + orchestrator's no-op ruff patch, both caught by reviewer)
- T-002: tests-written (21 failing cleanly, a357148; orchestrator freeze scan OK)
- T-004: tests-written (25 failing, 813cd49; freeze scan OK)
- T-003: tests-written (15 failing, c205336; freeze scan OK)
- T-002: impl DONE (dec61ad, 21/21 + suite 35/35; orchestrator gates re-run green)
- T-004: impl DONE (eec3758, 25/25; orchestrator gates re-run green)
- T-008: tests-written (8 failing, ec32c46)
- T-003: impl DONE (db916f8, 15/15, 10K-doc build 0.42s; orchestrator gates re-run green)
- T-005: tests-written (23 failing, 1f87893; dedicated test-design review dispatched pre-freeze — graded artifact)
- T-008: impl DONE (a174677, 8/8; orchestrator gates re-run green)
- T-002: review-passed (APPROVED 0C/0I/2m — CJK fusion + combining-marks notes, both spec-compliant)
- T-009: tests-written (14 failing, 045d2e5)
- T-006: tests-written (16 failing, 98f72b3; caught yt-dlp bracketed-filename glob landmine)
- T-009: impl DONE (7e8602c, 14/14; orchestrator gates re-run green)
- T-003: review APPROVED w/ 3 Important forward-compat findings (internal-id resolver, doc-length getter, mutable postings exposure) — fix round via test-agent contract extension before merge
- T-008: review REJECTED (1 Critical key-leak via unhandled httpx errors + 2 Important) — test-extension + fix round dispatched
- T-004: review REJECTED (1 Critical: id-space collision with T-003 contract — resolved by orchestrator adjudication + T-003 contract extension; T-004 code needs no change if reconciled contract lands; re-verify at wave merge)

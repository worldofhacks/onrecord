# AI Development Log — OnRecord

*Living document; started Day 1 (2026-08-11), finalized before submission.*

## Tools & Workflow
- **Claude Code (Opus)** as orchestrator running a ticketed TDD swarm: Planner → Test Agents (write frozen failing tests) → Implementation Agents (green them) → independent Reviewer+Security Agents (verdict with file:line evidence) → Integration Agent (wave merges + repo gates). 14 tickets across 5 waves on Day 1-2. Separation of powers is mechanical: implementers cannot edit tests; reviewers never author code; the orchestrator re-runs every gate itself before trusting any DONE claim.
- **MCP/tooling**: context7 for library docs; yt-dlp + EDGAR + FMP adapters built test-first with zero-network fixture suites.

## Effective Prompts (actual text, excerpted)
1. *Test Agent framing:* "These tests are frozen after you finish. Write them like the implementer is adversarial — cover the edge cases that a lazy implementation would skip." → produced dual-verification discipline (tests confirmed RED against stubs AND green against throwaway reference implementations).
2. *Reviewer framing:* "You did not write this code and owe its author nothing… REAL-DATA SPOT CHECK: run the parser against ONE real video dir and report what happens truthfully." → this single instruction caught the two biggest bugs of Day 1 (see Oracle Catches).
3. *Re-review framing:* "Re-run your original leak reproduction against the fixed code — the sentinel key must appear nowhere." → forced empirical re-verification instead of diff-reading approval.

## Code Analysis
~97% AI-generated (agents wrote all engine/test code); human contribution: corpus/product decisions, relevance judgments (labels are human-only by design), and orchestration approvals.

## Oracle Catches (where AI was confidently wrong and the process caught it)
1. **The orchestrator caught by its own reviewer**: a "fix" commit claimed ruff now linted `tests/` — the patch was a no-op regex (`"tests/"` vs `"tests"`), and verification was vacuous because excluded files pass checks by definition. An independent reviewer diffed the commit against its message and rejected it.
2. **Idealized fixtures vs real YouTube captions**: all 16 frozen tests green, yet 83% of *real* pulled captions parsed corrupted (karaoke `<c>` markup + incremental rollup the fixtures never modeled). Caught only because the reviewer was ordered to parse real pulled data. Two fix rounds later: 0% parser-caused corruption on a 20-video real sample.
3. **EDGAR ToC stubs**: section extractor locked onto hyperlinked Table-of-Contents "Item 1A." rows and silently discarded the real sections — DLR's "Risk Factors" was a 26-char stub. Caught by live-data spot check; fixed and re-verified against the same live filings (157K-char real sections).
4. **CSS-bold blindness**: round-2 re-verification of the same live filings surfaced a second, distinct defect (headings styled `font-weight:bold` invisible to a tag-only bold detector). Fixed round 3; verdict flipped only after live re-parse.
5. **API-key leak**: FMP adapter leaked the key in plaintext through unhandled `httpx.HTTPStatusError` messages on non-429 errors. Security reviewer reproduced it with a sentinel key; fix verified by re-running the reproduction on every error path.
6. **Cross-ticket contract drift**: two parallel tickets froze incompatible `get_doc` id-space assumptions (str external vs int internal). Two independent reviewers converged on it; resolved by an explicit adjudicated contract (accept both, disjoint types) pinned in frozen tests.

## Strengths & Limitations
- **Excelled**: parallel test-first implementation (8 concurrent tickets, zero merge conflicts by construction — disjoint file scopes + frozen interface contracts); adversarial review with mandatory real-data spot checks; empirical re-verification loops.
- **Struggled**: modeling messy real-world data formats from imagination (captions, EDGAR HTML) — every ingest ticket needed a reality-based fix round. Lesson: fixtures must be sampled from real data, not invented; "tests green" means nothing until an oracle sees real inputs.

## Key Learnings
- On a correctness-critical build, the highest-value prompt is not "write code" but "try to prove this wrong, against real data."
- Frozen tests + independent review turned 6 confidently-wrong implementations into caught-and-fixed incidents instead of shipped bugs — none reached the integration branch.

## Final-checkpoint addendum (2026-08-13/14)

The last 48 hours compressed the full arc of AI-first development —
including the failure modes the process exists to catch:

7. **The eval slandered its own best mode.** The judgment pool (grep +
   BM25 + random arms) never surfaced semantic retrieval's unique finds,
   so semantic scored 0.135. The repair was methodological, not code: add
   a semantic pooling arm, have the labeler judge its 886 unseen pairs,
   re-measure. Semantic turned out to be the strongest single mode
   (0.538), and BM25's earlier numbers were flattered by its own pooling
   arm. Both readings are published.
8. **The judge that never worked.** Validation of the faithfulness judge
   found it had never produced a real verdict against the live API: the
   gpt-5 family rejects the legacy `max_tokens` parameter (every call
   400'd), and after that fix, the 64-token output cap was consumed
   entirely by hidden reasoning (every verdict empty). Two latent defects,
   both invisible while the judge was only exercised through mocks —
   found the moment validation forced real calls. Validated at 0.944
   agreement afterward.
9. **Verbatim or nothing.** The Promise Ledger's extraction enforces in
   code that every quote is an exact substring of its source document;
   0.9% of model outputs violated it and were dropped, never repaired.
   The same session earlier removed a design-phase demo corpus that had
   rendered fabricated receipts during an outage — the platform now shows
   engine truth or nothing.
10. **Frozen contracts amended by evidence, not convenience.** Bounding
    hybrid fusion depth (7.8s → ~2s/query) amended a frozen full-depth
    design pin — shipped only after a 100-query differential against the
    frozen behavior (99.5% top-20 overlap, NDCG unchanged) was committed
    as the amendment's evidence.
11. **Operational reality kept diverging from clean-room assumptions**:
    stooq silently became a proof-of-work bot wall; EDGAR's
    `primaryDocument` points at XSL-rendered HTML rather than the raw
    XML; yahoo 429s a spoofed browser UA while accepting a bare one;
    Railway's upload edge caps context far below the artifact weight;
    macOS revoked the agent's file access mid-session (work continued via
    the GitHub API and a scratchpad workspace, with CI as the test gate).
    Every one of these was found live, fixed tests-first where code
    changed, and recorded as a lesson.

Labeling division of labor, disclosed throughout: the owner directed
model labelers at each decision point (gpt-5.2, then gpt-5.6-sol) with
provenance sidecars committed; the 65 session-1 hand labels remain the
human anchor.

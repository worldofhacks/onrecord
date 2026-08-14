# Social post draft (X / LinkedIn — owner posts, tag @GauntletAI)

Built OnRecord in 5 days for @GauntletAI: a search + RAG engine over the
paper trail of the AI datacenter buildout — 289,536 documents of sworn
county testimony and SEC filings across 51 jurisdictions.

- BM25 from scratch, verified against a reference implementation
- 100-query judgment set; we caught our own eval slandering semantic
  retrieval (0.135 -> 0.538 after repairing pooling bias) — measured, not
  vibed
- Grounded answers with citations: faithfulness 0.93, 12/12 unanswerable
  questions correctly refused
- The accountability layer: a Promise Ledger of 1,527 verbatim commitments,
  insider-conduct joins (NVDA insiders: -$574M net while on the record),
  and a Dodge Index of evasion formulas per jurisdiction

Every answer carries a receipt: https://onrecord-production-842c.up.railway.app

(attach: Ledger screenshot + Ask screenshot + conduct strip screenshot)

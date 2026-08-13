# Judgment session 2 — q6–q15 (corpus-v2, Early checkpoint)

Extends the judgment set from 5 to 15 queries per spec §4.1. Protocol unchanged
(T-009): criterion written **before** any candidate is seen (the criteria below
were drafted before any pooling or retrieval ran on these queries), candidates
pooled from grep + rank_bm25 + seeded random, shuffled, judged blind to source.
Grades: 2 = clearly relevant per criterion, 1 = partially/peripherally relevant,
0 = not relevant, s = skip.

Per query, run (paste the criterion verbatim at the prompt, or edit it first —
whatever you type is what's recorded; the drift-guard will hold you to it on
resume):

```bash
uv run python -m onrecord.eval.judgments \
  --query "<query>" --query-id <qid> \
  --corpus corpus/v2/corpus.jsonl \
  --out evalsets/judgments.jsonl \
  --k-per-source 10 --seed <seed>
```

`--seed` = the query number (6 for q6, 7 for q7, …) so the random-source picks
decorrelate across queries (q1–q5 shared a seed; harmless, but distinct seeds
pool more diverse spice docs).

Sourcing intent: q1–q4 judged yt-only and q5 was the sole mixed query — this
batch leans two queries (q10, q11) toward EDGAR filings and keeps the rest
civic-record so the set stops being monoculture.

## FIRST: top up q1–q5 against corpus-v2 (pooling-bias repair)

The v1 judgments were pooled against 24K docs; corpus-v2 is ~10.6x larger, so
the old pools no longer cover the top ranks — a rehearsal harness run on v2
showed BM25 mean NDCG@10 at 0.173 vs 0.622 on v1, driven by unjudged (not
irrelevant) v2 docs scoring high. Before judging q6–q15, re-run each of q1–q5
with `--corpus corpus/v2/corpus.jsonl` and the ORIGINAL seed (0) and criterion
(paste it verbatim from `evalsets/judgments.jsonl` — the drift-guard enforces
an exact match). Already-judged (query_id, doc_id) pairs are skipped
automatically; you only grade the new v2 candidates.

---

## q6 — `data center noise complaints`

A relevant document discusses noise from a data center or data-center
construction — resident complaints, sound studies, mitigation measures
(berms, setbacks, equipment enclosures, decibel limits), or enforcement;
grade 2 for noise concerns or mitigation tied to a specific named or located
facility/project with substantive detail or a decision; grade 1 if data-center
noise is discussed generally or as a secondary aspect of another matter;
grade 0 for noise complaints unrelated to data centers, or data-center
discussion with no noise angle.

## q7 — `data center moratorium`

A relevant document discusses pausing or halting data-center development —
a moratorium, interim ordinance, or development freeze; grade 2 for a specific
moratorium or pause that is proposed, voted on, enacted, or lifted, with scope
or duration on record; grade 1 for calls to pause, study, or slow data-center
approvals without formal action; grade 0 for moratoria on unrelated matters,
or data-center discussion with no pause/halt angle.

## q8 — `grid capacity interconnection queue`

A relevant document discusses electric-grid capacity constraints or the
interconnection process for new load or generation; grade 2 for a specific
project's interconnection status, queue position, timeline, or a utility's
concrete statement on capacity constraints (figures, dates, named projects);
grade 1 for general discussion of grid capacity, load growth, or
interconnection delays without project-level substance; grade 0 for passing
mentions of the grid or electricity with no capacity/interconnection angle.

## q9 — `diesel backup generators permit`

A relevant document discusses backup/emergency generators at a data center or
industrial facility and their permitting — installation counts or capacity,
air-quality permits, variances, testing schedules, or fuel storage; grade 2
for a specific generator installation or permit matter with concrete detail
or a decision; grade 1 if backup generation is discussed generally or as a
side aspect; grade 0 for generator mentions with no permitting/facility
context, or permits unrelated to generators.

## q10 — `artificial intelligence capital expenditures`

A relevant document discusses capital spending driven by AI or data-center
buildout; grade 2 for concrete capex figures, guidance, or commitments
explicitly tied to AI/data-center infrastructure (dollar amounts, capacity,
named projects); grade 1 for general statements that AI is driving investment
without figures or commitments; grade 0 for AI mentions with no spending
angle, or capex discussion unconnected to AI/data centers.

## q11 — `small modular reactor nuclear power`

A relevant document discusses nuclear power for new load — small modular
reactors, restarts, or nuclear procurement; grade 2 for a specific agreement,
MOU, siting, or procurement with named parties, site, capacity, or a decision;
grade 1 for general discussion of nuclear/SMR options or feasibility; grade 0
for passing mentions of nuclear or energy mix with no project or procurement
substance.

## q12 — `water reclamation reuse cooling`

A relevant document discusses reclaimed or reuse water for cooling or
industrial supply — purple-pipe infrastructure, reuse agreements, treatment
capacity for industrial customers; grade 2 for a specific reuse arrangement
or infrastructure project with volumes, parties, cost, or a decision; grade 1
for general water-reuse discussion; grade 0 for water discussion with no
reclamation/reuse angle.

## q13 — `land sale industrial development acres`

A relevant document discusses the sale, purchase, or optioning of land for
industrial or technology development; grade 2 for a specific transaction with
acreage, price, buyer/seller, or a vote/decision on it; grade 1 for general
land-assembly or industrial-park discussion without transaction-level detail;
grade 0 for land matters unrelated to industrial/tech development.

## q14 — `fiber optic broadband expansion`

A relevant document discusses fiber or broadband buildout — new routes,
franchise or permit approvals, funding awards, provider agreements; grade 2
for a specific project with provider, funding, coverage area, or a decision;
grade 1 for general connectivity or digital-divide discussion; grade 0 for
passing mentions of internet service with no buildout substance.

## q15 — `electric rate increase data center load growth`

A relevant document discusses electric rates or cost allocation in connection
with large-load growth; grade 2 for a rate case, tariff, or cost-allocation
matter explicitly tied to data-center/large-customer load with figures or a
decision; grade 1 for general discussion of rates or load growth where the
connection is implied but not concrete; grade 0 for rate matters with no
load-growth tie, or load discussion with no rate/cost angle.

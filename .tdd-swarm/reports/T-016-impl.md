# T-016 Implementation Report — Wire the design app to the live API
(search, tickers, prices, metrics, ask)

**Status:** DONE — the studio app's embedded sample-data layer is replaced by
live API calls; verified endpoint-by-endpoint with curl against the real
~24k-doc index, plus a headless execution of the wired dc-logic against that
same live server. Design fidelity preserved (data bindings only — no layout,
style, animation or interaction rewrites). `ui/support.js` untouched.

**Files:** `ui/OnRecord App.dc.html` (wired), `ui/index.html` (byte-for-byte
servable copy), `ui/WIRING.md` (new — endpoint map, curl evidence, manual
browser checklist). Nothing outside `ui/**` was modified.

**Verification note:** no browser was available to this agent. Everything
below was verified by curl + a headless node harness that runs the real
`class Component extends DCLogic` (stubbing only `DCLogic`/`window`/`location`)
against the live server and asserts the mapped `renderVals()` output. The
in-browser pass is written up as a 36-item checklist in `ui/WIRING.md` §8 and
is **unexecuted** — it needs an orchestrator/human run.

## Wiring map — status against the ticket's 8 items

1. **`apiBase` → `''` (same-origin).** Default changed in `data-props` *and*
   in `apiBase()`; the prop override survives (and now strips trailing `/`).
2. **Search → `GET /api/search`, debounced 250 ms.** `currentResults()`'s
   local scoring is gone. Request: `q`, `mode=lexical`, `op=OR`, `k=20`, plus
   `source`/`venue`/`ticker`/`jurisdiction` from the pills (only when not
   "All"). Mapping: `doc_id`→id, `snippet`→segments via `<mark>` parsing,
   `source_type`→icon/CTA/meta, `venue_type`→venue chip, `deep_link`→link,
   `&t=NNNs`→`mm:ss`/`h:mm:ss` for the `▶` pill, `score`→the BM25 figure,
   `line` composed as `<jurisdiction ?? ticker> · <source label> · <date>`.
   Stale-response guard via a request sequence token; keyboard nav and
   `selIdx` behavior unchanged. The fake `18 + (q.length*7)%40` latency is now
   a real `performance.now()` measurement.
3. **Tickers → `GET /api/tickers` once per mount.** `SECTORS`/`FEATURED`
   deleted. Registry sector slugs are mapped to the design's own ten section
   headings and re-sorted into the design's order (the endpoint sorts
   alphabetically by slug). `NAMES` kept as the detail-pane display fallback,
   per the ticket. Also feeds the ticker filter pill and the hero
   "N tickers" stat (live: 102).
4. **Detail pane → `GET /api/prices/{sym}?range=365`.** `series()`, `rng()`,
   `hashSym()`, `weekIndex()` and the fake shock injection are deleted. Series
   → SVG path (x generalized to `i/(n-1)*720` for daily data),
   `significant_moves` → dashed rules + the moves list, their
   `nearby_receipts` → the green receipt markers with `mkI` hover intact.
   **The route 404s today** (parallel ticket); loading / 404 / empty-series all
   land on a design-language "price data isn't on the record yet" note with
   `—` price and a hidden delta chip. No code change needed when it ships.
5. **Scoreboard → `GET /api/metrics`.** Hardcoded `METRICS` deleted. Rows map
   `metrics.mean["P@10"/"R@50"/"MRR"/"NDCG@10"]`, `timestamp[:10]`, and
   `corpus_version` (falling back to short `git_sha` while it is
   `"unversioned"`). Empty → tiles/table hidden behind an honest "No eval runs
   yet. / The red harness is pending labels…" card in the design's voice.
6. **Ask → `POST /api/answer`.** The design had *no* handler (Enter only
   queued locally), so one was added sending exactly the pinned
   `{question, mode:"lexical", k:8}`. `{"error":"available_thursday"}` renders
   through the design's existing QUEUED-FOR-THURSDAY card. The Semantic/Hybrid
   teasers now also do a real `mode=` contract check and would say so if
   semantic ever goes live.
7. **`CORPUS` retained as the api-down demo fallback only.** Used solely when
   `state.apiDown`; visibly labeled in three places — header chip
   `demo data · API unreachable`, list label `Demo data · API unreachable`,
   and `countLine` `N receipts · demo data`. Never rendered while the API
   answers. Tickers/Scoreboard do **not** fall back to invented data; they show
   honest offline cards. `retry` re-runs the whole bootstrap.
8. **`ui/index.html` created** as a byte-for-byte copy (`cmp` clean); the
   `.dc.html` design filename is kept for studio round-trips.

**DoD:** `ui/WIRING.md` written (view→endpoint table, curl transcripts,
deviations, known gaps, run instructions, 36-item browser checklist).
`git diff --stat` on `ui/support.js`: **zero changes**.

## Curl evidence (server: `ONRECORD_INDEX=.../advanced-rag/artifacts/index uv run uvicorn onrecord.api:app --port 8123`)

Index: 24,115 docs · 28 jurisdictions · 102 registry tickers (76 with ≥1 receipt).

- `/health` → `{"status":"ok"}`
- `/api/search?q=substation&k=2&op=OR` → full 9-key result dicts; BM25 scores
  ~11.06; `deep_link` `…&t=4125s`. **Snippets carry no `<mark>`.**
- Filters confirmed AND-combined: `ticker=VST` (2/2 VST), `source=filing&venue=coached`
  (3/3 both), `jurisdiction=Chandler, AZ` (2/2). `q=` and a gibberish term both → 0 results.
- `mode=semantic` → `{"error":"available_wednesday"}`; `op=or` → 422; `k=0` → 422
  (the UI only ever sends uppercase `OR` and `k=20`).
- `/api/tickers` → `{"sectors":[…]}`, 10 sectors / 102 tickers / 958 receipts;
  two sectors legitimately have 0.
- `/api/metrics` → `[]` today; re-checked with a temporary two-row
  `artifacts/scoreboard.jsonl` (gitignored, deleted afterwards) to prove the
  populated mapping — tiles `P@10 0.31 (+0.19 vs a1b2c3d)`, newest-first table.
- `POST /api/answer {"question","mode","k"}` → `{"error":"available_thursday"}` 200.
- `/api/prices/VST?range=365` → **404 `{"detail":"Not Found"}`** (expected).

Headless harness results (against the same server): `20 receipts · 59 ms`,
row line `Culpeper County, VA · county meeting · 2026-06-03`, CTA `▶ 1:08:45`,
score `11.06`, 5 snippet segments with 2 highlighted; sector order matches the
design; 12 rapid keystrokes → **1** request at ~250 ms (0 at 120 ms); no
empty-card flash at first paint; jurisdiction options 7 → 17 after the probe;
prices 404 → graceful note; a simulated pinned prices payload → 250-point path,
`+29.1% 1Y`, 2 dashed rules, 1 receipt marker, correct hover card; api-down →
all three demo labels. Full transcripts in `ui/WIRING.md` §6.

## Deliberate deviations (all justified in `ui/WIRING.md` §4)

1. **`<mark>` parsing has a term-highlight fallback.** Mark-span parsing is the
   primary path, but live snippets contain no marks today, so a snippet without
   any falls back to highlighting the query terms client-side. Without it every
   row would render as flat unhighlighted text — a visible design regression.
   Segments render as React text nodes, so snippet content is never markup.
2. **`max-height:280px; overflow-y:auto` on the ticker and jurisdiction
   dropdowns** — the designer sized them for 6 sample values; live cardinality
   is 76 and 28. Only addition to any style attribute in the file.
3. **`1Y · weekly close` → `1Y · daily close`** and **`weekly move over 6%` →
   `significant daily move (±5%)`** — the old copy described the deleted
   synthetic weekly generator; the pinned contract is daily closes at a 5.0%
   default threshold.
4. **Significant moves ranked "has nearby receipts" first, then by magnitude**
   (same 6 rules / 4 rows as designed) — with 365 real days, the design's
   first-6-chronologically slice would surface the oldest moves, not the ones
   the record explains.
5. **Empty-state copy is a two-variant binding** — the designer's exact
   original strings for a real zero-hit, a "Start with a term." variant for a
   blank query. Same card, same styles, same chips.

## Follow-ups for other tickets (not actioned — out of `ui/**` scope)

- **`nearby_receipts` lacks `venue_type` and `snippet`.** The pinned shape is
  `{id, date, source_type, deep_link}`, so the chart's receipt hover card shows
  a neutral source chip and a factual line instead of the passage. Adding those
  two fields upgrades the card with no UI change beyond two field reads.
- **The API does not serve `ui/` yet**, which `apiBase: ''` assumes. Until a
  static mount exists, cross-origin dev needs
  `__dcSetProps(__dcRootName(), {apiBase: '…'})` and the UI served from
  `http://localhost:5173` (the only CORS-allowed origin).
- **No corpus-stats endpoint.** The hero strip's "24,412 documents indexed" and
  "31 jurisdictions" remain static design copy (live: 24,115 / 28). Only the
  ticker figure is wired. A small `GET /api/stats` would close this.
- **`docket` source and `candid` venue filters return zero results** — offered
  by the design, absent from the current index. Left as designed; they produce
  the honest empty state.

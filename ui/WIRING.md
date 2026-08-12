# ui/ — live API wiring (T-016)

The studio app (`ui/OnRecord App.dc.html`) shipped rendering **embedded sample
data**: a 14-row `CORPUS` array, a seeded-RNG `series()` price generator, and
hardcoded `SECTORS` / `FEATURED` / `METRICS`. T-016 swaps the **data layer** for
the live API. Layout, styles, animations, keyboard nav and interaction patterns
are unchanged — only where the numbers come from changed.

- `ui/OnRecord App.dc.html` — the design file (kept for studio round-trips).
- `ui/index.html` — byte-for-byte servable copy of the same file.
- `ui/support.js` — **untouched** (zero changes, per the ticket).

`apiBase` now defaults to `''` (**same-origin** — the API serves this UI). The
prop override survives for cross-origin dev; see "Running it" below.

---

## 1. View → endpoint map

| View / surface | Endpoint | Mapping |
|---|---|---|
| **Search results** | `GET /api/search?q=&mode=lexical&op=OR&k=20` + `source`/`venue`/`ticker`/`jurisdiction` | `doc_id`→row id · `snippet`→`segs` (`<mark>` parsing) · `source_type`→`source` (icon + CTA + `meta`) · `venue_type`→venue chip · `deep_link`→`link` · `&t=NNNs` in the link→`ts` (`mm:ss` / `h:mm:ss`, the `▶` CTA) · `date`→`dateStr` · `score`→the right-hand BM25 figure · `line` composed as `<jurisdiction ?? ticker> · <source label> · <date>` |
| Search latency (`countLine`) | same request | real wall-clock ms (`performance.now()` around the fetch). Was a fake `18 + (q.length*7)%40`. |
| Filter pills | same request | `source`/`venue`/`ticker`/`jurisdiction` query params, AND-combined server-side |
| Ticker pill options | `GET /api/tickers` | symbols with `receipt_count > 0`, busiest first |
| Jurisdiction pill options | `GET /api/search` responses | accumulated from live results; one broad probe (`k=150`) fires the first time the dropdown opens |
| Semantic / Hybrid teasers | `GET /api/search?mode=semantic\|hybrid` | contract check — API answers `{"error":"available_wednesday"}`; the designer's teaser copy shows. If the mode ever goes live the teaser says so instead. |
| Hero "N tickers" | `GET /api/tickers` | live total (102) |
| **Tickers view** | `GET /api/tickers` once per mount | `sectors[].sector` (registry slug) → the design's own section headings, in the design's order · `tickers[].symbol`→card · `receipt_count`→count chip + section `countLine` · `last_receipt`→card teaser. `NAMES` kept as the detail-pane display fallback (the endpoint carries no company name). |
| **Detail pane series** | `GET /api/prices/{sym}?range=365` | `series[]`→SVG path (x = `i/(n-1)*720`) · `significant_moves[]`→dashed rules + the "Significant moves" list · `significant_moves[].nearby_receipts[]`→the green receipt markers (`mkI` hover card, deduped by `id`) · last/first close→price + 1Y delta |
| **Scoreboard** | `GET /api/metrics` | `metrics.mean["P@10"/"R@50"/"MRR"/"NDCG@10"]`→tiles + table · `timestamp[:10]`→date · `corpus_version` (or short `git_sha` when it is `"unversioned"`)→version · last row vs previous→tile deltas |
| **Ask** | `POST /api/answer` `{question, mode:"lexical", k:8}` | `{"error":"available_thursday"}` → the design's existing QUEUED-FOR-THURSDAY card. Fires on Enter and on every suggestion chip. |

**Removed:** `SECTORS`, `FEATURED`, `METRICS`, `hashSym`, `rng`, `series()`,
`WEEK0`/`weekIndex` (the fake shock injection is gone with them).
**Kept:** `NAMES` (display fallback), `CORPUS` (**api-down demo only**, below).

## 2. Demo data — where it survives, and how it is labeled

`CORPUS` is used **only** when `state.apiDown` is true. When it is showing:

- header engine chip reads **`demo data · API unreachable`** (amber dot) with
  the designer's `retry` button next to it;
- the results list label reads **`Demo data · API unreachable`**;
- `countLine` reads `N receipts · demo data` instead of a latency figure;
- the Tickers and Scoreboard views show honest "offline" cards — they never
  fall back to invented sectors or metrics.

It is never rendered while the API answers. `retry` re-runs the full bootstrap
(tickers + metrics + search).

## 3. Graceful states

| Condition | What renders |
|---|---|
| First paint / debounce window | `searching…`; the empty card cannot flash |
| Empty query | the designer's empty card with "Start with a term." copy |
| Zero hits | the designer's original "The record is silent on this." copy |
| `/api/prices` 404 (route not built yet), or empty series | design-language note: *"Price data isn't on the record yet — the EOD series arrives with the prices route. Receipt counts stand on their own."* Price/delta show `—` and the delta chip hides. |
| `/api/prices` in flight | *"Fetching the price series…"* |
| Series present, no receipts in window | the designer's existing "No receipts on this timeline yet" copy |
| `/api/metrics` → `[]` | *"No eval runs yet."* / "The red harness is pending labels. `make eval` writes every run to artifacts/scoreboard.jsonl and this board fills itself in — nothing here is ever hand-typed." |
| `/api/metrics` unreachable | *"The scoreboard is out of reach."* |
| `/api/tickers` 503 / unreachable | *"The universe is offline."* |

## 4. Deliberate deviations (and why)

1. **`<mark>` parsing has a documented fallback.** `segsFromSnippet()` parses
   `<mark>…</mark>` spans into the design's `{t, style}` segments. Today's
   `/api/search` snippets carry **no** `<mark>` at all (curl evidence below), so
   when a snippet has none the analyzed query terms are highlighted client-side.
   Without this every result row would silently render as flat, unhighlighted
   text — a visible design regression. Mark parsing is the primary path and
   takes over automatically the day the API emits marks. Segments render as
   React text nodes, so snippet content is never interpreted as markup.
2. **`max-height:280px; overflow-y:auto` added to the ticker and jurisdiction
   dropdowns.** The designer sized them for 6 sample values; live cardinality is
   76 tickers and 28 jurisdictions, which would run off-screen. Same border,
   radius, shadow, padding and animation — it only scrolls now.
3. **`1Y · weekly close` → `1Y · daily close`, and `weekly move over 6%` →
   `significant daily move (±5%)`.** The pinned prices contract is daily closes
   with a 5.0% default threshold; the old labels described the removed synthetic
   weekly generator.
4. **Significant moves are ranked "has nearby receipts" first, then by
   magnitude.** Same visual density as the design (6 dashed rules, 4 listed
   rows), but with 365 days of real data the first-6-chronologically slice would
   have shown the oldest moves rather than the ones the record explains.
5. **The `mkI` hover card states what is known instead of inventing a passage.**
   The pinned `nearby_receipts` shape is `{id, date, source_type, deep_link}` —
   no `venue_type` and no snippet text. The chip therefore shows the source in a
   neutral treatment (same chip geometry as `VENUES`) and the body reads
   "Receipt on the record inside this move's window — open the source to read
   the passage in context." **Recommendation for the prices ticket: add
   `venue_type` and `snippet` to `nearby_receipts`** and this card becomes a
   full receipt with zero UI change beyond the two field reads.

## 5. Known gaps / gracefully pending

- **`GET /api/prices/{ticker}` does not exist yet** (404 today — a parallel
  ticket adds it). It is wired to the pinned payload and the panel degrades to
  the "not on the record yet" note. No change needed here when it lands.
- **`POST /api/answer`** returns the Thursday stub; the queued card is the
  teaser. The pinned real shape (`answer_id`/`text`/`citations`/`retrieved`/
  `grounding`/`refusal`) is not rendered — that's the RAG ticket's job.
- **The API does not serve `ui/` yet.** `apiBase: ''` assumes it will. Until a
  static mount exists, use the override in "Running it".
- **Hero stat strip: "24,412 documents indexed" and "31 jurisdictions" are
  static design copy.** No endpoint exposes corpus-wide totals. Measured live
  values right now: **24,115 documents, 28 jurisdictions, 102 tickers** (the
  ticker figure *is* wired). A small `GET /api/stats` would close this.
- **`docket` source and `candid` venue filters return zero results** — the
  design offers them, the current index has only `county_meeting`/`filing` and
  `sworn`/`coached`. The options are left as designed; they produce the honest
  empty state.
- **CORS** currently allow-lists only `http://localhost:5173`.

---

## 6. Curl evidence

Server used for every check below:

```
ONRECORD_INDEX=/Users/quietguy/Documents/Dev/Gauntlet/advanced-rag/artifacts/index \
  uv run uvicorn onrecord.api:app --port 8123
```

Real index: 24,115 docs · 28 jurisdictions · 102 registry tickers (76 with ≥1 receipt).

**Health**
```
$ curl -s http://127.0.0.1:8123/health
{"status":"ok"}
```

**Search — result shape, all 9 keys, deep-link timestamp, no `<mark>`**
```
$ curl -s 'http://127.0.0.1:8123/api/search?q=substation&k=2&op=OR'
{"query":"substation","mode":"lexical","results":[
 {"doc_id":"yt:xg-oyNQXjLU:seg055","score":11.058376667917042,
  "snippet":" said that that in your opinion yeet was always meant to finish at the existing substation in Falker County >> not an existing substation. There's existing nodes. Yeet wa",
  "date":"2026-06-03","source_type":"county_meeting","venue_type":"sworn",
  "jurisdiction":"Culpeper County, VA","ticker":null,
  "deep_link":"https://youtube.com/watch?v=xg-oyNQXjLU&t=4125s"}, ...]}
```
→ snippet carries **no `<mark>`** (drives deviation #1); `&t=4125s` → `1:08:45`.

**Search — filters, AND-combined**
```
$ curl -s 'http://127.0.0.1:8123/api/search?q=capacity&k=2&ticker=VST'
  → 2 hits, every ticker "VST", source_type "filing"
$ curl -s 'http://127.0.0.1:8123/api/search?q=megawatts&k=3&source=filing&venue=coached'
  → 3 hits, all source_type=filing AND venue_type=coached
$ curl -sG 'http://127.0.0.1:8123/api/search' --data-urlencode 'q=water' \
      --data-urlencode 'jurisdiction=Chandler, AZ' --data-urlencode 'k=2'
  → 2 hits, both jurisdiction "Chandler, AZ"
$ curl -s '.../api/search?q=zzzznotarealterm&k=5'   → results: 0   (empty state)
$ curl -s '.../api/search?q=&k=5'                   → results: 0   (empty-query state)
```

**Search — validation + stub modes (drives the teasers)**
```
$ curl -s '.../api/search?q=x&mode=semantic'   → {"error":"available_wednesday"}  200
$ curl -so/dev/null -w '%{http_code}' '.../api/search?q=x&op=or'  → 422
$ curl -so/dev/null -w '%{http_code}' '.../api/search?q=x&k=0'    → 422
```
The UI only ever sends `op=OR` (uppercase) and `k=20`, so it stays inside the
whitelist.

**Tickers**
```
$ curl -s http://127.0.0.1:8123/api/tickers
top-level keys: ["sectors"] · 10 sectors · 102 tickers · 958 receipts · 76 with >0
sample: {"symbol":"ACM","receipt_count":11,"last_receipt":"2026-08-10"}
sector slugs: builders_ec, dc_reit_land, gas_midstream_fuel,
  grid_copper_fiber_materials, hyperscaler_ai, neocloud_miner_pivot,
  nuclear_smr_uranium, power_equipment_cooling, servers_networking, utilities_ipp
```
→ slugs mapped to the design's ten headings, re-ordered into the design's order.
Sectors with 0 receipts (`grid_copper_fiber_materials`, `servers_networking`)
still render, cards read "no receipts on the record yet".

**Metrics — empty (current real state)**
```
$ curl -s -w ' HTTP %{http_code}' http://127.0.0.1:8123/api/metrics
[] HTTP 200
```
→ renders "No eval runs yet."

**Metrics — populated** (temporary `artifacts/scoreboard.jsonl`, two rows, deleted after the check)
```
[{"timestamp":"2026-08-09T21:04:11+00:00","git_sha":"a1b2c3d4…","corpus_version":"unversioned",
  "metrics":{"per_query":{...},"mean":{"P@5":0.2,"P@10":0.12,"R@10":0.2,"R@50":0.28,"MRR":0.19,"NDCG@10":0.15}}},
 {"timestamp":"2026-08-11T18:47:02+00:00","git_sha":"9f8e7d6…", ...
  "mean":{...,"P@10":0.31,"R@50":0.52,"MRR":0.38,"NDCG@10":0.34}}]
```
→ table rows newest-first `9f8e7d6 / 2026-08-11 / 0.31 / 0.52 / 0.38 / 0.34`,
tiles `P@10 0.31 (+0.19 vs a1b2c3d)` etc., red under 0.50 exactly as designed.

**Answer**
```
$ curl -s -X POST http://127.0.0.1:8123/api/answer \
    -H 'Content-Type: application/json' -d '{"question":"test q","mode":"lexical","k":8}'
{"error":"available_thursday"}   HTTP 200
```

**Prices — not built yet**
```
$ curl -s -w ' HTTP %{http_code}' 'http://127.0.0.1:8123/api/prices/VST?range=365'
{"detail":"Not Found"} HTTP 404
```
→ panel shows the "not on the record yet" note; no crash, no fake series.

### Headless logic check

The dc-logic class was additionally executed **outside a browser** (node harness
stubbing `DCLogic`/`window`/`location`) against this same live server, asserting
the mapped `renderVals()` output. Results:

```
countLine        20 receipts · 59 ms          row.line   Culpeper County, VA · county meeting · 2026-06-03
row.venueLabel   SWORN                        row.cta    ▶ 1:08:45
row.refChip      Culpeper County, VA          row.score  11.06
row.meta         2026-06-03 · county meeting  row.segs   5 segments, 2 highlighted ("substation")
hero tickerTotal 102                          tickerOpts 77 (All + 76 live)
filter source=filing&ticker=VST → 4 hits, line "VST · SEC filing · 2026-01-09"
sector order     Utilities & IPPs, Hyperscalers & AI, Neoclouds & Miner Pivots, …  (design order)
debounce         12 rapid keystrokes → 0 requests at 120 ms, 1 request at 720 ms
first paint      countLine "searching…", noResults false (no empty-card flash)
jur probe        7 options before opening the dropdown → 17 after
prices (404)     detPriceMsg "Price data isn't on the record yet…", detPrice "—", delta chip hidden
prices (payload) 250-pt path, +29.1% 1Y, 2 dashed rules, 1 receipt marker,
                 mk card [SEC FILING · VST · 2025-11-23 · EDGAR ↗]
api-down         engineLabel "demo data · API unreachable", listLabel "Demo data · API unreachable",
                 countLine "3 receipts · demo data", tickers "The universe is offline."
```

---

## 7. Running it

**Same-origin (target).** Once the API serves `ui/`, `apiBase: ''` just works —
open the API's own origin, no configuration.

**Today (API has no static mount).** Serve `ui/` on the origin the API's CORS
already allows (`http://localhost:5173`) and point the app at the API:

```bash
# terminal 1 — API
ONRECORD_INDEX=/path/to/advanced-rag/artifacts/index uv run uvicorn onrecord.api:app --port 8000

# terminal 2 — UI
python3 -m http.server 5173 --directory ui
```

Open `http://localhost:5173/index.html`, then in the browser console:

```js
__dcSetProps(__dcRootName(), { apiBase: 'http://localhost:8000' })
```

(`__dcSetProps` / `__dcRootName` are support.js's own prop-override bridge.)

---

## 8. Manual browser checklist

No browser was available to this agent — every item below is **unexecuted** and
needs a human/orchestrator pass. Set up per §7 first. Keep DevTools → Network
open throughout.

### A. Boot + search
1. Load the page. Header chip goes `connecting…` → **`live engine`** with a
   green dot. No `retry` link. Network shows `GET /api/tickers`,
   `GET /api/metrics`, `GET /api/search?q=substation+capacity&mode=lexical&op=OR&k=20`.
2. Results list shows ~20 rows. Each row: date on the left, a green source icon,
   a venue chip (`SWORN`/`COACHED`), a ref chip (jurisdiction or ticker), the
   snippet with **green highlight** on matched terms, a `▶ mm:ss` pill (county
   meetings) or `EDGAR ↗` / `Docket ↗` outline pill, the composed
   `Jurisdiction · source · date` line, and a BM25 score on the right.
3. `countLine` (top right of the filter row) reads `N receipts · NN ms` with a
   **real, varying** latency — not a value that tracks the query's length.
4. Type into the search box. Confirm in Network that a **single** request fires
   ~250 ms after you stop typing, not one per keystroke.
5. Clear the box → "Start with a term." card with the four suggestion chips.
   Click `substation` → it searches immediately.
6. Type gibberish (`zzzznotarealterm`) → "The record is silent on this." card.
   No empty-card flicker while the request is in flight.

### B. Filters
7. Open **Source** → pick "SEC filings". Pill turns green, request carries
   `&source=filing`, every row's icon is the document icon.
8. Open **Ticker** → the list is long and **scrolls inside the popup** (does not
   run off-screen). Pick one → request carries `&ticker=…`.
9. Open **Jurisdiction** → a broad `k=150` probe fires once; the list fills out
   and scrolls. Pick one → request carries the URL-encoded jurisdiction.
10. Two filters at once → both params on one request, results satisfy both.
11. `clear ✕` resets all four pills and re-searches.
12. Click **Semantic** → amber teaser banner appears (a `mode=semantic` request
    fires and returns `available_wednesday`). `✕` dismisses it. Same for Hybrid.
13. Click outside an open dropdown → it closes (root-click behavior intact).

### C. Keyboard
14. Press `/` anywhere → search input focuses. `?` → jumps to Ask and focuses.
15. `↑`/`↓` move the highlighted row (cream background) without scrolling the
    page; the selection clamps at both ends.
16. `Enter` on a selected row opens its `deep_link` in a new tab; for a county
    meeting the YouTube video starts at the `▶ mm:ss` offset shown on the pill.
17. Hovering a row also selects it. `Escape` closes dropdowns/modals and blurs.

### D. Tickers
18. Go to **Tickers**. Ten sections in the design's order, starting
    "Utilities & IPPs". Header copy reads "102 tickers across the buildout's…".
19. Section sub-line reads `N receipts · M tickers`; cards show the symbol, a
    green receipt-count chip, and `latest receipt · YYYY-MM-DD`.
20. Sections with no receipts (Grid/Copper/Fiber, Servers & Networking) still
    render, with `0` chips and "no receipts on the record yet" — **not** invented
    counts.
21. Card hover → green border + lift (unchanged).

### E. Detail pane / prices
22. Click any ticker → modal opens with the symbol, the `NAMES` display name (or
    "On the record"), gridlines, and briefly *"Fetching the price series…"*.
23. **Before the prices route lands:** price reads `—`, the delta chip is hidden,
    and the note reads *"Price data isn't on the record yet — the EOD series
    arrives with the prices route…"*. No fake line, no console error.
24. **After it lands:** a real price path draws, the header shows `$X.XX` and a
    `±N.N% 1Y` chip (green/red), dashed rules mark significant moves, and green
    circles mark receipts. Hovering a circle opens the receipt card below the
    chart (source chip, ticker, date, and its `EDGAR ↗` / `▶ mm:ss` link).
    "Significant moves" lists up to 4 rows with signed percentages.
25. `✕`, backdrop click, and `Escape` all close the modal. Clicking inside it
    does not close it.

### F. Scoreboard
26. Go to **Scoreboard**. With no eval runs: the tiles and table are hidden and
    the card reads "No eval runs yet." + the red-harness sentence. "Measured, not
    vibed." still sits below.
27. Run `make eval` (or drop rows into `artifacts/scoreboard.jsonl`), reload:
    four tiles (P@10, R@50, MRR, NDCG@10) with values **red under 0.50**, a
    signed delta chip and `vs <previous version>`; the table lists runs
    newest-first with version + date. Values must match the JSONL's
    `metrics.mean` exactly.

### G. Ask
28. Go to **Ask**. The "PREVIEW THREAD · illustrative answers until /api/answer
    lands Thursday" banner is present (this is the label on the two illustrative
    Q&A blocks).
29. Type a question, press Enter → Network shows `POST /api/answer` with body
    **`{"question":"…","mode":"lexical","k":8}`** and response
    `{"error":"available_thursday"}`. The Q·3 "QUEUED FOR THURSDAY" card appears
    with your question; the input clears.
30. Each suggestion chip fires the same POST. Hovering a citation `n` opens its
    popover; "HOW THIS WAS ANSWERED" expands and the chevron rotates.

### H. API-down / demo data
31. Stop uvicorn, click `retry` in the header. Chip goes amber and reads
    **`demo data · API unreachable`**; results label reads **`Demo data · API
    unreachable`**; `countLine` reads `N receipts · demo data`.
32. Tickers view shows "The universe is offline." — **no** sector grid.
    Scoreboard shows "The scoreboard is out of reach." — **no** numbers.
33. Restart uvicorn, click `retry` → everything returns to live, and no demo row
    is visible anywhere.

### I. Responsive / fidelity
34. At <640 px: bottom tab bar appears, the date column and score column drop,
    rows stack. At 640–1024 px and >1024 px the padding steps 18/32/56 px and the
    Ask rail becomes a sticky sidebar at ≥1024 px.
35. Fade-up/pop animations still play on the results list, cards and modal; the
    `▶` pill still pulses on hover.
36. Console is free of errors and of dc-runtime `sc-interp sc-missing` warnings
    on every view.

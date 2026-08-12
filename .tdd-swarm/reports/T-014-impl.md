# T-014 Implementation Report — Prices layer (EOD series cache,
significant-move detection, receipts-vs-price window join, /api/prices)

**Status:** DONE — all 17 frozen tests in `tests/unit/ingest/test_prices.py`
pass; all local gates green.

**File scope:** `onrecord/ingest/prices.py` only (new file — no
pre-existing stub for this ticket). `tests/` and `tests/fixtures/prices/**`
untouched.

## What was implemented

`onrecord/ingest/prices.py`, per the ticket + the pinned contract in
`tests/unit/ingest/test_prices.py`'s module docstring and
`.tdd-swarm/reports/T-014-test.md`:

- `parse_stooq_csv(text) -> list[dict]` — pure stooq CSV parser. Header row
  detected as the first non-blank line (not a hardcoded line number, for
  robustness against leading blank lines). A data row is skipped + logged
  at WARNING (message contains `"skip"`) when it doesn't split into exactly
  6 fields, the `Close` field isn't a valid float, or the `Date` field
  isn't a valid `YYYY-MM-DD` date. Blank lines skipped silently. Result
  sorted ascending by date.
- `parse_fmp_historical_prices(payload) -> list[dict]` — pure FMP
  `historical-price-full` payload parser. Missing/non-list `"historical"`
  -> `[]`. Rows with a missing/non-numeric `close` or unparsable `date` are
  skipped. Result re-sorted ascending (FMP returns newest-first).
- `fetch_eod(ticker, range_days=365, transport=None, cache_dir=None) ->
  list[dict]` — on-disk cache at `<cache_dir>/<ticker>.json` (`cache_dir=
  None` defaults to `artifacts/prices`, never exercised by tests), fresh
  (`now - fetched_at <= 1 day`) cache hits short-circuit with **zero**
  network calls. Stale/missing cache triggers stooq (host `stooq.com`,
  `<ticker>.us` symbol lowercase in the query) as primary; FMP (host
  `financialmodelingprep.com`) attempted ONLY when stooq fails AND
  `FMP_API_KEY` is set/non-blank. Never raises: per-source failures log at
  DEBUG (below the AC-5 INFO capture threshold, so they never inflate the
  "one log line" count); total failure returns `[]` plus exactly one
  `logger.info(...)` line naming the ticker, and does NOT write a cache
  entry (avoids a misleadingly "fresh" empty cache masking real recovery).
  A successful fetch overwrites the cache with the new series + a current
  `fetched_at`.
  - **T-008 lesson applied**: never calls `response.raise_for_status()`
    (its `HTTPStatusError.__str__` embeds the full request URL — including
    the FMP `apikey` query param — in plaintext) and never logs the
    request URL/params/response body for the FMP path; only ticker + HTTP
    status code, at DEBUG. The FMP key itself is never interpolated into
    any log message or exception anywhere in this module.
- `significant_moves(series, threshold_pct=5.0) -> list[dict]` — signed
  `(close[i]-close[i-1])/close[i-1]*100` per day from index 1 onward
  (first day never appears), inclusive `abs(return_pct) >= threshold_pct`
  boundary, order preserved. Pure.
- `nearby_receipts(moves, corpus_rows, ticker, window_days=7) ->
  list[dict]` — new list (never mutates `moves`), one entry per move plus
  a `"nearby_receipts"` key: `{"id", "date", "source_type", "deep_link"}`
  dicts for every `corpus_rows` `Doc` where `doc.ticker == ticker` and
  `0 <= (move_date - doc_date).days <= window_days`. Pure.
- `api_payload(ticker, corpus_path, range_days=365, threshold_pct=5.0,
  window_days=7, transport=None, cache_dir=None) -> dict` — composes
  `fetch_eod` -> `significant_moves` -> `nearby_receipts` (over
  `onrecord.ingest.build_corpus.load_corpus_snapshot(corpus_path)`) into
  the exact `/api/prices` payload shape: `{"ticker", "series",
  "significant_moves": [{"date", "return_pct", "nearby_receipts": [...]},
  ...]}`. Function exposed only — no HTTP route wiring (out of scope,
  lands in T-013/wave-5 per the ticket).

No test disputes — the ticket's ACs mapped directly onto the pinned test
contract; no `BLOCKED(TEST_DISPUTE)` needed.

## Verification

```
uv run pytest tests/unit/ingest/test_prices.py -v
```
-> **17 passed**.

```
.tdd-swarm/run-local-gates.sh . tickets/T-014.md
```
-> `ruff format --check` clean, `ruff check` clean, full suite **200
passed** (183 pre-existing baseline + 17 new, zero regressions),
`spec-lint OK: all ACs covered for T-014` -> **ALL LOCAL GATES GREEN**.

`git status --short`: only `onrecord/ingest/prices.py` added; no changes
under `tests/`.

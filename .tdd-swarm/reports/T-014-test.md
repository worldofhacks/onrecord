# T-014 Test Report — Prices layer (EOD series cache, significant-move
detection, receipts-vs-price window join, /api/prices payload)

**Status:** DONE (frozen failing tests written, confirmed RED for the right
reason against the current empty state, confirmed GREEN against a
throwaway correct implementation built and run in-worktree, then fully
reverted — zero diff outside `tests/`).

**Test file:** `tests/unit/ingest/test_prices.py`
**Fixtures:** `tests/fixtures/prices/{stooq_sample.csv, fmp_historical_price_full.json}`

**Run command:**
```
uv run pytest tests/unit/ingest/test_prices.py -v
```

## Import-guard note

`onrecord/ingest/prices.py` does not exist at all (this is a later-added
scope ticket with no pre-existing T-001 stub, unlike T-006/T-007/T-008). A
bare `from onrecord.ingest import prices` raises `ImportError` at
COLLECTION time, which would blow up the whole file with a collection
error rather than clean per-test failures. The import is guarded
(`prices = None` on `ImportError`), and every test resolves its callable
via `_callable_or_fail`, which converts both "module missing" and "module
exists but function missing" into the same clean `pytest.fail(...)` — no
traceback, no collection error. Confirmed by running the suite with no
`onrecord/ingest/prices.py` present: 17 collected, 17 failed, each via a
one-line `pytest.fail`, 0 errors.

## API contract fixed by this ticket's test agent (not otherwise fully pinned)

The ticket sketches `fetch_eod`, `significant_moves`, `nearby_receipts`,
`api_payload` in prose. Full signatures, the on-disk cache shape, the
stooq/FMP source-selection rule, the nearby-receipts window-join semantics
(inclusive both ends, same-ticker-only), and the exact `/api/prices`
payload shape are all pinned in the test file's module docstring — treat
it as part of the frozen contract. Key decisions:

1. **`fetch_eod` gains a `cache_dir: str | Path | None = None` parameter**
   not in the ticket's sketched signature — the dependency-injection point
   (parallel to T-007/T-008's `transport`/`sleep`) that lets every test
   redirect the cache into `tmp_path` instead of ever touching the real
   `artifacts/` directory. Production default (`cache_dir=None` → use
   `artifacts/prices`) is never exercised by any test.
2. **Cache file** `<cache_dir>/<ticker>.json`, shaped `{"ticker",
   "fetched_at": <ISO-8601 UTC>, "series": [...]}`. Fresh = `now -
   fetched_at <= 1 day`. A total fetch failure must NOT write a cache
   entry (would otherwise look "fresh" and mask a real recovery next call)
   — asserted directly in the AC-5 test.
3. **Source URLs**: stooq primary (host `stooq.com`, must carry the
   lowercase `<ticker>.us` symbol somewhere in the URL — exact
   query-string shape left to the implementer); FMP fallback (host
   `financialmodelingprep.com`) attempted ONLY when stooq fails AND
   `FMP_API_KEY` is set — asserted via a network-guard-style
   `httpx.MockTransport` router that raises on any unrouted host, so a
   wrongly-triggered FMP call with no key set surfaces as a clear failure.
4. **`significant_moves`**: `return_pct = (close[i]-close[i-1])/close[i-1]*100`,
   signed, unrounded; boundary is inclusive (`abs(return_pct) >=
   threshold_pct`), per the ticket's own "≥ threshold" wording — verified
   with a parametrized exactly-±5.0%-vs-4.9% boundary test, not just the
   headline -8.2%/+5.1% pair.
5. **`nearby_receipts` receipt-dict shape** (not given by the ticket, pinned
   here): `{"id", "date", "source_type", "deep_link"}` — JSON-serializable,
   never a raw `Doc`. Window join: same ticker AND `0 <= (move_date -
   doc_date).days <= window_days` (before-or-on the move date, up to
   `window_days` earlier; a doc dated after the move never attaches —
   covered by an extra adversarial fixture row beyond what AC-3 strictly
   asks for). Function is pure — asserted the input `moves` list/dicts are
   never mutated in place.
6. **`api_payload`** signature/payload shape pinned in the docstring
   (composes `fetch_eod` → `significant_moves` → `nearby_receipts` +
   `onrecord.ingest.build_corpus.load_corpus_snapshot(corpus_path)`) but
   NOT independently tested here — none of AC-1..AC-5 name it directly,
   its constituent pieces are each covered individually, and its HTTP
   route wiring is explicitly out of this ticket's scope (T-013/wave-5).

## Criterion → test mapping

| Criterion | Test(s) | What it checks |
|---|---|---|
| AC-1 | `test_parse_stooq_csv_pure_parses_ordered_rows_and_skips_malformed` | Pure CSV parser: 5 well-formed rows + 1 malformed row (non-numeric `Close` "N/D") → ascending `{date, close}` list, malformed row skipped (not crashed, not zero-filled), ≥1 WARNING log line containing "skip" |
| AC-1 | `test_parse_fmp_historical_prices_pure_returns_ascending_close_series` | FMP fixture (`historical` newest-first) → re-sorted ascending `{date, close}` list |
| AC-1 | `test_fetch_eod_parses_ordered_rows_from_stooq_and_skips_malformed` | Same CSV fixture served through a mocked stooq transport → `fetch_eod` returns the same ordered/malformed-skipped series; asserts the request URL carries `vst.us`; asserts a successful fetch writes the cache file |
| AC-1 | `test_fetch_eod_falls_back_to_fmp_when_stooq_fails_and_key_is_set` | stooq 500s, `FMP_API_KEY` set → FMP fixture served instead, both sources hit, correct fallback series returned |
| AC-2 | `test_significant_moves_flags_exact_signed_moves_at_threshold` | Hand-built 6-day series (arithmetic shown in the module docstring/constant comment) → exactly the -8.2% and +5.1% days flagged at `threshold_pct=5.0`, correct signed values, the ~0.22%/-2.17%/~0.43% days excluded, order preserved |
| AC-2 | `test_significant_moves_default_threshold_is_5_percent` | Same series, `threshold_pct` omitted → default is 5.0 |
| AC-2 | `test_significant_moves_first_day_never_flagged_no_prior_close` | First series day never appears in output |
| AC-2 | `test_significant_moves_threshold_boundary_is_inclusive` (parametrized ×3) | Exactly +5.0%, exactly -5.0% → flagged (inclusive `>=`); 4.9% → not flagged |
| AC-3 | `test_nearby_receipts_window_join_two_days_attaches_nine_days_and_wrong_ticker_dont` | 4-doc corpus fixture (2-days-prior same-ticker, 9-days-prior same-ticker, 2-days-prior wrong-ticker, 1-day-after same-ticker) against one -8.2% move, `window_days=7` → only the 2-days-prior doc attaches, exact receipt-dict shape asserted, input `moves` not mutated |
| AC-3 | `test_nearby_receipts_default_window_days_is_7` | `window_days` omitted → default is 7 (2-days-prior doc still attaches) |
| AC-4 | `test_fetch_eod_fresh_cache_performs_zero_network_calls` | Cache written 1 hour ago (well under the 1-day freshness window) → `fetch_eod` returns the cached series verbatim, transport call counter stays at 0 |
| AC-4 | `test_fetch_eod_stale_cache_triggers_refetch_and_rewrites_cache` | Cache written 2 days ago → real fetch happens, fresh series returned (not the stale cached one), cache file rewritten with a current `fetched_at` |
| AC-4 | `test_fetch_eod_missing_cache_triggers_fetch_and_writes_cache` | No cache file at all → fetch happens, cache file created |
| AC-5 | `test_fetch_eod_both_sources_fail_returns_empty_with_one_log_line_no_exception` | `FMP_API_KEY` set, both stooq and FMP mocked to 500 → `[]`, both sources actually attempted, exactly ONE `onrecord.ingest.prices` log record at INFO+, no exception escapes, no cache entry written on total failure |
| AC-5 | `test_fetch_eod_stooq_fails_without_fmp_key_returns_empty_and_never_contacts_fmp` | No `FMP_API_KEY` set, stooq 500s → `[]`, FMP never contacted (unrouted-host guard would raise if it were), exactly ONE log line |

17 test items total (3 parametrized as one function = 3 cases counted
individually above).

## Verification performed

1. Ran the suite with no `onrecord/ingest/prices.py` present:
   **17 failed, 0 errors** — every failure a clean one-line `pytest.fail`
   from `_callable_or_fail`, never an `AttributeError`/`ImportError`
   traceback or a pytest collection error. Full repo: **17 failed, 183
   passed** (183 = the pre-existing baseline, untouched).
2. Wrote a throwaway correct implementation directly at
   `onrecord/ingest/prices.py` (not committed) covering every function in
   the pinned contract. Re-ran: **17 passed**. Full repo: **200 passed**
   (183 baseline + 17 new, zero regressions).
3. Deleted the throwaway implementation (`rm onrecord/ingest/prices.py`)
   and confirmed the suite returns to the exact same RED state as step 1
   (**17 failed, 183 passed**) — achievability confirmed, then reverted.
4. `git status` after revert: only `tests/fixtures/prices/` and
   `tests/unit/ingest/test_prices.py` are untracked/new; `onrecord/`
   shows no diff (the throwaway file was never tracked, so its deletion
   leaves no trace) — **zero diff outside `tests/`**.
5. `.tdd-swarm/spec-lint.sh tickets/T-014.md` → `spec-lint OK: all ACs
   covered for T-014`.
6. `uv run ruff format --check .` and `uv run ruff check .` (whole repo,
   post ruff auto-fix on `tests/` for import-sort + `datetime.UTC` alias)
   → both clean.

## Notes for the Implementation Agent

- `parse_stooq_csv`/`parse_fmp_historical_prices` are pure (no I/O) —
  build and unit-test these first, then wire them into `fetch_eod`'s
  stooq-primary/FMP-fallback orchestration + the on-disk cache.
- The AC-5 "one log line" requirement is about `fetch_eod`'s own
  outward-facing summary log, not internal per-source diagnostics — keep
  any per-source failure detail below INFO (e.g. DEBUG) if you want it at
  all; the tests capture at `logging.INFO` for
  `logger("onrecord.ingest.prices")` and require the count to be exactly
  1 when everything fails.
- Cache freshness/staleness and cache-file existence are asserted
  directly (not just the returned series), so an implementation that
  ignores `cache_dir` (always hits `artifacts/prices` for real) will fail
  loudly rather than silently passing by coincidence.
- No `BLOCKED(TEST_DISPUTE)` — all 5 ACs were directly testable against
  the ticket text; gaps not otherwise pinned (cache_dir injection point,
  receipt-dict shape, window-join inclusivity, URL host conventions) were
  resolved with written, documented decisions in the test file's module
  docstring, following the T-007/T-008 precedent for test-agent-pinned
  contracts.

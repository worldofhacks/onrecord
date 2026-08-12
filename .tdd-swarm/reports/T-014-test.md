# T-014 Test Report — Prices layer (EOD series cache, significant-move
detection, receipts-vs-price window join, /api/prices payload)

**Status:** DONE (frozen failing tests written, confirmed RED for the right
reason against the current empty state, confirmed GREEN against a
throwaway correct implementation built and run in-worktree, then fully
reverted — zero diff outside `tests/`). **Update below**: extended
post-review-REJECTED with 5 new regression tests (4 named findings + 1
optional Minor), all confirmed RED against the current (rejected)
implementation, original 17 untouched and still green.

**Test file:** `tests/unit/ingest/test_prices.py`
**Fixtures:** `tests/fixtures/prices/{stooq_sample.csv, fmp_historical_price_full.json}`

## Update — post-review (REJECTED) extension: 5 new regression tests

Review (`.tdd-swarm/reports/T-014-review.md`) REJECTED the implementation
(commit `ab0d9ed`) on one Critical, one Important, one latent-security
finding, plus an optional Minor. All four are now encoded as new,
frozen-on-top tests appended to `tests/unit/ingest/test_prices.py` (the
original 17 tests from the initial handoff, commit `4397d52`, are
untouched — `git diff 4397d52 -- tests/unit/ingest/test_prices.py` only
ever appends). No fixture files needed changing; the `range_days` test
synthesizes its 2-year CSV in-test via a new `_build_synthetic_daily_csv`
helper rather than committing a ~730-line fixture file.

1. **`test_fetch_eod_fmp_key_never_leaks_via_any_logger_at_repo_info_level`**
   (`spec(T-014:AC-5)`, Critical C1) — regression for the verified
   `httpx`-own-logger key leak. Sets a sentinel `FMP_API_KEY`, forces both
   stooq and FMP to fail (mocked), reproduces the repo's own
   `logging.basicConfig(level=logging.INFO, ...)` condition (paired with a
   direct `root_logger.setLevel(logging.INFO)`, since `basicConfig` is a
   documented no-op once a handler already exists on the root logger —
   true inside pytest), captures at the ROOT logger (`caplog.at_level(
   logging.INFO)`, no `logger=` filter — sees every logger, not just
   `onrecord.ingest.prices`), and asserts the sentinel appears in ZERO
   captured records. **Confirmed failing for the right reason**: captured
   output shows `('httpx', 'HTTP Request: GET
   https://financialmodelingprep.com/.../historical-price-full/VST
   ?apikey=SUPERSECRET-sentinel-fmpkey-zzz9999 "HTTP/1.1 500 ..."')` — the
   exact leak the review's sentinel experiment found, reproduced
   independently here via `httpx.Client`'s own `logging.getLogger("httpx")`
   INFO-level request log, live-verified with a standalone probe script
   before writing the test.
2. **`test_fetch_eod_range_days_trims_to_trailing_calendar_window`**
   (`spec(T-014:AC-1)`, Important I1) — a synthetic 2-year, one-row-per-
   calendar-day CSV (`_build_synthetic_daily_csv`, 730 rows from
   2022-01-01) fed through a mocked stooq transport with `range_days=30`.
   **Trailing-window semantics pinned** (not given by the ticket): the
   window is `[<series' own latest date> - 29 days, <series' own latest
   date>]` inclusive, calendar days, anchored to the DATA's own latest
   date (never wall-clock "today" — the fixture's dates are unrelated to
   the test run date). Also asserts the cache persists the SAME
   (already-trimmed) series that's returned, not the untrimmed 2-year
   history. **Confirmed failing for the right reason**: earliest returned
   date is `2022-01-01` (the full untrimmed history) instead of the
   expected `2023-12-02` — directly reproduces I1's "dead parameter"
   finding.
3. **`test_fetch_eod_malicious_ticker_cache_write_never_escapes_or_nests_in_cache_dir`**
   (`spec(T-014:AC-4)`, latent-security, parametrized over `"../evil"` and
   `"A/B"`) — a fully successful mocked fetch (so `_write_cache` is
   actually reached, whether the fix rejects-early or sanitizes-and-
   proceeds) with a malicious `ticker`, `cache_dir` one level inside
   `tmp_path`. Asserts every file written as a side effect has
   `written_file.resolve().parent == cache_dir.resolve()` EXACTLY — not a
   level up (directory-traversal escape) and not a level down (an
   unsanitized `/` creating a nested subdirectory). One assertion catches
   both failure modes cleanly. **Confirmed failing for the right reason**:
   `"../evil"` writes `<tmp_path>/evil.json` (one level above `cache_dir` —
   a real escape); `"A/B"` writes `<cache_dir>/A/B.json` (an unsanitized
   nested subdirectory) — both exactly reproduce the review's
   traced-through-code analysis of `_cache_path`'s unsanitized
   `Path(cache_dir) / f"{ticker}.json"`.
4. **`test_significant_moves_zero_prior_close_is_skipped_with_a_log_line`**
   (`spec(T-014:AC-2)`, optional Minor M3, cheap) — a `prior_close == 0.0`
   day must still leave >=1 log record from `onrecord.ingest.prices`, not
   vanish silently. **Confirmed failing for the right reason**: the
   current implementation's `if prior_close == 0: continue` has no log
   call at all (0 records captured).

**Verified RED for the right reason**: `uv run pytest
tests/unit/ingest/test_prices.py -v` → **5 failed, 17 passed** (the
original 17 from the initial handoff all still pass against the current
implementation — confirming they're untouched/still valid — and exactly
the 4 new-finding tests + 1 optional Minor test fail, each inspected
individually above to confirm the failure reproduces the named review
finding rather than a test bug). Full repo: **5 failed, 200 passed** (200
= 183 pre-T-014 baseline + 17 original T-014 tests, all still green).
`.tdd-swarm/spec-lint.sh tickets/T-014.md` → `spec-lint OK: all ACs
covered for T-014`. `uv run ruff format --check .` / `uv run ruff check .`
(whole repo) both clean after `ruff format`/`ruff check --fix` on
`tests/`.

No fixture changes were needed for this round; only
`tests/unit/ingest/test_prices.py` changed (append-only past the original
17 tests + one new in-test synthetic-CSV helper + a docstring "AMENDMENT"
section pinning the trailing-window/leak-suppression/ticker-sanitization
contract extensions for the Implementation Agent, mirroring the
T-008/T-010 precedent for post-review contract amendments).

---

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

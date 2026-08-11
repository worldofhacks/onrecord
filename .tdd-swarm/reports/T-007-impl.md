# T-007 Implementation Agent Report — EDGAR filings adapter

**Status:** DONE — all 11 frozen tests pass, all local gates green (updated
after Review REJECTED the first pass — see "Review round 2" below).

**File touched (scope-compliant):** `onrecord/ingest/edgar.py` only. No test
or fixture files were edited.

## Approach

Two independently-testable layers, matching the frozen contract in
`tests/unit/ingest/test_edgar.py`'s module docstring:

**Parse layer** (`parse_filing_html`, `list_recent_filings` — pure, no I/O):

- `_SectionExtractor(html.parser.HTMLParser)` does tag-stripping,
  script/style skipping, and entity decoding (via `convert_charrefs=True`)
  in one linear pass over the document, using only the Python stdlib (no
  bs4/lxml available in this project's deps). It simultaneously records
  "Item heading" marker offsets into the flat output text.
- **Heading detection is structural, not a free-text regex scan**: a
  heading marker is only recorded for a `<p>` element whose *entire* text
  content sits inside `<b>`/`<strong>` (tracked via a bold-depth counter
  and a "saw non-bold text in this paragraph" flag) AND whose collapsed
  text matches `^item\s+(\d+)\s*([a-z]?)\.` at the very start. Mid-sentence
  mentions like "...discussed in Item 1A below..." live inside ordinary
  (non-bold-only) flowing prose, so they can never produce a marker —
  this is what survives the fixtures' adversarial traps
  (`test_parse_10k_ignores_item_heading_mentioned_mid_sentence`).
- For 10-K/10-Q, sections are sliced between consecutive marker offsets
  (each kept section runs from its own heading through to the start of
  the next heading, whatever that next heading is) and only
  `("1","a")->item1a` / `("7","")->item7` are kept — everything else
  (Item 1 Business, Item 8, ...) is discarded, never leaking across the
  kept sections' boundaries.
- For 8-K, the whole document becomes one `section="body"` Doc — 8-K's own
  internal Item 2.02/9.01 numbering is walked past like any other heading
  but the whole-document path never slices on it (no per-form branching
  bug where the 10-K splitter gets reused).
- For `EX-99*` (case-insensitive), the whole document becomes one Doc with
  `section=form.lower()` (e.g. `ex-99.1`). Any other `form` (EX-10.1, "4",
  "DEF 14A", ...) returns `[]`.
- `list_recent_filings` reads the `filings.recent` parallel arrays, filters
  by `forms`, and explicitly sorts by `filingDate` descending (not just
  filter-and-truncate in raw JSON order) — required by the fixture's
  deliberately unsorted `submissions.json`.

**Fetch layer** (`fetch_filings` — live-shaped, offline-testable):

- Builds an `httpx.Client` with the injected `transport` (MockTransport in
  tests, real defaults in production) and a `User-Agent` header sourced
  from `EDGAR_USER_AGENT`.
- `_get_with_retry` wraps every GET (company_tickers lookup, submissions
  fetch, each filing's primary document) with up to 3 attempts and
  exponential backoff via the injected `sleep` callable, treating both
  `httpx.TimeoutException` and any non-2xx status (404 included) as
  retryable failures; after exhausting attempts it returns `None` and the
  caller logs a `logging.warning(...)` naming the ticker/accession and
  continues — no exception ever escapes `fetch_filings`, and one broken
  filing/ticker never poisons a later call against the same transport.
- A small module-level `_pace()` helper enforces a shared ≤8 req/s cap
  (using the same injected `sleep`) across every real request in the
  process, so it costs nothing in tests (no-op `sleep=lambda _s: None`)
  but genuinely throttles the live CLI pull.

**CLI entrypoint** (DoD, not covered by frozen tests): `main()` /
`_parse_args()` give `python -m onrecord.ingest.edgar --tickers VST,CEG
--forms 10-K,10-Q,8-K --out DIR [--limit N]` — parses tickers/forms,
calls `fetch_filings` once per ticker (each call independently
skip-and-log safe), writes one `<TICKER>.jsonl` file per ticker
(`dataclasses.asdict(doc)` per line), and warns (does not fail) if
`EDGAR_USER_AGENT` is unset. Kept thin: all real logic lives in the
tested functions above.

## Verification

```
uv run pytest tests/unit/ingest/test_edgar.py -v   -> 9 passed
uv run pytest -q                                    -> 23 passed (9 T-007 + 14 T-001)
.tdd-swarm/run-local-gates.sh . tickets/T-007.md    -> ALL LOCAL GATES GREEN
  (format, lint, unit, spec-lint all green)
python -m onrecord.ingest.edgar --help              -> argparse entrypoint works
```

No live network calls were made anywhere (parse-layer tests are pure
fixture-driven; fetch-layer tests use `httpx.MockTransport` exclusively).

## Review round 2 (REJECTED -> fixed)

Review (`.tdd-swarm/reports/T-007-review.md`) rejected the first pass on
live-data evidence: **Critical** — real 10-Ks' hyperlinked Table-of-Contents
"Item 1A."/"Item 7." rows are structurally identical to a real heading
(own `<p>`, entirely bold), and first-occurrence-wins locked onto the ToC
stub, permanently discarding the real section (live-confirmed: DLR's
item1a/item7 came back as 26-98-char ToC stubs, HUT's item7 was silently
dropped). **Important** — a malformed `cik_str` (non-numeric, e.g. `"N/A"`)
reached an unguarded `int(cik)` and would raise out of `fetch_filings`,
with no per-ticker `try/except` in the CLI's `main()` loop to catch it,
so one corrupt ticker could kill a multi-ticker batch. The Test Agent
pinned both at commit `9c8c226` (2 new tests +
`tests/fixtures/edgar/10k_with_toc.html` + a `BADCIK` entry added to
`company_tickers.json`).

Fixes, `onrecord/ingest/edgar.py` only:

- **ToC-vs-real-heading discrimination**: `_SectionExtractor` now also
  records, per heading marker, whether that `<p>` was wrapped in an
  `<a href=...>` anchor (a real heading is preceded by a plain
  `<a id="...">` target *outside* the `<p>`, never wrapped by an
  `<a href>` itself — confirmed against the live DLR HTML the reviewer
  fetched). `_extract_item_sections` now rejects a candidate occurrence —
  in favor of a later occurrence of the same section key, if one exists —
  when EITHER it was href-wrapped OR its slice to the next heading
  occurrence is under `_MIN_SECTION_CHARS` (200; a ToC row is "heading +
  page number", not section prose). Both the fixture's ToC rows fail on
  both signals simultaneously (href-wrapped AND short); the real headings
  that follow satisfy neither rejection reason and are picked up.
- **`fetch_filings` exception isolation**: `_resolve_cik` now validates
  `cik_str` is int-convertible before returning it (a non-numeric CIK is
  treated the same as "ticker not found" — logged with the ticker name,
  `None` returned, caller's existing skip-and-log path handles it — no
  `int()` call downstream can ever see bad data). As defense-in-depth per
  the review's broader "must be exception-safe standing alone" framing,
  `fetch_filings` also now wraps the whole CIK/submissions resolution in a
  `try/except Exception` and each per-filing fetch+parse iteration in its
  own `try/except Exception`, logging and continuing/returning
  whatever Docs were already built rather than ever propagating — so the
  "one ticker's failure doesn't kill the batch" guarantee holds regardless
  of whether the CLI's `main()` ever grows its own per-ticker
  `try/except` (it currently doesn't).

Verification: `uv run pytest tests/unit/ingest/test_edgar.py -v` → 11
passed (9 original + 2 new: `test_parse_10k_prefers_real_heading_over_...`,
`test_fetch_filings_malformed_cik_does_not_raise_...`);
`uv run pytest -q` → 25 passed; `.tdd-swarm/run-local-gates.sh . tickets/T-007.md`
→ `ALL LOCAL GATES GREEN`.

## Notes / deferrals (explicit, per posture.md philosophy)

- `fetch_filings` fetches only each filing's **primary document** (per the
  frozen contract's docstring, which explicitly limits it to that) —
  exhibit fetching from a live filing's index page is not implemented,
  since real EDGAR submissions JSON doesn't list exhibit filenames and
  nothing in the frozen tests exercises it. AC-2's 8-K-body + EX-99
  composition is fully covered at the `parse_filing_html` level (the
  fetch layer would call it once per constituent document if/when exhibit
  discovery is added).
- Rate limiting (≤8 req/s) is implemented but, per the Test Agent's report,
  intentionally not independently unit-tested (timing assertions in a unit
  suite are flaky); it degrades to a no-op during tests via the injected
  `sleep`.

# T-007 Test Agent Report — EDGAR filings adapter

**Status:** DONE (frozen failing tests written, confirmed RED against the
current empty stub, confirmed GREEN against a throwaway correct
implementation built outside the worktree's tracked files, then reverted).

**Test file:** `tests/unit/ingest/test_edgar.py` (+ `tests/unit/ingest/__init__.py`)
**Fixtures:** `tests/fixtures/edgar/{10k.html, 8k.html, ex99_1.html, ex10_1.html, submissions.json, company_tickers.json, submissions_good.json}`

**Run command:**
```
uv run pytest tests/unit/ingest/test_edgar.py -v
```

## API contract fixed by this ticket's test agent (not otherwise pinned)

The ticket sketches `parse_filing_html(html, form, ticker, accession)`,
`list_recent_filings(submissions_json, forms, limit)`, and
`fetch_filings(ticker, forms, limit, transport=None)`. Two gaps needed a
concrete, documented decision (full rationale lives in the test file's
module docstring — treat it as part of the frozen contract):

1. **`parse_filing_html` gets a 5th argument, `filing_date: str`.**
   `onrecord.types.Doc.date` is a required frozen-dataclass field with no
   default, and a filing's date isn't reliably derivable from the primary
   document's own HTML body (that's SEC/EDGAR-system metadata, not
   filing-body content). The fetch layer already has it for free from
   `FilingRef.filing_date` (via `list_recent_filings`), so it's a
   trivial, well-justified pass-through.

2. **`form` is the SEC document TYPE for the *single* document `html`
   represents, not necessarily the filing's overall form.** For 10-K/10-Q
   it's `"10-K"`/`"10-Q"` (split into Item 1A + Item 7 Docs). For 8-K it's
   `"8-K"` for the primary body (one Doc, `section="body"`, **not**
   split on the 8-K's own internal Item 2.02/9.01 numbering) or
   `"EX-99.1"` etc. for an exhibit document (one Doc,
   `section=form.lower()`). Any other form (`"EX-10.1"`, `"4"`,
   `"DEF 14A"`, ...) returns `[]`. This is how AC-2's "8-K → body +
   exhibits" comes out of a function whose one `html` argument is a
   single document: the fetch layer calls it once per constituent
   document of the filing and concatenates results. Non-EX-99 exhibits
   are explicitly excluded (ticket: "exhibits EX-99 included when
   present") — covered by `test_parse_8k_non_ex99_exhibit_is_excluded`.

3. **`deep_link` uses `ticker` in the archives-path CIK slot**, e.g.
   `https://www.sec.gov/Archives/edgar/data/{ticker}/{accession_nodash}/{accession}-index.htm`.
   Real EDGAR archive paths key by numeric CIK, but `parse_filing_html`'s
   frozen signature only carries `ticker`. Documented as a deliberate,
   written simplification (in the spirit of `posture.md`'s "deferrals must
   be explicit, never silent") rather than a live-SEC-accurate URL.

4. **`fetch_filings` gets a `sleep` parameter** (`Callable[[float], None] | None`,
   defaulting to `time.sleep`) purely so retry/backoff tests run instantly
   instead of sleeping for real. Ticker→CIK resolution is pinned to
   `GET https://www.sec.gov/files/company_tickers.json` (the real static
   file the ticket names explicitly); submissions to
   `GET https://data.sec.gov/submissions/CIK{cik:0>10}.json` (the real SEC
   endpoint shape). Per-filing document fetch URL is only pinned by
   suffix (`.../<primaryDocument filename>`) — exact CIK zero-padding in
   that path is left as an implementation detail. `EDGAR_USER_AGENT` (not
   the ticket prose's `EDGAR_UA`) is the env var used for the politeness
   header, matching the already-committed `.env.example` /
   `.tdd-swarm/reports/T-001-*` precedent.

## Criterion → test mapping

| Criterion | Test(s) | What it checks |
|---|---|---|
| AC-1 | `test_parse_10k_extracts_item1a_and_item7_with_correct_ids_and_deep_links` | 10-K fixture (Items 1, 1A, 7, 8) → exactly `item1a` + `item7` Docs, correct `id`/`deep_link`/`source_type="filing"`/`venue_type="coached"`/`date`, correct content per section, no cross-bleed between sections |
| AC-1 (adversarial) | `test_parse_10k_ignores_item_heading_mentioned_mid_sentence` | Item 1's body contains "...discussed in Item 1A below..." mid-sentence (not a heading); Item 7's body contains "...presented in Item 8 of this report..." mid-sentence. Asserts the real Item 1A body marker is present (not short-circuited by the fake mention) and Item 7's tail marker (placed between the fake "Item 8" mention and the real Item 8 heading) survives — i.e. Item 7 isn't truncated early. Verified against a naive last-match-wins non-anchored regex: it actually loses the Item-7 tail marker, confirming the trap has teeth. |
| AC-4 | `test_parse_10k_strips_tags_scripts_and_decodes_entities` | Same 10-K fixture (nested `<table>`s, a `<script>` block placed *inside* the Item 1A section, `&amp;`/`&nbsp;` entities): no `<`/`>` in output, script payload never leaks, no literal `&amp;`/`&nbsp;` remains, `&amp;` decodes to a real `&`, nested-table cell text survives as plain text |
| AC-2 | `test_parse_8k_produces_body_and_exhibit_docs` | 8-K body fixture + separate EX-99.1 exhibit fixture, each parsed independently → one `body` Doc + one `ex-99.1` Doc, correct ids/links, no smearing between the two, tags/scripts/entities cleaned in the 8-K body too |
| AC-2 | `test_parse_8k_body_not_split_by_internal_item_headings` | 8-K's own Item 2.02 / Item 9.01 headings must NOT trigger a 10-K-style split — content from both survives in the single `body` Doc |
| AC-2 (scope) | `test_parse_8k_non_ex99_exhibit_is_excluded` | An EX-10.1 fixture (material-contract exhibit) parses to `[]` — only EX-99.* exhibits become Docs |
| AC-3 | `test_list_recent_filings_filters_sorts_newest_first_and_applies_limit` | Deliberately un-sorted submissions.json (11 entries, 7 matching 10-K/8-K spanning 2025-11-15..2026-08-01) → `forms={"10-K","8-K"}, limit=5` returns exactly the 5 newest matches, in strict newest-first order, by a hand-computed (not re-derived-in-test) expected accession list — catches an implementation that filters-and-truncates in raw JSON order instead of actually sorting |
| AC-5 | `test_fetch_filings_retries_then_skips_404_and_timeout_and_continues` | `fetch_filings("GOOD", ...)` against an `httpx.MockTransport`: one filing's doc 404s every attempt, another's times out (`httpx.TimeoutException`) every attempt, a third succeeds. Asserts: only the successful filing's 2 Docs come back, no exception escapes, each broken URL was hit ≥2 times (a retry genuinely happened, without pinning an exact backoff policy), a WARNING+ log record mentions the skipped filing, and a real non-empty `User-Agent` (sourced from `EDGAR_USER_AGENT`) was sent on every request |
| AC-5 | `test_fetch_filings_unknown_ticker_skips_without_raising_and_other_tickers_proceed` | Ticker absent from the `company_tickers.json` fixture → `fetch_filings("BAD", ...)` returns `[]`, logs a warning mentioning "BAD", raises nothing; a subsequent call for `"GOOD"` against the *same* transport instance still succeeds — proves failures don't poison later calls |

9 test items total (all currently RED with clean, per-test `Failed:` messages
— no collection errors, no uncaught tracebacks).

## Verification performed

1. Ran the suite against the current stub (`onrecord/ingest/edgar.py` is a
   docstring-only file) — all 9 tests fail cleanly via a
   `pytest.fail("onrecord.ingest.edgar.<name> is not defined yet")` helper
   (`_get_callable`), not a raw `AttributeError`/`ImportError`/collection
   error. `from onrecord.ingest import edgar` is a plain module import
   (always succeeds since the file exists), so a missing function is a
   normal per-test failure rather than blowing up the whole file's
   collection — same pattern T-001's report used for the analogous
   "module doesn't exist yet" problem.
2. Built a throwaway reference implementation
   (`onrecord/ingest/edgar.py` temporarily overwritten, then restored via
   `git status`-verified diff of zero) satisfying the contract above and
   confirmed **all 9 tests pass** against it — the tests are achievable,
   not vacuously red. The reference implementation was never committed;
   it lives only in this session's scratchpad
   (`/private/tmp/.../scratchpad/edgar_reference_impl.py`) for the record.
3. Additionally scripted a **naive, non-heading-anchored** regex
   implementation (matching `Item\s+\d+[A-Z]?\.?` anywhere in
   plain-extracted text, last-match-wins per section) against the 10-K
   fixture outside pytest: it correctly loses `ITEM7_TAIL_TOKEN_DELTA`
   (Item 7 gets truncated at the fake mid-sentence "Item 8" mention),
   confirming `test_parse_10k_ignores_item_heading_mentioned_mid_sentence`
   would fail a plausible buggy implementation, not just the empty stub.
4. `uv run ruff format --check tests/` and `uv run ruff check tests/` —
   both clean (ruff reformatted the test file's long lines once during
   authoring; reran the full suite after and it's still 9/9 green against
   the reference implementation).
5. `.tdd-swarm/spec-lint.sh tickets/T-007.md` → `spec-lint OK: all ACs
   covered for T-007`.
6. Full repo suite (`uv run pytest -q`) at hand-off: **9 failed, 14
   passed** (the 14 are T-001's untouched scaffold tests) — regression
   baseline for the wave is unaffected.

## Failure output (current worktree, RED)

```
collected 9 items

tests/unit/ingest/test_edgar.py::test_parse_10k_extracts_item1a_and_item7_with_correct_ids_and_deep_links FAILED
tests/unit/ingest/test_edgar.py::test_parse_10k_ignores_item_heading_mentioned_mid_sentence FAILED
tests/unit/ingest/test_edgar.py::test_parse_10k_strips_tags_scripts_and_decodes_entities FAILED
tests/unit/ingest/test_edgar.py::test_parse_8k_produces_body_and_exhibit_docs FAILED
tests/unit/ingest/test_edgar.py::test_parse_8k_body_not_split_by_internal_item_headings FAILED
tests/unit/ingest/test_edgar.py::test_parse_8k_non_ex99_exhibit_is_excluded FAILED
tests/unit/ingest/test_edgar.py::test_list_recent_filings_filters_sorts_newest_first_and_applies_limit FAILED
tests/unit/ingest/test_edgar.py::test_fetch_filings_retries_then_skips_404_and_timeout_and_continues FAILED
tests/unit/ingest/test_edgar.py::test_fetch_filings_unknown_ticker_skips_without_raising_and_other_tickers_proceed FAILED

E           Failed: onrecord.ingest.edgar.parse_filing_html is not defined yet
E           Failed: onrecord.ingest.edgar.list_recent_filings is not defined yet
E           Failed: onrecord.ingest.edgar.fetch_filings is not defined yet

9 failed in 0.16s
```

## Notes for the Implementation Agent

- Zero live network anywhere in this file — AC-1..AC-4 are pure
  fixture-driven parse-layer tests; AC-5 uses `httpx.MockTransport`
  exclusively via the injected `transport=` parameter.
- `fetch_filings` **must** accept `transport` and `sleep` keyword
  parameters exactly as documented in the test file's module docstring —
  the tests pass both explicitly.
- Don't try to make 10-K item-heading splitting reuse the same code path
  as 8-K/exhibit handling — they're genuinely different (Item-heading
  split vs. whole-document-is-one-Doc), and the 8-K fixture's own
  Item 2.02/9.01 headings exist specifically to catch an implementation
  that (wrongly) tries to reuse the 10-K splitter for everything.
- The DoD's CLI entrypoint (`python -m onrecord.ingest.edgar --tickers
  VST,CEG --forms 10-K,10-Q,8-K --out corpus/raw/edgar`) is **not**
  covered by these frozen tests (it's a DoD line, not one of AC-1..AC-5,
  and testing it meaningfully would mean either live network or a lot of
  extra CLI-arg-parsing mock scaffolding out of scope for this ticket's
  ACs) — still required for the ticket's Definition of Done, just
  verified by the reviewer/orchestrator rather than by this file.
- Rate limiting (≤8 req/s) is mentioned in the ticket but not
  independently tested here — timing-based assertions in a unit suite are
  flaky by nature; treat it as an implementation-quality expectation
  checked by code review, not a frozen test.
- Do not edit `tests/unit/ingest/test_edgar.py` or `tests/fixtures/edgar/**`
  to make an implementation pass — fix `onrecord/ingest/edgar.py` instead.
  If a genuine defect or ambiguity is found in the tests/fixtures,
  escalate to the orchestrator/Reviewer rather than editing directly.

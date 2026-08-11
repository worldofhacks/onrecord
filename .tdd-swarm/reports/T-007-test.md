# T-007 Test Agent Report — EDGAR filings adapter

**Status:** DONE (frozen failing tests written, confirmed RED against the
current empty stub, confirmed GREEN against a throwaway correct
implementation built outside the worktree's tracked files, then reverted).
**Update (post-review, round 1):** review REJECTED the implementation on
live-data evidence (`.tdd-swarm/reports/T-007-review.md`); suite extended
with 2 more adversarial tests per the reviewer's findings — see "Update:
review-driven extension" below.
**Update (post-review, round 2):** re-review confirmed the round-1 fix
(ToC stubs + per-ticker isolation) but found a DISTINCT, still-open defect
on the SAME live filings (CSS-inline-bold headings silently produce no
marker at all); suite extended again — see "Update 2: round-2
review-driven extension" below.

**Test file:** `tests/unit/ingest/test_edgar.py` (+ `tests/unit/ingest/__init__.py`)
**Fixtures:** `tests/fixtures/edgar/{10k.html, 10k_with_toc.html, 10k_css_bold.html, 8k.html, ex99_1.html, ex10_1.html, submissions.json, company_tickers.json, submissions_good.json}`

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
| AC-1 (adversarial, post-review r1) | `test_parse_10k_prefers_real_heading_over_table_of_contents_stub` | `10k_with_toc.html`: a realistic hyperlinked Table of Contents (`<p><a href="#...">...<b>Item 1A.</b>...</a></p>` rows — same shape confirmed on the live DLR 10-K) sits BEFORE the real headings (each preceded by a plain `<a id="...">` target). Asserts the real, paragraphs-long section content wins (real marker tokens present, `len(text) > 200`), not the ToC row's heading-plus-page-number stub. |
| AC-1 (adversarial, post-review r2) | `test_parse_10k_recognizes_css_bold_headings_without_tag_bold` | `10k_css_bold.html`: real Item 1A/Item 7 headings bolded purely via inline CSS (`style="font-weight:bold"` on the `<p>`, `font-weight:700` on a nested `<span>`, `font-weight:bolder`) with NO `<b>`/`<strong>` tag anywhere in the document (fixture self-asserts this). Asserts both sections still come back with substantive real content — same live shape confirmed on DLR's real Item 1A + Item 7 headings and HUT's real Item 7 heading. |
| AC-4 | `test_parse_10k_strips_tags_scripts_and_decodes_entities` | Same 10-K fixture (nested `<table>`s, a `<script>` block placed *inside* the Item 1A section, `&amp;`/`&nbsp;` entities): no `<`/`>` in output, script payload never leaks, no literal `&amp;`/`&nbsp;` remains, `&amp;` decodes to a real `&`, nested-table cell text survives as plain text |
| AC-2 | `test_parse_8k_produces_body_and_exhibit_docs` | 8-K body fixture + separate EX-99.1 exhibit fixture, each parsed independently → one `body` Doc + one `ex-99.1` Doc, correct ids/links, no smearing between the two, tags/scripts/entities cleaned in the 8-K body too |
| AC-2 | `test_parse_8k_body_not_split_by_internal_item_headings` | 8-K's own Item 2.02 / Item 9.01 headings must NOT trigger a 10-K-style split — content from both survives in the single `body` Doc |
| AC-2 (scope) | `test_parse_8k_non_ex99_exhibit_is_excluded` | An EX-10.1 fixture (material-contract exhibit) parses to `[]` — only EX-99.* exhibits become Docs |
| AC-3 | `test_list_recent_filings_filters_sorts_newest_first_and_applies_limit` | Deliberately un-sorted submissions.json (11 entries, 7 matching 10-K/8-K spanning 2025-11-15..2026-08-01) → `forms={"10-K","8-K"}, limit=5` returns exactly the 5 newest matches, in strict newest-first order, by a hand-computed (not re-derived-in-test) expected accession list — catches an implementation that filters-and-truncates in raw JSON order instead of actually sorting |
| AC-5 | `test_fetch_filings_retries_then_skips_404_and_timeout_and_continues` | `fetch_filings("GOOD", ...)` against an `httpx.MockTransport`: one filing's doc 404s every attempt, another's times out (`httpx.TimeoutException`) every attempt, a third succeeds. Asserts: only the successful filing's 2 Docs come back, no exception escapes, each broken URL was hit ≥2 times (a retry genuinely happened, without pinning an exact backoff policy), a WARNING+ log record mentions the skipped filing, and a real non-empty `User-Agent` (sourced from `EDGAR_USER_AGENT`) was sent on every request |
| AC-5 | `test_fetch_filings_unknown_ticker_skips_without_raising_and_other_tickers_proceed` | Ticker absent from the `company_tickers.json` fixture → `fetch_filings("BAD", ...)` returns `[]`, logs a warning mentioning "BAD", raises nothing; a subsequent call for `"GOOD"` against the *same* transport instance still succeeds — proves failures don't poison later calls |
| AC-5 (adversarial, post-review) | `test_fetch_filings_malformed_cik_does_not_raise_and_other_tickers_proceed` | `company_tickers.json`'s new `"BADCIK"` entry has `"cik_str": "N/A"` (malformed/corrupt data, distinct from an absent ticker). Asserts `fetch_filings("BADCIK", ...)` itself does not raise (pinned at the `fetch_filings` contract level, not by driving the CLI/`main()`, since `main()`'s per-ticker loop has no try/except of its own) and a subsequent `fetch_filings("GOOD", ...)` on the same transport still succeeds |

12 test items total: the original 9 + the 2 round-1 additions (11) all stay
green against the current (round-1-fixed) implementation; 1 new round-2
addition is RED for the exact root cause the round-2 reviewer confirmed on
the SAME live filings (see "Update 2: round-2 review-driven extension" below).

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

## Update: review-driven extension (post-implementation, post-review)

The orchestrator dispatched an Implementation Agent (commit `6d940d2`), which
passed all 9 original tests, local gates, and spec-lint — but Review
**REJECTED** on live-data evidence (`.tdd-swarm/reports/T-007-review.md`):
a Critical finding that real 10-Ks' hyperlinked Table of Contents rows get
mistaken for real Item headings (confirmed: `DLR.jsonl` item1a/item7 are
26-98-char ToC stubs; `HUT.jsonl`'s real 10-K has no `item7` Doc at all), and
an Important finding that `fetch_filings` can raise on malformed live data
(`int(cik)` uncaught on a non-numeric `cik_str`), which `main()`'s
try/except-less per-ticker loop would let kill an entire batch. Both gaps
existed because the frozen fixtures had no ToC and no malformed-CIK case to
exercise them.

Two tests were added (fixtures + tests only — `onrecord/ingest/edgar.py` was
never modified; every `git diff`/`git status` check below confirms zero diff
against the last commit at hand-off):

1. **`test_parse_10k_prefers_real_heading_over_table_of_contents_stub`**
   (AC-1) — new fixture `tests/fixtures/edgar/10k_with_toc.html`: a 4-row
   ToC (Item 1/1A/7/8) whose cells are `<p><a href="#...">...<b>Item
   1A.</b>...</a></p>` (hyperlinked, bold-only paragraphs — structurally
   identical to a real heading), placed before the real headings (each
   preceded by a bare `<a id="...">` anchor target, matching the exact
   shape the reviewer confirmed by fetching the live DLR 10-K HTML
   directly). The module docstring's frozen contract now pins the
   discriminating rule: a candidate heading occurrence must be rejected in
   favor of a later occurrence of the same section key when its
   slice-until-next-heading content is trivially short (≲200 chars, a ToC
   row is a heading + a page number) or sits inside an anchor/ToC-href
   context — implementers are free to choose either signal (or another)
   as long as the *observable* outcome (real section wins, by both content
   marker and length) matches what the test asserts.
2. **`test_fetch_filings_malformed_cik_does_not_raise_and_other_tickers_proceed`**
   (AC-5) — `tests/fixtures/edgar/company_tickers.json` gained a `"BADCIK"`
   entry with `"cik_str": "N/A"`. Asserts `fetch_filings("BADCIK", ...)`
   itself does not raise and a subsequent `fetch_filings("GOOD", ...)` call
   on the same transport still succeeds. Deliberately pinned at the
   `fetch_filings` level (not by driving the CLI/`main()`) so the "other
   tickers proceed" guarantee is `fetch_filings`'s own contract, not
   contingent on `main()` ever growing a try/except.

### Verification performed (this update)

1. Ran the extended suite against the actual committed (rejected)
   `onrecord/ingest/edgar.py` (commit `6d940d2`, no reference-implementation
   swap needed this time since the real code was already sitting there):
   **2 failed, 9 passed** — both new failures are the exact confirmed root
   causes, not incidental breakage:
   - `test_parse_10k_prefers_real_heading_over_table_of_contents_stub`:
     `item1a.text == 'Item\xa01A.\n\nRisk Factors18'` — the literal ToC-row
     stub, reproducing the reviewer's `DLR.jsonl` finding exactly.
   - `test_fetch_filings_malformed_cik_does_not_raise_and_other_tickers_proceed`:
     an uncaught `ValueError: invalid literal for int() with base 10: 'N/A'`
     raised from `_submissions_url` (`edgar.py:379`) escapes `fetch_filings`
     entirely — reproducing the reviewer's Important-1 finding exactly.
2. Built a throwaway two-line patch directly on the committed
   implementation (a) `_extract_item_sections`: collect all same-key
   candidate slices and keep the longest instead of first-wins, (b)
   `fetch_filings`: wrap the per-ticker body in `try/except Exception` ->
   log + return partial `docs` — confirmed **11/11 pass** against the
   patch, proving both new tests are achievable, not just failing-by-
   construction. Reverted via `git checkout -- onrecord/ingest/edgar.py`,
   confirmed zero diff against the commit, then re-ran and confirmed
   **2 failed, 9 passed** again (RED restored).
3. `uv run ruff format --check tests/` and `uv run ruff check tests/` —
   clean.
4. `.tdd-swarm/spec-lint.sh tickets/T-007.md` → `spec-lint OK: all ACs
   covered for T-007` (AC-1/AC-5 tags already existed from the original 9;
   the 2 new tests are additional tagged instances of the same ACs, not
   new AC numbers).
5. Full repo suite (`uv run pytest -q`) at hand-off: **25 collected, 2
   failed, 23 passed** (23 passed = 14 T-001 scaffold tests + the original
   9 T-007 tests, all still green; the 2 new T-007 tests are the only
   failures, both RED for the intended reasons above).

### Notes for the Implementation Agent (revision round)

- The ToC fix and the try/except fix are independent of each other and of
  every other passing test — no existing assertion needed to change to
  accommodate either fix path proven above (the two-line patch touched
  only `_extract_item_sections` and `fetch_filings`'s outer structure).
- "Longest slice wins" is one valid strategy for the ToC discriminating
  rule (proven above), not the only one — an anchor/`<a href>`-context
  check would also satisfy the frozen tests; pick whichever is simpler to
  maintain, the tests only check the observable outcome.
- The malformed-CIK fix should be structural (catch `Exception` broadly
  around `fetch_filings`'s per-ticker body, as the throwaway patch does),
  not a narrow `except ValueError` — the point of AC-5 is "no exception
  escapes," not "this one specific exception type is handled."

## Update 2: round-2 review-driven extension

Commit `b525c9b` fixed round 1's Critical-1 (ToC stubs) and Important-1
(CLI isolation) — round-2 re-review confirmed both fixed (11/11 T-007
tests pass, 25/25 full suite, all local gates green) by re-deriving the
exact same live DLR/HUT filings through the patched `parse_filing_html`.
But that same re-derivation surfaced a **distinct, still-open Critical-2**
on those same two filings: DLR's real Item 1A **and** Item 7 headings, and
HUT's real Item 7 heading, are all styled `<p style="...font-weight:bold;
...">ITEM 1A. RISK FACTORS</p>` — bold via **inline CSS on the `<p>`
itself**, with **no `<b>`/`<strong>` tag anywhere in the paragraph**.
`_SectionExtractor`'s bold tracking only increments on `<b>`/`<strong>`
start/end tags (never inspects `style`), so `_p_has_nonbold_text` becomes
`True` the instant any text is emitted and `_ITEM_HEADING_RE` is never
even attempted — the real heading produces **no marker at all**. This is a
different failure mode than Critical-1 (false-positive ToC marker): this
is a false-negative, the real heading is structurally invisible. Net
effect on the filings that motivated the original review: DLR went from
"misleading ToC-stub text" (round 1) to "nothing for either section" (still
wrong, just failing more safely); HUT's `item7` was and still is silently
absent.

One new test added (fixture + test only — `onrecord/ingest/edgar.py` was
never modified; verified via `git diff --stat`/`git status` at every step
below):

**`test_parse_10k_recognizes_css_bold_headings_without_tag_bold`** (AC-1) —
new fixture `tests/fixtures/edgar/10k_css_bold.html`: Items 1/1A/7/8, each
real heading CSS-bold only, covering the DLR-observed variants named by
the coordinator: `font-weight:bold` directly on the `<p>` (Items 1, 1A),
`font-weight:700` on a `<span>` nested inside the `<p>` (Item 7 — the
"possibly within a span" variant), and `font-weight:bolder` directly on
the `<p>` (Item 8, an extra variant for coverage). The fixture has no ToC
(that concern is already covered/fixed by the round-1 test) and the test
itself asserts `"<b>" not in html and "<strong>" not in html` as a fixture
sanity check, so a future accidental edit reintroducing tag-bold would be
caught immediately rather than silently invalidating the test's purpose.
Asserts both `item1a` and `item7` come back with substantive real content
(real marker tokens present, `len(text) > 200`), matching the coordinator's
"parse must return substantive Item 1A + Item 7 sections."

The module docstring's frozen contract gained a second PINNED paragraph
(after the round-1 ToC one) spelling out that "bold" for heading
recognition must include CSS `font-weight` (on the `<p>` or a nested
`<span>`) in addition to `<b>`/`<strong>` tags.

### Verification performed (this update)

1. Ran the extended suite against the actual committed (round-1-fixed,
   round-2-still-flawed) `onrecord/ingest/edgar.py` (commit `b525c9b`):
   **1 failed, 11 passed** — the one failure is the exact confirmed root
   cause, not incidental breakage: `by_section == set()` (no `item1a`/
   `item7` key at all — `_extract_item_sections` recorded zero markers for
   the CSS-bold headings), reproducing the reviewer's "DLR item1a/item7
   now 0 chars; HUT item7 same cause" finding exactly.
2. Built a throwaway patch directly on the committed implementation:
   added a `_style_is_bold(style)` helper (`font-weight` value is
   `bold`/`bolder`/numeric ≥ 600) and extended `_SectionExtractor` to (a)
   treat a `<p>` whose own `style` attribute is bold as bold context for
   its direct text, and (b) track a `<span style="font-weight:...">`
   nested inside a `<p>` the same way `<b>`/`<strong>` already are (via a
   small per-paragraph tag stack so nesting/unwinding stays correct) —
   confirmed **12/12 pass** against the patch, proving the new test is
   achievable, not failing-by-construction. Reverted via
   `git checkout -- onrecord/ingest/edgar.py`, confirmed zero diff against
   the commit (`git diff --stat` empty), then re-ran and confirmed
   **1 failed, 11 passed** again (RED restored).
3. `uv run ruff format --check tests/` and `uv run ruff check tests/` —
   clean.
4. `.tdd-swarm/spec-lint.sh tickets/T-007.md` → `spec-lint OK: all ACs
   covered for T-007`.
5. Full repo suite (`uv run pytest -q`) at hand-off: **26 collected, 1
   failed, 25 passed** (25 passed = 14 T-001 + all 11 prior T-007 tests,
   still green; the 1 new T-007 test is the only failure, RED for the
   intended reason above).

### Notes for the Implementation Agent (round-2 revision)

- This is orthogonal to the round-1 ToC fix — the throwaway patch above
  touched only bold-tracking inside `_SectionExtractor` (`__init__`,
  `handle_starttag`, `handle_endtag`, `handle_data`); the ToC
  href-anchor/min-length filter in `_extract_item_sections` did not need
  to change at all, and none of the 11 previously-passing tests needed
  their assertions touched.
- Don't special-case "`<p style=...>` directly" vs "`<span style=...>`
  nested inside `<p>`" as two different code paths if avoidable — both are
  just "is there bold styling in scope for this run of text," and the
  fixture exercises both plus a third CSS value (`bolder`) specifically so
  a narrow, single-shape fix (e.g. only checking the `<p>`'s own `style`
  and missing the nested-`<span>` case) would still fail this test.
- Real EDGAR filings are not internally consistent about how they bold a
  given heading (tag-bold vs. CSS-bold, sometimes within the same
  document) — a robust fix treats tag-bold and CSS-bold as two OR'd
  signals for the same underlying "is this bold" concept, not an
  either/or dispatch on document shape.

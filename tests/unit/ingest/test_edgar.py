"""Failing tests for T-007 — EDGAR filings adapter (fetch + parse layers).

Encodes tickets/T-007.md AC-1..AC-5. FROZEN after Test Agent handoff: do not
edit this file to make an implementation pass — fix `onrecord/ingest/edgar.py`
instead. Written adversarially: assumes nothing about an implementer's good
intentions (see the mid-sentence "Item 1A"/"Item 8" traps embedded in the
10-K fixture, and the non-sorted submissions fixture).

Run with:
    uv run pytest tests/unit/ingest/test_edgar.py -v

## Frozen API contract (not otherwise pinned by the ticket; fixed here)

`onrecord/ingest/edgar.py` must define:

    parse_filing_html(html: str, form: str, ticker: str, accession: str,
                       filing_date: str) -> list[Doc]

  Pure function. `form` is the SEC document TYPE for the *single* document
  represented by `html` (not necessarily the overall filing's form) --
  `"10-K"` / `"10-Q"` for a primary annual/quarterly report body,
  `"8-K"` for a current-report primary body, or `"EX-99.1"` (etc.) for an
  individual exhibit document. This lets the fetch layer call the same pure
  function once per constituent document of a filing (primary doc, each
  exhibit doc) and combine the results -- which is how AC-2's "8-K -> body +
  exhibits" is achieved from a function whose single `html` argument is one
  document's markup.

    - form in {"10-K", "10-Q"}: split on Item headings, return Docs for
      Item 1A (Risk Factors) and Item 7 (MD&A) ONLY -- section ids
      "item1a" and "item7". Headings must be recognized by their own
      heading/block context, not by any substring match of
      "Item <n>[<letter>]" appearing mid-sentence in flowing body prose
      (see the adversarial test below).

      PINNED (per review finding, live-data confirmed on real DLR/HUT
      10-Ks): a real filing's hyperlinked Table of Contents renders each
      Item row as `<p><a href="#...">...<b>Item 1A.</b>...</a></p>` --
      structurally a "<p> whose entire text sits inside <b>", i.e. the
      SAME shape a real heading has. A candidate heading occurrence must
      therefore be rejected (in favor of a later occurrence of the same
      section key, if one exists) when EITHER: (a) the text from that
      occurrence up to the next heading occurrence is trivially short
      (roughly < 200 chars -- a ToC row is a heading + a page number, not
      a section body), or (b) the occurrence sits inside an anchor/ToC
      context (e.g. wrapped in `<a href="...">`, as opposed to a real
      heading which is preceded by a plain `<a id="...">` target, not
      wrapped by an `<a href>`). Only the first occurrence surviving that
      filter counts -- "first-occurrence-wins" with no such filter
      incorrectly locks onto the ToC stub and permanently discards the
      real section (confirmed: DLR's item1a/item7 came back as 26-98-char
      ToC-row stubs; HUT's item7 was silently dropped entirely). See
      `test_parse_10k_prefers_real_heading_over_table_of_contents_stub`.

      PINNED (per round-2 review finding, live-data re-confirmed on the
      SAME DLR/HUT 10-Ks after the ToC fix above landed): "bold" for
      heading-recognition purposes is not only a `<b>`/`<strong>` TAG --
      real filings commonly bold an Item heading via inline CSS on the
      `<p>` itself (`style="...font-weight:bold;..."` or `font-weight:700`
      / `font-weight:bolder`) or on a `<span>` nested inside the `<p>`,
      with NO `<b>`/`<strong>` tag anywhere in that paragraph. A heading
      styled this way must be recognized exactly like a tag-bold one --
      confirmed live: DLR's real Item 1A AND Item 7 headings, and HUT's
      real Item 7 heading, are ALL styled this way with no `<b>`/`<strong>`
      present, and a bold-tracker that only watches `<b>`/`<strong>` never
      records a marker for them at all -- not a stub (Critical-1's
      failure mode), a silent, total absence with no warning and no Doc.
      See `test_parse_10k_recognizes_css_bold_headings_without_tag_bold`.
    - form == "8-K": the ENTIRE document becomes ONE Doc, section "body".
      8-K internal item numbering (2.02, 9.01, ...) uses a different scheme
      than 10-K/Q Items 1-15 and must NOT be split on.
    - form starts with "EX-99" (case-insensitive): the entire document
      becomes ONE Doc, section = `form.lower()` (e.g. "ex-99.1") -- matches
      the ticket's "exhibits EX-99 included when present".
    - any other form (e.g. "EX-10.1", "4", "DEF 14A"): returns `[]` -- no
      exception, no Doc (exhibits other than EX-99.* are out of corpus
      scope per the ticket).

  Every returned Doc:
    - id = f"edgar:{ticker}:{accession}:{section}"
    - source_type = "filing", venue_type = "coached"
    - ticker = the given ticker; jurisdiction = None; speaker = None
    - date = the given filing_date (verbatim)
    - deep_link = f"https://www.sec.gov/Archives/edgar/data/{ticker}/
      {accession.replace('-', '')}/{accession}-index.htm"
      NOTE: real EDGAR archive paths key by numeric CIK, not ticker. This
      function's frozen signature only carries `ticker` (not `cik`), so
      deep_link substitutes ticker into the CIK slot -- a documented,
      written simplification (matches this project's posture.md philosophy:
      deferrals must be explicit, never silent), not a live-SEC-accurate
      URL. Revisit if/when a `cik` is threaded through.
    - text has all HTML tags and <script> contents stripped, and all HTML
      entities (&amp;, &nbsp;, ...) decoded.

    list_recent_filings(submissions_json: dict, forms: set[str],
                         limit: int) -> list[FilingRef]

  Pure function over a parsed SEC `data.sec.gov/submissions/CIK##########
  .json`-shaped dict (top-level "cik" + "filings"."recent" parallel arrays:
  "accessionNumber", "filingDate", "form", "primaryDocument", ...). Returns
  up to `limit` filings whose form is in `forms`, across ALL matching forms
  combined (not per-form), sorted strictly newest-first by filingDate.
  Each returned FilingRef exposes (at least) `.accession`, `.form`,
  `.filing_date`, `.primary_document`, `.cik` attributes.

    fetch_filings(ticker: str, forms: set[str], limit: int,
                   transport: httpx.BaseTransport | None = None,
                   sleep: Callable[[float], None] | None = None,
                   ) -> list[Doc]

  Live-shaped but fully offline-testable via `transport` (an httpx
  MockTransport in tests; real httpx.Client() defaults in production) and
  `sleep` (injected as the retry-backoff delay function; tests pass a
  no-op so retry tests run instantly -- production defaults to
  `time.sleep`). Flow: resolve ticker -> CIK via
  `GET https://www.sec.gov/files/company_tickers.json` (SEC's real static
  ticker index, per the ticket's explicit mention), then
  `GET https://data.sec.gov/submissions/CIK{cik:0>10}.json`, then
  `list_recent_filings(...)`, then fetch each filing's primary document
  from an EDGAR archives URL under `https://www.sec.gov/Archives/edgar/
  data/...` ending in that filing's `primaryDocument` filename (exact CIK
  zero-padding/int format in that URL is an implementation detail these
  tests do not pin), parsed via `parse_filing_html`. Sends a `User-Agent`
  header sourced from the `EDGAR_USER_AGENT` env var (politeness, per
  ticket + `.env.example`).

  AC-5 (no exception escapes; retry w/ backoff then skip-and-log on
  404/timeout; other tickers proceed): a failure resolving the ticker's CIK
  (unknown ticker) OR fetching a specific filing's document (404 or
  httpx.TimeoutException) is retried at least once, then that ticker
  (or that one filing, if only its document fetch failed) is skipped with
  a `logging.warning(...)`-or-higher log record -- `fetch_filings` returns
  whatever Docs it *did* manage to build (possibly `[]`) and never raises.
  A subsequent `fetch_filings(...)` call for a different ticker against the
  same transport is unaffected.

  PINNED (per review finding, Important-1): this "never raises" guarantee
  is a property of `fetch_filings` ITSELF, not of its caller. The CLI's
  `main()` loops over tickers with no per-ticker try/except, so it relies
  entirely on `fetch_filings` catching everything internally -- including
  malformed *data*, not just transport-level failures. A ticker resolving
  to a non-numeric/malformed CIK (e.g. a corrupt `company_tickers.json`
  entry) must be caught, logged, and skipped from inside `fetch_filings`
  the same way a 404 is -- it must not surface as an uncaught
  ValueError/TypeError that kills the rest of a multi-ticker batch. See
  `test_fetch_filings_malformed_cik_does_not_raise_and_other_tickers_proceed`.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path

import httpx
import pytest

from onrecord.ingest import edgar
from onrecord.types import Doc

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "edgar"

TENK_ACCESSION = "0001234567-26-000099"
TENK_FILING_DATE = "2026-02-17"
EIGHTK_ACCESSION = "0001234567-26-000101"
EIGHTK_FILING_DATE = "2026-08-10"
TENK_TOC_ACCESSION = "0001234567-26-000199"
TENK_TOC_FILING_DATE = "2026-03-05"
TENK_CSS_BOLD_ACCESSION = "0001234567-26-000299"
TENK_CSS_BOLD_FILING_DATE = "2026-04-12"

SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL_GOOD = "https://data.sec.gov/submissions/CIK0007654321.json"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _get_callable(name: str):
    """Fetch `onrecord.ingest.edgar.<name>`, failing cleanly (not a raw
    AttributeError at an arbitrary call site) if the stub hasn't defined it
    yet. Once the function exists but raises NotImplementedError when
    called, that propagates as a normal (and correct, per the swarm's RED
    convention) test failure -- it is intentionally NOT caught here.
    """
    obj = getattr(edgar, name, None)
    if obj is None:
        pytest.fail(f"onrecord.ingest.edgar.{name} is not defined yet")
    return obj


def _read_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text()


def _load_json_fixture(name: str) -> dict:
    return json.loads(_read_fixture(name))


def _expected_deep_link(ticker: str, accession: str) -> str:
    accession_nodash = accession.replace("-", "")
    return (
        f"https://www.sec.gov/Archives/edgar/data/{ticker}/{accession_nodash}/{accession}-index.htm"
    )


def _assert_doc(doc: Doc, *, ticker: str, accession: str, section: str, filing_date: str) -> None:
    assert isinstance(doc, Doc)
    assert doc.id == f"edgar:{ticker}:{accession}:{section}"
    assert doc.source_type == "filing"
    assert doc.venue_type == "coached"
    assert doc.ticker == ticker
    assert doc.date == filing_date
    assert doc.deep_link == _expected_deep_link(ticker, accession)
    assert doc.jurisdiction is None
    assert doc.speaker is None
    assert isinstance(doc.text, str)
    assert doc.text.strip() != ""


def _docs_by_section(docs: list[Doc]) -> dict[str, Doc]:
    by_section: dict[str, Doc] = {}
    for d in docs:
        parts = d.id.split(":")
        assert len(parts) == 4 and parts[0] == "edgar", f"unexpected Doc.id shape: {d.id!r}"
        by_section[parts[3]] = d
    return by_section


def _make_good_transport():
    """MockTransport wired for ticker GOOD (CIK 0007654321, matches
    submissions_good.json): its 10-K's primary doc fetches fine (2 Docs);
    its 8-K's primary doc 404s on every attempt; its 10-Q's primary doc
    times out on every attempt. Ticker "BAD" is deliberately absent from
    the company_tickers.json fixture.

    Returns (transport, call_counts, user_agents_seen).
    """
    company_tickers = _load_json_fixture("company_tickers.json")
    submissions_good = _load_json_fixture("submissions_good.json")
    tenk_html = _read_fixture("10k.html")
    counts: dict[str, int] = defaultdict(int)
    user_agents: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        user_agents.append(request.headers.get("user-agent", ""))
        url = str(request.url)
        if url == SEC_COMPANY_TICKERS_URL:
            counts["company_tickers"] += 1
            return httpx.Response(200, json=company_tickers)
        if url == SEC_SUBMISSIONS_URL_GOOD:
            counts["submissions_good"] += 1
            return httpx.Response(200, json=submissions_good)
        if url.endswith("good10k.htm"):
            counts["good10k"] += 1
            return httpx.Response(200, text=tenk_html)
        if url.endswith("good8k_missing.htm"):
            counts["good8k_missing"] += 1
            return httpx.Response(404, text="not found")
        if url.endswith("good10q_timeout.htm"):
            counts["good10q_timeout"] += 1
            raise httpx.TimeoutException("simulated timeout", request=request)
        counts["unmapped"] += 1
        return httpx.Response(404, text=f"unmapped url in test transport: {url}")

    return httpx.MockTransport(handler), counts, user_agents


# --------------------------------------------------------------------------
# AC-1: 10-K -> Item 1A + Item 7 Docs, heading-bounded, correct ids/links
# --------------------------------------------------------------------------


def test_parse_10k_extracts_item1a_and_item7_with_correct_ids_and_deep_links():
    """spec(T-007:AC-1)"""
    parse_filing_html = _get_callable("parse_filing_html")
    html = _read_fixture("10k.html")

    docs = parse_filing_html(html, "10-K", "ACME", TENK_ACCESSION, TENK_FILING_DATE)

    by_section = _docs_by_section(docs)
    assert set(by_section) == {"item1a", "item7"}

    item1a, item7 = by_section["item1a"], by_section["item7"]
    _assert_doc(
        item1a,
        ticker="ACME",
        accession=TENK_ACCESSION,
        section="item1a",
        filing_date=TENK_FILING_DATE,
    )
    _assert_doc(
        item7,
        ticker="ACME",
        accession=TENK_ACCESSION,
        section="item7",
        filing_date=TENK_FILING_DATE,
    )

    # heading-bounded: each section's own content is present...
    assert "ITEM1A_BODY_TOKEN_BETA" in item1a.text
    assert "ITEM7_BODY_TOKEN_GAMMA" in item7.text
    # ...and there is no cross-bleed from neighboring/unkept sections
    assert "ITEM1_PREAMBLE_TOKEN_ALPHA" not in item1a.text
    assert "ITEM7_BODY_TOKEN_GAMMA" not in item1a.text
    assert "ITEM8_BODY_TOKEN_EPSILON" not in item1a.text
    assert "ITEM1A_BODY_TOKEN_BETA" not in item7.text
    assert "ITEM8_BODY_TOKEN_EPSILON" not in item7.text
    assert "ITEM1_PREAMBLE_TOKEN_ALPHA" not in item7.text


def test_parse_10k_ignores_item_heading_mentioned_mid_sentence():
    """spec(T-007:AC-1)

    Adversarial per T-007: the fixture's Item 1 body contains the
    mid-sentence phrase "...discussed in Item 1A below..." (flowing prose,
    not its own heading/block element), and Item 7's body contains a
    mid-sentence "...presented in Item 8 of this report...". A naive,
    non-anchored regex scan for "Item <n>[<letter>]" anywhere in the text
    would mis-place the Item 1A boundary or truncate Item 7 early. The real
    headings are the ones set off in their own bold heading paragraphs.
    """
    parse_filing_html = _get_callable("parse_filing_html")
    html = _read_fixture("10k.html")

    docs = parse_filing_html(html, "10-K", "ACME", TENK_ACCESSION, TENK_FILING_DATE)
    by_section = _docs_by_section(docs)

    # Item 1A's real body content must be present: if a naive scanner
    # anchored on the mid-sentence "Item 1A" mention (which precedes the
    # real heading) instead of the true heading, the section it built would
    # start too early and MISS this marker (which sits after the real
    # heading, inside the real Item 1A body).
    assert "ITEM1A_BODY_TOKEN_BETA" in by_section["item1a"].text

    # Item 7 must not be truncated at the mid-sentence "Item 8" mention --
    # the tail marker sits between that mention and the real "Item 8."
    # heading, and must survive in the returned text.
    assert "ITEM7_TAIL_TOKEN_DELTA" in by_section["item7"].text


def test_parse_10k_prefers_real_heading_over_table_of_contents_stub():
    """spec(T-007:AC-1)

    Adversarial per review (live-data finding on real DLR/HUT 10-Ks): a
    real EDGAR 10-K opens with a hyperlinked Table of Contents whose
    "Item 1A."/"Item 7." rows are, structurally, indistinguishable from a
    true heading under a naive "own <p>, entirely bold" rule -- each ToC
    row is `<p><a href="#...">...<b>Item 1A.</b>...</a></p>`, i.e. a <p>
    whose entire text sits inside <b>, same shape as a real heading. A
    first-occurrence-wins implementation locks onto the ToC row and
    returns a heading-plus-page-number stub instead of the real,
    paragraphs-long section that appears later in the document (or drops
    the section entirely if the "next heading" after the stub slices to
    nothing).

    tests/fixtures/edgar/10k_with_toc.html reproduces this shape: a 4-row
    ToC (Item 1/1A/7/8) with hyperlinked, bold-only heading cells, placed
    BEFORE the real headings (each preceded by a plain `<a id="...">`
    anchor target, NOT wrapped in an `<a href="...">`, matching the live
    DLR HTML the reviewer fetched directly). Every gap between consecutive
    ToC rows is a couple of words plus a page number -- nowhere near the
    hundreds of characters of real prose that follow each real heading.
    """
    parse_filing_html = _get_callable("parse_filing_html")
    html = _read_fixture("10k_with_toc.html")

    docs = parse_filing_html(html, "10-K", "ACME", TENK_TOC_ACCESSION, TENK_TOC_FILING_DATE)
    by_section = _docs_by_section(docs)
    assert set(by_section) == {"item1a", "item7"}

    item1a, item7 = by_section["item1a"], by_section["item7"]
    _assert_doc(
        item1a,
        ticker="ACME",
        accession=TENK_TOC_ACCESSION,
        section="item1a",
        filing_date=TENK_TOC_FILING_DATE,
    )
    _assert_doc(
        item7,
        ticker="ACME",
        accession=TENK_TOC_ACCESSION,
        section="item7",
        filing_date=TENK_TOC_FILING_DATE,
    )

    # the REAL section body must win, not the ToC row's heading+page stub
    assert "TOC_FIXTURE_ITEM1A_REAL_BODY_TOKEN" in item1a.text
    assert "TOC_FIXTURE_ITEM7_REAL_BODY_TOKEN" in item7.text

    # a ToC stub is a couple of words + a page number; the real section is
    # paragraphs long -- this is the same length signal the reviewer used
    # to diagnose the live DLR/HUT bug (26-98 char stubs vs. 100K+ char
    # real sections)
    assert len(item1a.text) > 200
    assert len(item7.text) > 200

    # no cross-bleed into neighboring/unkept sections
    assert "TOC_FIXTURE_ITEM1_PREAMBLE_TOKEN" not in item1a.text
    assert "TOC_FIXTURE_ITEM7_REAL_BODY_TOKEN" not in item1a.text
    assert "TOC_FIXTURE_ITEM8_BODY_TOKEN" not in item7.text
    assert "TOC_FIXTURE_ITEM1A_REAL_BODY_TOKEN" not in item7.text


def test_parse_10k_recognizes_css_bold_headings_without_tag_bold():
    """spec(T-007:AC-1)

    Adversarial per round-2 review (live-data finding on real DLR/HUT
    10-Ks, re-verified AFTER the ToC fix above already landed): a real
    10-K commonly bolds an Item heading via inline CSS -- on the `<p>`
    itself (`style="...font-weight:bold;..."`, `font-weight:bolder`) or on
    a `<span>` nested inside the `<p>` (`font-weight:700`) -- with NO
    `<b>`/`<strong>` tag anywhere in that paragraph. Confirmed live: DLR's
    real Item 1A AND Item 7 headings, and HUT's real Item 7 heading, are
    ALL styled exactly this way. A bold-tracker that only watches
    `<b>`/`<strong>` tags never records a marker for these at all -- the
    section isn't a short stub (that was Critical-1, already fixed), it is
    silently, totally absent: no Doc, no warning.

    tests/fixtures/edgar/10k_css_bold.html has NO Table of Contents (that
    concern is already covered elsewhere) and, by construction, NO
    `<b>`/`<strong>` tag anywhere in the document -- every Item heading
    (1, 1A, 7, 8) is CSS-bold only, covering the DLR-observed style
    variants: font-weight:bold directly on <p>, font-weight:700 on a
    nested <span>, and font-weight:bolder directly on <p>.
    """
    parse_filing_html = _get_callable("parse_filing_html")
    html = _read_fixture("10k_css_bold.html")
    # fixture sanity: this really does exercise "bold with no tag-bold"
    assert "<b>" not in html
    assert "<strong>" not in html

    docs = parse_filing_html(
        html, "10-K", "ACME", TENK_CSS_BOLD_ACCESSION, TENK_CSS_BOLD_FILING_DATE
    )
    by_section = _docs_by_section(docs)
    assert set(by_section) == {"item1a", "item7"}

    item1a, item7 = by_section["item1a"], by_section["item7"]
    _assert_doc(
        item1a,
        ticker="ACME",
        accession=TENK_CSS_BOLD_ACCESSION,
        section="item1a",
        filing_date=TENK_CSS_BOLD_FILING_DATE,
    )
    _assert_doc(
        item7,
        ticker="ACME",
        accession=TENK_CSS_BOLD_ACCESSION,
        section="item7",
        filing_date=TENK_CSS_BOLD_FILING_DATE,
    )

    # substantive real content, not merely "some non-empty text"
    assert "CSS_FIXTURE_ITEM1A_REAL_BODY_TOKEN" in item1a.text
    assert "CSS_FIXTURE_ITEM7_REAL_BODY_TOKEN" in item7.text
    assert len(item1a.text) > 200
    assert len(item7.text) > 200

    # no cross-bleed into neighboring/unkept sections
    assert "CSS_FIXTURE_ITEM1_PREAMBLE_TOKEN" not in item1a.text
    assert "CSS_FIXTURE_ITEM7_REAL_BODY_TOKEN" not in item1a.text
    assert "CSS_FIXTURE_ITEM8_BODY_TOKEN" not in item7.text
    assert "CSS_FIXTURE_ITEM1A_REAL_BODY_TOKEN" not in item7.text


# --------------------------------------------------------------------------
# AC-4: tag/script stripping + entity decoding (shares the AC-1 fixture,
# which is deliberately messy: nested tables, &amp;/&nbsp; entities, <script>)
# --------------------------------------------------------------------------


def test_parse_10k_strips_tags_scripts_and_decodes_entities():
    """spec(T-007:AC-4)"""
    parse_filing_html = _get_callable("parse_filing_html")
    html = _read_fixture("10k.html")

    docs = parse_filing_html(html, "10-K", "ACME", TENK_ACCESSION, TENK_FILING_DATE)
    by_section = _docs_by_section(docs)
    item1a, item7 = by_section["item1a"], by_section["item7"]

    for doc in (item1a, item7):
        assert "<" not in doc.text
        assert ">" not in doc.text
        assert "DO_NOT_LEAK_SCRIPT_XYZ123" not in doc.text
        assert "&amp;" not in doc.text
        assert "&nbsp;" not in doc.text

    # entities decoded to their real characters, not just deleted
    assert "Risk & Uncertainty Factors" in item1a.text

    # nested <table> content is preserved as text, not dropped or leaked as tags
    assert "Nested detail" in item1a.text
    assert "Elevated" in item1a.text
    assert "Data center interconnection" in item7.text
    assert "$1,240M" in item7.text


# --------------------------------------------------------------------------
# AC-2: 8-K body + EX-99.1 exhibit each become a Doc
# --------------------------------------------------------------------------


def test_parse_8k_produces_body_and_exhibit_docs():
    """spec(T-007:AC-2)"""
    parse_filing_html = _get_callable("parse_filing_html")
    body_html = _read_fixture("8k.html")
    exhibit_html = _read_fixture("ex99_1.html")

    body_docs = parse_filing_html(body_html, "8-K", "ACME", EIGHTK_ACCESSION, EIGHTK_FILING_DATE)
    exhibit_docs = parse_filing_html(
        exhibit_html, "EX-99.1", "ACME", EIGHTK_ACCESSION, EIGHTK_FILING_DATE
    )

    assert len(body_docs) == 1
    assert len(exhibit_docs) == 1

    body, exhibit = body_docs[0], exhibit_docs[0]
    _assert_doc(
        body,
        ticker="ACME",
        accession=EIGHTK_ACCESSION,
        section="body",
        filing_date=EIGHTK_FILING_DATE,
    )
    _assert_doc(
        exhibit,
        ticker="ACME",
        accession=EIGHTK_ACCESSION,
        section="ex-99.1",
        filing_date=EIGHTK_FILING_DATE,
    )

    assert "8K_BODY_TOKEN_ZETA" in body.text
    assert "EX99_BODY_TOKEN_ETA" in exhibit.text
    # the two documents stay distinct -- no smearing across doc boundaries
    assert "EX99_BODY_TOKEN_ETA" not in body.text
    assert "8K_BODY_TOKEN_ZETA" not in exhibit.text
    # tag/script/entity cleanup applies here too
    assert "<" not in body.text
    assert "DO_NOT_LEAK_SCRIPT_8K_TOKEN" not in body.text
    assert "Revenue & Other Income" in body.text


def test_parse_8k_body_not_split_by_internal_item_headings():
    """spec(T-007:AC-2)

    Unlike 10-K/Q, 8-K item numbering (2.02, 9.01, ...) is a different
    scheme than Items 1/1A/7/8 -- the whole primary document is a single
    Doc, so content from both Item 2.02 and Item 9.01 must survive together.
    """
    parse_filing_html = _get_callable("parse_filing_html")
    body_html = _read_fixture("8k.html")

    docs = parse_filing_html(body_html, "8-K", "ACME", EIGHTK_ACCESSION, EIGHTK_FILING_DATE)
    assert len(docs) == 1
    text = docs[0].text
    assert "8K_BODY_TOKEN_ZETA" in text
    assert "8K_EXHIBIT_ITEM_TOKEN_THETA" in text


def test_parse_8k_non_ex99_exhibit_is_excluded():
    """spec(T-007:AC-2)

    Ticket: "exhibits EX-99 included when present" -- other exhibit types
    (e.g. an EX-10.1 material contract) are part of the filing but out of
    scope for the search corpus; parse_filing_html must not turn them into
    Docs.
    """
    parse_filing_html = _get_callable("parse_filing_html")
    exhibit_html = _read_fixture("ex10_1.html")

    docs = parse_filing_html(exhibit_html, "EX-10.1", "ACME", EIGHTK_ACCESSION, EIGHTK_FILING_DATE)
    assert docs == []


# --------------------------------------------------------------------------
# AC-3: list_recent_filings -- forms filter, newest-first, limit
# --------------------------------------------------------------------------


def test_list_recent_filings_filters_sorts_newest_first_and_applies_limit():
    """spec(T-007:AC-3)

    Adversarial per T-007: the fixture's parallel arrays are deliberately
    NOT in date order, so an implementation that just filters-and-truncates
    in raw JSON array order (instead of actually sorting by filingDate)
    fails this test.
    """
    list_recent_filings = _get_callable("list_recent_filings")
    data = _load_json_fixture("submissions.json")

    refs = list_recent_filings(data, forms={"10-K", "8-K"}, limit=5)

    assert len(refs) == 5
    assert all(r.form in {"10-K", "8-K"} for r in refs)

    # hand-computed from tests/fixtures/edgar/submissions.json (7 matching
    # 10-K/8-K entries span 2025-11-15 .. 2026-08-01; top 5 newest, combined
    # across both forms, dropping the 2 oldest matches)
    expected_accessions = [
        "0001234567-26-000025",  # 2026-08-01 8-K
        "0001234567-26-000021",  # 2026-07-20 8-K
        "0001234567-26-000018",  # 2026-06-25 8-K
        "0001234567-26-000012",  # 2026-05-10 8-K
        "0001234567-26-000005",  # 2026-03-01 10-K
    ]
    assert [r.accession for r in refs] == expected_accessions

    dates = [r.filing_date for r in refs]
    assert dates == sorted(dates, reverse=True)
    assert len(set(dates)) == len(dates)  # all distinct here -> strict order is provable


# --------------------------------------------------------------------------
# AC-5: fetch_filings -- retry w/ backoff, skip-and-log on 404/timeout,
# no exception escapes, other tickers proceed
# --------------------------------------------------------------------------


def test_fetch_filings_retries_then_skips_404_and_timeout_and_continues(caplog, monkeypatch):
    """spec(T-007:AC-5)"""
    monkeypatch.setenv("EDGAR_USER_AGENT", "OnRecord Test test@example.com")
    caplog.set_level(logging.WARNING)
    fetch_filings = _get_callable("fetch_filings")
    transport, counts, user_agents = _make_good_transport()

    docs = fetch_filings(
        "GOOD",
        forms={"10-K", "10-Q", "8-K"},
        limit=10,
        transport=transport,
        sleep=lambda _seconds: None,
    )

    # only the filing whose document fetch actually succeeded yields Docs;
    # no exception escaped despite the 404 and the timeout below
    assert len(docs) == 2
    by_section = _docs_by_section(docs)
    assert set(by_section) == {"item1a", "item7"}
    for doc in docs:
        assert doc.ticker == "GOOD"
        assert "0007654321-26-000001" in doc.id

    # the two broken filings were retried (more than one attempt) before
    # being given up on -- retry w/ backoff, not "fail on first try"
    assert counts["good8k_missing"] >= 2
    assert counts["good10q_timeout"] >= 2
    assert counts["unmapped"] == 0

    # skip was logged, not silent
    assert any(
        "0007654321-26-000002" in r.message or "0007654321-26-000003" in r.message
        for r in caplog.records
    )

    # politeness: a real, non-empty contact User-Agent was sent
    assert all(ua for ua in user_agents)
    assert any("test@example.com" in ua for ua in user_agents)


def test_fetch_filings_unknown_ticker_skips_without_raising_and_other_tickers_proceed(caplog):
    """spec(T-007:AC-5)"""
    caplog.set_level(logging.WARNING)
    fetch_filings = _get_callable("fetch_filings")
    transport, _counts, _uas = _make_good_transport()

    bad_docs = fetch_filings(
        "BAD", forms={"10-K"}, limit=5, transport=transport, sleep=lambda _s: None
    )
    assert bad_docs == []
    assert any("BAD" in r.message for r in caplog.records)

    # same transport/session: a different, resolvable ticker still proceeds
    good_docs = fetch_filings(
        "GOOD", forms={"10-K"}, limit=5, transport=transport, sleep=lambda _s: None
    )
    assert len(good_docs) == 2


def test_fetch_filings_malformed_cik_does_not_raise_and_other_tickers_proceed(caplog):
    """spec(T-007:AC-5)

    Adversarial per review (Important-1): a ticker whose
    company_tickers.json entry has a non-numeric cik_str ("N/A" --
    malformed/corrupt SEC data, distinct from simply being absent from the
    mapping) must not raise INSIDE fetch_filings itself. The CLI's
    per-ticker batch loop (`main()`) has no try/except of its own, so the
    "one raising ticker doesn't kill the batch" guarantee has to be a
    property of fetch_filings's own contract, not of luck / of main()
    happening to wrap it. This is deliberately pinned at the fetch_filings
    level (not by driving the CLI/main() directly) so the guarantee holds
    regardless of whether main() ever grows a try/except of its own --
    fetch_filings must be exception-safe standing alone.

    tests/fixtures/edgar/company_tickers.json includes a "BADCIK" entry
    with `"cik_str": "N/A"` for exactly this purpose.
    """
    caplog.set_level(logging.WARNING)
    fetch_filings = _get_callable("fetch_filings")
    transport, _counts, _uas = _make_good_transport()

    # must not raise -- this is the whole point of the regression test
    badcik_docs = fetch_filings(
        "BADCIK", forms={"10-K"}, limit=5, transport=transport, sleep=lambda _s: None
    )
    assert badcik_docs == []
    assert any("BADCIK" in r.message for r in caplog.records)

    # same transport/session: a well-formed ticker still proceeds
    good_docs = fetch_filings(
        "GOOD", forms={"10-K"}, limit=5, transport=transport, sleep=lambda _s: None
    )
    assert len(good_docs) == 2

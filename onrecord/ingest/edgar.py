"""EDGAR filings adapter (T-007): fetch layer (ticker -> CIK -> submissions ->
filing documents) + parse layer (filing HTML -> section Docs).

Two independent layers, per tickets/T-007.md:

- Parse layer (`parse_filing_html`, `list_recent_filings`): pure functions,
  no I/O, fully unit-tested against fixtures.
- Fetch layer (`fetch_filings`): live-shaped but fully offline-testable via
  an injectable `httpx` transport and an injectable `sleep` (retry-backoff
  delay function). Politeness: `EDGAR_USER_AGENT` header, retry w/ backoff,
  skip-and-log on failure (never raises), <=8 req/s pacing.

See `tests/unit/ingest/test_edgar.py`'s module docstring for the frozen API
contract this module implements.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path

import httpx

from onrecord.types import Doc

logger = logging.getLogger(__name__)

COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

# Sections kept from a 10-K/10-Q's Item-heading split: (item number, item
# letter) -> section id. Everything else (Item 1 Business, Item 8 Financial
# Statements, ...) is parsed only far enough to find section boundaries and
# then discarded -- out of corpus scope per the ticket.
_KEEP_ITEM_SECTIONS: dict[tuple[str, str], str] = {
    ("1", "a"): "item1a",
    ("7", ""): "item7",
}

# Matches an Item heading's own text ("Item 1A. Risk Factors", "Item 7.
# Management's Discussion..."). Only ever tested against text pulled from a
# <p> element that is ENTIRELY bold (see `_SectionExtractor`) -- never
# against arbitrary flowing text -- so a mid-sentence "...discussed in
# Item 1A below..." can never match this (it isn't the start of its own
# bold-only paragraph).
_ITEM_HEADING_RE = re.compile(r"^item\s+(\d+)\s*([a-z]?)\.", re.IGNORECASE)

# Real filings commonly bold an Item heading via inline CSS (on the <p>
# itself, or on a nested <span>) instead of a <b>/<strong> tag -- confirmed
# live on real DLR/HUT 10-Ks (T-007 review, Critical-2). `bold`/`bolder`
# keywords and numeric weights >=600 (matches CSS's bold=700 vs.
# normal=400, with headroom for semi-bold-ish 600 values) both count.
_FONT_WEIGHT_RE = re.compile(r"font-weight\s*:\s*([a-z0-9]+)", re.IGNORECASE)


def _style_is_bold(style: str | None) -> bool:
    if not style:
        return False
    match = _FONT_WEIGHT_RE.search(style)
    if not match:
        return False
    value = match.group(1).lower()
    if value in ("bold", "bolder"):
        return True
    try:
        return int(value) >= 600
    except ValueError:
        return False


# A real filing's hyperlinked Table of Contents renders each Item row in the
# SAME shape as a real heading (own <p>, entirely bold) -- live-confirmed on
# real DLR/HUT 10-Ks (T-007 review, Critical-1). A candidate heading is
# rejected as a likely ToC-row stub (in favor of a later occurrence of the
# same section key) when its slice to the next heading occurrence is
# trivially short: a ToC row is "heading + page number", not a section body.
_MIN_SECTION_CHARS = 200

_SKIP_TAGS = frozenset({"script", "style"})
_BLOCK_BREAK_TAGS = frozenset({"p", "tr", "table", "hr", "div"})

_RETRY_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_BASE_SECONDS = 0.5
_RATE_LIMIT_PER_SECOND = 8.0

# Shared across calls in this process so the CLI's multi-ticker live pull
# honors <=8 req/s overall, not just per-ticker.
_last_request_monotonic: float | None = None


# --------------------------------------------------------------------------
# Parse layer
# --------------------------------------------------------------------------


class _SectionExtractor(HTMLParser):
    """Strips tags/scripts, decodes entities, and records Item-heading
    boundary offsets into the resulting flat text -- all in one linear pass.

    A heading is recognized purely by block/heading structure: a <p>
    element whose ENTIRE text content is bold (no other text in that
    paragraph) and whose collapsed text matches ``Item <n>[<letter>].`` at
    the very start. That is what lets this survive the fixtures'
    mid-sentence "Item 1A"/"Item 8" traps -- those mentions live inside
    ordinary flowing-prose paragraphs, never inside their own bold-only
    paragraph, so they never produce a marker.

    "Bold" covers both a <b>/<strong> tag AND inline CSS
    (`style="...font-weight:bold..."`, on the <p> itself or on any element
    nested inside it, e.g. a wrapping <span>) -- real filings commonly use
    the latter with no <b>/<strong> tag anywhere (live-confirmed on real
    DLR/HUT 10-Ks, T-007 review Critical-2). A per-paragraph stack of
    "was this open tag itself bold" flags (`_p_bold_stack`) tracks bold
    context through arbitrary nested inline elements, on top of a base
    bold state seeded from the <p> tag's own style when it opens.

    A real filing's hyperlinked Table of Contents renders each Item row in
    that SAME shape though (`<p><a href="#..."><b>Item 1A.</b></a></p>`), so
    each marker also records whether it was wrapped in an `<a href=...>`
    anchor -- a real heading is preceded by a plain `<a id="...">` target
    (outside the <p>, not wrapping it), never wrapped in an `<a href>`
    itself. `_extract_item_sections` uses this plus the trivially-short-slice
    signal to prefer a later, real occurrence over a ToC-row stub.

    Heading text is still emitted into the flat text (so whole-document
    callers like the 8-K/exhibit path get it back), but a marker's offset
    points to the START of the heading's own text -- so a kept section's
    slice runs from its own heading (inclusive) up to the start of the next
    heading (exclusive).
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        # (offset, item number, item letter, was-wrapped-in-<a href>)
        self.markers: list[tuple[int, str, str, bool]] = []
        self._length = 0
        self._skip_depth = 0
        self._in_p_depth = 0
        self._bold_depth = 0
        self._p_buffer: list[str] = []
        self._p_has_nonbold_text = False
        self._p_saw_href_anchor = False
        self._p_bold_stack: list[bool] = []

    def _emit(self, text: str) -> None:
        if not text:
            return
        self.chunks.append(text)
        self._length += len(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        attrs_map = dict(attrs)
        if tag == "p":
            self._in_p_depth += 1
            self._p_buffer = []
            self._p_has_nonbold_text = False
            self._p_saw_href_anchor = False
            self._p_bold_stack = []
            # A p-level inline-CSS bold applies to the whole paragraph from
            # the start, same as opening inside a <b> right away.
            self._bold_depth = 1 if _style_is_bold(attrs_map.get("style")) else 0
            return
        if not self._in_p_depth:
            return
        is_bold_tag = tag in ("b", "strong") or _style_is_bold(attrs_map.get("style"))
        self._p_bold_stack.append(is_bold_tag)
        if is_bold_tag:
            self._bold_depth += 1
        if tag == "a" and attrs_map.get("href") is not None:
            self._p_saw_href_anchor = True

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag == "p" and self._in_p_depth:
            self._in_p_depth -= 1
            text = "".join(self._p_buffer)
            self._p_buffer = []
            normalized = " ".join(text.split())
            match = None if self._p_has_nonbold_text else _ITEM_HEADING_RE.match(normalized)
            if match:
                self.markers.append(
                    (self._length, match.group(1), match.group(2).lower(), self._p_saw_href_anchor)
                )
            self._emit(text)
            self._emit("\n")
            return
        if self._in_p_depth and self._p_bold_stack:
            # Closing an inline element opened inside the current paragraph
            # (<b>/<strong>/a bold-styled <span>/an anchor/etc.) -- pop its
            # bold flag to keep `_bold_depth` balanced through nesting.
            if self._p_bold_stack.pop():
                self._bold_depth = max(0, self._bold_depth - 1)
            return
        if tag in _BLOCK_BREAK_TAGS:
            self._emit("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_p_depth:
            self._p_buffer.append(data)
            if self._bold_depth == 0 and data.strip():
                self._p_has_nonbold_text = True
        else:
            self._emit(data)

    @property
    def full_text(self) -> str:
        return "".join(self.chunks)


def _clean_text(text: str) -> str:
    """Collapse runs of blank lines left by block-tag separators."""
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _extract(html: str) -> _SectionExtractor:
    extractor = _SectionExtractor()
    extractor.feed(html)
    extractor.close()
    return extractor


def _extract_full_text(html: str) -> str:
    return _clean_text(_extract(html).full_text)


def _extract_item_sections(html: str) -> dict[str, str]:
    """10-K/10-Q only: split on Item headings, keep Item 1A + Item 7.

    First-occurrence-wins per section id, EXCEPT a candidate occurrence is
    rejected (in favor of a later occurrence of the same key, if any) when
    it looks like a Table-of-Contents row rather than a real heading: either
    it was wrapped in an `<a href=...>` anchor, or its slice to the next
    heading occurrence is too short to be real prose. See
    `_SectionExtractor`'s docstring and the T-007 review's Critical-1
    finding (live-confirmed on real DLR/HUT 10-Ks).
    """
    extractor = _extract(html)
    full_text = extractor.full_text
    markers = extractor.markers
    sections: dict[str, str] = {}
    for idx, (offset, number, letter, in_href_anchor) in enumerate(markers):
        section_id = _KEEP_ITEM_SECTIONS.get((number, letter))
        if section_id is None or section_id in sections:
            continue
        end = markers[idx + 1][0] if idx + 1 < len(markers) else len(full_text)
        text = _clean_text(full_text[offset:end])
        if in_href_anchor or len(text) < _MIN_SECTION_CHARS:
            continue  # looks like a ToC-row stub -- keep looking for the real heading
        if text:
            sections[section_id] = text
    return sections


def _build_deep_link(ticker: str, accession: str) -> str:
    accession_nodash = accession.replace("-", "")
    return (
        f"https://www.sec.gov/Archives/edgar/data/{ticker}/{accession_nodash}/{accession}-index.htm"
    )


def _make_doc(*, text: str, ticker: str, accession: str, filing_date: str, section: str) -> Doc:
    return Doc(
        id=f"edgar:{ticker}:{accession}:{section}",
        text=text,
        source_type="filing",
        venue_type="coached",
        date=filing_date,
        deep_link=_build_deep_link(ticker, accession),
        ticker=ticker,
        jurisdiction=None,
        speaker=None,
    )


def parse_filing_html(
    html: str, form: str, ticker: str, accession: str, filing_date: str
) -> list[Doc]:
    """Pure function: single-document HTML (`html`, of SEC document type
    `form`) -> section Docs. See module docstring / test file for the full
    contract of what `form` may be and what each case produces.
    """
    form_upper = form.upper()

    if form_upper in ("10-K", "10-Q"):
        sections = _extract_item_sections(html)
        docs = []
        for section_id in ("item1a", "item7"):
            text = sections.get(section_id)
            if text:
                docs.append(
                    _make_doc(
                        text=text,
                        ticker=ticker,
                        accession=accession,
                        filing_date=filing_date,
                        section=section_id,
                    )
                )
        return docs

    if form_upper == "8-K":
        text = _extract_full_text(html)
        if not text:
            return []
        return [
            _make_doc(
                text=text,
                ticker=ticker,
                accession=accession,
                filing_date=filing_date,
                section="body",
            )
        ]

    if form_upper.startswith("EX-99"):
        text = _extract_full_text(html)
        if not text:
            return []
        return [
            _make_doc(
                text=text,
                ticker=ticker,
                accession=accession,
                filing_date=filing_date,
                section=form.lower(),
            )
        ]

    # Any other document type (other exhibits, Form 4, DEF 14A, ...) is out
    # of corpus scope per the ticket -- explicitly, not silently: no Doc.
    return []


@dataclass(frozen=True)
class FilingRef:
    """One entry from a submissions JSON's `filings.recent` parallel arrays."""

    cik: str
    accession: str
    form: str
    filing_date: str
    primary_document: str


def list_recent_filings(submissions_json: dict, forms: set[str], limit: int) -> list[FilingRef]:
    """Pure function over a parsed `data.sec.gov/submissions/CIK....json`
    dict. Returns up to `limit` filings whose form is in `forms`, across all
    matching forms combined, sorted strictly newest-first by filingDate.
    """
    cik = str(submissions_json.get("cik", ""))
    recent = submissions_json.get("filings", {}).get("recent", {})
    accessions = recent.get("accessionNumber", [])
    filing_dates = recent.get("filingDate", [])
    forms_list = recent.get("form", [])
    primary_docs = recent.get("primaryDocument", [])

    refs: list[FilingRef] = []
    for i, accession in enumerate(accessions):
        form = forms_list[i] if i < len(forms_list) else ""
        if form not in forms:
            continue
        refs.append(
            FilingRef(
                cik=cik,
                accession=accession,
                form=form,
                filing_date=filing_dates[i] if i < len(filing_dates) else "",
                primary_document=primary_docs[i] if i < len(primary_docs) else "",
            )
        )

    refs.sort(key=lambda r: r.filing_date, reverse=True)
    return refs[:limit]


# --------------------------------------------------------------------------
# Fetch layer -- live-shaped, offline-testable via `transport` / `sleep`
# --------------------------------------------------------------------------


def _pace(sleep_fn: Callable[[float], None]) -> None:
    """Best-effort <=8 req/s pacing shared across calls in this process."""
    global _last_request_monotonic
    min_interval = 1.0 / _RATE_LIMIT_PER_SECOND
    now = time.monotonic()
    if _last_request_monotonic is not None:
        remaining = min_interval - (now - _last_request_monotonic)
        if remaining > 0:
            sleep_fn(remaining)
    _last_request_monotonic = time.monotonic()


def _get_with_retry(
    client: httpx.Client, url: str, sleep_fn: Callable[[float], None]
) -> httpx.Response | None:
    """GET `url`, retrying with backoff on timeout or non-2xx status. Never
    raises -- returns None (having logged nothing itself; caller logs with
    context) once attempts are exhausted.
    """
    last_error = "unknown error"
    for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
        _pace(sleep_fn)
        try:
            response = client.get(url)
        except httpx.TimeoutException as exc:
            last_error = f"timeout ({exc})"
        except httpx.HTTPError as exc:
            last_error = f"transport error ({exc})"
        else:
            if response.status_code < 400:
                return response
            last_error = f"HTTP {response.status_code}"
        if attempt < _RETRY_MAX_ATTEMPTS:
            sleep_fn(_RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
    logger.warning(
        "edgar: giving up on %s after %d attempts (%s)", url, _RETRY_MAX_ATTEMPTS, last_error
    )
    return None


def _resolve_cik(
    client: httpx.Client, ticker: str, sleep_fn: Callable[[float], None]
) -> str | None:
    """Ticker -> CIK, or None if unresolvable (unknown ticker, unfetchable
    index, OR a malformed/non-numeric `cik_str` in the source data -- SEC's
    static index is fetched, not authored by us, so a corrupt entry is
    treated as data to log and skip, not trusted blindly. Per T-007 review
    Important-1: this validation is what keeps a malformed CIK from ever
    reaching `int(cik)` downstream and raising out of `fetch_filings`.
    """
    response = _get_with_retry(client, COMPANY_TICKERS_URL, sleep_fn)
    if response is None:
        return None
    try:
        data = response.json()
    except ValueError:
        return None
    ticker_upper = ticker.upper()
    for entry in data.values():
        if str(entry.get("ticker", "")).upper() != ticker_upper:
            continue
        cik_str = entry.get("cik_str")
        try:
            return str(int(cik_str))
        except (TypeError, ValueError):
            logger.warning(
                "edgar: ticker %s has a malformed cik_str in company_tickers.json (%r); skipping",
                ticker,
                cik_str,
            )
            return None
    return None


def _submissions_url(cik: str) -> str:
    return f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"


def _fetch_submissions(
    client: httpx.Client, cik: str, sleep_fn: Callable[[float], None]
) -> dict | None:
    response = _get_with_retry(client, _submissions_url(cik), sleep_fn)
    if response is None:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def _primary_document_url(cik: str, ref: FilingRef) -> str:
    accession_nodash = ref.accession.replace("-", "")
    return (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
        f"{accession_nodash}/{ref.primary_document}"
    )


def fetch_filings(
    ticker: str,
    forms: set[str],
    limit: int,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] | None = None,
) -> list[Doc]:
    """Live-shaped fetch: ticker -> CIK -> submissions -> recent filings'
    primary documents -> Docs (via `parse_filing_html`). Never raises: any
    failure (unresolvable/malformed ticker data, unfetchable
    submissions/document, or any other unexpected internal error) is
    retried with backoff where applicable, then skipped with a
    `logging.warning` -- processing continues with whatever else can still
    be built, and the caller (the CLI's per-ticker batch loop has no
    try/except of its own -- see T-007 review Important-1) can rely on this
    function alone to keep one bad ticker from killing the rest of a batch.
    """
    sleep_fn = sleep if sleep is not None else time.sleep
    user_agent = os.environ.get("EDGAR_USER_AGENT", "").strip()
    headers = {"User-Agent": user_agent} if user_agent else {}

    client_kwargs: dict = {"headers": headers, "timeout": 10.0}
    if transport is not None:
        client_kwargs["transport"] = transport

    docs: list[Doc] = []
    try:
        with httpx.Client(**client_kwargs) as client:
            cik = _resolve_cik(client, ticker, sleep_fn)
            if cik is None:
                logger.warning("edgar: could not resolve ticker %s to a CIK; skipping", ticker)
                return []

            submissions = _fetch_submissions(client, cik, sleep_fn)
            if submissions is None:
                logger.warning(
                    "edgar: could not fetch submissions for ticker %s (cik %s); skipping",
                    ticker,
                    cik,
                )
                return []

            for ref in list_recent_filings(submissions, forms, limit):
                try:
                    url = _primary_document_url(cik, ref)
                    response = _get_with_retry(client, url, sleep_fn)
                    if response is None:
                        logger.warning(
                            "edgar: failed to fetch primary document for ticker %s accession %s "
                            "(%s); skipping",
                            ticker,
                            ref.accession,
                            ref.primary_document,
                        )
                        continue
                    docs.extend(
                        parse_filing_html(
                            response.text, ref.form, ticker, ref.accession, ref.filing_date
                        )
                    )
                except Exception:
                    logger.warning(
                        "edgar: unexpected error processing ticker %s accession %s; skipping "
                        "that filing",
                        ticker,
                        ref.accession,
                        exc_info=True,
                    )
                    continue
    except Exception:
        # Belt-and-braces, per T-007 review Important-1: fetch_filings must
        # never raise -- an unforeseen internal error resolving/using this
        # one ticker's data must not kill the rest of a multi-ticker batch.
        # Whatever Docs were already built for this ticker are still
        # returned rather than discarded.
        logger.warning(
            "edgar: unexpected error fetching filings for ticker %s; skipping",
            ticker,
            exc_info=True,
        )
        return docs

    return docs


# --------------------------------------------------------------------------
# CLI entrypoint (ticket DoD) -- thin wrapper over fetch_filings
# --------------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m onrecord.ingest.edgar",
        description="Fetch SEC EDGAR filings and write per-ticker section Docs as JSONL.",
    )
    parser.add_argument("--tickers", required=True, help="Comma-separated tickers, e.g. VST,CEG")
    parser.add_argument(
        "--forms", default="10-K,10-Q,8-K", help="Comma-separated SEC forms to include"
    )
    parser.add_argument("--out", required=True, help="Output directory for per-ticker .jsonl files")
    parser.add_argument(
        "--limit", type=int, default=20, help="Max filings per ticker considered (default: 20)"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _parse_args(argv)

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    forms = {f.strip().upper() for f in args.forms.split(",") if f.strip()}
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not os.environ.get("EDGAR_USER_AGENT", "").strip():
        logger.warning(
            "EDGAR_USER_AGENT is not set -- SEC fair-access policy requires a descriptive "
            "contact User-Agent (see .env.example); requests will proceed without one."
        )

    total_docs = 0
    for ticker in tickers:
        docs = fetch_filings(ticker, forms=forms, limit=args.limit)
        out_path = out_dir / f"{ticker}.jsonl"
        with out_path.open("w", encoding="utf-8") as fh:
            for doc in docs:
                fh.write(json.dumps(asdict(doc), ensure_ascii=False) + "\n")
        logger.info("edgar: %s -> %d docs (%s)", ticker, len(docs), out_path)
        total_docs += len(docs)

    logger.info("edgar: done -- %d total docs across %d ticker(s)", total_docs, len(tickers))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Filings delta ingest — T-052 (the living-platform filings lane).

Polls per-CIK EDGAR Atom feeds (keyless, same fair-access etiquette as
T-038) for filings newer than the corpus snapshot, then feeds NEW 8-K /
10-K / 10-Q accessions through the existing T-007 section extractor into a
delta JSONL for the next corpus build. Form 4 is deliberately excluded
here — T-038's `pull_form4` is already resumable and deduped by accession.
Pure parts pinned by tests/unit/ingest/test_filings_delta.py.
"""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

ATOM_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"
    "&type=&dateb=&owner=include&count=40&output=atom"
)
SEC_HEADERS = {"User-Agent": "OnRecord research alexander.miller@challenger.gauntletai.com"}
REQUEST_GAP_S = 0.15
DEFAULT_FORMS: tuple[str, ...] = ("8-K", "10-K", "10-Q")
DEFAULT_OUT = Path("artifacts/filings_delta.jsonl")

_ATOM_NS = "{http://www.w3.org/2005/Atom}"


def parse_edgar_atom(xml_text: str) -> list[dict]:
    """Atom feed -> filing rows. DTD/entity declarations rejected outright
    (T-038's XXE posture); malformed XML -> []."""
    head = xml_text[:4096]
    if "<!DOCTYPE" in head or "<!ENTITY" in head:
        logger.debug("edgar atom: DTD/entity declaration rejected")
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        logger.debug("edgar atom: unparseable XML")
        return []

    rows: list[dict] = []
    for entry in root.iter(f"{_ATOM_NS}entry"):
        content = entry.find(f"{_ATOM_NS}content")
        if content is None:
            continue

        def _field(name: str) -> str:
            # Children inherit the feed's default Atom namespace; accept
            # both spellings so a namespace-less test fixture and the real
            # feed parse identically.
            node = content.find(f"{_ATOM_NS}{name}")
            if node is None:
                node = content.find(name)
            return (node.text or "").strip() if node is not None else ""

        accession = _field("accession-number")
        if not accession:
            continue
        rows.append(
            {
                "accession": accession,
                "form": _field("filing-type"),
                "filing_date": _field("filing-date"),
                "filing_href": _field("filing-href"),
            }
        )
    return rows


def corpus_accessions(doc_ids: list[str]) -> set[str]:
    """Accessions already in the corpus, from `edgar:<accession>:<section>`
    ids; everything else ignored."""
    out: set[str] = set()
    for doc_id in doc_ids:
        parts = doc_id.split(":")
        if len(parts) >= 3 and parts[0] == "edgar" and parts[1]:
            out.add(parts[1])
    return out


def new_filings(
    entries: list[dict],
    known_accessions: set[str],
    since: str,
    forms: tuple[str, ...] = DEFAULT_FORMS,
) -> list[dict]:
    """Wanted-form entries newer than `since` and not already known,
    deduped by accession (first wins), filing_date ascending."""
    seen: set[str] = set()
    out: list[dict] = []
    for entry in entries:
        accession = entry.get("accession", "")
        if (
            not accession
            or accession in known_accessions
            or accession in seen
            or entry.get("form") not in forms
            or str(entry.get("filing_date", "")) < since
        ):
            continue
        seen.add(accession)
        out.append(entry)
    out.sort(key=lambda e: str(e.get("filing_date", "")))
    return out


# --------------------------------------------------------------------------
# Operational poller (live network; `make refresh-filings`)
# --------------------------------------------------------------------------


def poll_feeds(ciks_by_ticker: dict[str, str]) -> list[dict]:
    """Fetch every ticker's Atom feed; returns entries tagged with ticker."""
    entries: list[dict] = []
    with httpx.Client() as client:
        for ticker, cik in sorted(ciks_by_ticker.items()):
            time.sleep(REQUEST_GAP_S)
            try:
                response = client.get(
                    ATOM_URL.format(cik=cik), headers=SEC_HEADERS, timeout=30.0
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                logger.debug("atom feed %s: %s", ticker, type(exc).__name__)
                continue
            for row in parse_edgar_atom(response.text):
                row["ticker"] = ticker
                entries.append(row)
    return entries

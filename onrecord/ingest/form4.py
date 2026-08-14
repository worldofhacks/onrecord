"""Form 4 (insider transaction) ingestion — T-038.

Parses SEC ownershipDocument XML into flat transaction rows and resolves
registry tickers to zero-padded CIK strings via SEC's company_tickers.json
shape. The network pull (submissions API -> Form 4 XMLs) lives in
`pull_form4` below: keyless, SEC-etiquette user agent, <=8 req/s, resumable
by accession. Output artifact: `artifacts/form4/insider_transactions.jsonl`
(one row per non-derivative transaction; derivative table deliberately out
of scope in v1 — options/RSU mechanics need their own modeling to avoid
overstating "selling").

Contract pinned by tests/unit/ingest/test_form4.py: `parse_form4_xml` and
`cik_for_ticker` are pure (no I/O), malformed input yields `[]`/`None`,
never a raise.
"""

from __future__ import annotations

import json
import logging
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

SEC_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/{doc}"
# SEC fair-access etiquette: identify yourself, stay well under 10 req/s.
SEC_HEADERS = {"User-Agent": "OnRecord research alexander.miller@challenger.gauntletai.com"}
REQUEST_GAP_S = 0.15

DEFAULT_OUT = Path("artifacts/form4/insider_transactions.jsonl")


def _text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    value = node.findtext("value")
    if value is not None:
        return value.strip()
    return (node.text or "").strip()


def _num(node: ET.Element | None) -> float:
    raw = _text(node)
    if not raw:
        return 0.0
    try:
        return float(raw)
    except ValueError:
        return 0.0


def parse_form4_xml(
    xml_text: str, ticker: str, accession: str, filing_url: str
) -> list[dict]:
    """One ownershipDocument -> one row per nonDerivativeTransaction.
    Malformed XML or no transactions -> [] (never raises)."""
    # XXE/billion-laughs guard: reject any document carrying a DTD or
    # entity declaration outright. Genuine SEC ownershipDocuments never
    # have one, so this costs nothing and forecloses the stdlib parser's
    # entity-expansion attack surface without a defusedxml dependency.
    head = xml_text[:4096]
    if "<!DOCTYPE" in head or "<!ENTITY" in head:
        logger.debug("form4 %s: DTD/entity declaration rejected", accession)
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        logger.debug("form4 %s: unparseable XML, skipping", accession)
        return []

    cik = (root.findtext("issuer/issuerCik") or "").strip()
    owner = root.find("reportingOwner")
    filer_name = ""
    filer_title = ""
    is_officer = False
    is_director = False
    if owner is not None:
        filer_name = (owner.findtext("reportingOwnerId/rptOwnerName") or "").strip()
        rel = owner.find("reportingOwnerRelationship")
        if rel is not None:
            is_officer = (rel.findtext("isOfficer") or "").strip() in ("1", "true")
            is_director = (rel.findtext("isDirector") or "").strip() in ("1", "true")
            filer_title = (rel.findtext("officerTitle") or "").strip()

    rows: list[dict] = []
    for txn in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        shares = _num(txn.find("transactionAmounts/transactionShares"))
        price = _num(txn.find("transactionAmounts/transactionPricePerShare"))
        rows.append(
            {
                "ticker": ticker,
                "cik": cik,
                "filer_name": filer_name,
                "filer_title": filer_title,
                "is_officer": is_officer,
                "is_director": is_director,
                "transaction_date": _text(txn.find("transactionDate")),
                "code": (txn.findtext("transactionCoding/transactionCode") or "").strip(),
                "shares": shares,
                "price_per_share": price,
                "value": round(shares * price, 2),
                "shares_owned_after": _num(
                    txn.find("postTransactionAmounts/sharesOwnedFollowingTransaction")
                ),
                "filing_url": filing_url,
                "accession": accession,
            }
        )
    return rows


def cik_for_ticker(ticker: str, mapping: dict) -> str | None:
    """SEC company_tickers.json shape -> zero-padded 10-digit CIK string.
    Case-insensitive; dotted tickers map to SEC's dashed form."""
    wanted = ticker.upper().replace(".", "-")
    for entry in mapping.values():
        if str(entry.get("ticker", "")).upper() == wanted:
            return str(entry["cik_str"]).zfill(10)
    return None


# --------------------------------------------------------------------------
# Network pull (operational; exercised live, not by the frozen unit tests)
# --------------------------------------------------------------------------


def _get(client: httpx.Client, url: str):
    time.sleep(REQUEST_GAP_S)
    response = client.get(url, headers=SEC_HEADERS, timeout=30.0)
    response.raise_for_status()
    return response


def pull_form4(
    tickers: list[str],
    out_path: str | Path = DEFAULT_OUT,
    since: str = "2024-01-01",
    max_filings_per_ticker: int = 40,
) -> dict:
    """Pull Form 4 filings for `tickers` into `out_path` (JSONL, appended,
    deduped by accession across runs). Returns per-ticker counts."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    seen_accessions: set[str] = set()
    if out_path.exists():
        for line in out_path.open():
            try:
                seen_accessions.add(json.loads(line)["accession"])
            except (ValueError, KeyError):
                continue

    counts: dict[str, dict] = {}
    with httpx.Client() as client:
        ticker_map = _get(client, SEC_TICKER_MAP_URL).json()
        for ticker in tickers:
            cik = cik_for_ticker(ticker, ticker_map)
            if cik is None:
                counts[ticker] = {"error": "no CIK"}
                continue
            try:
                subs = _get(client, SEC_SUBMISSIONS_URL.format(cik=cik)).json()
            except httpx.HTTPError as exc:
                counts[ticker] = {"error": f"submissions fetch failed: {type(exc).__name__}"}
                continue

            recent = subs.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            accessions = recent.get("accessionNumber", [])
            dates = recent.get("filingDate", [])
            docs = recent.get("primaryDocument", [])
            pulled = rows_written = 0
            for form, accession, fdate, doc in zip(forms, accessions, dates, docs, strict=False):
                if form != "4" or fdate < since or accession in seen_accessions:
                    continue
                if pulled >= max_filings_per_ticker:
                    break
                url = SEC_ARCHIVE_URL.format(
                    cik_int=int(cik), accession_nodash=accession.replace("-", ""), doc=doc
                )
                try:
                    xml_text = _get(client, url).text
                except httpx.HTTPError:
                    logger.debug("form4 %s %s: fetch failed, skipping", ticker, accession)
                    continue
                rows = parse_form4_xml(xml_text, ticker, accession, url)
                with out_path.open("a", encoding="utf-8") as fh:
                    for row in rows:
                        fh.write(json.dumps(row) + "\n")
                seen_accessions.add(accession)
                pulled += 1
                rows_written += len(rows)
            counts[ticker] = {"filings": pulled, "rows": rows_written}
            print(f"{ticker}: {pulled} filings, {rows_written} rows", flush=True)
    return counts

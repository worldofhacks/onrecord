"""EDGAR full-text discovery — T-062 (efts.sec.gov, keyless).

DISCOVERY lane only: query terms ("data center", "hyperscale", registry
company names) x forms (8-K/10-K/10-Q/S-1) against SEC full-text search,
date-windowed; parse hits; dedupe against corpus accessions (REUSING
`corpus_accessions` from T-052's filings_delta — imported, not
reimplemented); emit an owner-reviewable candidate list for the corpus-v3
ingest decision. Nothing here auto-enters the corpus (AC-4) — the caller
writes candidates to artifacts/edgar_fts_candidates.json and a human
decides. Same SEC fair-access etiquette as T-038/T-052 (UA header,
request gaps >= 200ms, Retry-After honored). Pure parsing pinned by a
real-response fixture in tests/unit/ingest/test_edgar_fts.py.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterable, Sequence

import httpx

from onrecord.ingest.filings_delta import corpus_accessions

__all__ = ["parse_fts_hits", "novel_candidates", "corpus_accessions", "discover"]

logger = logging.getLogger(__name__)

FTS_URL = "https://efts.sec.gov/LATEST/search-index"
SEC_HEADERS = {"User-Agent": "OnRecord research alexander.miller@challenger.gauntletai.com"}
REQUEST_GAP_S = 0.2  # <= 5 req/s, well under the SEC's 10 req/s ceiling
MAX_HITS_PER_QUERY = 300
MAX_RETRIES = 3
DEFAULT_FORMS: tuple[str, ...] = ("8-K", "10-K", "10-Q", "S-1")

# "NVIDIA CORP  (NVDA)  (CIK 0001045810)" -> "NVDA"; the ticker group is
# the parenthesized list immediately before the trailing "(CIK ...)".
# Entries without one ("DEEP FISSION, INC.  (CIK 0001918102)") have no
# exchange ticker and contribute nothing.
_TICKERS_RE = re.compile(r"\(([^()]+)\)\s*\(CIK\s+\d+\)\s*$")


def _require(mapping: dict, key: str, where: str):
    """Loud-shape helper (AC-1): a missing key is a parse failure that
    names exactly what's missing, never a silently skipped row."""
    if not isinstance(mapping, dict) or key not in mapping:
        raise ValueError(f"efts response shape: missing {key!r} in {where}")
    return mapping[key]


def _tickers(display_names: Iterable[str]) -> list[str]:
    """Order-preserving unique tickers across a hit's display_names."""
    out: list[str] = []
    for name in display_names:
        match = _TICKERS_RE.search(name)
        if match is None:
            continue
        for token in match.group(1).split(","):
            ticker = token.strip()
            if ticker and ticker not in out:
                out.append(ticker)
    return out


def parse_fts_hits(response_json: dict) -> list[dict]:
    """efts.sec.gov search response -> candidate rows. Unknown/missing
    shapes raise ValueError naming what's missing (AC-1); parsing is
    pinned by a fixture trimmed verbatim from a real response."""
    hits_envelope = _require(response_json, "hits", "response")
    hit_list = _require(hits_envelope, "hits", "response['hits']")
    if not isinstance(hit_list, list):
        raise ValueError("efts response shape: 'hits' in response['hits'] is not a list")

    rows: list[dict] = []
    for position, hit in enumerate(hit_list):
        doc_id = _require(hit, "_id", f"hit[{position}]")
        source = _require(hit, "_source", f"hit {doc_id!r}")
        where = f"hit {doc_id!r} _source"

        form = source.get("form") or next(iter(source.get("root_forms") or []), None)
        if not form:
            raise ValueError(f"efts response shape: missing 'form'/'root_forms' in {where}")
        ciks = _require(source, "ciks", where)
        if not ciks:
            raise ValueError(f"efts response shape: empty 'ciks' in {where}")

        rows.append(
            {
                "accession": _require(source, "adsh", where),
                "form": form,
                "file_date": _require(source, "file_date", where),
                "tickers": _tickers(_require(source, "display_names", where)),
                "cik": ciks[0],
                "doc_id": doc_id,
                "states": _require(source, "biz_states", where),
            }
        )
    return rows


def novel_candidates(
    rows: Iterable[dict], known_accessions: set[str], provenance: dict
) -> list[dict]:
    """Rows not already in the corpus (AC-2 — build `known_accessions`
    with `corpus_accessions`, re-exported above), each tagged with the
    query provenance {query, forms, window} that found it (AC-3).
    Inputs are never mutated."""
    out: list[dict] = []
    for row in rows:
        if row.get("accession") in known_accessions:
            continue
        candidate = dict(row)
        candidate["provenance"] = dict(provenance)
        out.append(candidate)
    return out


# --------------------------------------------------------------------------
# Operational sweep (live network; caller writes the candidate artifact)
# --------------------------------------------------------------------------


def _fetch_page(client: httpx.Client, params: dict) -> dict | None:
    """One GET with SEC etiquette: gap before every request, Retry-After
    honored on 429/503 (bounded retries). Network errors skip the page
    with a log; shape errors stay loud upstream."""
    for _ in range(MAX_RETRIES + 1):
        time.sleep(REQUEST_GAP_S)
        try:
            response = client.get(FTS_URL, params=params, headers=SEC_HEADERS, timeout=30.0)
        except httpx.HTTPError as exc:
            logger.debug("efts %s: %s", params.get("q"), type(exc).__name__)
            return None
        if response.status_code in (429, 503):
            try:
                wait = float(response.headers.get("Retry-After", ""))
            except ValueError:
                wait = 1.0
            logger.debug("efts %s: HTTP %d, retrying in %.1fs", params.get("q"),
                         response.status_code, wait)
            time.sleep(wait)
            continue
        if response.status_code != 200:
            logger.warning("efts %s: HTTP %d, page skipped", params.get("q"),
                           response.status_code)
            return None
        return response.json()
    logger.warning("efts %s: retries exhausted, page skipped", params.get("q"))
    return None


def _query_hits(
    client: httpx.Client, term: str, form: str, date_from: str, date_to: str, cap: int
) -> list[dict]:
    """All hits for one (term x form) query, paginated via &from= offsets
    up to `cap`. Truncation is logged with what was left behind — a
    silent cap would hide discoverable filings (AC-4's owner review needs
    the honest total)."""
    collected: list[dict] = []
    offset = 0
    while True:
        payload = _fetch_page(
            client,
            {
                "q": f'"{term}"',
                "forms": form,
                "dateRange": "custom",
                "startdt": date_from,
                "enddt": date_to,
                "from": offset,
            },
        )
        if payload is None:
            break
        rows = parse_fts_hits(payload)
        if not rows:
            break
        collected.extend(rows)
        offset += len(rows)
        total = (payload["hits"].get("total") or {}).get("value")
        if len(collected) >= cap:
            if total is None or total > cap:
                logger.warning(
                    "efts query %r x %s: truncated at cap=%d (server total=%s, %s hits dropped)",
                    term, form, cap, total, "?" if total is None else total - cap,
                )
            del collected[cap:]
            break
        if total is not None and offset >= int(total):
            break
    return collected


def discover(
    terms: Sequence[str],
    forms: Sequence[str],
    date_from: str,
    date_to: str,
    known_accessions: set[str],
    *,
    max_hits_per_query: int = MAX_HITS_PER_QUERY,
    transport: httpx.BaseTransport | None = None,
) -> list[dict]:
    """Full discovery sweep: per (term x form) query over [date_from,
    date_to], deduped across queries by accession (first provenance
    wins), already-known accessions dropped. Returns the candidate list
    ready for the caller to write to artifacts/edgar_fts_candidates.json.
    Discovery only — nothing enters the corpus here (AC-4)."""
    window = f"{date_from}..{date_to}"
    seen: set[str] = set()
    candidates: list[dict] = []
    with httpx.Client(transport=transport) as client:
        for term in terms:
            for form in forms:
                rows = _query_hits(client, term, form, date_from, date_to, max_hits_per_query)
                provenance = {"query": term, "forms": form, "window": window}
                for candidate in novel_candidates(rows, known_accessions, provenance):
                    if candidate["accession"] in seen:
                        continue  # first provenance wins
                    seen.add(candidate["accession"])
                    candidates.append(candidate)
    return candidates

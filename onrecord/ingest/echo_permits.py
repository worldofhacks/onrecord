"""EPA ECHO CWA water-permit ingest — T-066 (module layer).

NPDES water permits are the keyless federal record of the WATER half of
the accountability story: what discharge permits actually exist in the
counties where capacity was promised. This module normalizes ECHO's CWA
REST facility rows into ONE shape:

    {facility, permit_id, county, state, status}

(all str; jurisdiction is added by the join, kept as SEPARATE labeled
figures beside promised GPD — never merged, the T-059 honesty pattern).

REALITY PIN (real responses fetched 2026-08-15, p_st=VA&p_co=Loudoun):
cwa_rest_services.get_facilities returns only a SUMMARY envelope
(QueryID + row counts, no facility rows); the rows come from the
cwa_rest_services.get_qid follow-up, whose Results.Facilities list
carries CWPName / SourceID / CWPCounty / CWPState / CWPPermitStatusDesc
(status is None on 8 of 100 real Loudoun rows -> ""). Parsers are pure
and LOUD: any unknown shape is a ValueError, never a quiet [] — only the
operational fetchers degrade.

County+state joins REUSE iso_queues' join_jurisdictions/load_mapping and
the same data/iso_jurisdictions.json table (exact match on
f"{county}, {state}"; misses returned, never fuzzy-matched or dropped).
ECHO spells counties WITHOUT the "County" suffix ("Loudoun"), like the
short-form mapping keys. Permit rows are structured data, not corpus
docs — they never enter the search index.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

from onrecord.ingest.iso_queues import (
    _get_with_retries,
    _snapshot,
    join_jurisdictions,
    load_mapping,
)

__all__ = [
    "parse_facilities",
    "parse_query_summary",
    "county_queries",
    "fetch_county",
    "pull_jurisdictions",
    "join_jurisdictions",
    "load_mapping",
]

logger = logging.getLogger(__name__)

ECHO_BASE = "https://echodata.epa.gov/echo"
GET_FACILITIES_URL = f"{ECHO_BASE}/cwa_rest_services.get_facilities"
GET_QID_URL = f"{ECHO_BASE}/cwa_rest_services.get_qid"
DEFAULT_OUT_DIR = Path("artifacts/echo")

_MAX_PAGES = 40  # get_qid pages per county; a hard stop, not a target
_SWEEP_PAUSE_S = 1.0  # etiquette pause between counties in a sweep


def _s(value: object) -> str:
    """Field -> stripped str; None -> "" (real rows carry None statuses)."""
    return "" if value is None else str(value).strip()


def _results(json_text: str, what: str) -> dict:
    """JSON text -> the Results dict, or a LOUD ValueError."""
    try:
        data = json.loads(json_text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"echo {what}: unparseable JSON") from exc
    if not isinstance(data, dict) or not isinstance(data.get("Results"), dict):
        raise ValueError(f"echo {what}: no Results object — unknown shape")
    return data["Results"]


def parse_facilities(json_text: str) -> list[dict]:
    """A Results.Facilities payload (get_qid page) -> normalized rows.
    Rows without a SourceID are skipped; a Results WITHOUT a Facilities
    list (e.g. the get_facilities summary) is a LOUD ValueError."""
    results = _results(json_text, "facilities")
    facilities = results.get("Facilities")
    if not isinstance(facilities, list):
        raise ValueError("echo facilities: Results has no Facilities list")
    rows: list[dict] = []
    for item in facilities:
        if not isinstance(item, dict):
            continue
        permit_id = _s(item.get("SourceID"))
        if not permit_id:
            continue
        rows.append(
            {
                "facility": _s(item.get("CWPName")),
                "permit_id": permit_id,
                "county": _s(item.get("CWPCounty")),
                "state": _s(item.get("CWPState")),
                "status": _s(item.get("CWPPermitStatusDesc")),
            }
        )
    return rows


def parse_query_summary(json_text: str) -> tuple[str, int]:
    """The get_facilities SUMMARY envelope -> (query_id, query_rows).
    QueryRows is a str in the real feed ("100") — returned as int.
    Missing/non-numeric fields are LOUD ValueErrors."""
    results = _results(json_text, "summary")
    query_id = _s(results.get("QueryID"))
    query_rows = _s(results.get("QueryRows"))
    if not query_id:
        raise ValueError("echo summary: no QueryID — unknown shape")
    if not query_rows.isdigit():
        raise ValueError(f"echo summary: QueryRows {query_rows!r} is not a count")
    return query_id, int(query_rows)


def county_queries(mapping: dict[str, str]) -> list[tuple[str, str]]:
    """data/iso_jurisdictions.json-style keys ("County, ST") -> ordered
    (county, state) query pairs. Both spellings of a county are distinct
    keys and BOTH swept (exact-match posture: every feed spelling earns
    its own query); malformed keys are skipped, never guessed."""
    pairs: list[tuple[str, str]] = []
    for key in mapping:
        county, _, state = key.rpartition(", ")
        if county and len(state) == 2:
            pairs.append((county, state))
        else:
            logger.debug("echo sweep: skipping malformed mapping key %r", key)
    return pairs


# --------------------------------------------------------------------------
# Operational fetchers (live network; not unit-tested)
# --------------------------------------------------------------------------


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def fetch_county(state: str, county: str, out_dir: str | Path = DEFAULT_OUT_DIR) -> list[dict]:
    """One county's CWA facilities: get_facilities (summary + QueryID),
    then get_qid pages until query_rows are collected. Raw pages are
    snapshotted under artifacts/echo/ with provenance sidecars. Returns
    normalized rows ([] on any failure — degrade, never crash)."""
    slug = _slug(f"{state}_{county}")
    with httpx.Client() as client:
        params = urlencode({"output": "JSON", "p_st": state, "p_co": county})
        response = _get_with_retries(client, f"{GET_FACILITIES_URL}?{params}")
        if response is None:
            return []
        try:
            query_id, query_rows = parse_query_summary(response.text)
        except ValueError as exc:
            logger.warning("echo %s/%s: %s", state, county, exc)
            return []
        if query_rows == 0:
            return []

        rows: list[dict] = []
        for page in range(1, _MAX_PAGES + 1):
            params = urlencode({"output": "JSON", "qid": query_id, "pageno": page})
            url = f"{GET_QID_URL}?{params}"
            page_response = _get_with_retries(client, url)
            if page_response is None:
                break
            try:
                page_rows = parse_facilities(page_response.text)
            except ValueError as exc:
                logger.warning("echo %s/%s page %d: %s", state, county, page, exc)
                break
            if not page_rows:
                break
            _snapshot(
                Path(out_dir), f"cwa_{slug}_p{page}.json", page_response.content, url
            )
            rows.extend(page_rows)
            if len(rows) >= query_rows:
                break
        return rows


def pull_jurisdictions(
    mapping: dict[str, str] | None = None,
    out_dir: str | Path = DEFAULT_OUT_DIR,
) -> tuple[list[dict], list[dict]]:
    """Operational sweep: fetch every county key in the jurisdiction
    mapping (load_mapping() when none is given, read-only), dedupe by
    permit_id across overlapping spellings, and exact-join back to
    registry jurisdictions. Returns (hits, misses) — misses are kept,
    never dropped (T-059 honesty pattern)."""
    if mapping is None:
        mapping = load_mapping()
    rows: list[dict] = []
    seen: set[str] = set()
    queries = county_queries(mapping)
    for i, (county, state) in enumerate(queries):
        if i:
            time.sleep(_SWEEP_PAUSE_S)
        for row in fetch_county(state, county, out_dir):
            if row["permit_id"] in seen:
                continue
            seen.add(row["permit_id"])
            rows.append(row)
    return join_jurisdictions(rows, mapping)

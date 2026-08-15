"""ISO interconnection-queue ingest — T-059 (module layer).

Grid operators' interconnection queues are structured, public, keyless
records of what was actually FILED — the counterpart to what was PROMISED
in hearing rooms. This module parses the two verified keyless feeds into
ONE normalized row shape:

    {iso, queue_id, county, state, mw, fuel, status, queue_date, withdrawn}

(all str except mw float and withdrawn bool), then joins county+state to
our registry jurisdictions via an EXPLICIT exact-match table
(data/iso_jurisdictions.json) — unmapped rows are returned as misses,
never fuzzy-matched or dropped. Queue rows are structured data, not
corpus docs: they never enter the search index (T-059 honesty pin).

Sources (verified 2026-08-14):
- MISO: https://www.misoenergy.org/api/giqueue/getprojects (JSON list)
- SPP:  https://opsportal.spp.org/Studies/GenerateActiveCSV (CSV with a
  "Last Updated On" preamble line above the header; active requests only,
  so "Date Withdrawn" is empty in practice but still honored)

SCOPE TRIM: CAISO publishes its queue as .xlsx only; reading it needs
openpyxl, which is not a project dependency — CAISO is skipped rather
than adding a dependency in this ticket. PJM/ERCOT need keys or click-
through and stay out per the ticket's keyless posture. Both feeds are
JSON/CSV, so the DTD-reject XML posture (T-038/T-052) has nothing to
reject here. Pure parsers pinned by tests/unit/ingest/test_iso_queues.py.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

MISO_URL = "https://www.misoenergy.org/api/giqueue/getprojects"
SPP_URL = "https://opsportal.spp.org/Studies/GenerateActiveCSV"
HEADERS = {"User-Agent": "OnRecord research alexander.miller@challenger.gauntletai.com"}
DEFAULT_OUT_DIR = Path("artifacts/iso")
MAPPING_PATH = Path("data/iso_jurisdictions.json")

_SPP_KEY_COLUMN = "Generation Interconnection Number"


def _iso_date(value: str) -> str:
    """Feed date -> YYYY-MM-DD. MISO sends ISO timestamps (keep the date
    part); SPP sends M/D/YYYY; empty stays empty; anything else verbatim."""
    value = (value or "").strip()
    if not value:
        return ""
    if "T" in value:
        return value.split("T", 1)[0]
    parts = value.split("/")
    if len(parts) == 3 and all(p.isdigit() for p in parts) and len(parts[2]) == 4:
        month, day, year = parts
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return value


def _mw(value: object) -> float:
    """MW cell -> float; blank or unparseable -> 0.0 (never a crash — a
    filed project with an unreadable MW still counts as a row)."""
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def parse_miso(json_text: str) -> list[dict]:
    """MISO giqueue getprojects JSON -> normalized rows. Malformed JSON or
    a non-list payload -> []; entries without a projectNumber skipped;
    county/state kept verbatim (multi-county strings are NOT split);
    withdrawn = withdrawnDate set OR applicationStatus == "Withdrawn"."""
    try:
        data = json.loads(json_text)
    except (TypeError, ValueError):
        logger.debug("miso queue: unparseable JSON")
        return []
    if not isinstance(data, list):
        logger.debug("miso queue: expected a JSON list, got %s", type(data).__name__)
        return []

    rows: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        queue_id = str(item.get("projectNumber") or "").strip()
        if not queue_id:
            continue
        status = str(item.get("applicationStatus") or "").strip()
        withdrawn_date = str(item.get("withdrawnDate") or "").strip()
        rows.append(
            {
                "iso": "MISO",
                "queue_id": queue_id,
                "county": str(item.get("county") or "").strip(),
                "state": str(item.get("state") or "").strip(),
                "mw": _mw(item.get("summerNetMW")),
                "fuel": str(item.get("fuelType") or "").strip(),
                "status": status,
                "queue_date": _iso_date(str(item.get("queueDate") or "")),
                "withdrawn": bool(withdrawn_date) or status == "Withdrawn",
            }
        )
    return rows


def parse_spp(csv_text: str) -> list[dict]:
    """SPP GenerateActiveCSV text -> normalized rows. The real file has a
    "Last Updated On" preamble above the header and a leading space in the
    " Nearest Town or County" header cell — the header row is located by
    its key column and every header stripped. No header -> []; rows
    without a queue number skipped; fuel = "Generation Type", falling back
    to "Fuel Type" when empty (652 of 1023 live rows have no Fuel Type)."""
    lines = csv_text.splitlines()
    header_idx = next(
        (i for i, line in enumerate(lines[:10]) if _SPP_KEY_COLUMN in line), None
    )
    if header_idx is None:
        logger.debug("spp queue: header row not found")
        return []

    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))
    rows: list[dict] = []
    for raw in reader:
        row = {
            key.strip(): (value or "").strip()
            for key, value in raw.items()
            if isinstance(key, str) and isinstance(value, (str, type(None)))
        }
        queue_id = row.get(_SPP_KEY_COLUMN, "")
        if not queue_id:
            continue
        rows.append(
            {
                "iso": "SPP",
                "queue_id": queue_id,
                "county": row.get("Nearest Town or County", ""),
                "state": row.get("State", ""),
                "mw": _mw(row.get("MAX Summer MW", "")),
                "fuel": row.get("Generation Type", "") or row.get("Fuel Type", ""),
                "status": row.get("Status", ""),
                "queue_date": _iso_date(row.get("Request Received", "")),
                "withdrawn": bool(row.get("Date Withdrawn", "")),
            }
        )
    return rows


def join_jurisdictions(
    rows: list[dict], mapping: dict[str, str]
) -> tuple[list[dict], list[dict]]:
    """Exact-match join on f"{county}, {state}" against the explicit
    mapping table. Hits are COPIES with a "jurisdiction" key added; every
    other row is returned in misses unchanged — logged, never guessed."""
    hits: list[dict] = []
    misses: list[dict] = []
    for row in rows:
        key = f"{row.get('county', '')}, {row.get('state', '')}"
        jurisdiction = mapping.get(key)
        if jurisdiction is None:
            misses.append(row)
            continue
        hit = dict(row)
        hit["jurisdiction"] = jurisdiction
        hits.append(hit)
    if misses:
        logger.debug("jurisdiction join: %d hits, %d honest misses", len(hits), len(misses))
    return hits, misses


def load_mapping(path: str | Path = MAPPING_PATH) -> dict[str, str]:
    """Load data/iso_jurisdictions.json; missing file -> {} (keyless-
    deploy posture: an absent artifact degrades, never crashes)."""
    path = Path(path)
    if not path.exists():
        logger.debug("iso jurisdiction mapping absent at %s", path)
        return {}
    return json.loads(path.read_text())


# --------------------------------------------------------------------------
# Operational fetchers (live network; not unit-tested)
# --------------------------------------------------------------------------

_MAX_ATTEMPTS = 3
_BACKOFF_S = 2.0
_RETRY_AFTER_CAP_S = 120.0


def _get_with_retries(client: httpx.Client, url: str) -> httpx.Response | None:
    """GET with etiquette: 30s timeout, retries on transport errors and
    429/5xx, honoring Retry-After (capped) when the server sends one."""
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        wait = _BACKOFF_S * attempt
        try:
            response = client.get(url, headers=HEADERS, timeout=30.0, follow_redirects=True)
        except httpx.HTTPError as exc:
            logger.debug("%s attempt %d: %s", url, attempt, type(exc).__name__)
        else:
            if response.status_code == 200:
                return response
            if response.status_code == 429 or response.status_code >= 500:
                retry_after = response.headers.get("Retry-After", "")
                if retry_after.strip().isdigit():
                    wait = min(float(retry_after), _RETRY_AFTER_CAP_S)
                logger.debug("%s attempt %d: HTTP %d", url, attempt, response.status_code)
            else:
                logger.debug("%s: HTTP %d, giving up", url, response.status_code)
                return None
        if attempt < _MAX_ATTEMPTS:
            time.sleep(wait)
    return None


def _snapshot(out_dir: Path, name: str, content: bytes, url: str) -> None:
    """Raw snapshot + provenance sidecar (fetch date + sha256, AC-1)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / name).write_bytes(content)
    provenance = {
        "url": url,
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
    }
    sidecar = out_dir / f"{name}.provenance.json"
    sidecar.write_text(json.dumps(provenance, indent=2) + "\n")


def fetch_miso(out_dir: str | Path = DEFAULT_OUT_DIR) -> list[dict]:
    """Fetch the MISO queue, snapshot the raw JSON under artifacts/iso/,
    return normalized rows ([] on any failure — degrade, never crash)."""
    with httpx.Client() as client:
        response = _get_with_retries(client, MISO_URL)
    if response is None:
        return []
    _snapshot(Path(out_dir), "miso_projects.json", response.content, MISO_URL)
    return parse_miso(response.text)


def fetch_spp(out_dir: str | Path = DEFAULT_OUT_DIR) -> list[dict]:
    """Fetch the SPP active-requests CSV, snapshot it under artifacts/iso/,
    return normalized rows ([] on any failure — degrade, never crash)."""
    with httpx.Client() as client:
        response = _get_with_retries(client, SPP_URL)
    if response is None:
        return []
    _snapshot(Path(out_dir), "spp_active.csv", response.content, SPP_URL)
    return parse_spp(response.text)

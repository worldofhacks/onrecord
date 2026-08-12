"""Prices layer (T-014) — EOD series cache, significant-move detection,
receipts-vs-price window join, `/api/prices` payload assembly.

Stock price history + significant-move timeline joined to receipts, for the
UI's receipts-vs-price correlation view. See `tickets/T-014.md` and the
module docstring of `tests/unit/ingest/test_prices.py` (authoritative,
pinned contract — cache shape, source-selection rule, window-join
semantics, receipt-dict shape, `/api/prices` payload shape) for the full
spec this module implements.

Out of scope (per the ticket): intraday data, jurisdiction->ticker
inference, causal claims, and the actual `/api/prices` HTTP route wiring
(T-013's `api.py`, wave-5 integration commit) — this module exposes
`api_payload` as a plain function only.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx

from onrecord.ingest.build_corpus import load_corpus_snapshot
from onrecord.types import Doc

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_DIR = "artifacts/prices"
_CACHE_FRESHNESS = timedelta(days=1)

_STOOQ_URL = "https://stooq.com/q/d/l/"
_FMP_URL_TEMPLATE = "https://financialmodelingprep.com/api/v3/historical-price-full/{ticker}"


# --------------------------------------------------------------------------
# Pure parsers (no I/O)
# --------------------------------------------------------------------------


def _parse_date(text: str) -> date | None:
    """Return a `date` if `text` is a valid `YYYY-MM-DD` string, else None."""
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def parse_stooq_csv(text: str) -> list[dict]:
    """Parse stooq daily-CSV text into an ascending-by-date `[{"date",
    "close"}, ...]` list. Malformed rows are skipped and logged at WARNING;
    blank lines are skipped silently. See module docstring / test contract
    for the exact malformed-row rules. Pure — no I/O."""
    rows: list[dict] = []
    header_seen = False
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if not header_seen:
            # First non-blank line is the header (e.g.
            # "Date,Open,High,Low,Close,Volume") — never a data row, never
            # logged as malformed.
            header_seen = True
            continue

        fields = line.split(",")
        if len(fields) != 6:
            logger.warning(
                "parse_stooq_csv: skipping malformed row %d (expected 6 fields, got %d): %r",
                lineno,
                len(fields),
                line,
            )
            continue

        date_field, _open, _high, _low, close_field, _volume = fields
        parsed_date = _parse_date(date_field.strip())
        if parsed_date is None:
            logger.warning(
                "parse_stooq_csv: skipping malformed row %d (invalid date %r)",
                lineno,
                date_field,
            )
            continue

        try:
            close = float(close_field.strip())
        except (ValueError, TypeError):
            logger.warning(
                "parse_stooq_csv: skipping malformed row %d (invalid close %r)",
                lineno,
                close_field,
            )
            continue

        rows.append({"date": parsed_date.isoformat(), "close": close})

    rows.sort(key=lambda row: row["date"])
    return rows


def parse_fmp_historical_prices(payload: dict) -> list[dict]:
    """Parse one FMP `historical-price-full/<ticker>` JSON payload into the
    same ascending-by-date `[{"date", "close"}, ...]` shape as
    `parse_stooq_csv`. The real FMP endpoint returns `historical`
    newest-first, so this re-sorts. Pure — no I/O."""
    historical = payload.get("historical")
    if not isinstance(historical, list):
        return []

    rows: list[dict] = []
    for entry in historical:
        if not isinstance(entry, dict):
            continue
        parsed_date = _parse_date(str(entry.get("date")))
        if parsed_date is None:
            continue
        close = entry.get("close")
        if not isinstance(close, int | float) or isinstance(close, bool):
            continue
        rows.append({"date": parsed_date.isoformat(), "close": float(close)})

    rows.sort(key=lambda row: row["date"])
    return rows


# --------------------------------------------------------------------------
# fetch_eod — cache + stooq-primary/FMP-fallback orchestration
# --------------------------------------------------------------------------


def _cache_path(cache_dir: str | Path, ticker: str) -> Path:
    return Path(cache_dir) / f"{ticker}.json"


def _read_fresh_cache(cache_dir: str | Path, ticker: str) -> list[dict] | None:
    """Return the cached series if a cache file exists and is fresh
    (<=1 day old), else None. Any read/parse failure is treated as a cache
    miss (never raises)."""
    path = _cache_path(cache_dir, ticker)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(payload["fetched_at"])
        series = payload["series"]
    except (OSError, ValueError, KeyError, TypeError):
        return None

    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=UTC)

    if datetime.now(UTC) - fetched_at > _CACHE_FRESHNESS:
        return None
    return series


def _write_cache(cache_dir: str | Path, ticker: str, series: list[dict]) -> None:
    path = _cache_path(cache_dir, ticker)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ticker": ticker,
        "fetched_at": datetime.now(UTC).isoformat(),
        "series": series,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _try_stooq(client: httpx.Client, ticker: str) -> list[dict] | None:
    """Attempt the stooq fetch; return a parsed series on success, None on
    any failure. Never raises. Diagnostic detail stays below INFO (never
    logs the response body/URL beyond the ticker + status)."""
    try:
        response = client.get(_STOOQ_URL, params={"s": f"{ticker.lower()}.us", "i": "d"})
    except httpx.HTTPError as exc:
        logger.debug("stooq fetch for %s raised %s: %s", ticker, type(exc).__name__, exc)
        return None

    if response.status_code >= 400:
        logger.debug("stooq fetch for %s failed with HTTP %d", ticker, response.status_code)
        return None

    series = parse_stooq_csv(response.text)
    if not series:
        logger.debug("stooq fetch for %s returned no usable rows", ticker)
        return None
    return series


def _try_fmp(client: httpx.Client, ticker: str, api_key: str) -> list[dict] | None:
    """Attempt the FMP fallback fetch; return a parsed series on success,
    None on any failure. Never raises, and NEVER logs the API key (per the
    T-008 lesson: don't call raise_for_status()/log URLs or params, which
    would leak `apikey` in plaintext)."""
    url = _FMP_URL_TEMPLATE.format(ticker=ticker)
    try:
        response = client.get(url, params={"apikey": api_key})
    except httpx.HTTPError as exc:
        logger.debug("FMP fetch for %s raised %s", ticker, type(exc).__name__)
        return None

    if response.status_code >= 400:
        logger.debug("FMP fetch for %s failed with HTTP %d", ticker, response.status_code)
        return None

    try:
        payload = response.json()
    except ValueError:
        logger.debug("FMP fetch for %s returned non-JSON body", ticker)
        return None

    series = parse_fmp_historical_prices(payload)
    if not series:
        logger.debug("FMP fetch for %s returned no usable rows", ticker)
        return None
    return series


def fetch_eod(
    ticker: str,
    range_days: int = 365,
    transport: httpx.BaseTransport | None = None,
    cache_dir: str | Path | None = None,
) -> list[dict]:
    """Fetch `ticker`'s end-of-day close series (ascending `{"date",
    "close"}` list), preferring an on-disk cache, falling back to a live
    fetch (stooq primary; FMP fallback when `FMP_API_KEY` is set and stooq
    fails). Never raises — total failure returns `[]` plus exactly one
    summary log line. See module docstring / test contract for the full
    cache-freshness and source-selection rules."""
    effective_cache_dir = cache_dir if cache_dir is not None else _DEFAULT_CACHE_DIR

    cached = _read_fresh_cache(effective_cache_dir, ticker)
    if cached is not None:
        return cached

    with httpx.Client(transport=transport) as client:
        series = _try_stooq(client, ticker)

        if series is None:
            fmp_key = os.environ.get("FMP_API_KEY")
            if fmp_key and fmp_key.strip():
                series = _try_fmp(client, ticker, fmp_key)

    if series is None:
        logger.info("fetch_eod: all price sources failed for %s; returning empty series", ticker)
        return []

    _write_cache(effective_cache_dir, ticker, series)
    return series


# --------------------------------------------------------------------------
# significant_moves — signed daily returns vs threshold
# --------------------------------------------------------------------------


def significant_moves(series: list[dict], threshold_pct: float = 5.0) -> list[dict]:
    """Return `[{"date", "return_pct"}, ...]` for every day (from the 2nd
    onward) whose signed close-to-close percent return has absolute value
    `>= threshold_pct`. Order preserved (ascending by date). Pure — no I/O."""
    moves: list[dict] = []
    for i in range(1, len(series)):
        prior_close = series[i - 1]["close"]
        today_close = series[i]["close"]
        if prior_close == 0:
            continue
        return_pct = (today_close - prior_close) / prior_close * 100
        if abs(return_pct) >= threshold_pct:
            moves.append({"date": series[i]["date"], "return_pct": return_pct})
    return moves


# --------------------------------------------------------------------------
# nearby_receipts — ticker match + window-days-before join
# --------------------------------------------------------------------------


def nearby_receipts(
    moves: list[dict],
    corpus_rows: list[Doc],
    ticker: str,
    window_days: int = 7,
) -> list[dict]:
    """Return a NEW list — one entry per input move, each the original
    move's keys plus a `"nearby_receipts"` list of receipt dicts for every
    `corpus_rows` doc matching `ticker` and dated within `window_days`
    before (inclusive) the move date. Never mutates `moves`. Pure — no
    I/O. See module docstring / test contract for the exact receipt-dict
    shape and window-join semantics."""
    matching_docs = [doc for doc in corpus_rows if doc.ticker == ticker]

    result: list[dict] = []
    for move in moves:
        move_date = _parse_date(move["date"])
        receipts: list[dict] = []
        if move_date is not None:
            for doc in matching_docs:
                doc_date = _parse_date(doc.date)
                if doc_date is None:
                    continue
                delta_days = (move_date - doc_date).days
                if 0 <= delta_days <= window_days:
                    receipts.append(
                        {
                            "id": doc.id,
                            "date": doc.date,
                            "source_type": doc.source_type,
                            "deep_link": doc.deep_link,
                        }
                    )
        result.append({**move, "nearby_receipts": receipts})
    return result


# --------------------------------------------------------------------------
# api_payload — the exact /api/prices contract
# --------------------------------------------------------------------------


def api_payload(
    ticker: str,
    corpus_path: str | Path,
    range_days: int = 365,
    threshold_pct: float = 5.0,
    window_days: int = 7,
    transport: httpx.BaseTransport | None = None,
    cache_dir: str | Path | None = None,
) -> dict:
    """Compose `fetch_eod` -> `significant_moves` -> `nearby_receipts` (over
    `corpus_path`'s loaded snapshot) into the exact `/api/prices` payload
    shape: `{"ticker", "series", "significant_moves": [{"date",
    "return_pct", "nearby_receipts": [...]}, ...]}`. The HTTP route itself
    is wired elsewhere (T-013, wave-5 integration commit) — out of this
    ticket's scope."""
    series = fetch_eod(ticker, range_days=range_days, transport=transport, cache_dir=cache_dir)
    moves = significant_moves(series, threshold_pct=threshold_pct)
    corpus_rows = load_corpus_snapshot(corpus_path)
    moves_with_receipts = nearby_receipts(moves, corpus_rows, ticker, window_days=window_days)
    return {
        "ticker": ticker,
        "series": series,
        "significant_moves": moves_with_receipts,
    }

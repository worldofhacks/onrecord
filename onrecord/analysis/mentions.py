"""Mention-anchored ticker performance — T-033 (the paste.trade mechanic
over OnRecord's receipt chain).

A "mention" is a corpus document attributed to a ticker at ingest
(`doc.ticker`); its entry price is the close ON the mention date, anchoring
BACKWARD across non-trading days (never forward — forward anchoring would
peek). Performance since, and peak since, are computed from daily closes
only, and every row carries its receipt verbatim. Deliberately honest
about grain: the record is day-grained, so entries are daily closes and
the UI must say so. Contract pinned by
tests/unit/analysis/test_mentions.py.
"""

from __future__ import annotations

from bisect import bisect_right

from onrecord.types import Doc

SNIPPET_LEN = 160


def _entry_close(series: list[dict], date: str) -> float | None:
    """Close on `date`, else the latest close BEFORE it; None when the
    mention predates the series (no honest entry exists)."""
    dates = [row["date"] for row in series]
    idx = bisect_right(dates, date) - 1
    if idx < 0:
        return None
    return float(series[idx]["close"])


def mention_rows(
    docs: list[Doc],
    series_by_ticker: dict[str, list[dict]],
    since: str,
    now_date: str,
) -> list[dict]:
    """One row per qualifying mention, return_pct descending. See module
    docstring / frozen tests."""
    del now_date  # reserved for future windows; latest close is series-defined
    rows: list[dict] = []
    per_ticker_count: dict[str, int] = {}

    for doc in docs:
        ticker = doc.ticker
        if not ticker or not doc.date or doc.date < since:
            continue
        series = series_by_ticker.get(ticker)
        if not series or len(series) < 2:
            continue
        entry = _entry_close(series, doc.date)
        if entry is None or entry <= 0:
            continue
        latest = float(series[-1]["close"])
        after = [float(r["close"]) for r in series if r["date"] >= doc.date]
        peak = max(after) if after else latest
        rows.append(
            {
                "ticker": ticker,
                "doc_id": doc.id,
                "date": doc.date,
                "deep_link": doc.deep_link,
                "venue_type": doc.venue_type,
                "source_type": doc.source_type,
                "snippet": doc.text[:SNIPPET_LEN],
                "entry_close": round(entry, 2),
                "latest_close": round(latest, 2),
                "return_pct": round((latest / entry - 1.0) * 100, 2),
                "peak_pct": round((peak / entry - 1.0) * 100, 2),
            }
        )
        per_ticker_count[ticker] = per_ticker_count.get(ticker, 0) + 1

    for row in rows:
        row["co_mentions"] = per_ticker_count[row["ticker"]] - 1

    rows.sort(key=lambda r: (-r["return_pct"], r["doc_id"]))
    return rows

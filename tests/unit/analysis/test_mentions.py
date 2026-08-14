"""Failing tests for T-033 — mention-anchored ticker performance.

Contract (fixed here):

``mention_rows(docs, series_by_ticker, since, now_date) -> list[dict]``
(pure) — paste.trade's mechanic over OUR record: a "mention" is a corpus
doc attributed to a ticker (`doc.ticker` set — attribution happened at
ingest, no fragile text matching). For each mention with `date >= since`:

- ``entry_close``: the close ON the mention date, else the latest close
  BEFORE it (non-trading days anchor backward, never forward). A mention
  with no prior-or-same-day close is SKIPPED (no honest entry exists).
- ``latest_close``: the series' last close.
- ``return_pct`` = (latest/entry - 1) * 100, 2 decimals.
- ``peak_pct``: max close on/after the mention date vs entry, 2 decimals;
  always >= return_pct.
- ``co_mentions``: how many OTHER qualifying mentions share the ticker.
- Receipt fields carried verbatim: doc_id, deep_link, date, venue_type,
  source_type, snippet (text[:160]).
Rows sorted by return_pct descending, ties by doc_id ascending.
Tickers absent from `series_by_ticker` (or with <2 closes) are skipped.
"""

import pytest

try:
    from onrecord.analysis import mentions
except Exception:  # pragma: no cover - red phase
    mentions = None

from onrecord.types import Doc


def _attr(name):
    if mentions is None or not hasattr(mentions, name):
        pytest.fail(f"onrecord.analysis.mentions.{name} does not exist yet (T-033 red)")
    return getattr(mentions, name)


def _doc(i, ticker, date, text="the record speaks"):
    return Doc(id=f"ed:{ticker}:{i}", text=text, source_type="filing",
               venue_type="sworn", date=date,
               deep_link=f"https://sec.gov/{ticker}/{i}", ticker=ticker,
               jurisdiction=None)


SERIES = {
    "VST": [
        {"date": "2026-01-02", "close": 100.0},
        {"date": "2026-01-05", "close": 110.0},
        {"date": "2026-01-06", "close": 90.0},
        {"date": "2026-01-07", "close": 120.0},
    ],
    "NVDA": [
        {"date": "2026-01-02", "close": 50.0},
        {"date": "2026-01-07", "close": 40.0},
    ],
}


def test_mention_rows_math_anchoring_and_order():
    docs = [
        _doc(1, "VST", "2026-01-02"),   # entry 100 -> latest 120: +20%, peak 120 -> +20%
        _doc(2, "VST", "2026-01-04"),   # non-trading: anchors BACK to 01-02 close 100
        _doc(3, "NVDA", "2026-01-02"),  # entry 50 -> latest 40: -20%, peak 50 -> 0%
    ]
    rows = _attr("mention_rows")(docs, SERIES, since="2026-01-01", now_date="2026-01-08")
    assert [r["doc_id"] for r in rows] == ["ed:VST:1", "ed:VST:2", "ed:NVDA:3"]

    top = rows[0]
    assert top["entry_close"] == 100.0 and top["latest_close"] == 120.0
    assert top["return_pct"] == 20.0
    assert top["peak_pct"] == 20.0
    assert top["co_mentions"] == 1          # the other VST mention
    assert top["deep_link"].startswith("https://")
    assert top["snippet"] == "the record speaks"

    nv = rows[2]
    assert nv["return_pct"] == -20.0 and nv["peak_pct"] == 0.0
    assert nv["peak_pct"] >= nv["return_pct"]


def test_mention_rows_window_and_missing_series_skips():
    docs = [
        _doc(1, "VST", "2025-06-01"),   # before `since` -> excluded
        _doc(2, "ZZZZ", "2026-01-05"),  # no series -> skipped
        _doc(3, "VST", "2026-01-01"),   # before first close -> no honest entry, skipped
        _doc(4, "VST", "2026-01-05"),
    ]
    rows = _attr("mention_rows")(docs, SERIES, since="2026-01-01", now_date="2026-01-08")
    assert [r["doc_id"] for r in rows] == ["ed:VST:4"]
    assert rows[0]["co_mentions"] == 0


def test_mention_rows_empty():
    assert _attr("mention_rows")([], SERIES, since="2026-01-01", now_date="2026-01-08") == []

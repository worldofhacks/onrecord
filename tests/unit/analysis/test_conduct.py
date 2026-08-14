"""Failing tests for T-039 — Confidence-vs-Conduct (insider net-flow core).

Contract (fixed here):

``BUY_CODES = ("P",)`` / ``SELL_CODES = ("S",)`` — open-market decisions
only. Awards (A), option exercises (M), tax withholding (F), gifts (G)
are NEVER counted in flow: they are compensation mechanics, not conviction.

``net_flow(rows: list[dict], ticker: str, since: str) -> dict`` (pure)

- Filters to `ticker` (exact) and `transaction_date >= since` (ISO
  compare); rows with a blank/malformed date are skipped.
- Returns {"ticker", "since", "transactions", "buys_value", "sells_value",
  "net_value" (buys - sells), "buys_shares", "sells_shares",
  "insiders_selling" (distinct filer_name with a sell),
  "insiders_buying", "by_month" ([{month: "YYYY-MM", buys_value,
  sells_value}] ascending, only months with activity),
  "recent" (last 10 counted rows, date descending),
  "last_transaction_date"}.
- Values rounded to 2 decimals. Empty input -> zeroed shape, recent=[],
  by_month=[], last_transaction_date=None.
"""

import pytest

try:
    from onrecord.analysis import conduct
except Exception:  # pragma: no cover - red phase
    conduct = None


def _attr(name):
    if conduct is None or not hasattr(conduct, name):
        pytest.fail(f"onrecord.analysis.conduct.{name} does not exist yet (T-039 red)")
    return getattr(conduct, name)


def _row(date, code, shares, price, filer="DOE JANE", ticker="NVDA"):
    return {
        "ticker": ticker, "cik": "0001045810", "filer_name": filer,
        "filer_title": "", "is_officer": True, "is_director": False,
        "transaction_date": date, "code": code, "shares": shares,
        "price_per_share": price, "value": round(shares * price, 2),
        "shares_owned_after": 0.0, "filing_url": "https://sec.gov/x",
        "accession": f"acc-{date}-{code}",
    }


FIXTURE = [
    _row("2026-06-02", "S", 1000, 100.0),                     # sell $100k
    _row("2026-06-15", "S", 500, 110.0, filer="ROE RICHARD"),  # sell $55k
    _row("2026-07-01", "P", 200, 120.0),                       # buy $24k
    _row("2026-07-02", "A", 5000, 0.0),                        # award: ignored
    _row("2026-05-01", "S", 100, 90.0),                        # before `since`
    _row("2026-06-20", "S", 999, 100.0, ticker="MSFT"),        # other ticker
    _row("", "S", 10, 10.0),                                   # malformed date
]


def test_net_flow_filters_counts_and_aggregates():
    flow = _attr("net_flow")(FIXTURE, "NVDA", since="2026-06-01")
    assert flow["ticker"] == "NVDA" and flow["since"] == "2026-06-01"
    assert flow["transactions"] == 3            # 2 sells + 1 buy counted
    assert flow["sells_value"] == pytest.approx(155000.0)
    assert flow["buys_value"] == pytest.approx(24000.0)
    assert flow["net_value"] == pytest.approx(-131000.0)
    assert flow["sells_shares"] == 1500 and flow["buys_shares"] == 200
    assert flow["insiders_selling"] == 2 and flow["insiders_buying"] == 1
    assert flow["last_transaction_date"] == "2026-07-01"


def test_net_flow_by_month_and_recent_ordering():
    flow = _attr("net_flow")(FIXTURE, "NVDA", since="2026-06-01")
    months = [m["month"] for m in flow["by_month"]]
    assert months == ["2026-06", "2026-07"]
    june = flow["by_month"][0]
    assert june["sells_value"] == pytest.approx(155000.0)
    assert june["buys_value"] == 0.0
    recent_dates = [r["transaction_date"] for r in flow["recent"]]
    assert recent_dates == sorted(recent_dates, reverse=True)
    assert len(flow["recent"]) == 3


def test_net_flow_awards_and_exercises_never_count():
    rows = [_row("2026-06-01", code, 1000, 50.0) for code in ("A", "M", "F", "G")]
    flow = _attr("net_flow")(rows, "NVDA", since="2026-01-01")
    assert flow["transactions"] == 0
    assert flow["net_value"] == 0.0 and flow["recent"] == []


def test_net_flow_empty_shape():
    flow = _attr("net_flow")([], "NVDA", since="2026-01-01")
    assert flow["transactions"] == 0 and flow["by_month"] == []
    assert flow["last_transaction_date"] is None

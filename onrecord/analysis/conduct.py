"""Confidence-vs-Conduct — insider net-flow core (T-039).

Aggregates T-038's Form 4 rows into a per-ticker conduct summary: what the
company's own officers and directors DID with their shares while the record
carries their statements. Open-market decisions only (P buys, S sells) —
awards, option exercises, tax withholding, and gifts are compensation
mechanics, not conviction, and never count toward flow. The UI presents
juxtaposition, never causation and never advice. Contract pinned by
tests/unit/analysis/test_conduct.py.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)

BUY_CODES: tuple[str, ...] = ("P",)
SELL_CODES: tuple[str, ...] = ("S",)

DEFAULT_TRANSACTIONS_PATH = Path("artifacts/form4/insider_transactions.jsonl")


def load_transactions(path: str | Path = DEFAULT_TRANSACTIONS_PATH) -> list[dict]:
    """Read the T-038 artifact; malformed lines are skipped with a debug
    log, a missing file is an empty list (the API's ladder handles it)."""
    path = Path(path)
    if not path.exists():
        return []
    rows: list[dict] = []
    for lineno, line in enumerate(path.open(encoding="utf-8"), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            logger.debug("form4 artifact line %d: malformed, skipped", lineno)
    return rows


def net_flow(rows: list[dict], ticker: str, since: str) -> dict:
    """Per-ticker open-market insider flow since `since` (ISO date).
    See module docstring / frozen tests for the exact shape."""
    counted: list[dict] = []
    for row in rows:
        if row.get("ticker") != ticker:
            continue
        date = str(row.get("transaction_date") or "")
        if len(date) != 10 or date < since:
            continue
        if row.get("code") in BUY_CODES + SELL_CODES:
            counted.append(row)

    buys = [r for r in counted if r["code"] in BUY_CODES]
    sells = [r for r in counted if r["code"] in SELL_CODES]

    monthly: dict[str, dict] = defaultdict(lambda: {"buys_value": 0.0, "sells_value": 0.0})
    for row in buys:
        monthly[row["transaction_date"][:7]]["buys_value"] += float(row.get("value", 0.0))
    for row in sells:
        monthly[row["transaction_date"][:7]]["sells_value"] += float(row.get("value", 0.0))

    by_month = [
        {"month": month,
         "buys_value": round(bucket["buys_value"], 2),
         "sells_value": round(bucket["sells_value"], 2)}
        for month, bucket in sorted(monthly.items())
    ]

    recent = sorted(counted, key=lambda r: r["transaction_date"], reverse=True)[:10]
    buys_value = round(sum(float(r.get("value", 0.0)) for r in buys), 2)
    sells_value = round(sum(float(r.get("value", 0.0)) for r in sells), 2)

    return {
        "ticker": ticker,
        "since": since,
        "transactions": len(counted),
        "buys_value": buys_value,
        "sells_value": sells_value,
        "net_value": round(buys_value - sells_value, 2),
        "buys_shares": round(sum(float(r.get("shares", 0.0)) for r in buys), 2),
        "sells_shares": round(sum(float(r.get("shares", 0.0)) for r in sells), 2),
        "insiders_selling": len({r.get("filer_name", "") for r in sells}),
        "insiders_buying": len({r.get("filer_name", "") for r in buys}),
        "by_month": by_month,
        "recent": recent,
        "last_transaction_date": (
            max(r["transaction_date"] for r in counted) if counted else None
        ),
    }

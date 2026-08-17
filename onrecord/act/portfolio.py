"""Portfolio lens — SnapTrade read-only client (T-065, module layer).

Single-connection design: the platform has no user system, so there is one
connected brokerage per deployment — the owner's own. Request signing
follows SnapTrade's HMAC scheme: base64(HMAC-SHA256(consumerKey, canonical
JSON of {"content": <body-or-null>, "path": "/api/v1/<endpoint>",
"query": <sorted query string>})) travels in the `Signature` header; every
request carries clientId + timestamp (epoch seconds) as query params, and
user-scoped calls add userId + userSecret to the query.

Pins frozen by tests/unit/act/test_portfolio.py:
- `_sign` is a PURE function, pinned by known-answer tests — canonical JSON
  is `json.dumps(..., separators=(",", ":"), sort_keys=True)` and a POST
  body is sent as exactly those canonical bytes, so the wire content and
  the signed content can never drift apart.
- Secret discipline (T-014): userSecret/consumerKey are never logged
  (httpx/httpcore loggers are silenced for the duration of every keyed
  call, the `onrecord/rag/embeddings.py` mechanism), never echoed in an
  exception message or chain (transport errors re-raise `from None` with
  generic text — httpx error text can carry the full keyed URL), and never
  appear in any repr.
- Strictly factual join: `cross_with_record` reports what the record holds
  for a held symbol — counts and values only, no verdict, no guidance
  (word-boundary grep gate over this file's source).
- Zero brokerage-action endpoints: only registerUser, login (Connection
  Portal, connectionType=read), the account listing, and per-account
  positions are reachable from here; a grep gate over this source keeps it
  that way.
- Connection state is a JSON file written with 0600 permissions; its path
  comes from ONRECORD_SNAPTRADE_STATE (default artifacts/snaptrade_user
  .json). Operational credentials come from SNAPTRADE_CLIENT_ID +
  SNAPTRADE_CONSUMER_KEY via `credentials_from_env()`.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import logging
import os
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

__all__ = [
    "SnapTradeNotConfigured",
    "SnapTradeRequestError",
    "credentials_from_env",
    "cross_with_record",
    "holdings",
    "load_connection",
    "login_url",
    "register_user",
    "save_connection",
    "state_path",
]

_BASE_URL = "https://api.snaptrade.com"

CLIENT_ID_ENV = "SNAPTRADE_CLIENT_ID"
CONSUMER_KEY_ENV = "SNAPTRADE_CONSUMER_KEY"
STATE_ENV = "ONRECORD_SNAPTRADE_STATE"
USER_ENV = "ONRECORD_SNAPTRADE_USER"
USER_SECRET_ENV = "ONRECORD_SNAPTRADE_USER_SECRET"
DEFAULT_STATE_PATH = "artifacts/snaptrade_user.json"

_LIBRARY_LOGGER_NAMES = ("httpx", "httpcore")


class SnapTradeRequestError(Exception):
    """A SnapTrade call failed. Messages carry status + path only — never
    the query string (it holds userSecret), never response text (a server
    echo could hold anything)."""


class SnapTradeNotConfigured(Exception):
    """Operational credentials are missing from the environment. Messages
    name the missing variables, never any value."""


@contextlib.contextmanager
def _silenced_library_loggers():
    """Silence httpx/httpcore loggers for the duration of a keyed request
    (LESSONS T-014, the `onrecord/rag/embeddings.py` mechanism: a
    secret-leak check must cover library loggers, not just this module's
    own — httpx logs full request URLs at INFO, and here the URL query
    carries userSecret).

    `Logger.disabled = True` makes `isEnabledFor` return False
    unconditionally regardless of level or propagation, so no log record is
    ever created for these loggers while the context is active.
    """
    loggers = [logging.getLogger(name) for name in _LIBRARY_LOGGER_NAMES]
    previous = [(lg.level, lg.disabled) for lg in loggers]
    for lg in loggers:
        lg.setLevel(logging.CRITICAL + 1)
        lg.disabled = True
    try:
        yield
    finally:
        for lg, (level, disabled) in zip(loggers, previous, strict=True):
            lg.setLevel(level)
            lg.disabled = disabled


def _canonical_json(payload) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _sign(consumer_key: str, path: str, query: str, content) -> str:
    """PURE signature primitive, pinned by frozen known-answer tests:
    base64(HMAC-SHA256(consumer_key, canonical JSON of
    {"content": content, "path": path, "query": query})). `content` is the
    parsed request body (dict) or None for body-less requests."""
    canonical = _canonical_json({"content": content, "path": path, "query": query})
    digest = hmac.new(
        consumer_key.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def _timestamp() -> str:
    return str(int(time.time()))


def _signed_request(
    method: str,
    path: str,
    query_params: dict[str, str],
    body: dict | None,
    consumer_key: str,
    transport: httpx.BaseTransport | None,
):
    query = urlencode(sorted(query_params.items()))
    signature = _sign(consumer_key, path, query, body)
    headers = {"Signature": signature}
    content = None
    if body is not None:
        # The signed canonical bytes ARE the wire bytes — no re-serialization
        # that could reorder keys out from under the signature.
        content = _canonical_json(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    url = f"{_BASE_URL}{path}?{query}"
    with _silenced_library_loggers(), httpx.Client(transport=transport) as client:
        try:
            response = client.request(method, url, content=content, headers=headers)
        except httpx.HTTPError:
            # Never re-emit a transport error's own text (it can carry the
            # full request URL, whose query holds userSecret); `from None`
            # keeps the original out of the rendered exception chain.
            raise SnapTradeRequestError(
                f"SnapTrade request failed for {path}: transport error"
            ) from None
    if not (200 <= response.status_code < 300):
        raise SnapTradeRequestError(
            f"SnapTrade request failed for {path}: HTTP {response.status_code}"
        )
    try:
        return response.json()
    except ValueError:
        raise SnapTradeRequestError(
            f"SnapTrade response for {path} was not valid JSON"
        ) from None


def register_user(
    client_id: str,
    consumer_key: str,
    user_id: str,
    transport: httpx.BaseTransport | None = None,
) -> str:
    """POST /api/v1/snapTrade/registerUser; returns the new userSecret.
    Body carries userId; only clientId + timestamp travel in the query."""
    payload = _signed_request(
        "POST",
        "/api/v1/snapTrade/registerUser",
        {"clientId": client_id, "timestamp": _timestamp()},
        {"userId": user_id},
        consumer_key,
        transport,
    )
    secret = payload.get("userSecret") if isinstance(payload, dict) else None
    if not isinstance(secret, str) or not secret:
        raise SnapTradeRequestError("SnapTrade registerUser response had no userSecret field")
    return secret


def login_url(
    client_id: str,
    consumer_key: str,
    user_id: str,
    user_secret: str,
    connection_type: str = "read",
    transport: httpx.BaseTransport | None = None,
) -> str:
    """POST /api/v1/snapTrade/login; returns the hosted Connection Portal
    URL. connectionType defaults to "read" — this module's whole posture."""
    payload = _signed_request(
        "POST",
        "/api/v1/snapTrade/login",
        {
            "clientId": client_id,
            "timestamp": _timestamp(),
            "userId": user_id,
            "userSecret": user_secret,
        },
        {"connectionType": connection_type},
        consumer_key,
        transport,
    )
    portal = payload.get("redirectURI") if isinstance(payload, dict) else None
    if not isinstance(portal, str) or not portal:
        raise SnapTradeRequestError("SnapTrade login response had no redirectURI field")
    return portal


def _symbol_node(raw_symbol):
    """Descend SnapTrade's nested symbol wrappers (position.symbol.symbol is
    the universal symbol object) down to the innermost dict."""
    node = raw_symbol
    while isinstance(node, dict) and isinstance(node.get("symbol"), dict):
        node = node["symbol"]
    return node


def _normalize_position(raw: dict) -> dict | None:
    """One SnapTrade position -> {symbol, quantity, market_value, currency,
    kind}; rows without a symbol string are dropped (nothing to join on)."""
    node = _symbol_node(raw.get("symbol"))
    if isinstance(node, dict):
        symbol = node.get("symbol")
        currency = node.get("currency")
        currency_code = currency.get("code") if isinstance(currency, dict) else currency
        type_info = node.get("type")
        kind = None
        if isinstance(type_info, dict):
            kind = type_info.get("description") or type_info.get("code")
    else:
        symbol, currency_code, kind = node, None, None
    if not isinstance(symbol, str) or not symbol:
        return None
    units = raw.get("units")
    if units is None:
        units = raw.get("fractional_units")
    quantity = float(units) if isinstance(units, (int, float)) else None
    market_value = raw.get("market_value")
    if market_value is None and quantity is not None and isinstance(raw.get("price"), (int, float)):
        market_value = quantity * float(raw["price"])
    return {
        "symbol": symbol,
        "quantity": quantity,
        "market_value": float(market_value) if isinstance(market_value, (int, float)) else None,
        "currency": currency_code,
        "kind": kind,
    }


def holdings(
    client_id: str,
    consumer_key: str,
    user_id: str,
    user_secret: str,
    account_id: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> list[dict]:
    """Normalized positions across the connection's accounts (GET
    /api/v1/accounts, then per-account GET /api/v1/accounts/{id}/positions
    /all). Passing account_id skips the listing call and reads only that
    account. Rows: {symbol, quantity, market_value, currency, kind}."""
    base_query = {"clientId": client_id, "userId": user_id, "userSecret": user_secret}
    if account_id is not None:
        account_ids = [account_id]
    else:
        listing = _signed_request(
            "GET",
            "/api/v1/accounts",
            {**base_query, "timestamp": _timestamp()},
            None,
            consumer_key,
            transport,
        )
        accounts = listing if isinstance(listing, list) else []
        account_ids = [a["id"] for a in accounts if isinstance(a, dict) and a.get("id")]
    rows: list[dict] = []
    for acct in account_ids:
        positions = _signed_request(
            "GET",
            f"/api/v1/accounts/{acct}/positions/all",
            {**base_query, "timestamp": _timestamp()},
            None,
            consumer_key,
            transport,
        )
        for raw in positions if isinstance(positions, list) else []:
            row = _normalize_position(raw) if isinstance(raw, dict) else None
            if row is not None:
                rows.append(row)
    return rows


def cross_with_record(
    positions: list[dict],
    events_rows: list[dict],
    conduct_by_ticker: dict[str, dict],
    promised_by_ticker: dict[str, dict],
    mention_rows: list[dict],
) -> list[dict]:
    """PURE join of held positions against the record: per held symbol
    present in any registry input, {symbol, quantity, market_value,
    record: {n_events, insider_net_value, promised, n_mentions}}; a symbol
    absent from every input gets record=None. Counts and values only —
    "you hold X; the record shows Y" — nothing more (the T-033 pin)."""
    events_count: dict[str, int] = {}
    for row in events_rows:
        ticker = row.get("ticker")
        if ticker:
            events_count[ticker] = events_count.get(ticker, 0) + 1
    mentions_count: dict[str, int] = {}
    for row in mention_rows:
        ticker = row.get("ticker")
        if ticker:
            mentions_count[ticker] = mentions_count.get(ticker, 0) + 1

    out: list[dict] = []
    for position in positions:
        symbol = position.get("symbol")
        on_record = (
            symbol in events_count
            or symbol in conduct_by_ticker
            or symbol in promised_by_ticker
            or symbol in mentions_count
        )
        record = None
        if on_record:
            conduct = conduct_by_ticker.get(symbol)
            record = {
                "n_events": events_count.get(symbol, 0),
                "insider_net_value": conduct.get("net_value") if conduct else None,
                "promised": promised_by_ticker.get(symbol),
                "n_mentions": mentions_count.get(symbol, 0),
            }
        out.append({
            "symbol": symbol,
            "quantity": position.get("quantity"),
            "market_value": position.get("market_value"),
            "record": record,
        })
    return out


def state_path() -> Path:
    """Connection-state file path: ONRECORD_SNAPTRADE_STATE, defaulting to
    artifacts/snaptrade_user.json."""
    return Path(os.environ.get(STATE_ENV) or DEFAULT_STATE_PATH)


def save_connection(path: str | Path | None, user_id: str, user_secret: str) -> Path:
    """Persist the single connection's identity as JSON with 0600 perms
    (chmod runs even over a pre-existing file, so a loosened mode is always
    restored). path=None resolves via `state_path()`."""
    target = Path(path) if path is not None else state_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"user_id": user_id, "user_secret": user_secret}, indent=2)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(payload + "\n")
    os.chmod(target, 0o600)
    return target


def load_connection(path: str | Path | None = None) -> dict | None:
    """The single connection's {user_id, user_secret}, or None.

    ONRECORD_SNAPTRADE_USER + ONRECORD_SNAPTRADE_USER_SECRET win when BOTH
    are set, because the state file lives on the container's ephemeral disk
    and does not survive a redeploy. Losing it is unrecoverable: SnapTrade
    returns the userSecret exactly once, and re-registering the same userId
    fails with HTTP 400, which is what killed the connect button on
    production (2026-08-17). Env is the durable home for a
    single-connection deployment; the file remains the local-dev path.
    """
    env_user = os.environ.get(USER_ENV, "")
    env_secret = os.environ.get(USER_SECRET_ENV, "")
    if env_user.strip() and env_secret.strip():
        return {"user_id": env_user.strip(), "user_secret": env_secret.strip()}
    target = Path(path) if path is not None else state_path()
    if not target.exists():
        return None
    payload = json.loads(target.read_text(encoding="utf-8"))
    return {"user_id": payload.get("user_id"), "user_secret": payload.get("user_secret")}


def credentials_from_env() -> tuple[str, str]:
    """(client_id, consumer_key) from SNAPTRADE_CLIENT_ID +
    SNAPTRADE_CONSUMER_KEY; raises SnapTradeNotConfigured naming (never
    echoing) whatever is missing."""
    client_id = (os.environ.get(CLIENT_ID_ENV) or "").strip()
    consumer_key = (os.environ.get(CONSUMER_KEY_ENV) or "").strip()
    missing = [
        name
        for name, value in ((CLIENT_ID_ENV, client_id), (CONSUMER_KEY_ENV, consumer_key))
        if not value
    ]
    if missing:
        raise SnapTradeNotConfigured(
            f"missing environment variable(s): {', '.join(missing)}"
        )
    return client_id, consumer_key

"""Take Action — evidence-backed constituent letters over the Lob rail
(T-064, module layer).

Receipts in, one reviewed letter out: `draft_letter` prompts an INJECTED
generator with the selected receipts, then validates the draft AFTER
generation the way the Promise Ledger validates output — every inline
citation `"<span>" [doc_id]` must quote a VERBATIM substring of that
receipt's quote, and a citation-free draft is treated as a refusal.
`render_letter_html` turns a validated draft into the deterministic HTML
Lob prints; `verify_address`/`send_letter`/`cancel_letter` are the whole
Lob surface.

Pins frozen by tests/unit/act/test_letters.py:
- Grounded drafting: paraphrased or phantom citations raise
  DraftValidationError listing every violation; zero receipts or zero
  citations refuse outright. body_text always ends with the EXACT footer
  "Prepared and mailed via OnRecord at the request of {sender_name}, a
  resident of {jurisdiction}." (Lob AUP no-false-origin clause — the
  sender is always the user).
- Consent: `send_letter` takes confirmed=False by default and raises
  ConsentRequired before any transport I/O; no other send-shaped callable
  exists in this module (grep gate), so there is no batch/auto path.
- TEST-MODE PIN: a key that does not start with "test_" raises
  LiveSendNotEnabled unless ONRECORD_LOB_LIVE == "1" — also before any
  transport I/O, and the key value never appears in the exception.
- The letter POST body carries use_type="operational" and NEVER a
  scheduling field (grep gate over this source), so Lob's cancellation
  window stays open after every send.
- Secret discipline (T-014, the onrecord/act/portfolio.py posture): the
  Lob key travels only in the Basic auth header (key as username, empty
  password); httpx/httpcore loggers are silenced for the duration of every
  keyed call; transport errors re-raise `from None` with generic text and
  HTTP failures report status + path only — never response text, never
  the key.
- `consent_record` freezes the consent shape: sha256 of the exact letter
  HTML bytes + sender name + timestamp_field_name="confirmed_at" (the
  caller stamps the timestamp when the user confirms).
- `load_board_table` validates data/jurisdiction_boards.json rows
  ({jurisdiction, board_name, source, address:{line1, city, state, zip}})
  and NAMES every bad row in the BoardTableError it raises.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import logging
import os
import re
from collections.abc import Callable
from html import escape
from pathlib import Path

import httpx

__all__ = [
    "BoardTableError",
    "ConsentRequired",
    "DraftValidationError",
    "LIVE_ENV",
    "LiveSendNotEnabled",
    "LobRequestError",
    "cancel_letter",
    "consent_record",
    "draft_letter",
    "load_board_table",
    "render_letter_html",
    "send_letter",
    "verify_address",
]

_BASE_URL = "https://api.lob.com"

LIVE_ENV = "ONRECORD_LOB_LIVE"
TEST_KEY_PREFIX = "test_"

FOOTER_TEMPLATE = (
    "Prepared and mailed via OnRecord at the request of {sender_name}, "
    "a resident of {jurisdiction}."
)

DEFAULT_BOARDS_PATH = Path(__file__).resolve().parents[2] / "data" / "jurisdiction_boards.json"

_LIBRARY_LOGGER_NAMES = ("httpx", "httpcore")

_CITATION_RE = re.compile(r'"([^"]*)"\s*\[([^\][]+)\]')


class DraftValidationError(Exception):
    """A generated draft failed post-generation validation: a quoted span
    is not verbatim in its receipt, a citation names no selected receipt,
    or the draft cites nothing at all (the refusal path)."""


class ConsentRequired(Exception):
    """`send_letter` was called without confirmed=True. Nothing was sent;
    the user must explicitly confirm the exact rendered letter first."""


class LiveSendNotEnabled(Exception):
    """A non-test Lob key was refused because ONRECORD_LOB_LIVE != "1".
    Messages name the env flag, never the key."""


class LobRequestError(Exception):
    """A Lob call failed. Messages carry status + path only — never the
    key, never response text (a server echo could hold anything)."""


class BoardTableError(Exception):
    """The jurisdiction board table is malformed. Messages name every bad
    row so the curation pass knows exactly what to fix."""


# ---------------------------------------------------------------------------
# Drafting — grounded generation with post-generation verbatim validation
# ---------------------------------------------------------------------------


def _build_prompt(
    receipts: list[dict], sender: dict, jurisdiction: str, board: dict
) -> str:
    lines = [
        "Draft a constituent letter to a local public body, grounded ONLY in the",
        "receipts below. Cite evidence inline as \"<excerpt>\" [doc_id], where every",
        "quoted excerpt is copied verbatim (character for character) from that",
        "receipt's quote — never paraphrase inside quotation marks.",
        "If the receipts do not support the letter's point, refuse plainly and cite",
        "nothing.",
        f"Sender: {sender['name']}, a resident of {jurisdiction}.",
        f"Recipient: {board['board_name']}.",
        "Receipts:",
    ]
    for receipt in receipts:
        lines.append(f"- doc_id: {receipt['doc_id']} (date {receipt['date']})")
        lines.append(f"  quote: {receipt['quote']}")
        lines.append(f"  deep_link: {receipt['deep_link']}")
    return "\n".join(lines)


def draft_letter(
    receipts: list[dict],
    sender: dict,
    jurisdiction: str,
    board: dict,
    generator_fn: Callable[[str], str],
) -> dict:
    """Generate and validate one letter draft. Returns {body_text,
    citations: [{doc_id, deep_link}]} (citations unique, first-appearance
    order); body_text ends with the exact OnRecord footer. Raises
    DraftValidationError on any grounding violation or on the refusal
    path (no receipts selected / no citations produced)."""
    if not receipts:
        raise DraftValidationError(
            "no receipts selected — refusing to draft an evidence-free letter"
        )
    by_id = {receipt["doc_id"]: receipt for receipt in receipts}
    draft = generator_fn(_build_prompt(receipts, sender, jurisdiction, board))

    violations: list[str] = []
    citations: list[dict] = []
    cited_ids: set[str] = set()
    for span, doc_id in _CITATION_RE.findall(draft):
        receipt = by_id.get(doc_id)
        if receipt is None:
            violations.append(f"citation [{doc_id}] names no selected receipt")
            continue
        if not span.strip():
            violations.append(f"empty quoted span cited against [{doc_id}]")
            continue
        if span not in receipt["quote"]:
            violations.append(
                f'quoted span "{span}" is not a verbatim substring of receipt [{doc_id}]'
            )
            continue
        if doc_id not in cited_ids:
            cited_ids.add(doc_id)
            citations.append({"doc_id": doc_id, "deep_link": receipt["deep_link"]})
    if violations:
        raise DraftValidationError("draft failed verbatim validation: " + "; ".join(violations))
    if not citations:
        raise DraftValidationError(
            "draft contains no receipt citation — treating it as a refusal, nothing to mail"
        )
    footer = FOOTER_TEMPLATE.format(sender_name=sender["name"], jurisdiction=jurisdiction)
    return {"body_text": draft.strip() + "\n\n" + footer, "citations": citations}


# ---------------------------------------------------------------------------
# Rendering — deterministic HTML for Lob's file field
# ---------------------------------------------------------------------------


def _short_link(url: str) -> str:
    """Deep links are printed on paper: strip the scheme for display."""
    for prefix in ("https://", "http://"):
        if url.startswith(prefix):
            return url[len(prefix):]
    return url


def _postal_lines(name: str, address: dict) -> list[str]:
    lines = [name, address["line1"]]
    if address.get("line2"):
        lines.append(address["line2"])
    lines.append(f"{address['city']}, {address['state']} {address['zip']}")
    return lines


def render_letter_html(draft: dict, sender: dict, board: dict) -> str:
    """Deterministic letter HTML (no clock, no randomness): sender block,
    recipient block, escaped body paragraphs (the footer is the last body
    paragraph, verbatim), then a "Sources" appendix printing every
    citation's short deep link."""
    sender_address = {key: sender.get(key) for key in ("line1", "line2", "city", "state", "zip")}
    sender_block = "<br>\n      ".join(
        escape(line) for line in _postal_lines(sender["name"], sender_address)
    )
    recipient_block = "<br>\n      ".join(
        escape(line) for line in _postal_lines(board["board_name"], board["address"])
    )
    paragraphs = [part.strip() for part in draft["body_text"].split("\n\n")]
    body_html = "\n".join(f"      <p>{escape(p)}</p>" for p in paragraphs if p)
    sources_html = "\n".join(
        "        <li>{doc} &mdash; {link}</li>".format(
            doc=escape(citation["doc_id"]), link=escape(_short_link(citation["deep_link"]))
        )
        for citation in draft["citations"]
    )
    return f"""<html>
  <head>
    <meta charset="utf-8">
    <style>
      body {{ font-family: Georgia, 'Times New Roman', serif; font-size: 12pt;
              color: #111; margin: 0.75in; }}
      .sender {{ margin-bottom: 24pt; }}
      .recipient {{ margin-bottom: 24pt; }}
      .body p {{ line-height: 1.45; margin: 0 0 12pt 0; }}
      .sources {{ margin-top: 24pt; border-top: 1px solid #111; padding-top: 8pt; }}
      .sources h2 {{ font-size: 11pt; margin: 0 0 6pt 0; }}
      .sources ol {{ margin: 0; padding-left: 18pt; font-size: 10pt; }}
    </style>
  </head>
  <body>
    <div class="sender">
      {sender_block}
    </div>
    <div class="recipient">
      {recipient_block}
    </div>
    <div class="body">
{body_html}
    </div>
    <div class="sources">
      <h2>Sources</h2>
      <ol>
{sources_html}
      </ol>
    </div>
  </body>
</html>
"""


# ---------------------------------------------------------------------------
# Lob client — hermetic, Basic-auth, secret-disciplined
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _silenced_library_loggers():
    """Silence httpx/httpcore loggers for the duration of a keyed request
    (LESSONS T-014, the `onrecord/rag/embeddings.py` mechanism: a
    secret-leak check must cover library loggers, not just this module's
    own). `Logger.disabled = True` makes `isEnabledFor` return False
    unconditionally, so no log record is ever created while active."""
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


def _auth_header(key: str) -> str:
    token = base64.b64encode(f"{key}:".encode()).decode("ascii")
    return f"Basic {token}"


def _request(
    method: str,
    path: str,
    key: str,
    body: dict | None,
    transport: httpx.BaseTransport | None,
):
    headers = {"Authorization": _auth_header(key)}
    content = None
    if body is not None:
        content = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
        headers["Content-Type"] = "application/json"
    with _silenced_library_loggers(), httpx.Client(transport=transport) as client:
        try:
            response = client.request(method, f"{_BASE_URL}{path}", content=content,
                                      headers=headers)
        except httpx.HTTPError:
            # Never re-emit a transport error's own text (it can carry
            # request details); `from None` keeps the original out of the
            # rendered exception chain.
            raise LobRequestError(f"Lob request failed for {path}: transport error") from None
    if not (200 <= response.status_code < 300):
        raise LobRequestError(f"Lob request failed for {path}: HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError:
        raise LobRequestError(f"Lob response for {path} was not valid JSON") from None


def _lob_address(address: dict) -> dict:
    """{name, line1[, line2], city, state, zip} -> Lob's inline address."""
    lob = {
        "name": address["name"],
        "address_line1": address["line1"],
        "address_city": address["city"],
        "address_state": address["state"],
        "address_zip": address["zip"],
    }
    if address.get("line2"):
        lob["address_line2"] = address["line2"]
    return lob


def verify_address(
    key: str, address: dict, transport: httpx.BaseTransport | None = None
) -> dict:
    """POST /v1/us_verifications for {line1[, line2], city, state, zip};
    returns Lob's verification payload (deliverability et al.)."""
    body = {
        "primary_line": address["line1"],
        "city": address["city"],
        "state": address["state"],
        "zip_code": address["zip"],
    }
    if address.get("line2"):
        body["secondary_line"] = address["line2"]
    return _request("POST", "/v1/us_verifications", key, body, transport)


def send_letter(
    key: str,
    from_addr: dict,
    to_addr: dict,
    html: str,
    transport: httpx.BaseTransport | None = None,
    confirmed: bool = False,
) -> dict:
    """POST /v1/letters — the module's ONLY send path. Refuses before any
    transport I/O unless (a) the user explicitly confirmed the exact
    letter (confirmed=True) and (b) the key is a test_ key or
    ONRECORD_LOB_LIVE is "1". The body never schedules delivery, so Lob's
    cancellation window stays open."""
    if not confirmed:
        raise ConsentRequired(
            "send_letter refused: confirmed=True is required — the user must "
            "explicitly confirm the exact rendered letter"
        )
    if not key.startswith(TEST_KEY_PREFIX) and os.environ.get(LIVE_ENV) != "1":
        raise LiveSendNotEnabled(
            f"live Lob key refused: set {LIVE_ENV}=1 to allow real mail "
            "(test_ keys need no flag)"
        )
    body = {
        "to": _lob_address(to_addr),
        "from": _lob_address(from_addr),
        "file": html,
        "use_type": "operational",
    }
    return _request("POST", "/v1/letters", key, body, transport)


def cancel_letter(
    key: str, letter_id: str, transport: httpx.BaseTransport | None = None
) -> dict:
    """DELETE /v1/letters/{id} — the undo banner's rail, valid inside
    Lob's cancellation window."""
    return _request("DELETE", f"/v1/letters/{letter_id}", key, None, transport)


# ---------------------------------------------------------------------------
# Consent record — frozen shape, exact-bytes hash
# ---------------------------------------------------------------------------


def consent_record(letter_html: str, sender_name: str) -> dict:
    """The consent log entry for one confirmed letter: sha256 of the EXACT
    HTML the user reviewed, who asked for it, and the name of the
    timestamp field the caller stamps at confirmation time."""
    return {
        "sha256": hashlib.sha256(letter_html.encode("utf-8")).hexdigest(),
        "sender_name": sender_name,
        "timestamp_field_name": "confirmed_at",
    }


# ---------------------------------------------------------------------------
# Jurisdiction board table — validated loader
# ---------------------------------------------------------------------------

_ROW_FIELDS = ("jurisdiction", "board_name", "source")
_ADDRESS_FIELDS = ("line1", "city", "state", "zip")


def _row_problems(index: int, row) -> list[str]:
    if not isinstance(row, dict):
        return [f"row {index}: not an object"]
    jurisdiction = row.get("jurisdiction")
    label = jurisdiction if isinstance(jurisdiction, str) and jurisdiction else f"row {index}"
    problems = [
        f"{label}: missing or empty {field}"
        for field in _ROW_FIELDS
        if not (isinstance(row.get(field), str) and row.get(field))
    ]
    address = row.get("address")
    if not isinstance(address, dict):
        problems.append(f"{label}: missing address")
    else:
        problems.extend(
            f"{label}: missing or empty address.{field}"
            for field in _ADDRESS_FIELDS
            if not (isinstance(address.get(field), str) and address.get(field))
        )
    return problems


def load_board_table(path: str | Path | None = None) -> list[dict]:
    """Load and validate the jurisdiction board table (default:
    data/jurisdiction_boards.json, repo-anchored). Every row must carry
    {jurisdiction, board_name, source, address:{line1, city, state, zip}}
    as non-empty strings; a BoardTableError names every bad row."""
    target = Path(path) if path is not None else DEFAULT_BOARDS_PATH
    rows = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise BoardTableError(f"board table {target.name} must be a JSON list of rows")
    problems = [problem for index, row in enumerate(rows) for problem in _row_problems(index, row)]
    if problems:
        raise BoardTableError("invalid board rows — " + "; ".join(problems))
    return rows

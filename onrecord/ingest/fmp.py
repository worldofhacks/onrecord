"""FMP earnings-call transcripts adapter (T-008).

Financial Modeling Prep `earning_call_transcript` endpoint -> speaker-turn
Docs. Owner timebox: best-effort. No API key / free-tier blocked -> live
fetch simply logs and returns `[]` (EDGAR 8-K exhibits already cover call
content); `parse_transcript` is pure and fully fixture-tested regardless of
live access.

See `.tdd-swarm/reports/T-008-test.md` and the docstring of
`tests/unit/ingest/test_fmp.py` for the authoritative contract.
"""

from __future__ import annotations

import logging
import os
import re
import time

import httpx

from onrecord.types import Doc

logger = logging.getLogger(__name__)

_BASE_URL = "https://financialmodelingprep.com/api/v3/earning_call_transcript"

# A single "word" of a plausible speaker name: starts with an uppercase
# letter, may contain internal apostrophes/hyphens (e.g. "O'Brien",
# "Jean-Pierre"). Used to reject continuation lines that merely happen to
# contain ": " (e.g. "Turning to guidance: ...") from being mistaken for a
# new speaker turn.
_NAME_WORD_RE = re.compile(r"^[A-Z][A-Za-z'’\-]*$")


def _looks_like_speaker_name(prefix: str) -> bool:
    """True if `prefix` (text before ": ") plausibly looks like a speaker name.

    Heuristic: 1-5 whitespace-separated words, every word title-cased.
    """
    words = prefix.split()
    if not (1 <= len(words) <= 5):
        return False
    return all(_NAME_WORD_RE.match(word) for word in words)


def _deep_link(ticker: str, year: int, quarter: int) -> str:
    """FMP-cited URL for this transcript (falls back to the ticker's IR-style page)."""
    return f"{_BASE_URL}/{ticker}?quarter={quarter}&year={year}"


def parse_transcript(payload: dict, ticker: str) -> list[Doc]:
    """Pure parse of one FMP transcript payload into speaker-turn Docs.

    No I/O. See module docstring / test contract for exact behavior.
    """
    content: str = payload["content"]
    quarter: int = payload["quarter"]
    year: int = payload["year"]
    date = str(payload["date"]).strip()[:10]

    deep_link = _deep_link(ticker, year, quarter)

    # Raw turns: split on newlines, match a leading "Speaker: text" marker
    # whose prefix looks like a plausible name. A line that contains ": "
    # but whose prefix fails the name heuristic (e.g. "Turning to
    # guidance: ...") is continuation text: it merges into the immediately
    # preceding raw turn (whole line, verbatim) rather than becoming its
    # own bogus-speaker Doc.
    raw_turns: list[tuple[str | None, str]] = []
    for raw_line in content.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        name, sep, rest = line.partition(": ")
        if sep and name and _looks_like_speaker_name(name):
            raw_turns.append((name, rest))
        elif raw_turns:
            prev_speaker, prev_text = raw_turns[-1]
            raw_turns[-1] = (prev_speaker, f"{prev_text} {line}")
        else:
            raw_turns.append((None, line))

    # No recognizable speaker markers anywhere -> one whole-transcript Doc.
    if not any(speaker is not None for speaker, _ in raw_turns):
        whole = content.strip()
        return [
            Doc(
                id=f"fmp:{ticker}:{year}q{quarter}:turn001",
                text=whole,
                source_type="earnings_call",
                venue_type="coached",
                date=date,
                deep_link=deep_link,
                ticker=ticker,
                jurisdiction=None,
                speaker=None,
            )
        ]

    # Merge consecutive same-speaker turns.
    merged: list[tuple[str | None, list[str]]] = []
    for speaker, text in raw_turns:
        if merged and merged[-1][0] == speaker:
            merged[-1][1].append(text)
        else:
            merged.append((speaker, [text]))

    docs: list[Doc] = []
    for i, (speaker, texts) in enumerate(merged, start=1):
        docs.append(
            Doc(
                id=f"fmp:{ticker}:{year}q{quarter}:turn{i:03d}",
                text=" ".join(texts),
                source_type="earnings_call",
                venue_type="coached",
                date=date,
                deep_link=deep_link,
                ticker=ticker,
                jurisdiction=None,
                speaker=speaker,
            )
        )
    return docs


def _fetch_one_quarter(
    client: httpx.Client, ticker: str, year: int, quarter: int, api_key: str
) -> list[Doc]:
    """Fetch and parse a single (year, quarter); retry once on 429; [] on give-up."""
    url = f"{_BASE_URL}/{ticker}"
    params = {"quarter": quarter, "year": year, "apikey": api_key}

    for attempt in range(2):  # initial attempt + exactly one retry (429 only)
        response = client.get(url, params=params)

        if response.status_code == 429:
            if attempt == 0:
                time.sleep(1.0)
                continue
            logger.info(
                "FMP transcript fetch for %s %dQ%d hit 429 twice; skipping this quarter",
                ticker,
                year,
                quarter,
            )
            return []

        if response.status_code >= 400:
            # Deliberately never call response.raise_for_status() here: its
            # HTTPStatusError.__str__ embeds the full request URL, including
            # the apikey query param, in plaintext. Log only ticker/year/
            # quarter/status code — never the URL, params, or response body
            # — and skip this quarter without retrying (retry is 429-only).
            logger.info(
                "FMP transcript fetch for %s %dQ%d failed with HTTP %d; skipping this quarter",
                ticker,
                year,
                quarter,
                response.status_code,
            )
            return []

        body = response.json()
        if not body:
            return []
        return parse_transcript(body[0], ticker)

    return []  # pragma: no cover - loop always returns above


def fetch_transcripts(
    ticker: str,
    quarters: list[tuple[int, int]],
    api_key: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> list[Doc]:
    """Fetch earnings-call transcripts for `ticker` over `quarters` via FMP.

    `quarters` is a list of (year, quarter) tuples, processed in order.
    See module docstring / test contract for the no-key and 429 behaviors.
    """
    effective_key = api_key if api_key else os.environ.get("FMP_API_KEY")
    if not effective_key or not str(effective_key).strip():
        logger.info(
            "FMP_API_KEY not set (and no api_key provided) — skipping live FMP "
            "transcript fetch for %s; EDGAR 8-K exhibits remain the fallback source",
            ticker,
        )
        return []

    docs: list[Doc] = []
    with httpx.Client(transport=transport) as client:
        for year, quarter in quarters:
            docs.extend(_fetch_one_quarter(client, ticker, year, quarter, effective_key))
    return docs

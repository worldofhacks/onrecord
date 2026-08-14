"""Quantified promises — T-056.

Deterministic quantity extraction over verbatim promise quotes. The input
is already an exact substring of a source document (T-040's verbatim pin),
and every extraction's `raw_span` is an exact substring of the quote — so
spans inherit the receipt chain end to end (AC-1, frozen tests).

Precision over recall, deliberately: a number extracts only when a unit
keyword anchors it (AC-2's false-positive corpus is the contract — vote
tallies, ordinance numbers, clock times, addresses, years must never fire).
Spelled-out numbers use a small closed lexicon (units, teens, tens, and
million/billion multipliers); anything fancier stays unextracted.
"""

from __future__ import annotations

import re

__all__ = ["extract_quantities", "aggregate_quantities"]

# Digits: 1,234,567.89 or plain 400 / 2.5
_DIGITS = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"

_SPELLED: dict[str, float] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
}
_SPELLED_ALT = "|".join(_SPELLED)

_MULTIPLIERS = {"million": 1e6, "billion": 1e9}

# A number: digits or one spelled word, with an optional million/billion.
_NUMBER = rf"(?:{_DIGITS}|(?:{_SPELLED_ALT}))(?:\s+(?:million|billion))?"

_POWER_SCALE = {"mw": 1.0, "megawatt": 1.0, "megawatts": 1.0,
                "gw": 1000.0, "gigawatt": 1000.0, "gigawatts": 1000.0,
                "kw": 0.001, "kilowatt": 0.001, "kilowatts": 0.001}

_POWER_RE = re.compile(
    rf"\b({_NUMBER})\s*(MW|GW|kW|megawatts?|gigawatts?|kilowatts?)\b",
    re.IGNORECASE,
)
_WATER_RATE_RE = re.compile(
    rf"\b({_NUMBER})\s*gallons?\s+(?:per|a)\s+day\b", re.IGNORECASE
)
_WATER_TOTAL_RE = re.compile(
    rf"\b({_NUMBER})\s*gallons?\b(?!\s+(?:per|a)\s+day)", re.IGNORECASE
)
# Up to two plain word tokens (no digits) may sit between the number and
# the jobs keyword: "300 permanent jobs", "45 full-time positions".
_JOBS_RE = re.compile(
    rf"\b({_NUMBER})\s+((?:[A-Za-z][\w-]*\s+){{0,2}}?)(jobs|positions|employees)\b",
    re.IGNORECASE,
)
_MONEY_SIGN_RE = re.compile(
    rf"\$\s?({_DIGITS}|(?:{_SPELLED_ALT}))(?:\s+(million|billion))?\b",
    re.IGNORECASE,
)
_MONEY_WORD_RE = re.compile(
    rf"\b({_DIGITS}|(?:{_SPELLED_ALT}))\s+(million|billion)\s+dollars\b",
    re.IGNORECASE,
)
_ANNUAL_RE = re.compile(r"\bannual(?:ly)?\b|\bper\s+year\b|\ba\s+year\b", re.IGNORECASE)

_ANNUAL_WINDOW = 60  # chars each side of a money match scanned for cadence


def _parse_number(text: str) -> float:
    parts = text.lower().split()
    multiplier = 1.0
    if parts and parts[-1] in _MULTIPLIERS:
        multiplier = _MULTIPLIERS[parts[-1]]
        parts = parts[:-1]
    core = " ".join(parts)
    if core in _SPELLED:
        return _SPELLED[core] * multiplier
    return float(core.replace(",", "")) * multiplier


def _cadence(quote: str, start: int, end: int) -> str:
    window = quote[max(0, start - _ANNUAL_WINDOW): end + _ANNUAL_WINDOW]
    return "annual" if _ANNUAL_RE.search(window) else "total"


def extract_quantities(quote: str) -> list[dict]:
    """All anchored quantities in `quote`, each with a verbatim `raw_span`.

    Row shape: {kind, value, unit?, cadence?, raw_span} — see frozen tests
    for the exact per-kind fields.
    """
    out: list[dict] = []
    claimed: list[tuple[int, int]] = []

    def _claim(start: int, end: int) -> bool:
        for s, e in claimed:
            if start < e and end > s:
                return False
        claimed.append((start, end))
        return True

    for match in _MONEY_SIGN_RE.finditer(quote):
        if not _claim(*match.span()):
            continue
        value = _parse_number(match.group(1))
        if match.group(2):
            value *= _MULTIPLIERS[match.group(2).lower()]
        out.append({"kind": "money", "value": value,
                    "cadence": _cadence(quote, *match.span()),
                    "raw_span": match.group(0)})
    for match in _MONEY_WORD_RE.finditer(quote):
        if not _claim(*match.span()):
            continue
        value = _parse_number(match.group(1)) * _MULTIPLIERS[match.group(2).lower()]
        out.append({"kind": "money", "value": value,
                    "cadence": _cadence(quote, *match.span()),
                    "raw_span": match.group(0)})

    for match in _POWER_RE.finditer(quote):
        if not _claim(*match.span()):
            continue
        scale = _POWER_SCALE[match.group(2).lower()]
        out.append({"kind": "power", "value": _parse_number(match.group(1)) * scale,
                    "unit": "MW", "raw_span": match.group(0)})

    for match in _WATER_RATE_RE.finditer(quote):
        if not _claim(*match.span()):
            continue
        out.append({"kind": "water", "value": _parse_number(match.group(1)),
                    "unit": "GPD", "raw_span": match.group(0)})
    for match in _WATER_TOTAL_RE.finditer(quote):
        if not _claim(*match.span()):
            continue
        out.append({"kind": "water", "value": _parse_number(match.group(1)),
                    "unit": "GAL", "raw_span": match.group(0)})

    for match in _JOBS_RE.finditer(quote):
        if not _claim(*match.span()):
            continue
        out.append({"kind": "jobs", "value": _parse_number(match.group(1)),
                    "raw_span": match.group(0)})

    out.sort(key=lambda e: quote.index(e["raw_span"]))
    return out


_AGG_ZERO = {
    "promised_mw": 0.0,
    "promised_gpd": 0.0,
    "promised_jobs": 0.0,
    "promised_dollars_annual": 0.0,
    "promised_dollars_total": 0.0,
    "n_quantified": 0,
}


def aggregate_quantities(rows: list[dict], by: str) -> dict[str, dict]:
    """Rollups keyed by `jurisdiction` or `ticker`; rows whose key is None
    are skipped; rows with no quantities still appear (n_quantified 0)."""
    if by not in ("jurisdiction", "ticker"):
        raise ValueError(f"aggregate_quantities: by must be jurisdiction|ticker, got {by!r}")
    agg: dict[str, dict] = {}
    for row in rows:
        key = row.get(by)
        if key is None:
            continue
        bucket = agg.setdefault(key, dict(_AGG_ZERO))
        quantities = row.get("quantities") or []
        if quantities:
            bucket["n_quantified"] += 1
        for q in quantities:
            kind = q.get("kind")
            value = float(q.get("value", 0.0))
            if kind == "power":
                bucket["promised_mw"] += value
            elif kind == "water" and q.get("unit") == "GPD":
                bucket["promised_gpd"] += value
            elif kind == "jobs":
                bucket["promised_jobs"] += value
            elif kind == "money":
                if q.get("cadence") == "annual":
                    bucket["promised_dollars_annual"] += value
                else:
                    bucket["promised_dollars_total"] += value
    return agg

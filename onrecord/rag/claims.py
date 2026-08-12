"""Claim segmentation authority -- the single place `split_claims` lives.

`onrecord.rag.claims.split_claims` is shared by TWO consumers: T-023's
grounding arithmetic (`grounding.supported_claims` / `total_claims`) and
T-026's faithfulness judge (per-claim verdicts). Sharing this module is what
makes both features count the SAME claims for the SAME text (locked
consistency decision, tickets/T-027.md) -- T-023 and T-026 import
`split_claims` from here and MUST NOT reimplement segmentation themselves.

Contract (tickets/T-027.md):
- Split on `.` `!` `?` (ASCII) when the terminator is followed by whitespace
  or end-of-string -- this whitespace-or-EOS guard is what lets abbreviations
  and decimal numbers survive unsplit.
- Split on `。` `！` `？` (CJK/full-width) UNCONDITIONALLY, i.e. with no
  whitespace-or-EOS guard: real Japanese/Chinese prose is not spaced after
  its terminators, and full-width terminators never occur inside decimals or
  the fixed abbreviation list the way ASCII `.` does, so they carry none of
  the ambiguity the ASCII guard exists to resolve (orchestrator ruling,
  locked).
- `[n]` citation marker chains (one or more, spaced or not) immediately
  following a terminator -- including at the very end of the input -- stay
  attached to the sentence they follow; they never orphan into the next
  claim or form a claim of their own.
- A period is NOT a split point when it closes one of the fixed
  `ABBREVIATIONS` entries (a whole-word match, e.g. "Inc." does not match
  inside "Vinci."). The list is a module constant: additions are a contract
  change, not a drive-by edit.
- Terminators stay attached to the sentence they end. Each returned claim is
  whitespace-trimmed and never empty. Text with no terminator yields exactly
  one claim (the whole trimmed text). Empty/whitespace-only input yields `[]`.
"""

from __future__ import annotations

import re

# Fixed abbreviation list (tickets/T-027.md Context, AC-2). A period closing
# one of these does not split -- checked as a whole-word match (not preceded
# by an alnum char) so e.g. "Vinci." does not falsely match "Inc.".
ABBREVIATIONS: tuple[str, ...] = ("Inc.", "No.", "U.S.", "Corp.", "Co.")

# ASCII terminators only end a sentence when followed by whitespace or
# end-of-string (protects abbreviations and decimals, e.g. "240.5"). CJK
# terminators end a sentence unconditionally -- no such guard.
_TERMINATOR_RE = re.compile(r"(?P<ascii>[.!?])(?=\s|\Z)|(?P<cjk>[。！？])")

# Absorb zero or more `[n]` markers (each optionally preceded by whitespace)
# immediately following a terminator, so they stay attached to their claim.
_MARKER_CHAIN_RE = re.compile(r"(?:\s*\[\d+\])*")


def _ends_with_abbreviation(text: str, end: int) -> bool:
    """True if `text[:end]` ends with a whole-word entry from ABBREVIATIONS."""
    for abbr in ABBREVIATIONS:
        start = end - len(abbr)
        if start < 0 or text[start:end] != abbr:
            continue
        if start == 0 or not text[start - 1].isalnum():
            return True
    return False


def split_claims(text: str) -> list[str]:
    """Segment `text` into claims (sentences, with attached citations).

    See module docstring for the full segmentation contract.
    """
    if not text or not text.strip():
        return []

    claims: list[str] = []
    start = 0
    pos = 0
    length = len(text)

    while pos < length:
        match = _TERMINATOR_RE.search(text, pos)
        if match is None:
            break

        if match.group("cjk") is None and _ends_with_abbreviation(text, match.end()):
            pos = match.end()
            continue

        claim_end = _MARKER_CHAIN_RE.match(text, match.end()).end()
        claim = text[start:claim_end].strip()
        if claim:
            claims.append(claim)
        start = claim_end
        pos = claim_end

    tail = text[start:].strip()
    if tail:
        claims.append(tail)

    return claims

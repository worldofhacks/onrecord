"""Analyzer — tokenize + normalize, one function for index AND query time.

Implements the frozen `analyze(text) -> list[str]` contract (T-001/T-002,
Spec §3): Unicode NFKC normalize -> casefold -> split on non-alphanumeric
(digits are kept fused with adjacent letters, not stripped) -> drop empty
tokens. Token i's position == list index i, so order and duplicates are
preserved exactly as encountered (no dedup, no sort).

v1 design decision (documented per DoD): NO stemming, NO stopword removal.
Stopwords are retained because phrase queries need them (e.g. "the applicant
of record"), and stemming is deferred to keep index-time and query-time
analysis identical and simple. This may change in a later ticket, but v1
intentionally does neither.
"""

from __future__ import annotations

import re
import unicodedata

_TOKEN_RE = re.compile(r"[^\W_]+", flags=re.UNICODE)


def analyze(text: str) -> list[str]:
    """Tokenize and normalize `text`; token i's position is list index i."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return _TOKEN_RE.findall(normalized)

"""Analyzer stub — implemented by T-002 (lowercase, NFKC, punctuation strip)."""

from __future__ import annotations


def analyze(text: str) -> list[str]:
    """Tokenize and normalize `text`; token i's position is list index i."""
    raise NotImplementedError

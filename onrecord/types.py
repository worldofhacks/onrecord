"""Frozen core data contracts shared by every onrecord module (T-001)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Doc:
    """A single retrieval unit (speaker turn, caption window, filing section)."""

    id: str
    text: str
    source_type: str
    venue_type: str
    date: str
    deep_link: str
    ticker: str | None = None
    jurisdiction: str | None = None
    speaker: str | None = None


@dataclass(frozen=True)
class SearchResult:
    """A single ranked hit returned by a search function."""

    doc_id: str
    score: float
    snippet: str

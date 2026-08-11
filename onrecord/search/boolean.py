"""Boolean/phrase search stubs — implemented by T-004 (AND/OR, phrase adjacency)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from onrecord.index.inverted import InvertedIndex
    from onrecord.types import SearchResult


def boolean_search(index: InvertedIndex, query: str, op: str) -> list[SearchResult]:
    """Run a boolean AND/OR query (`op` in {"AND", "OR"}) against `index`."""
    raise NotImplementedError


def phrase_search(index: InvertedIndex, phrase: str) -> list[SearchResult]:
    """Run an exact phrase query against `index` via position adjacency."""
    raise NotImplementedError

"""InvertedIndex stub — implemented by T-003 (df, tf, positions; save/load/delete).

`build()`'s `analyzer` keyword (contract extension pinned by T-003's Test Agent,
see tests/unit/test_index.py module docstring): `None` means "use the real
`onrecord.analysis.analyzer.analyze` (T-002)"; callers may inject any
`str -> list[str]` callable instead, primarily so T-003 can be tested in
isolation while T-002 is still a stub in parallel worktrees.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from onrecord.types import Doc


@dataclass(frozen=True)
class Postings:
    """Compact parallel arrays for a single term's postings list."""

    doc_ids: object  # array-like of doc ids, sorted
    tfs: object  # array-like of term frequencies, aligned with doc_ids
    positions: list  # per-doc array-like of within-doc term positions


class InvertedIndex:
    """Array-backed inverted index over a corpus of `Doc`s."""

    @classmethod
    def build(
        cls, docs: list[Doc], analyzer: Callable[[str], list[str]] | None = None
    ) -> InvertedIndex:
        """Build a fresh index from an iterable of Docs.

        `analyzer` defaults to `onrecord.analysis.analyzer.analyze` when None;
        pass an explicit `str -> list[str]` callable to inject a different
        tokenizer (used by T-003's tests to avoid depending on T-002).
        """
        raise NotImplementedError

    def df(self, term: str) -> int:
        """Document frequency of `term`."""
        raise NotImplementedError

    def postings(self, term: str) -> Postings:
        """Postings list for `term`."""
        raise NotImplementedError

    def doc_count(self) -> int:
        """Number of documents currently in the index."""
        raise NotImplementedError

    def get_doc(self, id: str) -> Doc:
        """Fetch a stored Doc by id."""
        raise NotImplementedError

    def delete(self, id: str) -> None:
        """Remove a document (and purge its postings) by id."""
        raise NotImplementedError

    def save(self, path: str | Path) -> None:
        """Serialize the index (msgpack + npy) to `path`."""
        raise NotImplementedError

    @classmethod
    def load(cls, path: str | Path) -> InvertedIndex:
        """Deserialize an index previously written by `save`."""
        raise NotImplementedError

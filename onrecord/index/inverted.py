"""InvertedIndex — array-backed postings (df, tf, positions); save/load/delete.

`build()`'s `analyzer` keyword (contract extension pinned by T-003's Test Agent,
see tests/unit/test_index.py module docstring): `None` means "use the real
`onrecord.analysis.analyzer.analyze` (T-002)"; callers may inject any
`str -> list[str]` callable instead, primarily so T-003 can be tested in
isolation while T-002 is still a stub in parallel worktrees.

Internal doc ids are assigned once at `build()` time, in the order docs
appear in the input `docs` list (docs[i] -> internal id i), and are stable
thereafter — `delete` never renumbers survivors. `Postings.doc_ids` is always
returned sorted ascending with no duplicates.

`get_doc(id)` accepts EITHER an external string id OR an internal integer id
(the same ints that appear in `postings(term).doc_ids`) — dispatch is by
Python type (`str` -> external map, `int` -> internal map), so the two id
spaces stay disjoint even when an external id happens to look numeric.
`KeyError` on an unknown id holds in both spaces. (Reconciled contract per
orchestrator adjudication of a T-003/T-004 id-space collision — see
`.tdd-swarm/LESSONS.md` and `.tdd-swarm/reports/T-003-review.md`.)

`doc_length(internal_id)` and `avg_doc_length()` are public accessors over
per-doc token counts recorded at `build()` time; both survive `save`/`load`.

`postings()` for a term absent from the corpus returns a fresh, unshared
`Postings` object on every call — never a shared mutable singleton — so a
caller mutating one absent-term result can't corrupt another lookup.

On-disk layout (`save(path)` writes a directory):
    <path>/meta.msgpack   - df, doc lengths, id<->doc_id maps, next_internal_id
    <path>/docs.msgpack   - internal_id -> Doc fields (skips tombstoned/deleted)
    <path>/postings.npy   - single npy array (int64) holding every term's
                            doc_ids + tfs + positions, concatenated; offsets
                            into this array are recorded per-term in meta.
"""

from __future__ import annotations

from array import array
from bisect import bisect_left
from pathlib import Path
from typing import TYPE_CHECKING

import msgpack
import numpy as np

if TYPE_CHECKING:
    from collections.abc import Callable

from onrecord.types import Doc


class Postings:
    """Compact parallel arrays for a single term's postings list."""

    __slots__ = ("doc_ids", "tfs", "positions")

    def __init__(self, doc_ids, tfs, positions):
        self.doc_ids = doc_ids  # array-like ('q') of internal doc ids, sorted
        self.tfs = tfs  # array-like ('q') of term frequencies, aligned with doc_ids
        self.positions = positions  # list of array-like ('q'), one per doc_id entry

    def __eq__(self, other):
        if not isinstance(other, Postings):
            return NotImplemented
        return (
            list(self.doc_ids) == list(other.doc_ids)
            and list(self.tfs) == list(other.tfs)
            and [list(p) for p in self.positions] == [list(p) for p in other.positions]
        )

    def __repr__(self):
        return (
            f"Postings(doc_ids={list(self.doc_ids)!r}, tfs={list(self.tfs)!r}, "
            f"positions={[list(p) for p in self.positions]!r})"
        )


def _empty_postings() -> Postings:
    """A fresh, unshared empty Postings — never a module-level singleton.

    Returning the same mutable object by reference for every absent-term
    lookup would let a caller's in-place mutation of one result leak into
    every other absent-term lookup (and, transitively, into real terms'
    postings via accidental aliasing bugs elsewhere). Allocating fresh
    arrays/lists per call is cheap (empty) and closes that off entirely.
    """
    return Postings(array("q"), array("q"), [])


def _analyze_positions(tokens: list[str]) -> dict[str, list[int]]:
    """Group a token list's indices by token, preserving first-seen term order."""
    out: dict[str, list[int]] = {}
    for pos, tok in enumerate(tokens):
        out.setdefault(tok, []).append(pos)
    return out


class InvertedIndex:
    """Array-backed inverted index over a corpus of `Doc`s."""

    def __init__(self):
        # term -> parallel arrays: doc_ids ('q', sorted), tfs ('q'), positions (list[array('q')])
        self._postings: dict[str, Postings] = {}
        # term -> df (kept alongside postings so a df-only lookup never needs
        # to materialize/allocate a Postings object)
        self._df: dict[str, int] = {}
        # internal id -> Doc
        self._docs: dict[int, Doc] = {}
        # external doc_id -> internal id (only live docs are present)
        self._id_to_internal: dict[str, int] = {}
        # internal id -> doc length (token count) — stored now for BM25 later
        self._doc_lengths: dict[int, int] = {}
        self._next_internal_id = 0

    # ------------------------------------------------------------------
    # build
    # ------------------------------------------------------------------

    @classmethod
    def build(
        cls, docs: list[Doc], analyzer: Callable[[str], list[str]] | None = None
    ) -> InvertedIndex:
        """Build a fresh index from an iterable of Docs.

        `analyzer` defaults to `onrecord.analysis.analyzer.analyze` when None;
        pass an explicit `str -> list[str]` callable to inject a different
        tokenizer (used by T-003's tests to avoid depending on T-002).
        """
        if analyzer is None:
            from onrecord.analysis.analyzer import analyze as analyzer

        idx = cls()
        # term -> list[(internal_id, tf, positions)], built up per doc then
        # bulk-converted to sorted arrays once at the end (docs list order ==
        # ascending internal id order already, so no sort needed per term).
        staging: dict[str, list[tuple[int, int, list[int]]]] = {}

        for internal_id, doc in enumerate(docs):
            idx._docs[internal_id] = doc
            idx._id_to_internal[doc.id] = internal_id
            tokens = analyzer(doc.text)
            idx._doc_lengths[internal_id] = len(tokens)
            for term, positions in _analyze_positions(tokens).items():
                staging.setdefault(term, []).append((internal_id, len(positions), positions))

        for term, entries in staging.items():
            doc_ids = array("q", (e[0] for e in entries))
            tfs = array("q", (e[1] for e in entries))
            positions = [array("q", e[2]) for e in entries]
            idx._postings[term] = Postings(doc_ids, tfs, positions)
            idx._df[term] = len(doc_ids)

        idx._next_internal_id = len(docs)
        return idx

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------

    def df(self, term: str) -> int:
        """Document frequency of `term`."""
        return self._df.get(term, 0)

    def postings(self, term: str) -> Postings:
        """Postings list for `term`."""
        postings = self._postings.get(term)
        return postings if postings is not None else _empty_postings()

    def doc_count(self) -> int:
        """Number of documents currently in the index."""
        return len(self._id_to_internal)

    def get_doc(self, id: str | int) -> Doc:
        """Fetch a stored Doc by external string id or internal integer id.

        Dispatch is by Python type: `str` looks up the external-id map,
        `int` looks up the internal-id map directly (the same ints returned
        in `postings(term).doc_ids`). `KeyError` on an unknown id in either
        space.
        """
        if isinstance(id, int):
            doc = self._docs.get(id)
            if doc is None:
                raise KeyError(id)
            return doc
        internal_id = self._id_to_internal.get(id)
        if internal_id is None:
            raise KeyError(id)
        return self._docs[internal_id]

    def doc_length(self, internal_id: int) -> int:
        """Token count (under the analyzer used at build time) for `internal_id`."""
        length = self._doc_lengths.get(internal_id)
        if length is None:
            raise KeyError(internal_id)
        return length

    def avg_doc_length(self) -> float:
        """Mean token count over currently-live documents (0.0 if empty)."""
        if not self._doc_lengths:
            return 0.0
        return sum(self._doc_lengths.values()) / len(self._doc_lengths)

    # ------------------------------------------------------------------
    # delete
    # ------------------------------------------------------------------

    def delete(self, id: str) -> None:
        """Remove a document (and purge its postings) by id."""
        internal_id = self._id_to_internal.get(id)
        if internal_id is None:
            raise KeyError(id)

        del self._id_to_internal[id]
        del self._docs[internal_id]
        del self._doc_lengths[internal_id]

        terms_to_drop = []
        for term, postings in self._postings.items():
            doc_ids = postings.doc_ids
            i = bisect_left(doc_ids, internal_id)
            if i < len(doc_ids) and doc_ids[i] == internal_id:
                new_doc_ids = array("q", doc_ids[:i]) + array("q", doc_ids[i + 1 :])
                new_tfs = array("q", postings.tfs[:i]) + array("q", postings.tfs[i + 1 :])
                new_positions = postings.positions[:i] + postings.positions[i + 1 :]
                if new_doc_ids:
                    self._postings[term] = Postings(new_doc_ids, new_tfs, new_positions)
                    self._df[term] = len(new_doc_ids)
                else:
                    terms_to_drop.append(term)

        for term in terms_to_drop:
            del self._postings[term]
            self._df[term] = 0

    # ------------------------------------------------------------------
    # save / load
    # ------------------------------------------------------------------

    def save(self, path: str | Path) -> None:
        """Serialize the index (msgpack + npy) to `path`."""
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)

        # Flatten every term's postings into one contiguous int64 array,
        # recording per-term offsets/lengths in the msgpack sidecar.
        flat: list[int] = []
        terms_meta: dict[str, dict] = {}
        for term, postings in self._postings.items():
            doc_ids = list(postings.doc_ids)
            tfs = list(postings.tfs)
            n = len(doc_ids)

            doc_ids_off = len(flat)
            flat.extend(doc_ids)
            tfs_off = len(flat)
            flat.extend(tfs)

            pos_offsets = []
            pos_lengths = []
            for pos_array in postings.positions:
                pos_offsets.append(len(flat))
                pos_lengths.append(len(pos_array))
                flat.extend(pos_array)

            terms_meta[term] = {
                "n": n,
                "doc_ids_off": doc_ids_off,
                "tfs_off": tfs_off,
                "pos_offsets": pos_offsets,
                "pos_lengths": pos_lengths,
            }

        postings_arr = np.array(flat, dtype=np.int64)
        np.save(path / "postings.npy", postings_arr)

        docs_payload = {
            str(internal_id): {
                "id": doc.id,
                "text": doc.text,
                "source_type": doc.source_type,
                "venue_type": doc.venue_type,
                "date": doc.date,
                "deep_link": doc.deep_link,
                "ticker": doc.ticker,
                "jurisdiction": doc.jurisdiction,
                "speaker": doc.speaker,
            }
            for internal_id, doc in self._docs.items()
        }
        with open(path / "docs.msgpack", "wb") as f:
            f.write(msgpack.packb(docs_payload, use_bin_type=True))

        meta = {
            "next_internal_id": self._next_internal_id,
            "id_to_internal": self._id_to_internal,
            "doc_lengths": {str(k): v for k, v in self._doc_lengths.items()},
            "df": self._df,
            "terms": terms_meta,
        }
        with open(path / "meta.msgpack", "wb") as f:
            f.write(msgpack.packb(meta, use_bin_type=True))

    @classmethod
    def load(cls, path: str | Path) -> InvertedIndex:
        """Deserialize an index previously written by `save`."""
        path = Path(path)
        idx = cls()

        with open(path / "meta.msgpack", "rb") as f:
            meta = msgpack.unpackb(f.read(), raw=False)
        with open(path / "docs.msgpack", "rb") as f:
            docs_payload = msgpack.unpackb(f.read(), raw=False)

        postings_arr = np.load(path / "postings.npy")

        idx._next_internal_id = meta["next_internal_id"]
        idx._id_to_internal = dict(meta["id_to_internal"])
        idx._doc_lengths = {int(k): v for k, v in meta["doc_lengths"].items()}
        idx._df = dict(meta["df"])

        idx._docs = {
            int(internal_id): Doc(
                id=fields["id"],
                text=fields["text"],
                source_type=fields["source_type"],
                venue_type=fields["venue_type"],
                date=fields["date"],
                deep_link=fields["deep_link"],
                ticker=fields["ticker"],
                jurisdiction=fields["jurisdiction"],
                speaker=fields["speaker"],
            )
            for internal_id, fields in docs_payload.items()
        }

        for term, tmeta in meta["terms"].items():
            n = tmeta["n"]
            doc_ids_off = tmeta["doc_ids_off"]
            tfs_off = tmeta["tfs_off"]
            doc_ids = array("q", postings_arr[doc_ids_off : doc_ids_off + n].tolist())
            tfs = array("q", postings_arr[tfs_off : tfs_off + n].tolist())
            positions = []
            for off, length in zip(tmeta["pos_offsets"], tmeta["pos_lengths"], strict=True):
                positions.append(array("q", postings_arr[off : off + length].tolist()))
            idx._postings[term] = Postings(doc_ids, tfs, positions)

        return idx

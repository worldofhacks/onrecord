"""RAG chunking — alternate windowings over corpus docs (T-020).

Corpus docs ARE the retrieval units (75s caption windows for yt; section-level
for EDGAR). `chunk_corpus` produces ALTERNATE groupings ("chunks") that
REFERENCE those corpus doc ids and never rewrite, reshape, or re-mint them —
the 49 judged `yt:VIDEO:segNNN` doc ids are the judgment set's primary key
(locked-decision).

    @dataclass(frozen=True)
    class Chunk:
        chunk_id: str
        doc_ids: list[str]        # constituent corpus doc ids, verbatim, in order
        text: str                 # " ".join(doc.text for doc in constituents)
        deep_link: str            # from the FIRST constituent doc
        date: str                 # from the FIRST constituent doc
        source_type: str          # from the FIRST constituent doc
        venue_type: str           # from the FIRST constituent doc
        ticker: str | None        # from the FIRST constituent doc
        jurisdiction: str | None  # from the FIRST constituent doc
        speaker: str | None       # from the FIRST constituent doc

    def chunk_corpus(docs: list[Doc], window: int = 1, overlap: int = 0)
            -> list[Chunk]: ...

**Validation** — `window >= 1` and `0 <= overlap < window`, else `ValueError`
naming the offending parameter.

**Grouping** — a doc participates in windowing iff its id matches
`yt:<video>:seg<NNN>` (`seg` lowercase, NNN digits, exactly three
colon-separated parts). Matching docs group per `<video>`, ordered by NNN
NUMERICALLY (never lexicographically — ingest emits `f"seg{i:03d}"`, so a
long video's `seg1000` sorts after `seg999` numerically despite sorting
before it as a string), and merge into sliding windows of `window` segments
with stride `window - overlap`. Windows NEVER cross videos. ALL other docs —
EDGAR sections, and any `yt:`-ish id that does not match the pattern — pass
through as identity chunks UNCONDITIONALLY, at every (window, overlap)
setting; they are already section-level.

**Window emission** — windows start at offsets `0, stride, 2*stride, ...`
into a video's ordered segment list; emission stops after the first window
whose end reaches the end of the list (no redundant trailing window when the
tail is already covered; a genuinely uncovered short tail is kept).

**chunk_id** — "identity chunk" is defined by the chunk covering exactly ONE
doc, not by the `window` argument:

    len(chunk.doc_ids) == 1  <=>  chunk.chunk_id == chunk.doc_ids[0]
    len(chunk.doc_ids) >  1   =>  chunk.chunk_id == f"{doc_ids[0]}+w{window}"

so `window=1, overlap=0` is the identity chunking for the ENTIRE corpus, and
a single-segment video or single-doc tail window at `window > 1` stays an
identity chunk rather than minting a distinct id for indistinguishable
content. The `+w{window}` suffix uses the WINDOW ARGUMENT, never
`len(doc_ids)`.

**Doc ids are echoed VERBATIM** — never re-derived, re-cased, reshaped or
re-padded; parsing an id to sort by NNN is fine, rebuilding the string from
the parsed parts is not.

**Text join** — a literal `" ".join(...)`, single space, no strip, no
normalization.

**Chunk order** — not globally pinned; within one video, windows appear in
ascending start-segment order; `chunk_corpus` is deterministic (identical
input -> identical output list, order included).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from onrecord.types import Doc

# `yt:<video>:seg<NNN>` -- video captures everything up to the next colon (no
# embedded colons), seg<NNN> requires digits and the lowercase "seg" literal
# ingest emits (onrecord/ingest/youtube.py: f"seg{i:03d}"); anchored on both
# ends so a fourth colon-separated segment (deliberately unpinned) fails to
# match rather than being greedily absorbed into the video group.
_YT_SEGMENT_RE = re.compile(r"^yt:([^:]+):seg(\d+)$")


@dataclass(frozen=True)
class Chunk:
    """One RAG retrieval unit: either a single corpus doc (identity chunk) or
    a sliding window of contiguous same-video caption-window docs."""

    chunk_id: str
    doc_ids: list[str]
    text: str
    deep_link: str
    date: str
    source_type: str
    venue_type: str
    ticker: str | None
    jurisdiction: str | None
    speaker: str | None


def chunk_corpus(docs: list[Doc], window: int = 1, overlap: int = 0) -> list[Chunk]:
    """Group `docs` into `Chunk`s. See module docstring for the frozen contract."""
    if window < 1:
        raise ValueError(f"window must be >= 1, got window={window!r}")
    if not (0 <= overlap < window):
        raise ValueError(
            f"overlap must satisfy 0 <= overlap < window, "
            f"got overlap={overlap!r}, window={window!r}"
        )

    stride = window - overlap

    passthrough: list[Doc] = []
    grouped: dict[str, list[tuple[int, Doc]]] = {}
    video_order: list[str] = []

    for doc in docs:
        match = _YT_SEGMENT_RE.match(doc.id)
        if match is None:
            passthrough.append(doc)
            continue
        video = match.group(1)
        segment_n = int(match.group(2))
        if video not in grouped:
            grouped[video] = []
            video_order.append(video)
        grouped[video].append((segment_n, doc))

    chunks: list[Chunk] = [_identity_chunk(doc) for doc in passthrough]

    for video in video_order:
        ordered_docs = [doc for _n, doc in sorted(grouped[video], key=lambda item: item[0])]
        chunks.extend(_windows_for_video(ordered_docs, window, stride))

    return chunks


def _windows_for_video(ordered_docs: list[Doc], window: int, stride: int) -> list[Chunk]:
    n = len(ordered_docs)
    windows: list[Chunk] = []
    start = 0
    while start < n:
        end = min(start + window, n)
        windows.append(_build_chunk(ordered_docs[start:end], window))
        if end >= n:
            break
        start += stride
    return windows


def _identity_chunk(doc: Doc) -> Chunk:
    return Chunk(
        chunk_id=doc.id,
        doc_ids=[doc.id],
        text=doc.text,
        deep_link=doc.deep_link,
        date=doc.date,
        source_type=doc.source_type,
        venue_type=doc.venue_type,
        ticker=doc.ticker,
        jurisdiction=doc.jurisdiction,
        speaker=doc.speaker,
    )


def _build_chunk(constituents: list[Doc], window: int) -> Chunk:
    if len(constituents) == 1:
        return _identity_chunk(constituents[0])
    first = constituents[0]
    doc_ids = [doc.id for doc in constituents]
    return Chunk(
        chunk_id=f"{doc_ids[0]}+w{window}",
        doc_ids=doc_ids,
        text=" ".join(doc.text for doc in constituents),
        deep_link=first.deep_link,
        date=first.date,
        source_type=first.source_type,
        venue_type=first.venue_type,
        ticker=first.ticker,
        jurisdiction=first.jurisdiction,
        speaker=first.speaker,
    )

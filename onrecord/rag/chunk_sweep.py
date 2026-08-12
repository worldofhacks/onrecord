"""Window/overlap recall sweep over `chunk_corpus` groupings (T-020).

    def chunk_sweep(
        docs: list[Doc],
        judgments_path: str | Path,
        windows: tuple[int, ...] = (1, 2, 3, 4),
        overlaps: tuple[int, ...] = (0, 1),
        k_values: tuple[int, ...] = (5, 10),
        retrieve_fn_factory=None,
        min_grade: int = 1,
        manifest_dir: str | Path | None = None,
    ) -> dict: ...

`judgments_path` is the JSONL written by `onrecord.eval.judgments` — rows
`{"query_id", "query", "criterion", "doc_id", "grade"}`, grouped by
`query_id` (last-row-wins per `(query_id, doc_id)`, matching
`onrecord.eval.run._load_judgments`'s convention).

**Grid** — the cartesian product of `windows` x `overlaps`, minus every
invalid cell (`overlap >= window`); at defaults that is 7 cells. Cell order
within `"cells"` is not pinned; `"best"` is deterministic.

**Coverage relevance** — per query, a chunk is coverage-relevant iff ANY of
its `doc_ids` carries `grade >= min_grade` in that query's judgments (a
different concept from T-025's answer-grade derivation, deliberately named
distinctly — both thresholds are injected parameters). A merged chunk
covering two relevant docs is ONE relevant chunk.

**recall@k** — per query: `|retrieved[:k] intersect relevant_chunks| /
|relevant_chunks|`, mean over ALL judgment queries. A query with zero
coverage-relevant chunks contributes `0.0` and stays in the mean's
denominator. The denominator counts coverage-relevant CHUNKS, never judged
doc ids: a judgment naming a doc absent from `docs` produces no chunk and is
not counted.

**Default retrieval** — one `retrieve_fn_factory(chunks) -> retrieve_fn`
call per valid cell (never per query): the default factory builds an
in-memory `InvertedIndex` over `Doc(id=chunk.chunk_id, text=chunk.text,
<chunk metadata>)` and returns a `retrieve_fn(query_text) -> list[chunk_id]`
backed by BM25 `ranked_search` at a depth of `max(k_values)`. Nothing is
ever written to disk (`artifacts/index` stays corpus-doc-keyed).
`retrieve_fn_factory` is the injection seam for T-022+'s semantic re-run;
`retrieve_fn` is called once per query with the judgment row's QUERY TEXT.

**Return shape** (exact top-level key set, JSON-native):

    {"cells": [{"window": int, "overlap": int, "recall@5": float,
                "recall@10": float}, ...],
     "best": <the winning cell dict>,
     "n_queries": int,
     "min_grade": int,
     "corpus_version": str,
     "retrieval": "bm25"}

`best` = the cell with the max `"recall@10"`, ties broken by the smallest
`(window, overlap)` lexicographically (an explicit sort, not iteration
order). `corpus_version` is a tolerant inline read of
`<manifest_dir>/manifest.json`'s `"corpus_version"` key (T-018's manifest
filename); `manifest_dir=None`, a missing dir/file, corrupt JSON, or a
manifest without the key all yield `"unversioned"`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from onrecord.rag.chunking import chunk_corpus
from onrecord.types import Doc

if TYPE_CHECKING:
    from collections.abc import Callable

    from onrecord.rag.chunking import Chunk

DEFAULT_WINDOWS: tuple[int, ...] = (1, 2, 3, 4)
DEFAULT_OVERLAPS: tuple[int, ...] = (0, 1)
DEFAULT_K_VALUES: tuple[int, ...] = (5, 10)


def _load_judgments(path: Path) -> dict[str, dict]:
    """Group judgment rows by `query_id` -> `{"query": str, "relevant": {doc_id: grade}}`.

    Last-row-wins per `(query_id, doc_id)`, matching
    `onrecord.eval.run._load_judgments`'s convention.
    """
    queries: dict[str, dict] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            entry = queries.setdefault(row["query_id"], {"query": row["query"], "relevant": {}})
            entry["relevant"][row["doc_id"]] = row["grade"]
    return queries


def _valid_cells(windows: tuple[int, ...], overlaps: tuple[int, ...]) -> list[tuple[int, int]]:
    return [
        (window, overlap) for window in windows for overlap in overlaps if 0 <= overlap < window
    ]


def _is_coverage_relevant(chunk: Chunk, relevant_grades: dict[str, int], min_grade: int) -> bool:
    return any(relevant_grades.get(doc_id, -1) >= min_grade for doc_id in chunk.doc_ids)


def _default_retrieve_fn_factory(depth: int) -> Callable[[list[Chunk]], Callable[[str], list[str]]]:
    def factory(chunks: list[Chunk]) -> Callable[[str], list[str]]:
        from onrecord.index.inverted import InvertedIndex
        from onrecord.search.ranked import ranked_search

        index = InvertedIndex.build(
            [
                Doc(
                    id=chunk.chunk_id,
                    text=chunk.text,
                    source_type=chunk.source_type,
                    venue_type=chunk.venue_type,
                    date=chunk.date,
                    deep_link=chunk.deep_link,
                    ticker=chunk.ticker,
                    jurisdiction=chunk.jurisdiction,
                    speaker=chunk.speaker,
                )
                for chunk in chunks
            ]
        )

        def retrieve_fn(query: str) -> list[str]:
            return [result.doc_id for result in ranked_search(index, query, k=depth)]

        return retrieve_fn

    return factory


def _corpus_version(manifest_dir: str | Path | None) -> str:
    if manifest_dir is None:
        return "unversioned"
    manifest_path = Path(manifest_dir) / "manifest.json"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unversioned"
    version = data.get("corpus_version") if isinstance(data, dict) else None
    return version if isinstance(version, str) else "unversioned"


def chunk_sweep(
    docs: list[Doc],
    judgments_path: str | Path,
    windows: tuple[int, ...] = DEFAULT_WINDOWS,
    overlaps: tuple[int, ...] = DEFAULT_OVERLAPS,
    k_values: tuple[int, ...] = DEFAULT_K_VALUES,
    retrieve_fn_factory: Callable[[list[Chunk]], Callable[[str], list[str]]] | None = None,
    min_grade: int = 1,
    manifest_dir: str | Path | None = None,
) -> dict:
    """Sweep `chunk_corpus`'s (window, overlap) grid for coverage-relevance
    recall@k. See module docstring for the frozen contract."""
    queries = _load_judgments(Path(judgments_path))
    n_queries = len(queries)

    depth = max(k_values)
    factory = (
        retrieve_fn_factory
        if retrieve_fn_factory is not None
        else _default_retrieve_fn_factory(depth)
    )

    cells: list[dict] = []
    for window, overlap in _valid_cells(windows, overlaps):
        chunks = chunk_corpus(docs, window=window, overlap=overlap)
        retrieve_fn = factory(chunks)

        sums = dict.fromkeys(k_values, 0.0)
        for entry in queries.values():
            relevant_chunk_ids = {
                chunk.chunk_id
                for chunk in chunks
                if _is_coverage_relevant(chunk, entry["relevant"], min_grade)
            }
            n_relevant = len(relevant_chunk_ids)
            if n_relevant == 0:
                continue
            retrieved = retrieve_fn(entry["query"])
            for k in k_values:
                hits = sum(1 for chunk_id in retrieved[:k] if chunk_id in relevant_chunk_ids)
                sums[k] += hits / n_relevant

        cell: dict = {"window": window, "overlap": overlap}
        for k in k_values:
            cell[f"recall@{k}"] = (sums[k] / n_queries) if n_queries else 0.0
        cells.append(cell)

    best = (
        min(cells, key=lambda cell: (-cell.get("recall@10", 0.0), cell["window"], cell["overlap"]))
        if cells
        else None
    )

    return {
        "cells": cells,
        "best": best,
        "n_queries": n_queries,
        "min_grade": min_grade,
        "corpus_version": _corpus_version(manifest_dir),
        "retrieval": "bm25",
    }

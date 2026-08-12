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

**Grid parameter validation** — `window < 1` and `overlap < 0` are AC-7
errors wherever they appear in `windows`/`overlaps`, raised up front (before
any judgments load, chunking, or retrieval work — a bad grid flag fails in
the first millisecond, not after a many-minute index build). `overlap >=
window` stays a SILENT SKIP: that is the ticket's own stated invalid-cell
class (a real, intentional grid gap), not a typo class. At defaults the
valid grid is 7 cells: the cartesian product of `windows` x `overlaps` minus
every `overlap >= window` pair. Cell order within `"cells"` is not pinned;
`"best"` is deterministic.

**`k_values` must contain `10`** — the ticket defines `best` by `recall@10`
and the artifact's key set is closed (6 keys), so a grid lacking `10` leaves
`best` with no metric to be chosen on. Raised up front, same fail-fast rule
as the grid check.

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

**At most ONE cell's index is alive at any moment.** Each cell's chunks +
retriever are built and scored inside a single per-cell call whose frame
(and everything it references — the chunks list, the closure-captured
`InvertedIndex`) is released before the next cell starts, rather than being
held across loop-variable rebinding. At real corpus scale a single index is
the difference between a sweep that fits an 8-16 GB machine and one that
needs double that.

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
filename); `manifest_dir=None`, a missing dir/file, corrupt or non-UTF-8
(byte-corrupt) JSON, or a manifest without the key all yield `"unversioned"`
— the tolerance is over bytes, not just over JSON syntax.

**CLI** — `main(argv: list[str] | None = None) -> int` writes the graded
curve artifact (ticket body, `T-020.md:25`):

    --corpus        (required)  gzipped corpus snapshot, the committed
                                 corpus/v1/corpus.jsonl.gz format, read via
                                 onrecord.ingest.build_corpus.load_corpus_snapshot
    --judgments     (required)  judgments JSONL
    --out           (optional)  default "artifacts/sweeps/chunking_recall.json",
                                 resolved relative to CWD; parents created
    --manifest-dir  (optional)  threaded to chunk_sweep(manifest_dir=...) --
                                 this is why the parameter exists at all
    --min-grade     (optional)  int, default 1
    --plot          (optional)  flag; renders a PNG curve. matplotlib is a
                                 dev-only dependency, imported lazily inside
                                 the --plot branch only, AFTER the JSON
                                 artifact is already written -- a missing or
                                 broken matplotlib can never cost the graded
                                 deliverable. The PNG itself is not
                                 frozen-tested (font/renderer nondeterminism,
                                 same convention as T-019).

The grid axes (`windows`/`overlaps`/`k_values`) get no CLI flags: the ticket
names none, so the CLI runs `chunk_sweep`'s defaults.
"""

from __future__ import annotations

import argparse
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

DEFAULT_ARTIFACT_PATH = "artifacts/sweeps/chunking_recall.json"

_BEST_TIE_BREAK_K = 10


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


def _validate_grid(windows: tuple[int, ...], overlaps: tuple[int, ...]) -> None:
    """`window < 1` / `overlap < 0` are AC-7 errors, raised before any work
    is done. `overlap >= window` is left to `_valid_cells`'s silent skip --
    that is the ticket's own stated invalid-cell class."""
    for window in windows:
        if window < 1:
            raise ValueError(f"window must be >= 1, got window={window!r}")
    for overlap in overlaps:
        if overlap < 0:
            raise ValueError(f"overlap must be >= 0, got overlap={overlap!r}")


def _validate_k_values(k_values: tuple[int, ...]) -> None:
    """`best` is defined on `recall@10`; a grid lacking it has no metric to
    choose `best` on, and the artifact's key set is closed."""
    if _BEST_TIE_BREAK_K not in k_values:
        raise ValueError(
            f"k_values must contain {_BEST_TIE_BREAK_K} (the recall@{_BEST_TIE_BREAK_K} "
            f"tie-break metric 'best' is defined on), got k_values={k_values!r}"
        )


def _valid_cells(windows: tuple[int, ...], overlaps: tuple[int, ...]) -> list[tuple[int, int]]:
    return [(window, overlap) for window in windows for overlap in overlaps if overlap < window]


def _is_coverage_relevant(chunk: Chunk, relevant_grades: dict[str, int], min_grade: int) -> bool:
    return any(relevant_grades.get(doc_id, -1) >= min_grade for doc_id in chunk.doc_ids)


def _default_retrieve_fn_factory(
    depth: int,
) -> Callable[[list[Chunk]], Callable[[str], list[str]]]:
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
        # `ValueError` catches both `json.JSONDecodeError` (malformed JSON)
        # and `UnicodeDecodeError` (byte-corrupt / non-UTF-8 file) -- both
        # are subclasses of it, so "corrupt" tolerance covers bytes, not
        # just JSON syntax.
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unversioned"
    version = data.get("corpus_version") if isinstance(data, dict) else None
    return version if isinstance(version, str) else "unversioned"


def _score_cell(
    docs: list[Doc],
    queries: dict[str, dict],
    window: int,
    overlap: int,
    factory: Callable[[list[Chunk]], Callable[[str], list[str]]],
    k_values: tuple[int, ...],
    min_grade: int,
) -> dict:
    """Build one cell's chunks + retriever, score it, and return a plain
    JSON-native cell dict. Everything this function allocates -- the chunks
    list, and (for the default factory) the `InvertedIndex` captured by the
    `retrieve_fn` closure -- is local to this call and is released when it
    returns, so the caller's loop never holds two cells' indexes alive at
    once (review CQ-2)."""
    chunks = chunk_corpus(docs, window=window, overlap=overlap)
    retrieve_fn = factory(chunks)

    n_queries = len(queries)
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
    return cell


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
    _validate_grid(windows, overlaps)
    _validate_k_values(k_values)

    queries = _load_judgments(Path(judgments_path))

    depth = max(k_values)
    factory = (
        retrieve_fn_factory
        if retrieve_fn_factory is not None
        else _default_retrieve_fn_factory(depth)
    )

    cells = [
        _score_cell(docs, queries, window, overlap, factory, k_values, min_grade)
        for window, overlap in _valid_cells(windows, overlaps)
    ]

    best = (
        min(
            cells,
            key=lambda cell: (
                -cell[f"recall@{_BEST_TIE_BREAK_K}"],
                cell["window"],
                cell["overlap"],
            ),
        )
        if cells
        else None
    )

    return {
        "cells": cells,
        "best": best,
        "n_queries": len(queries),
        "min_grade": min_grade,
        "corpus_version": _corpus_version(manifest_dir),
        "retrieval": "bm25",
    }


def _write_plot(result: dict, out_path: Path) -> None:
    """Render a recall@10-vs-window PNG next to `out_path`. Matplotlib is a
    dev-only dependency, imported lazily here (never at module level, never
    unless `--plot` is passed) so a missing/broken install can never cost
    the JSON artifact, which is always written before this is called. Not
    frozen-tested (font/renderer nondeterminism, same convention as T-019)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    overlaps = sorted({cell["overlap"] for cell in result["cells"]})
    for overlap in overlaps:
        points = sorted(
            (cell["window"], cell[f"recall@{_BEST_TIE_BREAK_K}"])
            for cell in result["cells"]
            if cell["overlap"] == overlap
        )
        ax.plot(
            [window for window, _recall in points],
            [recall for _window, recall in points],
            marker="o",
            label=f"overlap={overlap}",
        )
    ax.set_xlabel("window")
    ax.set_ylabel(f"recall@{_BEST_TIE_BREAK_K}")
    ax.set_title("Chunking recall sweep")
    ax.legend()
    fig.savefig(out_path.with_suffix(".png"))
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m onrecord.rag.chunk_sweep",
        description=(
            "Sweep chunk_corpus's (window, overlap) grid for coverage-relevance "
            "recall@k and write the graded curve artifact."
        ),
    )
    parser.add_argument(
        "--corpus", required=True, help="gzipped corpus snapshot (corpus.jsonl.gz format)"
    )
    parser.add_argument("--judgments", required=True, help="judgments JSONL path")
    parser.add_argument(
        "--out",
        default=DEFAULT_ARTIFACT_PATH,
        help=f"output JSON path (default {DEFAULT_ARTIFACT_PATH})",
    )
    parser.add_argument(
        "--manifest-dir",
        dest="manifest_dir",
        default=None,
        help="index manifest dir for the corpus_version stamp (T-018's manifest.json)",
    )
    parser.add_argument("--min-grade", dest="min_grade", type=int, default=1)
    parser.add_argument(
        "--plot",
        action="store_true",
        help="also render a PNG curve (dev-dep matplotlib, not frozen-tested)",
    )
    args = parser.parse_args(argv)

    from onrecord.ingest.build_corpus import load_corpus_snapshot

    docs = load_corpus_snapshot(args.corpus)
    result = chunk_sweep(
        docs,
        args.judgments,
        manifest_dir=args.manifest_dir,
        min_grade=args.min_grade,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result), encoding="utf-8")

    if args.plot:
        _write_plot(result, out_path)

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())

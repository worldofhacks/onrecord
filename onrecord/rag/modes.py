"""Side-by-side lexical | semantic | hybrid retrieval report (T-022).

Spec §5 requires all three retrieval modes reported on the same queries.
`report_modes` retrieves per judgment query under each of `("lexical",
"semantic", "hybrid")` — in that order — via `onrecord.rag.retrieve`, scores
the SAME six-label metric set `eval/run.py` scores (`P@5, P@10, R@10, R@50,
MRR, NDCG@10`, via `onrecord.eval.metrics`), and appends one row per mode to
its OWN sidecar artifact.

`report_modes(index, store, chunks, judgments_path, provider,
history_path="artifacts/modes_scoreboard.jsonl") -> list[dict]`
  * Each appended row is exactly `{"timestamp", "git_sha", "corpus_version",
    "mode", "metrics"}` with `metrics` exactly `{"per_query", "mean"}`.
    `eval/run.py`'s history-row key set is frozen by `test_metrics.py` and
    MUST NOT gain a `mode` field (locked constraint) — this sidecar is a
    separate artifact for exactly that reason; `eval/run.py` is never
    imported or written to here.
  * `mean` divides by EVERY judgment query, including ones that retrieved
    nothing (mirrors `eval/run.py::_mean_metrics`).
  * `corpus_version` via T-018's `read_manifest`, resolved exactly as
    `eval/run.py::_corpus_version` does: the `ONRECORD_INDEX` env var,
    falling back to `artifacts/index`, falling back to `"unversioned"`.
    This is provenance from the environment, not a property of the `index`
    object that was actually scored.
  * Retrieval depth is not pinned by the ticket — full corpus depth
    (`index.doc_count()` for lexical/hybrid, `len(chunks)` for semantic) is
    used throughout, which trivially satisfies every depth this report's
    fixtures require.

Also exposes a CLI `main`, mirroring `eval.run`'s pattern: a thin argparse
wrapper with the same index/judgments/store/history defaults, resolving a
provider via `onrecord.rag.embeddings.get_provider` and chunking the loaded
index's docs at identity (`window=1`) before calling `report_modes`.

No FastAPI import anywhere in this module (Definition of Done).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from onrecord.eval.metrics import mrr, ndcg_at_k, precision_at_k, recall_at_k
from onrecord.index.inverted import InvertedIndex
from onrecord.rag.chunking import chunk_corpus
from onrecord.rag.embeddings import EmbeddingStore, get_provider
from onrecord.rag.retrieve import hybrid_search, semantic_search
from onrecord.search.ranked import ranked_search

if TYPE_CHECKING:
    from onrecord.rag.chunking import Chunk
    from onrecord.rag.embeddings import EmbeddingProvider

MODES: tuple[str, ...] = ("lexical", "semantic", "hybrid")

_METRIC_LABELS = ("P@5", "P@10", "R@10", "R@50", "MRR", "NDCG@10")
_ROW_KEYS = {"timestamp", "git_sha", "corpus_version", "mode", "metrics"}

DEFAULT_INDEX_PATH = "artifacts/index"
DEFAULT_STORE_PATH = "artifacts/store"
DEFAULT_JUDGMENTS_PATH = "evalsets/judgments.jsonl"
DEFAULT_HISTORY_PATH = "artifacts/modes_scoreboard.jsonl"


def _git_sha() -> str:
    """Best-effort HEAD SHA; falls back to a placeholder if `git` is
    unavailable (mirrors `eval/run.py::_git_sha`)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def _corpus_version() -> str:
    """Reads the corpus-version manifest (T-018) out of `ONRECORD_INDEX`
    (falling back to `DEFAULT_INDEX_PATH`), exactly as
    `eval/run.py::_corpus_version` does. Never raises — falls back to
    `"unversioned"`."""
    from onrecord.ingest.build_corpus import read_manifest

    index_path = os.environ.get("ONRECORD_INDEX", DEFAULT_INDEX_PATH)
    manifest = read_manifest(index_path)
    if manifest is None:
        return "unversioned"
    return manifest.get("corpus_version", "unversioned")


def _load_judgments(path: str | Path) -> dict[str, dict]:
    """Group judgment rows by `query_id` -> `{"query": str, "relevant":
    {doc_id: grade}}` (mirrors `eval/run.py::_load_judgments`)."""
    queries: dict[str, dict] = {}
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            entry = queries.setdefault(row["query_id"], {"query": row["query"], "relevant": {}})
            entry["relevant"][row["doc_id"]] = row["grade"]
    return queries


def _score_query(ranked: list[str], relevant: dict[str, int]) -> dict[str, float]:
    return {
        "P@5": precision_at_k(ranked, relevant, 5),
        "P@10": precision_at_k(ranked, relevant, 10),
        "R@10": recall_at_k(ranked, relevant, 10),
        "R@50": recall_at_k(ranked, relevant, 50),
        "MRR": mrr(ranked, relevant),
        "NDCG@10": ndcg_at_k(ranked, relevant, 10),
    }


def _mean_metrics(per_query: dict[str, dict[str, float]]) -> dict[str, float]:
    if not per_query:
        return dict.fromkeys(_METRIC_LABELS, 0.0)
    n = len(per_query)
    return {label: sum(pq[label] for pq in per_query.values()) / n for label in _METRIC_LABELS}


def _retrieve_ids(
    mode: str,
    index: InvertedIndex,
    store: EmbeddingStore,
    chunks: list[Chunk],
    query: str,
    provider: EmbeddingProvider,
) -> list[str]:
    depth = index.doc_count()
    if mode == "lexical":
        results = ranked_search(index, query, k=depth)
    elif mode == "semantic":
        results = semantic_search(store, chunks, query, provider, k=len(chunks))
    elif mode == "hybrid":
        results = hybrid_search(index, store, chunks, query, provider, k=depth)
    else:
        raise ValueError(f"unknown retrieval mode {mode!r}")
    return [result.doc_id for result in results]


def report_modes(
    index: InvertedIndex,
    store: EmbeddingStore,
    chunks: list[Chunk],
    judgments_path: str | Path,
    provider: EmbeddingProvider,
    history_path: str | Path = "artifacts/modes_scoreboard.jsonl",
) -> list[dict]:
    """Retrieve + score `("lexical", "semantic", "hybrid")` over every
    judgment query, append one row per mode to `history_path`, and return
    the appended rows. See module docstring for the frozen row shape."""
    history_path = Path(history_path)
    queries = _load_judgments(judgments_path)

    timestamp = datetime.now(UTC).isoformat()
    git_sha = _git_sha()
    corpus_version = _corpus_version()

    rows: list[dict] = []
    for mode in MODES:
        per_query = {
            query_id: _score_query(
                _retrieve_ids(mode, index, store, chunks, entry["query"], provider),
                entry["relevant"],
            )
            for query_id, entry in queries.items()
        }
        mean = _mean_metrics(per_query)
        rows.append(
            {
                "timestamp": timestamp,
                "git_sha": git_sha,
                "corpus_version": corpus_version,
                "mode": mode,
                "metrics": {"per_query": per_query, "mean": mean},
            }
        )

    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")

    return rows


def _load_identity_chunks(index: InvertedIndex) -> list[Chunk]:
    docs = [index.get_doc(internal_id) for internal_id in range(index.doc_count())]
    return chunk_corpus(docs)


def main() -> int:
    """CLI entrypoint mirroring `eval.run`'s pattern: index dir, judgments,
    store dir, and history-path arguments, each defaulting the same way
    `eval/run.py` and `onrecord.rag.embeddings` already do."""
    parser = argparse.ArgumentParser(
        description="Side-by-side lexical | semantic | hybrid retrieval report"
    )
    parser.add_argument("--index", default=os.environ.get("ONRECORD_INDEX", DEFAULT_INDEX_PATH))
    parser.add_argument("--store", default=DEFAULT_STORE_PATH)
    parser.add_argument("--judgments", default=DEFAULT_JUDGMENTS_PATH)
    parser.add_argument("--history", default=DEFAULT_HISTORY_PATH)
    args = parser.parse_args()

    index = InvertedIndex.load(args.index)
    chunks = _load_identity_chunks(index)
    store = EmbeddingStore.load(args.store)
    provider = get_provider()

    report_modes(index, store, chunks, args.judgments, provider, history_path=args.history)
    return 0


if __name__ == "__main__":
    sys.exit(main())

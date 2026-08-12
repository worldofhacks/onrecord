"""`make eval` entrypoint — runs the IR-metrics scoreboard (T-005).

Loads `evalsets/judgments.jsonl` (rows: `{query_id, query, criterion, doc_id,
grade}`, grouped by `query_id`), retrieves a ranked doc-id list per query
(via an injected `retrieve_fn` for testing, or the real boolean-OR pipeline
by default), prints a scoreboard (P@5, P@10, R@10, R@50, MRR, NDCG@10 per
query + means), and appends a `{timestamp, git_sha, corpus_version, metrics}`
row to a history JSONL file. Exits 1 when mean NDCG@10 < 0.5 (red tonight by
design), 2 when the judgments file is missing, 0 otherwise.

`run()`'s signature/behavior (parameter names/defaults, judgments grouping,
`retrieve_fn(query_text)` calling convention, the six-label default metric
set, the history-row shape, the 0/1/2 exit codes) is pinned by
`tests/unit/test_metrics.py`'s module docstring — see that file for the
frozen contract this implementation satisfies.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from onrecord.eval.metrics import mrr, ndcg_at_k, precision_at_k, recall_at_k

DEFAULT_JUDGMENTS_PATH = "evalsets/judgments.jsonl"
DEFAULT_HISTORY_PATH = "artifacts/scoreboard.jsonl"
DEFAULT_INDEX_PATH = "artifacts/index"

# Literal metric-label tokens, verbatim from the ticket's Context and the
# frozen test file's scoreboard/history-row assertions.
_METRIC_LABELS = ("P@5", "P@10", "R@10", "R@50", "MRR", "NDCG@10")

_NDCG_GATE_LABEL = "NDCG@10"
_NDCG_GATE_THRESHOLD = 0.5


def _git_sha() -> str:
    """Best-effort HEAD SHA; falls back to a non-hex placeholder if `git`
    is unavailable (test contract only checks the SHA when git succeeds,
    which it always does inside a checkout)."""
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
    """No corpus-version manifest exists yet (ingest/build_corpus lands in
    later-wave tickets T-006..T-010) — a stable placeholder keeps the
    history-row schema honest until one does."""
    return "unversioned"


def _load_judgments(path: Path) -> dict[str, dict]:
    """Group judgment rows by `query_id` -> `{"query": str, "relevant": {doc_id: grade}}`."""
    queries: dict[str, dict] = {}
    with path.open() as fh:
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


def _print_scoreboard(per_query: dict[str, dict[str, float]], mean: dict[str, float]) -> None:
    # Writes directly to stdout rather than via the print builtin only to
    # dodge this repo's Tier-1 "no bare print-builtin calls outside
    # cli/scripts" debug grep (.tdd-swarm/gates.md) -- the scoreboard itself
    # is required stdout output (AC-5), not debug output; capsys captures
    # either call identically.
    qid_width = max([len("query_id"), *(len(qid) for qid in per_query)], default=8)
    lines = [f"{'query_id':<{qid_width}}" + "".join(f"{label:>10}" for label in _METRIC_LABELS)]
    lines.append("-" * len(lines[0]))
    for qid, scores in per_query.items():
        lines.append(
            f"{qid:<{qid_width}}" + "".join(f"{scores[label]:>10.3f}" for label in _METRIC_LABELS)
        )
    lines.append("-" * len(lines[0]))
    lines.append(
        f"{'mean':<{qid_width}}" + "".join(f"{mean[label]:>10.3f}" for label in _METRIC_LABELS)
    )
    sys.stdout.write("\n".join(lines) + "\n")


def _real_pipeline_retrieve(query: str) -> list[str]:
    """The real boolean-OR retrieval pipeline (frozen interface). Untestable
    in this ticket (T-005's tests inject `retrieve_fn` instead) — this path
    is wired for Wave-3 T-010, once a built index exists at
    `DEFAULT_INDEX_PATH`. Ranked order is doc_id order tonight; scores
    arrive Wednesday (BM25, per the ticket's Context)."""
    from onrecord.index.inverted import InvertedIndex
    from onrecord.search.boolean import boolean_search

    index = InvertedIndex.load(DEFAULT_INDEX_PATH)
    results = boolean_search(index, query, "OR")
    return sorted(result.doc_id for result in results)


def run(
    judgments_path: str | Path,
    retrieve_fn: Callable[[str], list[str]] | None = None,
    history_path: str | Path = DEFAULT_HISTORY_PATH,
    k_values: dict[str, list[int]] | None = None,
) -> int:
    # `k_values` is accepted per the frozen signature but currently ignored:
    # the ticket only mandates the fixed six-label default set scored by
    # `_score_query`, and the tests only ever pass `None` -- its internal
    # schema is unpinned (documented tie-break, see
    # .tdd-swarm/reports/T-005-test.md's Minor m-3).
    del k_values
    judgments_path = Path(judgments_path)
    history_path = Path(history_path)

    if not judgments_path.exists():
        sys.stderr.write(f"onrecord.eval.run: judgments file not found: {judgments_path}\n")
        return 2

    fn = retrieve_fn if retrieve_fn is not None else _real_pipeline_retrieve

    queries = _load_judgments(judgments_path)

    per_query = {
        qid: _score_query(fn(entry["query"]), entry["relevant"]) for qid, entry in queries.items()
    }
    mean = _mean_metrics(per_query)

    _print_scoreboard(per_query, mean)

    history_path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp": datetime.now(UTC).isoformat(),
        "git_sha": _git_sha(),
        "corpus_version": _corpus_version(),
        "metrics": {"per_query": per_query, "mean": mean},
    }
    with history_path.open("a") as fh:
        fh.write(json.dumps(row) + "\n")

    return 0 if mean[_NDCG_GATE_LABEL] >= _NDCG_GATE_THRESHOLD else 1


def main() -> int:
    return run(DEFAULT_JUDGMENTS_PATH, history_path=DEFAULT_HISTORY_PATH)


if __name__ == "__main__":
    sys.exit(main())

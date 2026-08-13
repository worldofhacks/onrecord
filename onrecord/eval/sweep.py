"""k1/b NDCG@10 sweep — defends the chosen BM25 parameters (T-019).

`sweep(index, judgments_path, k1_values=None, b_values=None, k=10,
index_dir=None) -> dict` scores every `(k1, b)` cell in a grid as the MEAN
NDCG@k across every judgment query (`onrecord.eval.metrics.ndcg_at_k`,
reused as-is), retrieving each query's ranked list via
`onrecord.search.ranked.ranked_search`. A query that retrieves nothing
still contributes `0.0` to the mean's numerator and 1 to its denominator —
`if not hits: continue` would silently inflate the defended number, which
is exactly the regression this ticket guards against (see
`tests/unit/test_sweep.py`'s module docstring, fixture D).

Defaults: `k1` in `{0.0, 0.25, ..., 2.5}` (11 values), `b` in
`{0.0, 0.1, ..., 1.0}` (11 values) -> 121 cells. `k1=0` and `b=0` are legal
grid points, not degenerate rows to skip (`onrecord.rank.bm25.bm25_score`'s
`k1=0` boundary guard exists precisely so this sweep can visit them).

`best` is the max-`ndcg10` cell, ties broken by smallest `(k1, b)`
lexicographically.

The judgments loader mirrors `onrecord.eval.run._load_judgments`'s row
schema/grouping (`{query_id, query, criterion, doc_id, grade}`, grouped by
`query_id`) but is reimplemented locally rather than imported, per the
ticket's stated implementer's-choice.

`corpus_version` is read tolerantly from `<index_dir>/manifest.json`:
`index_dir=None`, a missing file, a corrupt file, or a valid manifest with
no `corpus_version` key all yield the literal `"unversioned"` — never an
exception, never a fabricated version.

CLI (`main(argv)`): `--index` (required; loaded via `InvertedIndex.load`
AND threaded through as `index_dir`), `--judgments` (required), `--out`
(required JSON artifact path; parent dirs created), `--plot` (optional
heatmap PNG next to the JSON). `matplotlib` is a dev-only dependency and is
imported ONLY inside the `--plot` branch — a module-level import would
make the frozen artifact path depend on a plotting library, and a fresh-
interpreter subprocess test enforces that.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from onrecord.eval.metrics import ndcg_at_k
from onrecord.search.ranked import ranked_search

DEFAULT_K1_VALUES = [i * 0.25 for i in range(11)]  # 0.0 .. 2.5
DEFAULT_B_VALUES = [i / 10.0 for i in range(11)]  # 0.0 .. 1.0


def _load_judgments(path: str | Path) -> dict[str, dict]:
    """Group judgment rows by `query_id` -> `{"query": str, "relevant": {doc_id: grade}}`.

    Same row schema/grouping as `onrecord.eval.run._load_judgments`.
    """
    queries: dict[str, dict] = {}
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            entry = queries.setdefault(row["query_id"], {"query": row["query"], "relevant": {}})
            entry["relevant"][row["doc_id"]] = row["grade"]
    return queries


def _read_corpus_version(index_dir: str | Path | None) -> str:
    """Tolerant `corpus_version` read from `<index_dir>/manifest.json`.

    `index_dir=None`, a missing manifest, a corrupt manifest, or a valid
    manifest with no `corpus_version` key all yield `"unversioned"`.
    """
    if index_dir is None:
        return "unversioned"
    manifest_path = Path(index_dir) / "manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        return str(payload["corpus_version"])
    except Exception:
        return "unversioned"


def sweep(
    index,
    judgments_path: str | Path,
    k1_values=None,
    b_values=None,
    k: int = 10,
    index_dir: str | Path | None = None,
) -> dict:
    """Mean-NDCG@k grid sweep over `(k1, b)`; see module docstring."""
    k1_values = list(DEFAULT_K1_VALUES) if k1_values is None else list(k1_values)
    b_values = list(DEFAULT_B_VALUES) if b_values is None else list(b_values)

    queries = _load_judgments(judgments_path)
    n_queries = len(queries)

    grid: list[dict] = []
    for k1 in k1_values:
        for b in b_values:
            total = 0.0
            for entry in queries.values():
                ranked = [
                    result.doc_id
                    for result in ranked_search(index, entry["query"], k=k, k1=k1, b=b)
                ]
                total += ndcg_at_k(ranked, entry["relevant"], k)
            mean_ndcg = total / n_queries if n_queries else 0.0
            grid.append({"k1": float(k1), "b": float(b), "ndcg10": float(mean_ndcg)})

    best = max(grid, key=lambda cell: (cell["ndcg10"], -cell["k1"], -cell["b"]))
    best = {"k1": best["k1"], "b": best["b"], "ndcg10": best["ndcg10"]}

    return {
        "grid": grid,
        "best": best,
        "n_queries": n_queries,
        "k": k,
        "corpus_version": _read_corpus_version(index_dir),
        "index_dir": str(index_dir) if index_dir is not None else None,
    }


# --------------------------------------------------------------------------
# CLI -- `python -m onrecord.eval.sweep`
# --------------------------------------------------------------------------


def _plot_heatmap(result: dict, out_path: Path) -> None:
    """Render a k1/b NDCG@10 heatmap PNG next to the JSON artifact.

    `matplotlib` is imported here, inside the `--plot` branch only, so the
    frozen (non-`--plot`) artifact path never touches it (dev-only dep;
    font/renderer output is nondeterministic and not exercised by tests).
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    k1_axis = sorted({cell["k1"] for cell in result["grid"]})
    b_axis = sorted({cell["b"] for cell in result["grid"]})
    values = {(cell["k1"], cell["b"]): cell["ndcg10"] for cell in result["grid"]}
    matrix = [[values[(k1, b)] for b in b_axis] for k1 in k1_axis]

    fig, ax = plt.subplots()
    im = ax.imshow(matrix, aspect="auto", origin="lower")
    ax.set_xticks(range(len(b_axis)), [f"{b:.2f}" for b in b_axis], rotation=90)
    ax.set_yticks(range(len(k1_axis)), [f"{k1:.2f}" for k1 in k1_axis])
    ax.set_xlabel("b")
    ax.set_ylabel("k1")
    ax.set_title("NDCG@k mean by (k1, b)")
    fig.colorbar(im, ax=ax, label="mean NDCG@k")
    fig.tight_layout()

    png_path = out_path.with_suffix(".png")
    fig.savefig(png_path)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m onrecord.eval.sweep",
        description="k1/b NDCG@10 grid sweep over the judgment set.",
    )
    parser.add_argument("--index", required=True, help="index directory (InvertedIndex.load)")
    parser.add_argument("--judgments", required=True, help="judgments JSONL path")
    parser.add_argument("--out", required=True, help="JSON artifact output path")
    parser.add_argument(
        "--plot", action="store_true", default=False, help="also render a heatmap PNG"
    )
    args = parser.parse_args(argv)

    from onrecord.index.inverted import InvertedIndex

    index = InvertedIndex.load(args.index)
    result = sweep(index, args.judgments, index_dir=args.index)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result), encoding="utf-8")

    if args.plot:
        _plot_heatmap(result, out_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())

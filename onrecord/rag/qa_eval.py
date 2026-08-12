"""QA + unanswerable eval sets, refusal / false-refusal / answer-recall
runner (T-025).

Frozen contract lives in `tests/unit/rag/test_qa_eval.py`'s module
docstring -- this implementation satisfies it. Summary:

    def load_qa(path) -> list[dict]: ...
    def load_unanswerable(path) -> list[dict]: ...
    def derive_qa_from_judgments(judgments_path, answer_grade: int = 2) -> list[dict]: ...
    def evaluate_refusal(answer_fn, answerable_rows, unanswerable_rows) -> dict: ...
    def answer_recall(qa_rows, retrieve_fn, k: int = 10, chunk_doc_ids=None) -> dict: ...
    def main(argv: list[str] | None = None) -> int: ...

Regenerate the committed `evalsets/qa.jsonl` deliverable (a transformer
output over `evalsets/judgments.jsonl`, never hand-edited) with:

    uv run python -c "
    import json
    from onrecord.rag.qa_eval import derive_qa_from_judgments
    rows = derive_qa_from_judgments('evalsets/judgments.jsonl')
    with open('evalsets/qa.jsonl', 'w') as fh:
        for row in rows:
            fh.write(json.dumps(row) + '\n')
    "

CONTRACT COUPLING: this module is CONTRACT-coupled to T-023, never
code-coupled -- it consumes answers as plain dicts of the pinned
`/api/answer` shape via an injected `answer_fn(question) -> dict`; refusal
detection is simply `row["refusal"] is not None`. This module never imports
`onrecord.rag.answer` at module scope; `_resolve_answer_fn` does so lazily,
inside its own body, only when the CLI's `--kind refusal` path actually
runs `main()` for real (plan-review I-9 -- T-023 is same-wave and may be
unmerged while this ticket is implemented).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

DEFAULT_ARTIFACT_PATH = "artifacts/rag_eval.jsonl"

_UNANSWERABLE_REASONS = {"out-of-corpus", "out-of-scope", "false-premise"}
_QA_ORIGINS = {"judgments", "owner"}


# --------------------------------------------------------------------------
# AC-1 -- schema-validating JSONL loaders
# --------------------------------------------------------------------------


def _require_non_empty_str(row: dict, field: str, line_no: int) -> str:
    if field not in row:
        raise ValueError(f"line {line_no}: missing required field {field!r}")
    value = row[field]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"line {line_no}: field {field!r} must be a non-empty string")
    return value


def _parse_row(line: str, line_no: int) -> dict:
    """Parse one JSONL line into a dict, wrapping json's own exceptions in a
    ValueError that names THIS file's 1-indexed line number (json's own
    line/column describe a position within the single line string handed to
    it, which would misname the real broken line)."""
    try:
        row = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError(f"line {line_no}: invalid JSON ({exc})") from None
    if not isinstance(row, dict):
        raise ValueError(f"line {line_no}: row is not a JSON object")
    return row


def _iter_nonblank_lines(path: str | Path):
    with Path(path).open(encoding="utf-8") as fh:
        for line_no, raw_line in enumerate(fh, start=1):
            stripped = raw_line.strip()
            if not stripped:
                continue
            yield line_no, stripped


def load_qa(path: str | Path) -> list[dict]:
    """Schema-validating loader for qa.jsonl-shaped files. Blank/whitespace
    lines are skipped silently; every other malformed line raises
    `ValueError` naming the 1-indexed line number and offending field --
    never a silent skip (eval sets are graded artifacts)."""
    rows: list[dict] = []
    for line_no, line in _iter_nonblank_lines(path):
        row = _parse_row(line, line_no)

        _require_non_empty_str(row, "qa_id", line_no)
        _require_non_empty_str(row, "question", line_no)
        _require_non_empty_str(row, "criterion", line_no)

        if "answer_doc_ids" not in row:
            raise ValueError(f"line {line_no}: missing required field 'answer_doc_ids'")
        answer_doc_ids = row["answer_doc_ids"]
        if (
            not isinstance(answer_doc_ids, list)
            or not answer_doc_ids
            or not all(isinstance(doc_id, str) for doc_id in answer_doc_ids)
        ):
            raise ValueError(
                f"line {line_no}: field 'answer_doc_ids' must be a non-empty list of strings"
            )

        origin = row.get("origin")
        if origin not in _QA_ORIGINS:
            raise ValueError(
                f"line {line_no}: field 'origin' must be one of {sorted(_QA_ORIGINS)}, "
                f"got {origin!r}"
            )

        rows.append(row)
    return rows


def load_unanswerable(path: str | Path) -> list[dict]:
    """Schema-validating loader for unanswerable.jsonl-shaped files. Same
    blank-line-tolerant / malformed-line-raises contract as `load_qa`."""
    rows: list[dict] = []
    for line_no, line in _iter_nonblank_lines(path):
        row = _parse_row(line, line_no)

        _require_non_empty_str(row, "qa_id", line_no)
        _require_non_empty_str(row, "question", line_no)
        _require_non_empty_str(row, "notes", line_no)

        reason = row.get("reason")
        if reason not in _UNANSWERABLE_REASONS:
            raise ValueError(
                f"line {line_no}: field 'reason' must be one of {sorted(_UNANSWERABLE_REASONS)}, "
                f"got {reason!r}"
            )

        rows.append(row)
    return rows


# --------------------------------------------------------------------------
# AC-4 -- derive_qa_from_judgments
# --------------------------------------------------------------------------


def derive_qa_from_judgments(judgments_path: str | Path, answer_grade: int = 2) -> list[dict]:
    """Groups judgment rows (`{"query_id", "query", "criterion", "doc_id",
    "grade"}`) by `query_id`. A query_id qualifies iff >=1 of its doc rows
    has `grade >= answer_grade`; non-qualifying query_ids are skipped.
    Deterministic: row order = first-appearance order of each qualifying
    query_id in the judgments file; `answer_doc_ids` order = file order of
    the qualifying doc rows (never sorted, never grade-ordered). Questions,
    criteria, and doc ids are copied VERBATIM -- byte-identical, never
    re-minted/re-cased (T-020's C-1 precedent)."""
    order: list[str] = []
    queries: dict[str, dict] = {}

    with Path(judgments_path).open(encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            query_id = row["query_id"]
            if query_id not in queries:
                order.append(query_id)
                queries[query_id] = {
                    "query": row["query"],
                    "criterion": row["criterion"],
                    "answer_doc_ids": [],
                }
            if row["grade"] >= answer_grade:
                queries[query_id]["answer_doc_ids"].append(row["doc_id"])

    return [
        {
            "qa_id": query_id,
            "question": queries[query_id]["query"],
            "criterion": queries[query_id]["criterion"],
            "answer_doc_ids": queries[query_id]["answer_doc_ids"],
            "origin": "judgments",
        }
        for query_id in order
        if queries[query_id]["answer_doc_ids"]
    ]


# --------------------------------------------------------------------------
# AC-2 -- evaluate_refusal
# --------------------------------------------------------------------------


def evaluate_refusal(
    answer_fn: Callable[[str], dict],
    answerable_rows: list[dict],
    unanswerable_rows: list[dict],
) -> dict:
    """Calls `answer_fn(row["question"])` once per row across both lists and
    inspects only `result["refusal"]` (`is not None` => refused). Both rate
    denominators are ALWAYS the corresponding list's total length, never
    reduced when zero items were refused. `per_item` order: every
    unanswerable_rows entry (input order), THEN every answerable_rows entry
    (input order)."""
    per_item: list[dict] = []

    unanswerable_refused = 0
    for row in unanswerable_rows:
        refused = answer_fn(row["question"])["refusal"] is not None
        unanswerable_refused += int(refused)
        per_item.append({"qa_id": row["qa_id"], "kind": "unanswerable", "refused": refused})

    answerable_refused = 0
    for row in answerable_rows:
        refused = answer_fn(row["question"])["refusal"] is not None
        answerable_refused += int(refused)
        per_item.append({"qa_id": row["qa_id"], "kind": "answerable", "refused": refused})

    n_unanswerable = len(unanswerable_rows)
    n_answerable = len(answerable_rows)

    return {
        "refusal_rate": (unanswerable_refused / n_unanswerable) if n_unanswerable else 0.0,
        "false_refusal_rate": (answerable_refused / n_answerable) if n_answerable else 0.0,
        "per_item": per_item,
        "n_answerable": n_answerable,
        "n_unanswerable": n_unanswerable,
    }


# --------------------------------------------------------------------------
# AC-3 -- answer_recall
# --------------------------------------------------------------------------


def _identity_chunk_doc_ids(chunk_or_doc_id: str) -> list[str]:
    return [chunk_or_doc_id]


def answer_recall(
    qa_rows: list[dict],
    retrieve_fn: Callable[[str], list[str]],
    k: int = 10,
    chunk_doc_ids: Callable[[str], list[str]] | None = None,
) -> dict:
    """Per row: `retrieved = retrieve_fn(row["question"])[:k]`. A labeled
    answer doc counts as retrieved iff it appears literally among
    `retrieved`, OR it appears in `chunk_doc_ids(r)` for some `r` in
    `retrieved`. `chunk_doc_ids` defaults to identity -- a merged/chunk-style
    id does NOT retroactively resolve into constituent doc ids unless an
    explicit resolver is injected. Per-row recall = |hits| / |answer_doc_ids|;
    `mean_recall` is the mean over ALL qa_rows, including zero-recall rows."""
    resolver = chunk_doc_ids if chunk_doc_ids is not None else _identity_chunk_doc_ids

    per_query: list[dict] = []
    total_recall = 0.0

    for row in qa_rows:
        retrieved = retrieve_fn(row["question"])[:k]
        resolved_ids: set[str] = set()
        for retrieved_id in retrieved:
            resolved_ids.update(resolver(retrieved_id))

        answer_doc_ids = row["answer_doc_ids"]
        hits = sum(1 for doc_id in answer_doc_ids if doc_id in retrieved or doc_id in resolved_ids)
        recall = hits / len(answer_doc_ids)
        total_recall += recall
        per_query.append({"qa_id": row["qa_id"], "recall": recall})

    n_queries = len(qa_rows)
    mean_recall = (total_recall / n_queries) if n_queries else 0.0

    return {
        "mean_recall": mean_recall,
        "k": k,
        "n_queries": n_queries,
        "per_query": per_query,
    }


# --------------------------------------------------------------------------
# AC-5 -- CLI main()
# --------------------------------------------------------------------------


def _git_sha() -> str:
    """Best-effort HEAD SHA; mirrors `onrecord.eval.run._git_sha` byte-for-byte."""
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


def _corpus_version(manifest_dir: str | None) -> str:
    """Tolerant `corpus_version` read via T-018's `read_manifest`, mirroring
    `onrecord.eval.run._corpus_version` / `chunk_sweep._corpus_version`.
    `manifest_dir=None` or any read failure yields `"unversioned"`."""
    if manifest_dir is None:
        return "unversioned"

    from onrecord.ingest.build_corpus import read_manifest

    manifest = read_manifest(manifest_dir)
    if manifest is None:
        return "unversioned"
    version = manifest.get("corpus_version", "unversioned")
    return version if isinstance(version, str) else "unversioned"


def _resolve_answer_fn() -> Callable[[str], dict]:
    """Real-pipeline wiring seam (plan-review I-9). LAZILY imports
    `onrecord.rag.answer` + retrieval inside this function body -- safe only
    because this CLI runs post-wave-9-merge and post-provisioning (T-023 is
    same-wave and may be unmerged during this ticket's implementation; a
    module-level import would be a collection error in this worktree). Tests
    monkeypatch this attribute wholesale and never call the real body."""
    from onrecord.rag.answer import answer as _answer  # pragma: no cover

    def _answer_fn(question: str) -> dict:  # pragma: no cover
        return _answer(question)

    return _answer_fn


_DEFAULT_INDEX_PATH = "artifacts/index"


def _resolve_retrieve_fn(k: int = 10) -> Callable[[str], list[str]]:
    """Real-pipeline wiring seam for `--kind answer_recall`, symmetric with
    `_resolve_answer_fn`. LAZILY imports the already-frozen BM25 ranked
    search pipeline (`onrecord.index.inverted.InvertedIndex` +
    `onrecord.search.ranked.ranked_search`, the same pair
    `onrecord.eval.run` / `onrecord.rag.chunk_sweep` wire against) inside
    this function body, for the same collection-safety reason as
    `_resolve_answer_fn`.

    `k` is the CALLING CONVENTION `main()` must thread through (review
    finding C-1: a `_resolve_retrieve_fn()` called with no arguments left
    the real retrieval depth hardcoded at 10 no matter what `--k` requested,
    while the emitted artifact stamped whatever `--k` was passed regardless
    -- a graded artifact lying about its own parameters). The returned
    closure is built AT depth `k`, not merely truncated to it afterward, so
    a retrieval backend that only ever fetches its first 10 candidates
    cannot silently satisfy a `--k 50` request.

    The seam's internal lazy imports / index load / closure body are
    deliberately NOT exercised by the frozen test suite (module docstring:
    "orchestrator-eval territory") -- unlike `_resolve_answer_fn`, this
    file's tests monkeypatch the whole seam rather than calling into it, but
    they DO pin the `k` calling convention (see
    `test_cli_answer_recall_kind_threads_k_into_resolve_retrieve_fn_seam`)."""
    from onrecord.index.inverted import InvertedIndex  # pragma: no cover
    from onrecord.search.ranked import ranked_search  # pragma: no cover

    index = InvertedIndex.load(_DEFAULT_INDEX_PATH)  # pragma: no cover

    def _retrieve_fn(question: str) -> list[str]:  # pragma: no cover
        return [result.doc_id for result in ranked_search(index, question, k=k)]

    return _retrieve_fn  # pragma: no cover


def _append_artifact_row(out_path: Path, row: dict) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m onrecord.rag.qa_eval",
        description=(
            "Run the refusal/false-refusal or answer-recall eval and append a "
            "row to the shared artifacts/rag_eval.jsonl sidecar."
        ),
    )
    parser.add_argument(
        "--kind",
        required=True,
        choices=["refusal", "answer_recall"],
        help="which eval to run",
    )
    parser.add_argument("--qa", required=True, help="path to a qa.jsonl-shaped file")
    parser.add_argument(
        "--unanswerable",
        default=None,
        help="path to an unanswerable.jsonl-shaped file (required for --kind refusal)",
    )
    parser.add_argument(
        "--out",
        default=DEFAULT_ARTIFACT_PATH,
        help=f"output JSONL path, appended not truncated (default {DEFAULT_ARTIFACT_PATH})",
    )
    parser.add_argument(
        "--manifest-dir",
        dest="manifest_dir",
        default=None,
        help="index manifest dir for the corpus_version stamp (T-018's manifest.json)",
    )
    parser.add_argument("--k", type=int, default=10, help="answer_recall depth (default 10)")
    args = parser.parse_args(argv)

    out_path = Path(args.out)

    if args.kind == "refusal":
        if args.unanswerable is None:
            sys.stderr.write("onrecord.rag.qa_eval: --kind refusal requires --unanswerable\n")
            return 1

        answerable_rows = load_qa(args.qa)
        unanswerable_rows = load_unanswerable(args.unanswerable)
        answer_fn = _resolve_answer_fn()
        metrics = evaluate_refusal(answer_fn, answerable_rows, unanswerable_rows)
        kind = "refusal"
    else:
        qa_rows = load_qa(args.qa)
        retrieve_fn = _resolve_retrieve_fn(args.k)
        metrics = answer_recall(qa_rows, retrieve_fn, k=args.k)
        kind = "answer_recall"

    row = {
        "timestamp": datetime.now(UTC).isoformat(),
        "git_sha": _git_sha(),
        "corpus_version": _corpus_version(args.manifest_dir),
        "kind": kind,
        "metrics": metrics,
    }
    _append_artifact_row(out_path, row)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Blind, shuffled judgment-collection CLI (T-009).

Interactive tool for building an honest judgment set: prompts for the
relevance criterion BEFORE any candidate is shown, then shows each pooled
candidate's text with no score/source/rank attached, takes a 0/1/2/skip
grade, and appends well-formed rows to a JSONL file. Resumable -- already
judged (query_id, doc_id) pairs are skipped on rerun.

Usage:
    python -m onrecord.eval.judgments --query "..." --query-id q1 \\
        --corpus path/to/corpus.jsonl --out evalsets/judgments.jsonl

See `tests/unit/test_judgments.py`'s module docstring for the exact, frozen
CLI flag set and session I/O contract this implements.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from onrecord.eval.pooling import pool_candidates


def _load_judged_pairs(out_path: Path) -> set[tuple[str, str]]:
    """Return the set of already-judged (query_id, doc_id) pairs in out_path."""
    if not out_path.exists():
        return set()
    judged: set[tuple[str, str]] = set()
    with out_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            judged.add((row["query_id"], row["doc_id"]))
    return judged


def _find_stored_criterion(out_path: Path, query_id: str) -> str | None:
    """Return the criterion of the first (file-order) existing row in
    out_path whose query_id matches, or None if out_path is missing or has
    no such row.
    """
    if not out_path.exists():
        return None
    with out_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if row["query_id"] == query_id:
                return row["criterion"]
    return None


def run_judging_session(
    query: str,
    query_id: str,
    corpus_path: str,
    out_path: str | Path,
    k_per_source: int,
    seed: int,
    amend_criterion: bool = False,
) -> int:
    """Run one interactive judging session; returns 0 on success.

    1. Prompt for and capture the relevance criterion (stdout, before any
       candidate text is shown -- AC-4).
    2. Criterion-drift guard: if a criterion is already on file for this
       query_id and the freshly typed one differs, refuse (stderr,
       "CRITERION MISMATCH", nonzero return, zero rows written) unless
       `amend_criterion` is set, in which case proceed with the new
       criterion applied to every row written this session.
    3. Pool candidates and drop any whose (query_id, doc.id) is already
       judged in out_path (AC-3, resumable).
    4. For each remaining candidate, print its text, prompt for a grade
       (0/1/2/s), and append a JSONL row on 0/1/2; "s"/"S" skips silently.
    """
    criterion = input("Relevance criterion: ")

    out_path = Path(out_path)
    stored_criterion = _find_stored_criterion(out_path, query_id)
    if stored_criterion is not None and stored_criterion != criterion and not amend_criterion:
        print(
            "CRITERION MISMATCH for query_id="
            f"{query_id!r}: stored criterion is {stored_criterion!r}, "
            f"freshly typed criterion is {criterion!r}. Refusing to resume "
            "under a materially different criterion -- pass --amend-criterion "
            "to proceed anyway (new rows will carry the new criterion; "
            "already-judged rows are left untouched).",
            file=sys.stderr,
        )
        return 1

    candidates = pool_candidates(query, corpus_path, k_per_source, seed)

    judged_pairs = _load_judged_pairs(out_path)
    remaining = [c for c in candidates if (query_id, c.id) not in judged_pairs]

    if remaining:
        out_path.parent.mkdir(parents=True, exist_ok=True)

    for candidate in remaining:
        print(candidate.text)
        grade_input = input("Grade (0/1/2/s=skip): ").strip()
        if grade_input.lower() == "s":
            continue
        if grade_input not in ("0", "1", "2"):
            # Defensive: ignore unrecognized input rather than crash the
            # session; nothing in the frozen contract specifies a retry loop.
            continue
        row = {
            "query_id": query_id,
            "query": query,
            "criterion": criterion,
            "doc_id": candidate.id,
            "grade": int(grade_input),
        }
        with out_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m onrecord.eval.judgments",
        description="Blind, shuffled judgment-collection CLI for onrecord.",
    )
    parser.add_argument("--query", required=True, help="the query string")
    parser.add_argument(
        "--query-id",
        required=True,
        help="short stable id for this query, e.g. 'q1'",
    )
    parser.add_argument(
        "--corpus",
        required=True,
        help="path to the corpus JSONL, passed through to pool_candidates",
    )
    parser.add_argument("--out", required=True, help="path to the judgments JSONL file")
    parser.add_argument("--k-per-source", type=int, default=10, help="candidates per source")
    parser.add_argument("--seed", type=int, default=0, help="seed for pooling RNG")
    parser.add_argument(
        "--amend-criterion",
        action="store_true",
        default=False,
        help=(
            "allow resuming this query_id under a criterion that differs from "
            "what's already on file; new rows carry the new criterion"
        ),
    )

    args = parser.parse_args(argv)

    return run_judging_session(
        query=args.query,
        query_id=args.query_id,
        corpus_path=args.corpus,
        out_path=args.out,
        k_per_source=args.k_per_source,
        seed=args.seed,
        amend_criterion=args.amend_criterion,
    )


if __name__ == "__main__":
    sys.exit(main())

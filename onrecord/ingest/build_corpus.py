"""`make ingest` entrypoint / corpus-v1 builder (T-010; tickets/T-010.md
AC-1; contracts #1/#2 in tests/integration/test_e2e.py's module docstring).

Merges every `*.jsonl` file discovered recursively under `--raw-dir`
(adapters write into per-source subdirectories, e.g. `DIR/youtube/*.jsonl`,
`DIR/edgar/*.jsonl` -- processed in sorted-path order for determinism) into
one corpus, writes it gzip-compressed newline-delimited JSON to
`<out>/corpus.jsonl.gz`, and builds + `.save()`s an `InvertedIndex` (real
analyzer, i.e. `InvertedIndex.build(docs)` with `analyzer=None`) to
`--index-out`.

Row schema (shared by raw-dir input rows, corpus.jsonl.gz output rows, and
the committed `corpus/v1/corpus.jsonl.gz` snapshot itself): one JSON object
per line, keys == `onrecord.types.Doc` field names exactly. The three
optional fields (`ticker`, `jurisdiction`, `speaker`) may be omitted or
`null`. A row is malformed -- skipped, with a logged warning, run continues
-- when the line is not valid JSON, or any *required* field (`id`, `text`,
`source_type`, `venue_type`, `date`, `deep_link`) is missing or `null`. An
unrecognized extra key is ignored, not fatal. A blank/whitespace-only line
is skipped silently (not counted as malformed, not logged).

`load_corpus_snapshot` (below) reads that same row schema back out of a
gzipped snapshot -- shared by `onrecord.cli`'s offline clean-clone fallback
(building an in-memory index from `corpus/v1/corpus.jsonl.gz` when no
`artifacts/index` exists yet).
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import sys
from collections.abc import Iterable, Iterator
from dataclasses import asdict
from pathlib import Path

from onrecord.index.inverted import InvertedIndex
from onrecord.types import Doc

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ("id", "text", "source_type", "venue_type", "date", "deep_link")
OPTIONAL_FIELDS = ("ticker", "jurisdiction", "speaker")

DEFAULT_RAW_DIR = "corpus/raw"
DEFAULT_OUT_DIR = "corpus/v1"
DEFAULT_INDEX_OUT = "artifacts/index"


def _parse_jsonl_lines(lines: Iterable[str], source_label: str) -> Iterator[Doc]:
    """Parse an iterable of raw JSONL text lines into `Doc`s per the row
    schema (module docstring), skipping + logging malformed rows."""
    for lineno, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue  # blank line: skipped silently, not "malformed"
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("%s:%d: skipping malformed row (invalid JSON)", source_label, lineno)
            continue

        missing = [field for field in REQUIRED_FIELDS if row.get(field) is None]
        if missing:
            logger.warning(
                "%s:%d: skipping malformed row (missing/null required field(s): %s)",
                source_label,
                lineno,
                ", ".join(missing),
            )
            continue

        yield Doc(
            id=row["id"],
            text=row["text"],
            source_type=row["source_type"],
            venue_type=row["venue_type"],
            date=row["date"],
            deep_link=row["deep_link"],
            ticker=row.get("ticker"),
            jurisdiction=row.get("jurisdiction"),
            speaker=row.get("speaker"),
        )


def _iter_raw_dir_docs(raw_dir: Path) -> list[Doc]:
    """Recursively discover every `*.jsonl` under `raw_dir` (sorted-path
    order for determinism) and merge their well-formed rows."""
    if not raw_dir.exists():
        logger.warning("raw-dir does not exist: %s", raw_dir)
        return []

    docs: list[Doc] = []
    for path in sorted(raw_dir.rglob("*.jsonl")):
        with path.open("r", encoding="utf-8") as fh:
            docs.extend(_parse_jsonl_lines(fh, str(path)))
    return docs


def load_corpus_snapshot(path: str | Path) -> list[Doc]:
    """Read a gzipped corpus-v1 snapshot (row schema per module docstring)
    into `Doc`s, skipping malformed rows the same way `build_corpus` does.
    Returns `[]` if `path` doesn't exist (callers treat that as "no
    snapshot available" rather than an error)."""
    path = Path(path)
    if not path.exists():
        return []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return list(_parse_jsonl_lines(fh, str(path)))


def build_corpus(raw_dir: Path, out_dir: Path, index_out: Path) -> int:
    """Merge `raw_dir`'s JSONL rows into `<out_dir>/corpus.jsonl.gz` and
    build + save an `InvertedIndex` to `index_out`. Returns the process
    exit code: 0 on success (>=1 valid doc merged), 1 if none were found."""
    docs = _iter_raw_dir_docs(raw_dir)
    if not docs:
        logger.warning("no valid docs discovered under %s; nothing to build", raw_dir)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    corpus_path = out_dir / "corpus.jsonl.gz"
    with gzip.open(corpus_path, "wt", encoding="utf-8") as fh:
        for doc in docs:
            fh.write(json.dumps(asdict(doc)) + "\n")

    index = InvertedIndex.build(docs)
    index.save(index_out)

    print(f"onrecord.ingest.build_corpus: merged {len(docs)} doc(s) -> {corpus_path}")
    print(f"onrecord.ingest.build_corpus: index saved -> {index_out}")
    return 0


# --------------------------------------------------------------------------
# CLI entrypoint
# --------------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m onrecord.ingest.build_corpus",
        description=(
            "Merge raw-dir adapter JSONL output into a gzipped corpus-v1 "
            "snapshot and build + save an InvertedIndex over it."
        ),
    )
    parser.add_argument(
        "--raw-dir",
        default=DEFAULT_RAW_DIR,
        help=f"Recursively search this dir for *.jsonl adapter output (default: {DEFAULT_RAW_DIR})",
    )
    parser.add_argument(
        "--out",
        default=DEFAULT_OUT_DIR,
        help=f"Output directory for corpus.jsonl.gz (default: {DEFAULT_OUT_DIR})",
    )
    parser.add_argument(
        "--index-out",
        default=DEFAULT_INDEX_OUT,
        help=f"Output directory for the saved InvertedIndex (default: {DEFAULT_INDEX_OUT})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _parse_args(argv)
    return build_corpus(Path(args.raw_dir), Path(args.out), Path(args.index_out))


if __name__ == "__main__":
    sys.exit(main())

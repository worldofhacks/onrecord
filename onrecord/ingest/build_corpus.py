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
-- when the line is not valid JSON, OR the line is valid JSON but doesn't
decode to a JSON object (a list, bare number/string, or bare `null` --
anything whose Python type isn't `dict`; never an uncaught exception), OR
any *required* field (`id`, `text`, `source_type`, `venue_type`, `date`,
`deep_link`) is missing or `null`. An unrecognized extra key is ignored,
not fatal. A blank/whitespace-only line is skipped silently (not counted
as malformed, not logged).

`load_corpus_snapshot` (below) reads that same row schema back out of a
gzipped snapshot -- shared by `onrecord.cli`'s offline clean-clone fallback
(building an in-memory index from `corpus/v1/corpus.jsonl.gz` when no
`artifacts/index` exists yet).

Corpus-version manifest (T-018; tickets/T-018.md): every successful build
also writes `MANIFEST_FILENAME` (`manifest.json`) into BOTH the snapshot
`out_dir` and `index_out` -- the version travels with the built index since
`onrecord.eval.run` / `onrecord.api` read the index, not the snapshot, at
serve time. The manifest is a JSON object with exactly six keys:
`corpus_version` (`"v{N}"`), `created_at` (ISO-8601 UTC), `doc_count`
(rows successfully indexed), `source_counts` (`{source_type: n, ...}`,
summing to `doc_count`), `git_sha` (`HEAD` short-circuited via `git
rev-parse HEAD`, or the literal string `"unknown"` outside a git repo / on
any git failure), and `snapshot_sha256` (the sha256 hexdigest of the
written `corpus.jsonl.gz` file's bytes -- what lets a fetched/rebuilt
Release-asset snapshot be verified by hashing). The gzip itself is written
with a pinned `mtime=0` header so byte-identical raw input produces a
byte-identical `corpus.jsonl.gz` (and thus an equal `snapshot_sha256`)
regardless of wall-clock build time. `read_manifest(dir_path)` reads a
directory's `manifest.json` back out and is tolerant of every failure mode
(missing directory, missing file, corrupt JSON, or JSON that isn't an
object) -- it returns `None` rather than raising, so callers like
`onrecord.eval.run._corpus_version()` can treat "no manifest yet" as a
plain, ordinary case.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from onrecord.index.inverted import InvertedIndex
from onrecord.types import Doc

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ("id", "text", "source_type", "venue_type", "date", "deep_link")
OPTIONAL_FIELDS = ("ticker", "jurisdiction", "speaker")

DEFAULT_RAW_DIR = "corpus/raw"
DEFAULT_OUT_DIR = "corpus/v1"
DEFAULT_INDEX_OUT = "artifacts/index"
DEFAULT_VERSION = 1

MANIFEST_FILENAME = "manifest.json"


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

        if not isinstance(row, dict):
            logger.warning(
                "%s:%d: skipping malformed row (valid JSON but not an object: %s)",
                source_label,
                lineno,
                type(row).__name__,
            )
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


def _git_sha() -> str:
    """Best-effort HEAD SHA; falls back to `"unknown"` outside a git repo or
    on any git failure (mirrors `onrecord.eval.run._git_sha`)."""
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


def read_manifest(dir_path: str | Path) -> dict | None:
    """Read `MANIFEST_FILENAME` out of `dir_path`. Tolerant contract: never
    raises -- returns `None` for a missing directory, a missing manifest
    file, corrupt JSON, or JSON that decodes to something other than a
    (schema-unvalidated) object."""
    manifest_path = Path(dir_path) / MANIFEST_FILENAME
    try:
        with manifest_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _write_manifest(dir_path: Path, manifest: dict) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    manifest_path = dir_path / MANIFEST_FILENAME
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def build_corpus(
    raw_dir: Path, out_dir: Path, index_out: Path, version: int = DEFAULT_VERSION
) -> int:
    """Merge `raw_dir`'s JSONL rows into `<out_dir>/corpus.jsonl.gz` and
    build + save an `InvertedIndex` to `index_out`. On success, also writes
    the corpus-version `manifest.json` (module docstring) into BOTH
    `out_dir` and `index_out`. Returns the process exit code: 0 on success
    (>=1 valid doc merged), 1 if none were found."""
    docs = _iter_raw_dir_docs(raw_dir)
    if not docs:
        logger.warning("no valid docs discovered under %s; nothing to build", raw_dir)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    corpus_path = out_dir / "corpus.jsonl.gz"
    payload = "".join(json.dumps(asdict(doc)) + "\n" for doc in docs).encode("utf-8")
    # mtime=0 pins the gzip header so byte-identical raw input produces a
    # byte-identical corpus.jsonl.gz (and equal snapshot_sha256) regardless
    # of wall-clock build time (ORCHESTRATOR RULING, locked; see module
    # docstring).
    compressed = gzip.compress(payload, mtime=0)
    corpus_path.write_bytes(compressed)

    index = InvertedIndex.build(docs)
    index.save(index_out)

    source_counts = dict(Counter(doc.source_type for doc in docs))
    manifest = {
        "corpus_version": f"v{version}",
        "created_at": datetime.now(UTC).isoformat(),
        "doc_count": len(docs),
        "source_counts": source_counts,
        "git_sha": _git_sha(),
        "snapshot_sha256": hashlib.sha256(compressed).hexdigest(),
    }
    _write_manifest(out_dir, manifest)
    _write_manifest(index_out, manifest)

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
        "--version",
        type=int,
        default=DEFAULT_VERSION,
        help=(
            "Corpus version N (int, default: 1). Also derives --out's default "
            "as corpus/v{N} when --out is not explicitly given."
        ),
    )
    parser.add_argument(
        "--out",
        default=None,
        help=(
            f"Output directory for corpus.jsonl.gz (default: corpus/v{{version}}, "
            f"i.e. {DEFAULT_OUT_DIR} when --version is omitted). Explicit --out "
            "always wins over the derived default."
        ),
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
    out = args.out if args.out is not None else f"corpus/v{args.version}"
    return build_corpus(Path(args.raw_dir), Path(out), Path(args.index_out), version=args.version)


if __name__ == "__main__":
    sys.exit(main())

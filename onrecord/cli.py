"""`onrecord` CLI -- `search` and `demo` subcommands (design spec Sec 3/7).

Wired up by T-010. Pinned contract (tests/integration/test_e2e.py's module
docstring, points 3/4):

- `search "QUERY" [--op AND|OR] [--phrase] [--k N] [--source TYPE]
  [--index DIR]`: `--index` defaults to `artifacts/index`, `--op` defaults
  to `AND`, `--k` defaults to 10 (top-K truncation happens after
  retrieval). `--source` filters the retrieved hits by `Doc.source_type`
  (a post-retrieval metadata filter, not a query-term restriction).
  `--phrase` runs `phrase_search` instead of `boolean_search`/`--op`. On
  >=1 result: a one-line summary containing `results for "QUERY"`,
  followed by one block per ranked result (rank starting at 1) with
  substrings `id=<id>`, `date=<date>`, the verbatim `deep_link`, the doc's
  jurisdiction-or-ticker-or-`-`, and a snippet prefix. On 0 results
  (empty query / all-terms-absent / tokenizes to nothing): a message
  containing `No results`, exit 0 always for a syntactically valid call --
  a 0-result search is never an error.
- `demo [--index DIR]`: runs exactly 3 canned queries against `--index`
  (default `artifacts/index`); if that path doesn't exist, builds an
  in-memory index from the committed snapshot `corpus/v1/corpus.jsonl.gz`
  instead of failing (the offline clean-clone fallback AC-4 exercises).
  Each query's output block is introduced by the literal marker substring
  `[demo] query "` immediately followed by the query text and a closing
  `"`. Same graceful zero-result behavior as `search` per query. Exit 0
  always.

Both subcommands share `_load_index`, which falls back through the
committed corpus-v1 snapshot -- and finally to an empty index -- rather
than raising when the on-disk artifact is absent, so an absent/never-built
index degrades to a graceful "No results" instead of a crash.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from onrecord.index.inverted import InvertedIndex
from onrecord.ingest.build_corpus import load_corpus_snapshot
from onrecord.search.boolean import boolean_search, phrase_search
from onrecord.types import Doc, SearchResult

DEFAULT_INDEX_DIR = "artifacts/index"
DEFAULT_SNAPSHOT_PATH = "corpus/v1/corpus.jsonl.gz"
DEFAULT_K = 10

# Canned demo queries -- exact text is the implementer's choice per the
# pinned contract; chosen to be meaningful over the fixture/registry corpus
# (substation buildout, earnings-call color, filing risk factors) while
# staying robust to a 0-result outcome on a tiny/empty snapshot.
DEMO_QUERIES = ("substation", "earnings call", "interconnection queue")


# --------------------------------------------------------------------------
# shared index loading / query execution / formatting
# --------------------------------------------------------------------------


def _load_index(index_dir: Path) -> InvertedIndex:
    """Load the index at `index_dir`; if that artifact is missing, build an
    in-memory index from the committed corpus-v1 snapshot instead (the
    offline clean-clone fallback shared by `search` and `demo` -- AC-4). If
    the snapshot is also absent, falls back to an empty index, which
    resolves to a graceful zero-result search rather than a crash."""
    if index_dir.exists():
        return InvertedIndex.load(index_dir)
    docs = load_corpus_snapshot(DEFAULT_SNAPSHOT_PATH)
    return InvertedIndex.build(docs)


def _run_query(
    index: InvertedIndex,
    query: str,
    *,
    op: str,
    phrase: bool,
    k: int,
    source: str | None,
) -> list[SearchResult]:
    if phrase:
        results = phrase_search(index, query)
    else:
        results = boolean_search(index, query, op)

    if source:
        results = [r for r in results if index.get_doc(r.doc_id).source_type == source]

    return results[:k]


def _jurisdiction_or_ticker(doc: Doc) -> str:
    if doc.jurisdiction:
        return doc.jurisdiction
    if doc.ticker:
        return doc.ticker
    return "-"


def _print_results(query: str, results: list[SearchResult], index: InvertedIndex) -> None:
    if not results:
        print(f'No results for "{query}"')
        return

    print(f'{len(results)} results for "{query}"')
    for rank, result in enumerate(results, start=1):
        doc = index.get_doc(result.doc_id)
        loc = _jurisdiction_or_ticker(doc)
        print(f"  {rank}. id={doc.id} date={doc.date} source={doc.source_type} loc={loc}")
        print(f"     {doc.deep_link}")
        snippet = result.snippet.strip().replace("\n", " ")
        if snippet:
            print(f"     {snippet}")


# --------------------------------------------------------------------------
# subcommands
# --------------------------------------------------------------------------


def _cmd_search(args: argparse.Namespace) -> int:
    index = _load_index(Path(args.index))
    results = _run_query(
        index, args.query, op=args.op, phrase=args.phrase, k=args.k, source=args.source
    )
    _print_results(args.query, results, index)
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    index = _load_index(Path(args.index))
    for query in DEMO_QUERIES:
        print(f'[demo] query "{query}"')
        results = _run_query(index, query, op="AND", phrase=False, k=DEFAULT_K, source=None)
        _print_results(query, results, index)
        print()
    return 0


# --------------------------------------------------------------------------
# argument parsing / entrypoint
# --------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m onrecord.cli",
        description="onrecord search CLI (design spec Sec 3/7).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    search_p = subparsers.add_parser("search", help="Run a query against a saved index.")
    search_p.add_argument("query", help="Query text")
    search_p.add_argument("--op", choices=["AND", "OR"], default="AND", help="Boolean op (default: AND)")
    search_p.add_argument(
        "--phrase", action="store_true", help="Run an exact-phrase query instead of --op boolean"
    )
    search_p.add_argument("--k", type=int, default=DEFAULT_K, help=f"Max results (default: {DEFAULT_K})")
    search_p.add_argument("--source", default=None, help="Filter results to this Doc.source_type")
    search_p.add_argument(
        "--index", default=DEFAULT_INDEX_DIR, help=f"Index directory (default: {DEFAULT_INDEX_DIR})"
    )
    search_p.set_defaults(func=_cmd_search)

    demo_p = subparsers.add_parser(
        "demo", help="Run 3 canned queries (offline fallback from corpus/v1 snapshot)."
    )
    demo_p.add_argument(
        "--index", default=DEFAULT_INDEX_DIR, help=f"Index directory (default: {DEFAULT_INDEX_DIR})"
    )
    demo_p.set_defaults(func=_cmd_demo)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

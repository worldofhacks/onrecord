# T-010 Test Report — Integration (CLI search, corpus-v1 build, clean clone)

**Status:** DONE (RED — as required, no implementation exists yet)
**Branch:** `ticket/T-010-integration`
**Worktree:** `/Users/quietguy/Documents/Dev/Gauntlet/wt-T-010`

## Summary

Wrote `tests/integration/test_e2e.py` encoding tickets/T-010.md AC-1..AC-4,
plus `tests/integration/__init__.py`. Nothing under `onrecord/` was touched
(`onrecord/cli.py` and `onrecord/ingest/build_corpus.py` remain the
signature-only stubs merged from T-001/Wave-2).

All 4 ACs build fixture corpora from real, merged Wave-2 modules
(`onrecord.types.Doc`, the real `InvertedIndex.build`/`.save`/`.load`, the
real analyzer via `analyzer=None`) — nothing here is mocked. AC-2/AC-3
build their index directly via `InvertedIndex.build(...).save(...)`,
bypassing `build_corpus`, so a `cli.py`-only bug can't be confused with a
`build_corpus.py` bug; AC-1 is the one test that exercises `build_corpus`
end-to-end (raw-dir JSONL → gzip corpus + saved index), per the ticket's own
wording.

## Contracts pinned (module docstring of test_e2e.py — authoritative for the
implementer)

1. **Adapter-output / corpus-snapshot JSONL row schema**: one JSON object
   per line, keys == `Doc` field names exactly. Required fields
   (`id`/`text`/`source_type`/`venue_type`/`date`/`deep_link`) missing/null,
   or invalid JSON → malformed → skip + log, never crash, never change exit
   code. Blank lines silently skipped (not "malformed").
2. **`build_corpus --raw-dir DIR --out OUTDIR --index-out INDEXDIR`**:
   recursively discovers `*.jsonl` anywhere under `DIR` (sorted-path order),
   merges well-formed rows into `<OUTDIR>/corpus.jsonl.gz` (gzip NDJSON,
   same schema), builds + `.save()`s an `InvertedIndex` to `INDEXDIR`. Exit
   0 on success (>=1 valid doc).
3. **`cli.py search "QUERY" [--op AND|OR] [--phrase] [--k N] [--source
   TYPE] [--index DIR]`**: defaults `--index=artifacts/index`, `--op=AND`,
   `--k=10`. `--source` filters retrieved hits by `Doc.source_type` (post-
   retrieval metadata filter). >=1 result → summary line containing
   `results for "QUERY"` + per-result block with substrings `id=<id>`,
   `date=<date>`, verbatim `deep_link`, jurisdiction-or-ticker-or-`-`, and a
   snippet prefix (tests assert substring containment only, never exact
   layout). 0 results (empty/absent-term/unicode-junk query) → message
   containing `No results`, exit 0 always for a syntactically valid call.
4. **`cli.py demo [--index DIR]`**: exactly 3 canned queries (text is
   implementer's choice) against `--index` (default `artifacts/index`);
   builds in-memory from `corpus/v1/corpus.jsonl.gz` if that path is
   missing (the offline clean-clone fallback). Each query block introduced
   by literal marker substring `[demo] query "` (asserted to occur exactly
   3 times — text itself unpinned). Exit 0 always.
5. **AC-4 hermeticity design**: the test clones the current worktree via
   `git clone file://<worktree>`, then — regardless of whether a real
   snapshot happens to already be committed — writes its own tiny 5-doc
   `corpus/v1/corpus.jsonl.gz` into the clone before `make setup && make
   demo`, so the test never depends on snapshot timing/content. The real
   snapshot committed later tonight supersedes this fixture but exercises
   the identical code path.

## Fixture corpus

`_fixture_docs()` builds 20 `Doc`s: 8 `county_meeting` (jurisdiction set,
venue `sworn`, youtube-style deep links), 6 `earnings_call` (ticker set,
venue `coached`, FMP-style deep links), 6 `filing` (ticker set, venue
`coached`, EDGAR-style deep links). 9 of the 20 mention "substation" spread
across all 3 source types (4 county / 2 earnings / 3 filing) — gives AC-1 a
real cross-source AND query and AC-2 a meaningful filter (9 unfiltered → 4
county-only).

## Malformed-row coverage (AC-1)

Appended to one raw-dir JSONL batch: a blank line (silently skipped), an
invalid-JSON line, and a valid-JSON row missing the required `text` field.
Test asserts the merged corpus contains exactly the 20 well-formed docs
(malformed rows counted neither as extra docs nor as a build failure).

## Run output

```
$ uv run pytest tests/integration/test_e2e.py -v
... 6 failed (see below), 0 errors ...

$ uv run pytest -q         # full repo suite
6 failed, 173 passed in 4.30s
```

All 6 failures are `AssertionError` (returncode 1/2 vs expected 0, or
missing expected stdout substrings) surfaced through the current
`onrecord.cli` / `onrecord.ingest.build_corpus` "not implemented" stubs —
never an import error, never an unhandled exception/traceback in the test
process itself. This is the correct RED state: 173 previously-passing
tests stay green; only the 6 new integration tests fail, cleanly.

Failing tests:
- `test_ac1_build_corpus_then_cli_search_prints_ranked_results_with_deep_links`
- `test_ac2_source_filter_returns_only_matching_source_type`
- `test_ac3_robustness_graceful_empty_result_exit_zero[empty_query-]`
- `test_ac3_robustness_graceful_empty_result_exit_zero[absent_terms-...]`
- `test_ac3_robustness_graceful_empty_result_exit_zero[unicode_junk-...]`
- `test_ac4_clean_clone_make_setup_and_demo_succeeds_offline` (`@pytest.mark.slow`)

`.tdd-swarm/spec-lint.sh tickets/T-010.md` → `spec-lint OK: all ACs covered
for T-010`.

`uv run ruff format --check tests/` and `uv run ruff check tests/` both
pass (ran `ruff format`/`ruff check --fix` on `tests/integration/` before
this report; one file reformatted, no lint findings).

## Notes / decisions for the Implementation Agent

- **`pytest.mark.slow` is unregistered** (`pyproject.toml` isn't in this
  ticket's `test_scopes`/`file_scopes` for the Test Agent) — produces a
  harmless `PytestUnknownMarkWarning`, not a failure. Whoever owns
  `pyproject.toml` next may want to add `markers = ["slow: ..."]` under
  `[tool.pytest.ini_options]` to silence it; not required for correctness.
- AC-4's `make setup`/`make demo` subprocess calls run with `VIRTUAL_ENV`
  inherited from the parent `uv run pytest` process pointing at this
  worktree's `.venv`; `uv` prints a one-line warning
  (`VIRTUAL_ENV=... does not match the project environment path`) and
  correctly ignores it, using the clone's own `.venv` instead — confirmed
  by a manual `/tmp` clone dry run outside pytest (`make setup` completed
  in ~0.3s fully from the local `uv` cache, no network). Not a test bug.
- `python -m onrecord.ingest.build_corpus`'s current stub `main()` takes no
  arguments and ignores `sys.argv` entirely (always prints "not
  implemented" and returns 1) — this is why AC-1's build step fails
  cleanly on the first assertion rather than reaching argparse; once the
  implementer adds real argument parsing, unrecognized/missing required
  flags should still fail cleanly (argparse's own `SystemExit(2)`), per the
  ticket's accepted failure modes.
- No `BLOCKED(TEST_DISPUTE)` — all 4 ACs were directly testable against the
  ticket text plus the design spec (`docs/superpowers/specs/2026-08-11-
  onrecord-design.md` §2.3/§3/§7) and the already-merged Wave-2 contracts
  (`InvertedIndex`, `boolean_search`/`phrase_search`, `Doc`).

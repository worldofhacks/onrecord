# T-010 Implementation Agent Report — Integration (CLI e2e, corpus-v1 build, clean clone)

**Status:** DONE — all 6 tests in `tests/integration/test_e2e.py` pass (5 fast + the
`@pytest.mark.slow` AC-4 clean-clone test); full repo suite green at 179 passing
(173 baseline + 6 new); all Tier-1 local gates green.

**Files touched (file scope, as ticketed):**
- `onrecord/cli.py` (rewritten from the T-001 stub)
- `onrecord/ingest/build_corpus.py` (rewritten from the T-001 stub)
- `README.md` (created — didn't exist yet)

No other files touched. `Makefile` was not edited (it already delegates to
these two entrypoints correctly).

## Implementation summary

**`onrecord/ingest/build_corpus.py`**
- `_parse_jsonl_lines(lines, source_label)`: shared row parser implementing
  contract #1 (blank lines skipped silently; invalid JSON or any missing/null
  required field — `id`/`text`/`source_type`/`venue_type`/`date`/`deep_link`
  — skipped with a logged warning naming the source file + line number;
  unrecognized extra keys ignored).
- `_iter_raw_dir_docs(raw_dir)`: `raw_dir.rglob("*.jsonl")` in sorted-path
  order, per contract #2's recursive-discovery requirement.
- `build_corpus(raw_dir, out_dir, index_out)`: merges well-formed rows,
  writes `<out_dir>/corpus.jsonl.gz` (gzip NDJSON via `dataclasses.asdict`),
  builds an `InvertedIndex.build(docs)` (real analyzer) and `.save()`s it to
  `index_out`. Returns 0 on `>=1` doc merged, 1 if none found (never raises).
- `load_corpus_snapshot(path)`: public helper reading a gzipped snapshot back
  into `Doc`s via the same row parser — imported by `cli.py` for the
  offline-fallback path (contract #4 / AC-4), so the malformed-row-skip logic
  isn't duplicated between the two files.
- `main(argv)`: argparse with `--raw-dir` (default `corpus/raw`), `--out`
  (default `corpus/v1`), `--index-out` (default `artifacts/index`) — all
  optional so `make ingest`'s no-args invocation still works; the test always
  passes explicit paths.

**`onrecord/cli.py`**
- `_load_index(index_dir)`: shared by `search` and `demo`. Loads
  `InvertedIndex.load(index_dir)` if the artifact exists; otherwise builds an
  in-memory index from `load_corpus_snapshot("corpus/v1/corpus.jsonl.gz")`
  (contract #4's offline clean-clone fallback); if the snapshot is also
  absent, builds an empty index rather than raising, which degrades a
  never-built index to a graceful "No results" instead of a crash.
- `_run_query(...)`: dispatches to `phrase_search` or `boolean_search`
  (op AND/OR), then applies `--source` as a post-retrieval filter over
  `index.get_doc(r.doc_id).source_type`, then truncates to `--k` — matching
  contract #3's "filter/truncate after retrieval" wording.
- `_print_results(...)`: 0 results → `No results for "QUERY"` message, exit
  0. `>=1` results → `"{n} results for \"QUERY\""` summary line, then one
  block per rank (1-indexed) with `id=<id>`, `date=<date>`, verbatim
  `deep_link`, `loc=<jurisdiction-or-ticker-or-"-">`, and the (already
  160-char-capped) snippet.
- `search` subcommand: positional `query`, `--op {AND,OR}` (default `AND`),
  `--phrase` (overrides `--op`), `--k` (default 10), `--source`, `--index`
  (default `artifacts/index`).
- `demo` subcommand: `--index` (default `artifacts/index`); runs 3 canned
  queries (`"substation"`, `"earnings call"`, `"interconnection queue"`)
  through the shared query/print path, each preceded by the literal marker
  `[demo] query "QUERY"`; always returns 0 (a 0-hit canned query doesn't fail
  the demo).

**`README.md`** (new): product one-liner + links to the design spec /
presearch doc, a Quickstart section (`git clone` → `make setup && make
demo`, explaining the offline snapshot-fallback path), a commands table
covering `setup`/`test`/`demo`/`ingest`/`eval`, and a "Searching directly"
section documenting the `search` flags.

## Decisions / notes

- **No real `corpus/v1/corpus.jsonl.gz` snapshot committed by this agent.**
  `corpus/v1/` is not in T-010's `file_scopes` (only `onrecord/cli.py`,
  `onrecord/ingest/build_corpus.py`, `README.md`), and no real adapter output
  exists yet under `corpus/raw/` in this worktree to build one from (no
  network/API keys available here). AC-4 is hermetic by design (module
  docstring contract #5) — it seeds its own tiny 5-doc snapshot inside the
  fresh clone before `make setup && make demo`, so it doesn't depend on a
  real snapshot being committed. The DoD line "corpus-v1 snapshot committed"
  is the orchestrator's/owner's ~22:00 ingest-cutoff action per `TICKETS.md`,
  not part of this ticket's file scope — flagging this explicitly rather than
  fabricating placeholder "real" civic-record data.
- `--raw-dir`/`--out`/`--index-out` were given defaults (matching the
  `corpus/raw` → `corpus/v1` → `artifacts/index` convention from the
  ticket's Context) even though the pinned contract only requires them to be
  accepted as flags, so `make ingest`'s no-args Makefile target degrades
  gracefully (warns, exit 1) instead of an argparse `SystemExit(2)` when
  `corpus/raw/` doesn't exist yet.
- `search`'s fallback-to-snapshot-when-index-missing behavior (mirroring
  `demo`) isn't explicitly required by contract #3, but is implied by this
  ticket's own brief ("index loading from --index or default artifacts/index,
  building from the committed snapshot when artifact missing") and by AC-3's
  "graceful ... absent ... handling" framing; it's untested by the frozen
  suite (all AC-1..3 tests always pass a real `--index` dir) but harmless and
  consistent with `demo`'s contract.
- `print()` is used for all CLI/build-corpus user-facing output. `gates.md`'s
  debug-grep note reads "print allowed in cli/ and scripts/"; `build_corpus.py`
  lives under `onrecord/ingest/` rather than a literal `cli/`/`scripts/`
  directory, but it is itself a `python -m` CLI entrypoint (same pattern as
  the already-merged `onrecord/eval/judgments.py`, which also uses bare
  `print()` outside those two directories) — followed that precedent rather
  than routing through `logging` or `sys.stdout.write`.
- No `BLOCKED(TEST_DISPUTE)`. The pinned contracts in `test_e2e.py`'s module
  docstring were unambiguous and directly implementable; no test edits were
  needed or made.

## Verification performed

1. `uv run pytest tests/integration/test_e2e.py -v` → **6/6 passed**
   (5 fast AC-1/2/3 + the `slow`-marked AC-4 clean-clone test, run both
   separately via `-m slow`/`-m "not slow"` and together).
2. `uv run pytest -q` (full repo suite) → **179 passed** (baseline 173 +
   these 6; no regressions).
3. `.tdd-swarm/run-local-gates.sh . tickets/T-010.md`:
   - format: clean (`uv run ruff format --check .`)
   - lint: `All checks passed!`
   - unit: `179 passed`
   - spec-lint: `spec-lint OK: all ACs covered for T-010`
   - **ALL LOCAL GATES GREEN**
4. Manual diff review: `git diff bba5ce8..HEAD | grep -nE '(TODO|FIXME|HACK)'`
   → empty. `print(`/`breakpoint(` diff hits are confined to `cli.py`'s and
   `build_corpus.py`'s user-facing CLI output (see Decisions above).
5. `git status --short` after both commits → clean; only
   `onrecord/cli.py`, `onrecord/ingest/build_corpus.py`, `README.md` touched.

# T-001 Review — Scaffold (Reviewer + Security Agent)

**Verdict: APPROVED** (updated after re-verification of fix commit `2cb611b` — see
"Re-verification" addendum at the bottom of this file. Original first-pass verdict below is
preserved unchanged for the record.)

---

## Re-verification addendum (commit `2cb611b`)

Coordinator reported fixes at `2cb611b` on `ticket/T-001-scaffold` addressing all three
first-pass findings. Re-verified independently rather than taking the summary at face value:

1. **Important — dependency floors.** `git show 2cb611b -- pyproject.toml` confirms all 8 deps
   now carry floors: `numpy>=2.1`, `msgpack>=1.1`, `pyyaml>=6.0`, `httpx>=0.27`,
   `rank-bm25>=0.2.2`, `pytest>=8.3`, `hypothesis>=6.115`, `ruff>=0.8`. `uv.lock` was
   regenerated in the same commit with matching `specifier = ">=..."` fields. Did a **second
   independent fresh clone** (`git clone --branch ticket/T-001-scaffold ... `, separate scratch
   dir) and ran `make setup` → `uv run python -c "import onrecord"` → `uv run pytest -q` end to
   end: resolves cleanly (numpy 2.5.2, msgpack 1.2.1, pyyaml 6.0.3, httpx 0.28.1, rank-bm25
   0.2.2, pytest 9.1.1, hypothesis 6.165.3, ruff 0.16.2 — every resolved version satisfies its
   floor), `import onrecord` → `OK`, 14/14 tests pass. **RESOLVED.**

2. **Minor — ruff scope / misleading commit message.** `pyproject.toml:33` `extend-exclude` is
   now `["tickets", "docs", ".tdd-swarm", "*.md"]` — `tests` and `scripts` genuinely removed
   this time. Confirmed ruff actually walks those dirs by running `uv run ruff check tests/
   scripts/` and `uv run ruff format --check tests/ scripts/` directly (not just trusting the
   config file): both pass, `format --check .` now covers 22 files (was 18 pre-fix). **Did not
   just eyeball the test-file diff** — parsed both the pre-fix (`8359208`) and post-fix
   (`2cb611b`) versions of `tests/unit/test_scaffold.py` with Python's `ast` module and compared
   `ast.dump()` output: **byte-for-byte identical AST**, confirming zero semantic change (every
   edit is a parenthesized-string → single-line collapse under the line-length-100 rule; no
   assert conditions, messages, thresholds, or key sets changed). Same AST-identical check on
   `scripts/export_presearch_transcript.py`. **RESOLVED**, verified at a stronger-than-requested
   bar (AST equality, not just diff inspection).

3. **Minor — impl-report staleness re `uv.lock`.** Coordinator claimed this was "noted in the
   swarm ledger." Checked: `.tdd-swarm/LESSONS.md` has two entries but **neither mentions
   `uv.lock`** (one is about the ruff-exclude gate-weakening from finding #2, one is about
   registry channel-handle verification for T-006) — and that file is currently an
   **uncommitted** local edit (`git status` shows ` M .tdd-swarm/LESSONS.md`), not part of
   `2cb611b` or any commit. `.tdd-swarm/reports/T-001-impl.md:128` still reads "`uv.lock` left
   untracked, not committed," unchanged, still contradicting the fact that `uv.lock` has been
   committed since `8359208`. **This remedy does not check out — the finding remains open.**
   It stays Minor severity (a documentation-accuracy nit with zero functional/security impact)
   and does not block approval on its own, but I'm not marking it resolved on an unverified
   claim.

**Full gate re-run at `2cb611b`** (worktree, independent of coordinator's report):
```
uv run ruff check .          → All checks passed!
uv run ruff format --check . → 22 files already formatted
uv run pytest -q             → 14 passed
.tdd-swarm/run-local-gates.sh . tickets/T-001.md → ALL LOCAL GATES GREEN (incl. spec-lint)
```
Plus a from-scratch `git clone` + `make setup` + import + pytest run (above), independent of
the worktree's cached `.venv`.

**Updated finding counts:** Critical: 0 · Important: 0 · Minor: 1 (open — impl-report/uv.lock
staleness, non-blocking).

**Verdict: APPROVED.** Both blocking-grade findings from the first pass (the Important
unpinned-deps DoD miss, and the Minor ruff-scope/commit-message issue) are fixed and
independently re-verified — the floors resolve correctly from a genuine clean clone, and the
tests/scripts reformat is proven AST-identical to the frozen test file, not just visually
inspected. The one remaining Minor (stale `uv.lock` narrative in the implementer report) is a
documentation nit with no functional, spec, or security consequence, and doesn't rise to a
blocking bar.

---

## First-pass report (commit `8359208`, superseded — kept for the record)

**Original verdict: REJECTED**

**Finding counts:** Critical: 0 · Important: 1 · Minor: 2

Basis for rejection: DoD checklist item "Deps pinned in pyproject" (`tickets/T-001.md:46`) is
unambiguously not met — `pyproject.toml` lists all eight required dependencies with zero
version specifiers. Everything else in this ticket is in excellent shape (all 14 frozen tests
pass from a genuine fresh clone, all local gates green, registry content is a verified,
near-exact match to spec §2.2). This is a fast, mechanical fix (add floors to 8 lines), not a
design problem — but it is a literal, explicit DoD line item, so I'm not waving it through.

---

## Method

- Read `tickets/T-001.md`, `.tdd-swarm/reports/T-001-impl.md`, `.tdd-swarm/reports/T-001-test.md`,
  `.tdd-swarm/gates.md`, `docs/superpowers/specs/2026-08-11-onrecord-design.md` §2.2.
- `git log --oneline 8857b81..HEAD` / `git diff 8857b81..HEAD` (5 commits, 25 files, 1601
  insertions, 0 deletions — clean additive diff, nothing under `tests/` touched).
- Read every changed source file end-to-end: `onrecord/types.py`, `onrecord/registry.py`,
  `onrecord/analysis/analyzer.py`, `onrecord/index/inverted.py`, `onrecord/search/boolean.py`,
  `onrecord/eval/metrics.py`, `onrecord/eval/run.py`, `onrecord/ingest/{youtube,edgar,fmp,
  build_corpus}.py`, `onrecord/cli.py`, `pyproject.toml`, `Makefile`, `.env.example`,
  `.gitignore`, `corpus/registry.yaml` (all 647 lines), `tests/unit/test_scaffold.py`.
- Ran the gates myself rather than trusting the report: `uv run pytest -q`,
  `uv run ruff format --check .`, `uv run ruff check .`, `bash .tdd-swarm/run-local-gates.sh .
  tickets/T-001.md`, `make -n {eval,ingest,demo,test}`, and manually invoked each stub
  entrypoint to confirm exit codes.
- **Did a real fresh clone** (`git clone --branch ticket/T-001-scaffold
  /Users/quietguy/Documents/Dev/Gauntlet/advanced-rag <scratch-dir>`) and ran `make setup` →
  `uv run python -c "import onrecord"` → `uv run pytest -q` from scratch, to verify AC-1/AC-2
  independent of the working worktree's pre-existing `.venv`/`uv.lock` cache state.
- Parsed `corpus/registry.yaml` with `yaml.safe_load` and diffed every ticker symbol, sector
  group, US state, and docket-source regulator against spec §2.2's literal enumeration
  (full-set comparison, not just a 10-item spot-check, since the data is small enough to check
  exhaustively).

---

## 1. SPEC COMPLIANCE

| Item | Verdict | Evidence |
|---|---|---|
| **AC-1** — clean clone + `make setup` → `import onrecord` succeeds | **MET** | Verified independently via real `git clone` + `make setup` + `uv run python -c "import onrecord"` → `OK`, in a scratch dir outside the worktree. Also covered by frozen test `test_make_setup_installs_deps_and_onrecord_imports` (`tests/unit/test_scaffold.py:117`), which passes. |
| **AC-2** — `uv run pytest -q` executes; scaffold's own tests pass | **MET** | `uv run pytest -q` → `14 passed in 0.25s` (worktree) and `14 passed in 0.99s` (fresh clone). `Makefile:6-7` `test:` target delegates to `pytest`. |
| **AC-3** — `corpus/registry.yaml` ≥45 channels / ≥90 tickers / ≥10 dockets, loadable via `onrecord.registry.load()`, matching spec §2.2 | **MET** | `corpus/registry.yaml` has 69 channels (`corpus/registry.yaml:17-361`), 102 tickers (`:363-566`), 26 docket sources (`:568-646`) — all above minimums. `onrecord/registry.py:16-25` `load()` reads the file and returns a dict exposing all three keys; frozen test `test_registry_loadable_via_onrecord_registry_load` passes. Full-set diff against spec §2.2 (not just spot-check): all 10 ticker sector groups are **character-for-character, order-preserving matches** to the spec's symbol lists (utilities_ipp 24/24, hyperscaler_ai 10/10, neocloud_miner_pivot 12/12, dc_reit_land 5/5, builders_ec 9/9, power_equipment_cooling 13/13, gas_midstream_fuel 5/5, nuclear_smr_uranium 8/8, grid_copper_fiber_materials 8/8, servers_networking 8/8 = 102 total, matches spec's ~100). All 26 docket sources match spec §2.2 T3's 18 state regulators + TVA + FERC + 6 RTOs by name/abbreviation. All 69 YouTube channels' `state`/`jurisdiction` values were cross-checked against every state bullet in spec §2.2 T1 (VA 16, TX 7, GA 6, OH 4, AZ 6, IA 4, NE 2, IL 1, WI 2, IN 1, MO 1, TN 2, LA 1, MS 1, AL 2, SC 1, NC 1, OR 2, WA 2, NV 2, WY 1, UT 1, OK 2, ND 1 = 69) — every jurisdiction named in the spec is present with the correct state; no wrong-state or wrong-jurisdiction entries found. No duplicate ticker symbols or channel ids. |
| **AC-4** — `setup\|test\|eval\|ingest\|demo` targets exist; eval/ingest/demo delegate to `uv run python -m onrecord...` | **MET** | `Makefile:1-16`. Manually ran all five targets: `setup`/`test` work; `eval`→`onrecord.eval.run` (exit 1, "not implemented"), `ingest`→`onrecord.ingest.build_corpus` (exit 1), `demo`→`onrecord.cli demo` (exit 1) — matches AC-4's "stubs may exit with not implemented EXCEPT setup/test" exactly. |
| **DoD** — All ACs pass via Test Agent's tests | **MET** | 14/14 frozen tests green, confirmed independently. |
| **DoD** — Deps pinned in pyproject: numpy, msgpack, pyyaml, httpx, rank-bm25, pytest, hypothesis, ruff | **NOT MET** | `pyproject.toml:6-12` (`dependencies = ["numpy", "msgpack", "pyyaml", "httpx", "rank-bm25"]`) and `pyproject.toml:14-19` (`dev = ["pytest", "hypothesis", "ruff"]`) — every one of the 8 named packages is a **bare name with zero version specifier** (no `>=`, no `==`, no upper bound). This is an explicit, checklist-listed DoD item and it is not satisfied by the letter of the ticket. See Security §3 for the risk this creates and why it isn't fully neutralized by the committed lock file. |
| **DoD** — Local gates green | **MET** | Re-ran `.tdd-swarm/run-local-gates.sh . tickets/T-001.md` myself: format/lint/unit/spec-lint all green, output byte-identical in substance to the implementer's report. |
| Frozen `Doc`/`SearchResult` contracts exact per ticket | **MET** | `onrecord/types.py:8-29` — field names, order, and defaults match the ticket's `tickets/T-001.md` frozen-contract block exactly; confirmed by passing `test_doc_dataclass_is_frozen_with_exact_fields` / `test_searchresult_dataclass_is_frozen_with_exact_fields`. |

**Anything built that the ticket did not ask for:**
- `onrecord/cli.py`, `onrecord/eval/run.py`, `onrecord/ingest/build_corpus.py` are not named in
  the ticket's "Module signatures" list, but they are the only way to satisfy AC-4's requirement
  that `eval`/`ingest`/`demo` "delegate to a `uv run python -m onrecord...` entrypoint" — this is
  necessary, in-scope work, not overreach.
- `uv.lock` (446 lines, committed in `8359208`) is **not** in the ticket's `file_scopes`
  (`pyproject.toml, Makefile, .gitignore, .env.example, onrecord/**, corpus/registry.yaml`). It's
  a reasonable-in-spirit artifact (it's what makes `make setup` reproducible), but it's an
  undeclared scope addition, and — see Code Quality §2 below — its commit directly contradicts
  a decision documented in the implementer's own report as final.

---

## 2. CODE QUALITY

**Stub signatures vs. frozen contracts (`tickets/T-001.md`) — all exact matches, no findings:**
- `onrecord/analysis/analyzer.py:6-8` — `def analyze(text: str) -> list[str]` ✓, `raise
  NotImplementedError` body ✓, one-line docstrings ✓.
- `onrecord/index/inverted.py:22-57` — `InvertedIndex.build` (classmethod) ✓, `df(term)->int` ✓,
  `postings(term)->Postings` ✓, `doc_count()->int` ✓, `get_doc(id)->Doc` ✓, `delete(id)->None` ✓,
  `save(path)` ✓, `load(path)` (classmethod) ✓. `Postings` (`:13-19`) carries `doc_ids`, `tfs`,
  `positions` as specified; typed `object`/`list` rather than a concrete array type, which is
  reasonable for a signature-only stub since the concrete backing type is T-003's decision, not
  frozen by the ticket.
- `onrecord/search/boolean.py:12-19` — `boolean_search(index, query: str, op: str) ->
  list[SearchResult]`, `phrase_search(index, phrase: str) -> list[SearchResult]` — exact.
- `onrecord/eval/metrics.py:6-23` — `precision_at_k`, `recall_at_k`, `mrr`, `ndcg_at_k` with
  `ranked: list[str]`, `relevant: dict[str, int]`, `k: int` — exact.
- `onrecord/ingest/{youtube,edgar,fmp}.py` — each is a single-line module docstring naming its
  owning ticket, no function stubs — matches the ticket's "empty" instruction literally.
- Iron Law respected: every frozen-signature stub body is exactly `raise NotImplementedError`;
  no logic beyond signatures anywhere in the Wave-2 interface files.

**Registry data sanity (full-set check, spec §2.2):** No findings. Every ticker symbol, sector
label, state, and docket regulator matches the spec verbatim (see §1 above for the full
breakdown). No wrong states, wrong sectors, or wrong jurisdictions found anywhere in the 69 +
102 + 26 = 197 entries.

**pyproject/Makefile hygiene:**
- `Makefile:1-16` — clean, tab-indented (`make -n` parses every target correctly), minimal,
  each non-setup/test target delegates to a real `onrecord` module. No findings.
- `pyproject.toml` `[tool.ruff] extend-exclude` (`:38`) excludes `tests`, `scripts`, `tickets`,
  `docs`, `.tdd-swarm`, `*.md` from ruff's format/lint scope, with a clear in-file comment
  explaining why (ruff ≥0.16 formats fenced ` ```python ` blocks in Markdown by default, which
  would otherwise touch the frozen ticket spec and frozen test file). Defensible, well-documented,
  and doesn't weaken the pytest gate (`testpaths = ["tests"]` at `pyproject.toml:44` still runs
  the untouched `tests/` tree in full).
- **(Minor) Misleading commit message.** Commit `8359208`'s message is `"feat(T-001): orchestrator
  tightening — ruff covers tests/ and scripts/; commit uv.lock for reproducible clean-clone"`, but
  `git show 8359208` touches **only** `uv.lock` (446 insertions) — `pyproject.toml`'s
  `extend-exclude` list (`pyproject.toml:38`) still excludes `tests`/`scripts`, unchanged from the
  prior commit. The claimed "ruff covers tests/ and scripts/" never happened. Low practical
  impact (the actual ruff scope is fine and matches the gates.md carve-out), but a reviewer or
  future maintainer skimming `git log` would draw the wrong conclusion about what ruff enforces.
- **(Minor) Implementer report contradicts final repo state.** `.tdd-swarm/reports/T-001-impl.md`
  "Decisions" item 3 states: *"`uv.lock` left untracked, not committed... Left as an untracked
  local artifact rather than added to `.gitignore` or committed, to avoid overstepping scope."*
  The very next commit after that report (`8359208`) reverses this and commits `uv.lock` anyway,
  but the report was never updated to reflect the reversal or explain why the earlier reasoning
  no longer applied. A reviewer relying on the report alone (as this review's brief instructs)
  would be actively misled about whether `uv.lock` is part of the deliverable. Recommend the
  implementer amend the report or note the reversal explicitly in future tickets.

---

## 3. SECURITY

**Secrets in code/config:** No findings. `.env.example` (`.env.example:1-19`) documents
`EDGAR_USER_AGENT`, `FMP_API_KEY`, `EMBEDDINGS_API_KEY`, `JUDGE_API_KEY` — all four have empty
values (`KEY=` with nothing after `=`), placeholders only, no real credentials. `git diff
8857b81..HEAD | grep -iE '(api[_-]?key|secret|password|token|AKIA...|-----BEGIN)'` turns up only
the `.env.example` variable *names* and doc-comment mentions of them — no values, no hardcoded
credentials anywhere in the diff. `.gitignore:20-23` correctly ignores `.env` / `.env.*` while
explicitly un-ignoring `.env.example`, which is the right shape for this pattern.

**Dependency risk in pyproject (typo-squats, unpinned floors):**
- **No typo-squats.** All 8 direct dependencies (`numpy`, `msgpack`, `pyyaml`, `httpx`,
  `rank-bm25`, `pytest`, `hypothesis`, `ruff`) and all 13 transitive dependencies resolved into
  `uv.lock` (`anyio`, `certifi`, `colorama`, `h11`, `httpcore`, `hypothesis`, `idna`, `iniconfig`,
  `packaging`, `pluggy`, `pygments`, `sortedcontainers`, `typing-extensions`) are legitimate,
  well-known PyPI packages with names matching their canonical projects. No lookalike/confusable
  names.
- **(Important) Unpinned floors — `pyproject.toml:6-12` and `:14-19`.** Every dependency is a
  bare name with no version specifier at all (not even a `>=` floor). This is both the DoD
  checklist violation noted in §1 and a real (if partially mitigated) supply-chain concern: any
  resolution path that doesn't go through the committed `uv.lock` — e.g. `uv add` on a fresh
  package, `uv lock --upgrade`, a different tool reading `pyproject.toml` directly, or a
  contributor deleting/regenerating the lock — has zero floor protection against a
  breaking or malicious future release of any of these 8 packages. **Mitigating factor:**
  `uv.lock` is committed (`8359208`) and pins exact versions with hashes, so the actual `make
  setup` → `uv sync` path this project's contributors and graders will use today is
  reproducible and deterministic. That mitigation covers "unpinned floors" as an availability/
  reproducibility risk but does not satisfy the DoD's literal text, and doesn't help if the lock
  is ever regenerated without floors being added at that point. Recommend adding minimum-version
  floors to `pyproject.toml` directly (e.g. `"numpy>=2.0"`) as a quick follow-up.

**Anything else unsafe:** No findings.
- No `eval`/`exec`/`pickle.loads`/`subprocess(shell=True)`/`os.system` anywhere in the diff.
- `onrecord/registry.py:24` uses `yaml.safe_load` (not `yaml.load` / `yaml.unsafe_load`) — correct,
  safe choice for parsing a repo-local YAML file.
- No network calls, no dynamic code loading, no `__reduce__`/pickle-adjacent patterns in any
  stub.
- `git diff 8857b81..HEAD | grep -nE '^\+.*(TODO|FIXME|HACK)'` → empty (todos gate clean).
- `git diff 8857b81..HEAD | grep -nE '^\+.*(print\(|breakpoint\()'` → only hit is
  `onrecord/cli.py:15` (`print(..., file=sys.stderr)`), which is the explicitly sanctioned
  carve-out in `.tdd-swarm/gates.md:11` ("print allowed in cli/ and scripts/"); `eval/run.py` and
  `ingest/build_corpus.py` correctly avoid `print(` in favor of `sys.stderr.write(...)` since
  they're not under `cli/`, per the implementer's own documented reasoning. No `breakpoint()`
  anywhere.

---

## Summary for return (superseded by first-pass numbers only — see addendum above for current)

- **APPROVED or REJECTED:** REJECTED (first pass, commit `8359208`)
- **Finding counts:** Critical: 0 · Important: 1 · Minor: 2
- **Important:** `pyproject.toml:6-19` — all 8 required deps (numpy, msgpack, pyyaml, httpx,
  rank-bm25, pytest, hypothesis, ruff) have zero version pins, violating the explicit DoD line
  item and leaving no floor protection outside the committed lock file.

---

## FINAL Summary for return (commit `2cb611b`, current)

- **APPROVED or REJECTED: APPROVED**
- **Finding counts:** Critical: 0 · Important: 0 · Minor: 1
- **Minor (open, non-blocking):** `.tdd-swarm/reports/T-001-impl.md:128` still claims `uv.lock`
  "left untracked, not committed," contradicting reality since `8359208`; coordinator's claimed
  ledger-note remedy isn't actually present in `.tdd-swarm/LESSONS.md` (checked directly — no
  `uv.lock` mention there, and that file is uncommitted besides).

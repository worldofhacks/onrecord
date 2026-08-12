# T-002 Implementation Agent Report — Analyzer

**Status:** DONE

## What was implemented

`onrecord/analysis/analyzer.py` — `analyze(text: str) -> list[str]`
(frozen signature, unchanged from the T-001 stub):

```python
import re
import unicodedata

_TOKEN_RE = re.compile(r"[^\W_]+", flags=re.UNICODE)


def analyze(text: str) -> list[str]:
    """Tokenize and normalize `text`; token i's position is list index i."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return _TOKEN_RE.findall(normalized)
```

Pipeline: Unicode NFKC normalize -> casefold -> regex-split on runs of
non-alphanumeric characters (via `[^\W_]+`, which matches Unicode word
characters minus underscore) -> `re.findall` naturally drops empty tokens
and preserves order/duplicates (no dedup, no sort — token `i`'s position is
list index `i`, per the ticket's index-position contract).

Docstring documents the v1 DoD-required decision: **no stemming, no
stopword removal** — stopwords are retained because phrase queries need
them, and index-time/query-time analysis stays identical and simple by
deferring stemming to a later ticket.

This is the same normalize -> casefold -> `\w`-regex-findall approach the
Test Agent's report (`.tdd-swarm/reports/T-002-test.md`) describes as its
verified-green throwaway reference implementation; I derived it
independently from the ticket's AC-1..AC-4 and confirmed each AC by hand
before running the suite (see "Manual AC verification" below), then
confirmed against the frozen tests.

## Manual AC verification (before running frozen tests)

Ran a standalone Python check of all worked examples from the ticket and
test file against the candidate implementation (NFKC -> casefold ->
`re.findall(r"[^\W_]+", ...)`), including the combining-mark edge case the
Test Agent's report calls out (`"9" + U+0301` correctly excluded from
`\w`, confirmed empirically: `re.match(r"\w", "́")` is `None` in
CPython's `re` engine). All 15 hand-checked cases matched expected output
exactly before the frozen suite was run.

## Test results

Frozen suite, before any change (RED, confirms Test Agent's report):
```
uv run pytest tests/unit/test_analyzer.py -v
=> 21 failed (all NotImplementedError from analyzer.py:8, the frozen stub)
```

Frozen suite, after implementation (GREEN):
```
uv run pytest tests/unit/test_analyzer.py -v
=> 21 passed in 0.21s
```

No test file was edited. `tests/` untouched.

## Local gates

```
.tdd-swarm/run-local-gates.sh . tickets/T-002.md
== format ==  23 files already formatted
== lint ==    All checks passed!
== unit ==    35 passed in 0.58s   (full repo suite — no regressions in T-001's tests)
== spec-lint ==  spec-lint OK: all ACs covered for T-002
ALL LOCAL GATES GREEN
```

## Definition of Done

- [x] ACs tested + green; local gates green
- [x] Docstring documents the v1 no-stemming/no-stopwords decision

## Scope discipline

Only `onrecord/analysis/analyzer.py` was modified (in `file_scopes:
[onrecord/analysis/**]`). No files under `tests/` were edited, deleted, or
skipped. No `git add -A` used; exact files staged per commit.

## Commits

- `feat(T-002): implement analyze() — NFKC normalize, casefold, regex tokenize (no stemming/stopwords per v1 DoD)`
  — stages `onrecord/analysis/analyzer.py`
- `docs(T-002): add implementation report`
  — stages `.tdd-swarm/reports/T-002-impl.md`

## Status

**DONE** — 21/21 frozen tests pass, all local gates green, no test-file
edits, no scope violations.

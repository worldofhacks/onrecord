# T-002 Test Agent Report — Analyzer

**Status:** DONE (frozen failing tests written; confirmed RED against the
`NotImplementedError` stub; confirmed GREEN against a throwaway correct
reference implementation, incl. 1000-example hypothesis stress runs)

**Test file:** `tests/unit/test_analyzer.py` (only new file; `__init__.py`
files for `tests/` and `tests/unit/` already existed from T-001)

**Run command:**
```
uv run pytest tests/unit/test_analyzer.py -v
```

## Design contract restated (from ticket Context + docs/presearch.md §3)

Unicode NFKC → casefold/lowercase → split on non-alphanumeric (digits kept,
not stripped) → drop empty tokens. NO stemming, NO stopword removal
(documented v1 choice — stopwords retained because phrase queries need
them). Token `i`'s position == list index `i`, so order and duplicates must
be preserved exactly as encountered (no dedup, no sort).

## Criterion → test mapping

| Criterion | Test(s) | What it checks |
|---|---|---|
| AC-1 | `test_ac1_ticket_example_tokenizes_apostrophe_dash_and_alnum` | Exact ticket string → exact expected token list |
| AC-1 | `test_ac1_alnum_runs_split_only_on_non_alphanumeric_separators[Q3\|10-K\|10K]` (parametrized ×3) | Letter+digit runs stay fused (`"Q3"→["q3"]`, `"10K"→["10k"]`); hyphen splits (`"10-K"→["10","k"]`) — the ticket's other worked examples |
| AC-1 | `test_ac1_preserves_order_and_duplicates` | `"The the THE"` → `["the","the","the"]` — catches an implementation that dedupes or sorts (would break "position == list index") |
| AC-1 | `test_ac1_collapses_runs_of_separators_without_empty_tokens` | `"hello,,,   world!!"` → `["hello","world"]` — no empty-string tokens from runs of separators |
| AC-1 | `test_ac1_returns_list_of_str` | Return type contract: `list[str]` |
| AC-2 | `test_ac2_ticket_example_fullwidth_folds_diacritic_preserved` | Exact ticket string `"Curaçao ＭＳＦＴ"` → `["curaçao","msft"]` (fullwidth folds, `ç` is NOT transliterated) |
| AC-2 | `test_ac2_fullwidth_digits_normalize_via_nfkc` | `"１２３"` (fullwidth digits) → `["123"]` — catches a `.lower()`-without-NFKC implementation |
| AC-2 | `test_ac2_ligature_decomposes_via_nfkc` | `"ﬁle"` (U+FB01 ligature) → `["file"]` — catches naive regex/str-based tokenizers that treat the ligature as one non-ASCII "letter" or drop it |
| AC-2 | `test_ac2_non_latin_uppercase_is_casefolded` | `"МОСКВА"` (Cyrillic) → `["москва"]` — catches an ASCII-only `.lower()` that ignores non-Latin case |
| AC-3 | `test_ac3_empty_string_returns_empty_list` | `""` → `[]`, no exception |
| AC-3 | `test_ac3_whitespace_only_returns_empty_list` | Whitespace-only → `[]` |
| AC-3 | `test_ac3_punctuation_only_returns_empty_list` | Punctuation-only (incl. em dash, ellipsis) → `[]` |
| AC-3 | `test_ac3_cjk_text_does_not_crash` | CJK input never raises; returns `list[str]` of non-empty tokens (no exact-boundary assertion — v1 does not segment CJK, per Test Plan's "CJK... don't crash") |
| AC-3 | `test_ac3_emoji_between_words_dropped_as_separator` | `"hello 🔥 world"` → `["hello","world"]` — emoji is unambiguously non-alphanumeric under any implementation choice |
| AC-3 | `test_ac3_emoji_only_input_returns_empty_list` | Emoji-only input → `[]`, no exception |
| AC-4 | `test_ac4_ticket_example_idempotent_after_rejoin` | Deterministic sanity check of idempotence on the AC-1 example before the property search |
| AC-4 (property) | `test_ac4_property_idempotent_after_rejoin` | hypothesis `st.text()`: `analyze(" ".join(analyze(text))) == analyze(text)` for arbitrary unicode, plus pinned `@example`s (empty, whitespace, ticket AC-1/AC-2 strings, CJK, emoji) |
| AC-4 (property) | `test_ac4_property_output_tokens_match_lowercase_alnum_charset` | hypothesis: every returned token is non-empty, has no leading/trailing whitespace, `str.isalnum()`, and contains no uppercase character — encodes the Test Plan's "output tokens always match `[a-z0-9]+` or non-Latin word chars" (scripts without case, e.g. CJK, are vacuously non-uppercase) |
| AC-4 (property) | `test_ac4_property_never_raises_on_arbitrary_unicode` | hypothesis: `analyze(text)` never raises for arbitrary unicode and always returns `list[str]` |

21 test items total (18 test functions + 1 parametrized ×3).

## Verification performed

1. **RED against the current worktree stub.** Ran the suite as-is; all 21
   items fail, every one with a clean `NotImplementedError` propagating from
   `onrecord/analysis/analyzer.py:8` (the frozen stub's `raise
   NotImplementedError`) — not a collection error, import error, or fixture
   crash. Full transcript below.
2. **GREEN against a throwaway correct implementation**, built and run only
   in the scratchpad (`/private/tmp/.../scratchpad/verify-t002`, an rsync
   copy of the worktree with only `onrecord/analysis/analyzer.py` edited)
   — never touched any forbidden path in `/Users/quietguy/Documents/Dev/Gauntlet/wt-T-002`.
   The reference implementation: `unicodedata.normalize("NFKC", text).casefold()`
   then `re.findall(r"[^\W_]+", ...)`. All 21 tests passed.
3. **Property-test stress run.** Re-ran the three hypothesis-based tests
   against the same reference implementation with `max_examples=1000`
   (default is 100) — all three properties (idempotence, charset, never-raises)
   held with zero failures, confirming they aren't accidentally vacuous or
   over-tight against a spec-compliant implementation. Specifically checked
   the trickiest charset case by hand: a bare combining mark with no
   precomposed base (e.g. `"9" + U+0301`) is correctly excluded from `\w`
   by Python's `re` module, so it never leaks into a token and never
   violates the `isalnum()`/no-uppercase charset property.
4. **Gates:** `uv run ruff format --check tests/` and `uv run ruff check
   tests/` both clean (line-length 100, project ruleset `E,F,I,UP`) — no
   exclusions added for `tests/`.
5. Scratchpad verification copy deleted after use; nothing left outside the
   worktree.

## Notes for the Implementation Agent

- Tests are frozen — do not edit `tests/unit/test_analyzer.py`; fix
  `onrecord/analysis/analyzer.py` instead. Escalate genuine ambiguities to
  the orchestrator/Reviewer rather than editing tests directly.
- `test_ac3_cjk_text_does_not_crash` deliberately does **not** assert an
  exact token boundary for CJK text (v1 has no CJK segmentation — "split on
  non-alphanumeric" naturally keeps a whole unsegmented CJK run as one
  token under a `\w`-style tokenizer, but the ticket/Test Plan only commits
  to "doesn't crash", so the test only checks type/no-crash/non-empty).
- `test_ac2_non_latin_uppercase_is_casefolded` deliberately uses Cyrillic
  (not German `ß` or Greek final-sigma) because those have `.lower()` vs.
  `.casefold()` divergences the ticket doesn't pin down; Cyrillic case
  folding is unambiguous under either method, so this test doesn't
  presuppose which one the implementer picks.
- The AC-4 charset property intentionally checks `not any(ch.isupper() for
  ch in tok)` rather than a hardcoded `[a-z0-9]` regex, so that non-Latin
  scripts without case (CJK, etc.) pass "vacuously" per the ticket's Test
  Plan wording ("`[a-z0-9]+` or non-Latin word chars").

## Failure output (current worktree, RED)

```
============================= test session starts ==============================
platform darwin -- Python 3.13.13, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/quietguy/Documents/Dev/Gauntlet/wt-T-002
configfile: pyproject.toml
plugins: anyio-4.14.2, hypothesis-6.165.3
collecting ... collected 21 items

tests/unit/test_analyzer.py::test_ac1_ticket_example_tokenizes_apostrophe_dash_and_alnum FAILED [  4%]
tests/unit/test_analyzer.py::test_ac1_alnum_runs_split_only_on_non_alphanumeric_separators[Q3-expected0] FAILED [  9%]
tests/unit/test_analyzer.py::test_ac1_alnum_runs_split_only_on_non_alphanumeric_separators[10-K-expected1] FAILED [ 14%]
tests/unit/test_analyzer.py::test_ac1_alnum_runs_split_only_on_non_alphanumeric_separators[10K-expected2] FAILED [ 19%]
tests/unit/test_analyzer.py::test_ac1_preserves_order_and_duplicates FAILED [ 23%]
tests/unit/test_analyzer.py::test_ac1_collapses_runs_of_separators_without_empty_tokens FAILED [ 28%]
tests/unit/test_analyzer.py::test_ac1_returns_list_of_str FAILED         [ 33%]
tests/unit/test_analyzer.py::test_ac2_ticket_example_fullwidth_folds_diacritic_preserved FAILED [ 38%]
tests/unit/test_analyzer.py::test_ac2_fullwidth_digits_normalize_via_nfkc FAILED [ 42%]
tests/unit/test_analyzer.py::test_ac2_ligature_decomposes_via_nfkc FAILED [ 47%]
tests/unit/test_analyzer.py::test_ac2_non_latin_uppercase_is_casefolded FAILED [ 52%]
tests/unit/test_analyzer.py::test_ac3_empty_string_returns_empty_list FAILED [ 57%]
tests/unit/test_analyzer.py::test_ac3_whitespace_only_returns_empty_list FAILED [ 61%]
tests/unit/test_analyzer.py::test_ac3_punctuation_only_returns_empty_list FAILED [ 66%]
tests/unit/test_analyzer.py::test_ac3_cjk_text_does_not_crash FAILED     [ 71%]
tests/unit/test_analyzer.py::test_ac3_emoji_between_words_dropped_as_separator FAILED [ 76%]
tests/unit/test_analyzer.py::test_ac3_emoji_only_input_returns_empty_list FAILED [ 80%]
tests/unit/test_analyzer.py::test_ac4_ticket_example_idempotent_after_rejoin FAILED [ 85%]
tests/unit/test_analyzer.py::test_ac4_property_idempotent_after_rejoin FAILED [ 90%]
tests/unit/test_analyzer.py::test_ac4_property_output_tokens_match_lowercase_alnum_charset FAILED [ 95%]
tests/unit/test_analyzer.py::test_ac4_property_never_raises_on_arbitrary_unicode FAILED [100%]

=================================== FAILURES ===================================
(21 failures; every one is `NotImplementedError` raised from
onrecord/analysis/analyzer.py:8 inside the stub `raise NotImplementedError`
statement — e.g.:)

    def analyze(text: str) -> list[str]:
        """Tokenize and normalize `text`; token i's position is list index i."""
>       raise NotImplementedError
E       NotImplementedError

onrecord/analysis/analyzer.py:8: NotImplementedError

=========================== short test summary info ============================
FAILED tests/unit/test_analyzer.py::test_ac1_ticket_example_tokenizes_apostrophe_dash_and_alnum
FAILED tests/unit/test_analyzer.py::test_ac1_alnum_runs_split_only_on_non_alphanumeric_separators[Q3-expected0]
FAILED tests/unit/test_analyzer.py::test_ac1_alnum_runs_split_only_on_non_alphanumeric_separators[10-K-expected1]
FAILED tests/unit/test_analyzer.py::test_ac1_alnum_runs_split_only_on_non_alphanumeric_separators[10K-expected2]
FAILED tests/unit/test_analyzer.py::test_ac1_preserves_order_and_duplicates
FAILED tests/unit/test_analyzer.py::test_ac1_collapses_runs_of_separators_without_empty_tokens
FAILED tests/unit/test_analyzer.py::test_ac1_returns_list_of_str
FAILED tests/unit/test_analyzer.py::test_ac2_ticket_example_fullwidth_folds_diacritic_preserved
FAILED tests/unit/test_analyzer.py::test_ac2_fullwidth_digits_normalize_via_nfkc
FAILED tests/unit/test_analyzer.py::test_ac2_ligature_decomposes_via_nfkc
FAILED tests/unit/test_analyzer.py::test_ac2_non_latin_uppercase_is_casefolded
FAILED tests/unit/test_analyzer.py::test_ac3_empty_string_returns_empty_list
FAILED tests/unit/test_analyzer.py::test_ac3_whitespace_only_returns_empty_list
FAILED tests/unit/test_analyzer.py::test_ac3_punctuation_only_returns_empty_list
FAILED tests/unit/test_analyzer.py::test_ac3_cjk_text_does_not_crash
FAILED tests/unit/test_analyzer.py::test_ac3_emoji_between_words_dropped_as_separator
FAILED tests/unit/test_analyzer.py::test_ac3_emoji_only_input_returns_empty_list
FAILED tests/unit/test_analyzer.py::test_ac4_ticket_example_idempotent_after_rejoin
FAILED tests/unit/test_analyzer.py::test_ac4_property_idempotent_after_rejoin
FAILED tests/unit/test_analyzer.py::test_ac4_property_output_tokens_match_lowercase_alnum_charset
FAILED tests/unit/test_analyzer.py::test_ac4_property_never_raises_on_arbitrary_unicode
============================== 21 failed in 0.20s ==============================
```

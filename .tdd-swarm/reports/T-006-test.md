# T-006 Test Agent Report — YouTube captions adapter

**Status:** DONE — Round 1 (frozen failing tests against the stub) + Round 2 (post-review,
real-data patch: 3 new failing tests for gaps `.tdd-swarm/reports/T-006-review.md` found that the
Round-1 fixtures didn't model) + Round 3 (post-Round-2-re-review: 1 new failing test for the
`prev_full`-reset-on-settle bug the Round-2 single-cycle fixture was too short to expose)

**Test file:** `tests/unit/ingest/test_youtube.py` (+ `tests/unit/ingest/__init__.py`)

**Fixtures:**
`tests/fixtures/youtube/{mixed_batch,malformed_only,nosubs_only,real_markup,real_entities,real_markup_multicycle}/`

**Stub touched:** `onrecord/ingest/youtube.py` — added the `parse_video_dir(directory,
registry_entry) -> list[Doc]` signature (raises `NotImplementedError`) plus a full contract
docstring, per the ticket's file_scope (this file is T-006's own, unlike the Wave-1-frozen
`onrecord/index/*`/`search/*` stubs).

**Run command:**
```
uv run pytest tests/unit/ingest/test_youtube.py -v
```

## API contract fixed by this ticket (documented in `onrecord/ingest/youtube.py`'s module docstring)

The ticket names the shape (`parse_video_dir`, 75s windows, id/deep_link formats) but leaves
several mechanics unpinned. Fixed here, and binding on the implementer:

- **File discovery**: glob `directory` (non-recursive) for `*.info.json`, sorted-filename order.
  Video id comes from the JSON body's `"id"` field, not the filename stem (yt-dlp embeds the
  title: `"<title> [<id>].info.json"`). Caption file = lexicographically-first `<stem>.*.vtt`
  match in the same directory (tolerates `--sub-langs en.*` suffix variants).
  - **Landmine documented for the implementer**: `<stem>` legitimately contains glob-special
    characters (yt-dlp's own `[<id>]` bracket suffix is a glob character class). A naive
    `directory.glob(f"{stem}.*.vtt")` silently matches **zero** files against the fixtures. This
    was caught by dogfooding a throwaway reference implementation against the fixtures during
    authoring (see below) — the fixtures deliberately keep the bracketed yt-dlp-style filenames
    rather than dodging the issue, and the docstring calls out `glob.escape()` /
    `iterdir()`-with-`str.startswith`/`endswith` as the fix.
- **Rollup dedupe (AC-2)**: drop a cue whose cleaned text equals the immediately preceding
  *retained* cue's cleaned text — consecutive-only, whole-video-order comparison.
- **Windowing**: fixed 75s windows, `window_index = int(start // 75)`. **Boundary rule**: a cue
  belongs to the window containing its START time. A cue spanning a boundary is not split (whole
  cue -> earlier window); a cue starting exactly on a boundary belongs to the later window. Empty
  windows are omitted. Window text = retained cues' cleaned text joined with a single space.
- **Malformed/truncated `.vtt` (AC-5)**: reject the **whole video** on any parse anomaly (no
  partial/best-effort recovery), log one WARNING, continue with other videos — same skip-and-log
  treatment as a missing `.vtt` (AC-3).
- **Logging**: stdlib `logging.getLogger("onrecord.ingest.youtube")` at WARNING level, message
  includes the offending video id/stem. Tests assert via `caplog`.
- **Doc field mapping**: `source_type="county_meeting"`, `venue_type="sworn"`,
  `date` = ISO-reformatted `info.json["upload_date"]`, `jurisdiction` =
  `registry_entry.get("jurisdiction")`, `ticker`/`speaker` = `None`.

## Fixture layout

A 3-video simulated channel-pull directory (`mixed_batch/`) plus two single-video isolation
directories, all under `tests/fixtures/youtube/`:

| Video (id) | Files | Purpose |
|---|---|---|
| `LCB0611meet` | `.info.json` + `.en.vtt` | Well-formed. Cues span 0s-200s (`upload_date` `20250611`). Includes 2 consecutive-duplicate ("rollup") cue pairs (AC-2), a cue starting at exactly t=75.000s, and a cue spanning t=70s→82s across the 75s boundary (adversarial). |
| `LCBbadvtt01` | `.info.json` + `.en.vtt` | Malformed/truncated: one valid cue, then a timing line cut off mid-timestamp (`00:00:05.000 --> 00:00:`) with no cue text following (AC-5). Also copied standalone into `malformed_only/`. |
| `LCBnosubs01` | `.info.json` only | No captions available (AC-3). Also copied standalone into `nosubs_only/`. |

Hand-computed expected window text (`WINDOW0/1/2_TEXT` constants in the test file) was verified
against the fixture by the self-verification harness described below, not just eyeballed.

## Criterion → test mapping

| Criterion | Test(s) | What it checks |
|---|---|---|
| AC-1 | `test_ac1_three_windows_with_correct_ids_and_deep_link_starts` | 3 Docs for the good video, ids `seg000/001/002`, `deep_link` `&t=` 0/75/150 |
| AC-1 | `test_ac1_window_text_is_concatenated_cue_text` | Each window's `text` exactly matches the hand-computed, deduped, space-joined concatenation |
| AC-1 adversarial | `test_window_boundary_cue_starting_exactly_at_75s_belongs_to_second_window` | Cue at t=75.000s lands in window 1, not window 0 |
| AC-1 adversarial | `test_cue_spanning_window_boundary_assigned_by_start_time_not_end_time` | Cue spanning t=70s→82s is NOT split; it belongs entirely to window 0 (assigned by start time) |
| AC-2 | `test_ac2_consecutive_duplicate_rollup_lines_collapsed` | Each duplicated rollup line appears exactly once in window 0's text |
| AC-2 | `test_ac2_no_adjacent_duplicate_lines_in_any_window` | No two adjacent "sentences" in any window's text are identical |
| AC-3 | `test_ac3_video_without_vtt_skipped_other_videos_still_parse` | No-vtt video produces zero Docs; a WARNING log line names its id; other videos in the same directory still parse |
| AC-3 | `test_ac3_isolated_nosubs_dir_returns_empty_list_no_exception` | A directory containing only a no-vtt video returns `[]`, no exception |
| AC-4 | `test_ac4_date_iso_and_constant_source_venue_fields` | `date == "2025-06-11"` (from `upload_date` `20250611`), `source_type`/`venue_type` constants, `ticker`/`speaker` are `None` |
| AC-4 | `test_ac4_jurisdiction_populated_from_registry_entry_argument` | Same fixture files parsed with two different `registry_entry` dicts (Loudoun vs. Fairfax) produce different `jurisdiction` values — proves the field is read from the argument, not hardcoded or read from `info.json` |
| AC-5 | `test_ac5_malformed_vtt_skipped_other_videos_still_parse` | Malformed-vtt video produces zero Docs; a WARNING log line names its id; other videos still parse |
| AC-5 | `test_ac5_isolated_malformed_dir_returns_empty_list_no_crash` | A directory containing only the malformed video returns `[]`, no crash |
| n/a (script DoD, not a numbered AC) | `test_pull_captions_script_exists` | `scripts/pull_captions.sh` exists |
| n/a | `test_pull_captions_script_is_executable` | executable bit (`chmod +x`) set |
| n/a | `test_pull_captions_script_uses_download_archive_for_resumability` | script text contains `--download-archive` |
| n/a | `test_pull_captions_script_uses_sleep_requests_for_politeness` | script text contains `--sleep-requests` |

16 test items total. `spec-lint.sh tickets/T-006.md` confirms all 5 ticket ACs are tagged.

The 4 pull-script tests are deliberately **not** tagged `spec(T-006:AC-n)` — none of the ticket's
5 ACs concern the shell script; they're tied instead to the ticket's Definition-of-Done line
("pull script is resumable"). Tagging them against an unrelated AC would be a false mapping, and
spec-lint.sh only requires that every AC that *does* exist in the ticket has ≥1 tagged test, which
already holds.

## Self-verification (fixtures/expectations vs. a compliant reference implementation)

Per the project's "no crash" and exact-text requirements, hand-computed fixture expectations are
easy to get subtly wrong (window bucketing off-by-one, join separators, dedupe scope). Before
freezing, I wrote a throwaway reference implementation (not committed — lived under the session
scratchpad only) that follows the contract documented in `onrecord/ingest/youtube.py`, and ran
every test's exact assertion logic against it: **26/26 checks passed**, including the two
boundary-adversarial checks and the jurisdiction-follows-argument check. This run is also what
surfaced the glob/bracket landmine now called out in the module docstring — a first draft of the
reference implementation used `directory.glob(f"{stem}.*.vtt")` and silently produced zero Docs
for the entire `mixed_batch/` fixture, because the fixture's yt-dlp-style `[LCB0611meet]` stem is
valid glob-metacharacter syntax.

## Verification performed

```
uv run ruff format --check tests/ onrecord/ scripts/     # 24 files already formatted
uv run ruff check tests/ onrecord/ scripts/               # All checks passed!
uv run pytest tests/unit/ingest/test_youtube.py -v         # 16 failed, 0 passed (RED, as expected)
uv run pytest -q                                            # 16 failed, 14 passed (T-001's scaffold suite unaffected)
bash .tdd-swarm/spec-lint.sh tickets/T-006.md               # spec-lint OK: all ACs covered for T-006
```

All 16 failures are the correct failure mode for this stage:
- 12 fail with `NotImplementedError` raised from `parse_video_dir`'s stub body (the parse-layer
  tests).
- 4 fail with a plain `AssertionError: scripts/pull_captions.sh missing` (the script doesn't
  exist yet — implementer scope).

No import errors, no fixture-not-found errors, and no other unexpected failure modes.

## Zero network

Every test reads only committed fixture files under `tests/fixtures/youtube/`; the pull-script
tests only stat/read the script's text, never execute it. No HTTP/yt-dlp calls anywhere in the
suite.

---

## Round 2 — reality-based caption fixtures (post-review patch)

**Trigger:** `.tdd-swarm/reports/T-006-review.md`, Critical + Important findings. Round-1 modeled
auto-caption "rollup" as byte-identical consecutive cues; a real-data spot check against
`corpus-raw/youtube/` (163 real video pairs) found 83% actually use YouTube's karaoke-tagged,
*incrementally*-growing rollup format instead — never byte-identical — so the frozen dedupe never
fires, and raw `<c>`/timestamp tags plus undecoded HTML entities (`&nbsp;`, `&amp;`) leak straight
into `Doc.text`. Scope for this round: `tests/` + `tests/fixtures/youtube/**` only, per the
coordinator's instruction — `onrecord/ingest/youtube.py` and `scripts/pull_captions.sh` are
untouched (implementer scope for the fast-follow fix).

**New fixtures** (read `corpus-raw/youtube/` only as reference, per the coordinator's pointer;
never modified, never read by the tests themselves — everything the suite touches is committed):

- `tests/fixtures/youtube/real_markup/` — one video (`KaraokeVid01`, `upload_date` `20260305`), 3
  cues modeling the real "growing rollup" karaoke pattern found in
  `corpus-raw/youtube/Loudoun_County_Board_of_Supervisors/-75a1WxvzdM.en.vtt` (cited by the
  reviewer): cue 1 is settled plain text ("The budget review begins with the water fund"); cue 2
  repeats cue 1's text on its first line and adds `<00:00:02.300><c> improvement</c>...`-tagged
  growth on its second; cue 3 is the settled, tag-free finalization of cue 2's growth. Wording is
  original — only the real file's cue-timing/markup *structure* is reproduced, kept under the
  15-word/one-quote copyright limit and attributed to the source path in the test file's
  docstring.
- `tests/fixtures/youtube/real_entities/` — one video (`EntitiesVid01`), 2 cues modeling the real
  "clean" (non-karaoke) variant's entity leakage found in
  `corpus-raw/youtube/Culpeper_County_Board_of_Supervisors/AaLqpzq-6gU.en-en.vtt` (cited by the
  reviewer): trailing `&nbsp;` after some words (sometimes doubled, `&nbsp;&nbsp;`, at a line
  break) and one `&amp;`. Wording is entirely original; only the entity-placement pattern is
  reproduced (not directly quoted, to keep this round to a single real-text quote overall — see
  `real_markup/` above).

**New tests** (appended to `tests/unit/ingest/test_youtube.py`, new "Round 2" section between the
AC-2 and AC-3 blocks):

| Criterion | Test | What it checks | Fails against current impl because |
|---|---|---|---|
| AC-1 | `test_ac1_karaoke_inline_tags_are_stripped` | `"<" not in doc.text` for the karaoke video's Doc(s) | `_parse_vtt_cues` joins raw cue lines verbatim; `<00:00:02.300><c>...</c>` tags pass straight through |
| AC-2 | `test_ac2_incremental_rollup_no_phrase_level_duplication` | `"The budget review begins with the water fund"` appears exactly once in `seg000.text` | `_dedupe_consecutive_rollups` only drops byte-identical consecutive cues; cue 2 (which repeats cue 1's text as a prefix, then extends it) is not identical to cue 1, so nothing is dropped and the phrase survives twice |
| AC-1 | `test_ac1_html_entities_are_decoded` | Neither `"&nbsp;"` nor `"&amp;"` appears in the entities video's Doc(s) | cue text is never passed through `html.unescape` (or equivalent) |

**Revised AC-2 contract** (documented in the test file's module docstring, since tests aren't
merged yet and this file's author still owns the contract this round): the byte-identical-only
dedupe rule from Round 1 is now a special case of a broader rule — after tag-stripping and
entity-decoding, no phrase may survive twice, consecutively-repeated-and-extended, in a window's
text. The exact algorithm (keep-first vs. keep-last of a growing chain, merge, etc.) is left to the
implementer; only the observable no-repeated-phrase outcome is pinned. This does not change any
Round-1 assertion — the existing `mixed_batch/` exact-duplicate fixture is the zero-growth special
case and remains satisfied by any implementation of the broader rule (verified: no Round-1 test
file edits were needed).

**Confirmed against the actual current implementation** (not a throwaway reference this round —
`parse_video_dir` is real code now, commit `00bb196`), directly, before adding assertions:

```
real_markup/  -> Doc.text contains literal '<00:00:02.300><c> improvement</c>...' tags,
                 and "The budget review begins with the water fund" appears twice
real_entities/-> Doc.text contains literal '&nbsp;' (3x) and '&amp;' (1x)
```

**Test run** (`uv run pytest tests/unit/ingest/test_youtube.py -v`): **3 failed, 16 passed** — all
3 new tests fail with plain `AssertionError`s carrying the exact offending text (not import/fixture
errors); all 16 Round-1 tests remain green, unmodified. Full suite (`uv run pytest -q`): **3
failed, 30 passed** (T-001's 14-test scaffold suite still unaffected). `spec-lint.sh
tickets/T-006.md`: all 5 ACs still covered. `ruff format --check` / `ruff check` over
`tests/ onrecord/ scripts/`: clean.

No existing fixture or assertion needed adjustment for the revised dedupe semantics — the two new
fixtures are additive and isolated (their own directories/video ids), so nothing already-frozen
was touched.

---

## Round 3 — multi-cycle rollup fixture (prev_full reset regression)

**Trigger:** `.tdd-swarm/reports/T-006-review.md`, "Round 2 re-verification" section. The Round-2
fix's `_dedupe_consecutive_rollups` genuinely strips karaoke tags and decodes entities (confirmed:
0/20 tag/entity leaks in the reviewer's real-data re-sample), but its case-3 branch ("redundant
settle" — `prev_full.endswith(text)` → drop) leaves `prev_full` unchanged instead of resetting it
to the settle cue's shorter, newly-confirmed text. The *next* growth cue then compares against the
stale, longer `prev_full`; its case-2 prefix check fails; it falls through to case 4 ("unrelated,
retain in full") and re-emits text that already survived via the previous cycle. Reviewer measured
this at 16/20 (80%) of a random real-video sample. Root cause: `real_markup/` (Round 2) is only a
**single** growth→settle cycle (3 cues) and never reaches a fourth cue, so it structurally cannot
exercise the hand-off from one settle cue to the *next* cycle's growth cue — the exact sequence the
bug lives in. Scope for this round: `tests/` + `tests/fixtures/youtube/**` only, per the
coordinator's instruction — `onrecord/ingest/youtube.py` untouched (implementer's fast-follow).

**New fixture:** `tests/fixtures/youtube/real_markup_multicycle/` — one video (`KaraokeVid02`,
`upload_date` `20260305`), 5 cues forming **two** full growth→settle cycles back to back, modeled
structurally on the reviewer's real `-75a1WxvzdM` trace quoted in the review report's "Root cause"
section (original wording throughout, only the cue-timing/growth/settle *structure* is
reproduced):

1. `t=0` — seed, settled: `"The budget review begins with the water fund"`
2. `t=2.0` — cycle-1 growth: line 1 repeats cue 1's text, line 2 adds `<c>`-tagged new words
   (`"capital improvement plan for fiscal year twenty twenty six"`, tag-stripped)
3. `t=4.7` — cycle-1 settle: re-emits just that new phrase, plain, no tags
4. `t=4.71` — cycle-2 growth: line 1 repeats cue 3's (short, settled) text, line 2 adds further
   `<c>`-tagged new words (`"for the coming fiscal cycle"`, tag-stripped)
5. `t=7.5` — cycle-2 settle: re-emits cycle 2's new phrase

**New test:** `test_ac2_multi_cycle_rollup_no_phrase_level_duplication`, tagged
`spec(T-006:AC-2)`, inserted in a new "Round 3" section after the Round 2 tests. Asserts
`seg000.text.count("capital improvement plan for fiscal year twenty twenty six") == 1` — the
cycle-1 phrase must not be re-emitted when cycle 2's growth cue is processed.

**Confirmed against the actual current implementation** (commit `ca1dee3`, unmodified) before
adding the assertion:

```
real_markup_multicycle/ -> Doc.text =
  "The budget review begins with the water fund capital improvement plan for fiscal year
   twenty twenty six capital improvement plan for fiscal year twenty twenty six for the
   coming fiscal cycle"
  ("capital improvement plan for fiscal year twenty twenty six" appears twice; no "<" markup
   leaks — the Round-2 tag-stripping fix is unaffected by this bug)
```

This exactly reproduces the reviewer's traced mechanism: case 3 drops the cycle-1 settle cue
(t=4.7) without resetting `prev_full`, so the cycle-2 growth cue (t=4.71, whose text starts with
cue 3's short settled text, not the stale long `prev_full`) fails its case-2 prefix check and is
retained in full via case 4 — re-duplicating the cycle-1 phrase it already contains.

**Test run** (`uv run pytest tests/unit/ingest/test_youtube.py -v`): **1 failed, 19 passed** — the
new test fails with a plain `AssertionError` (`got 2`, exact offending text included), not an
import/fixture error; all 19 Round-1/Round-2 tests remain green, unmodified. Full suite
(`uv run pytest -q`): **1 failed, 33 passed** (T-001's 14-test scaffold suite still unaffected).
`spec-lint.sh tickets/T-006.md`: all 5 ACs still covered. `ruff format --check` / `ruff check` over
`tests/ onrecord/ scripts/`: clean.

No existing fixture or assertion needed adjustment — `real_markup_multicycle/` is additive and
isolated (its own directory/video id), so nothing already-frozen was touched.

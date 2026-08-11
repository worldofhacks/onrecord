# T-006 Test Agent Report — YouTube captions adapter

**Status:** DONE (frozen failing tests written, confirmed RED against the stub, confirmed the
fixtures/expectations are internally achievable via a throwaway reference implementation that
follows the documented contract — see "Self-verification" below)

**Test file:** `tests/unit/ingest/test_youtube.py` (+ `tests/unit/ingest/__init__.py`)

**Fixtures:** `tests/fixtures/youtube/{mixed_batch,malformed_only,nosubs_only}/`

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

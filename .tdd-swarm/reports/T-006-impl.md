# T-006 Implementation Agent Report — YouTube captions adapter

**Status:** DONE — all 20 frozen tests pass (16 original + 3 Round-2
real-caption tests + 1 Round-3 multi-cycle-rollup regression test); local
gates green.

**Files touched (in-scope only):**
- `onrecord/ingest/youtube.py` — implemented `parse_video_dir`; Round 2
  adds karaoke-tag stripping, HTML-entity decoding, and a generalized
  incremental-rollup dedupe; Round 3 (below) fixes a `prev_full`-not-reset
  bug in that dedupe's redundant-settle branch
- `scripts/pull_captions.sh` — new, executable, yt-dlp wrapper

No edits to `tests/` or `tests/fixtures/youtube/**`.

## Round 3 — multi-cycle rollup duplication fix (post-re-review)

Round-2 re-review found the generalized dedupe (below) still duplicates text
on a *second* rollup growth→settle cycle within the same video (measured:
80% of real videos affected). Root cause: in `_dedupe_consecutive_rollups`'s
case 3 (redundant settle — `prev_full.endswith(text)` → drop the cue), the
code dropped the cue but left `prev_full` unchanged (still pointing at the
longer, pre-settle cue's text) instead of resetting it to the settle cue's
own (shorter) `text`. A second cycle's growth cue builds on the settle cue's
text, not the stale pre-settle text, so its `text.startswith(prev_full)`
check missed against the stale `prev_full`, fell through to the "unrelated
cue → retain in full" branch, and re-emitted the just-dropped phrase
verbatim inside its own full text.

The Test Agent pinned this at commit `3eba156`
(`real_markup_multicycle/KaraokeVid02`, 5 cues / two full growth→settle
cycles chained back to back — a single cycle, as in `real_markup/`, never
reaches a fourth cue and so can't expose this hand-off bug) with
`test_ac2_multi_cycle_rollup_no_phrase_level_duplication` (1 new failing
test; the existing 19 stayed green, confirming the bug was isolated to the
cross-cycle hand-off, not the single-cycle case).

**Fix** (`onrecord/ingest/youtube.py`, case 3 of
`_dedupe_consecutive_rollups`): add `prev_full = text` before the `continue`
that drops a redundant settle cue. One line. Traced by hand against the
5-cue fixture (`A`=cue1, `B`=cycle-1 growth, `C`=cycle-2 growth): cue3
(settle, text=`B`) now resets `prev_full` from the stale `"A B"` to `B`
before cue4 (text=`"B C"`) is evaluated, so cue4 correctly matches case 2
(`"B C".startswith(B)`) and contributes only its new suffix `C` — `B` no
longer appears a second time embedded inside cue4's full text. Final
`seg000.text` = `A + " " + B + " " + C`, each phrase exactly once, matching
the pinned test's assertion.

Also updated: the module docstring's "Cue extraction & rollup dedupe"
section and `_dedupe_consecutive_rollups`'s own docstring, both now document
the `prev_full` reset as part of case 3's binding contract.

## Round 2 — real-caption cleaning fix (post-review Critical)

`.tdd-swarm/reports/T-006-review.md` found (APPROVED, 1 Critical + 1
Important, not AC-blocking but corpus-quality-blocking) that real YouTube
auto-captions don't match the frozen fixtures' model: cue text embeds inline
karaoke markup (`<00:01:38.520><c>word</c>`) and the real "rollup" pattern is
incremental growth, not byte-identical repeats, so the original dedupe never
fired on real data (measured 83%/136-of-163 real corpus-raw video pairs
producing tag-laden, duplicated `Doc.text`). A separate Important finding:
undecoded HTML entities (`&nbsp;`, `&amp;`) leak into even "clean" captions.
The Test Agent extended the frozen suite at commit `353ba6e` with two new
fixtures (`real_markup/` karaoke, `real_entities/` HTML entities) and 3 new
tests; the original 16 stay green, unmodified.

Fix, entirely inside `onrecord/ingest/youtube.py`:

- **`_clean_line()`** (new): per raw cue-text line, strip inline `<...>`
  markup via `_INLINE_TAG_RE = re.compile(r"<[^>]+>")`, then
  `html.unescape()` to decode named entities, then `.strip()`. Decoded
  `&nbsp;` becomes `\xa0`, which Python's `str.strip()` also treats as
  whitespace, so a trailing/leading `&nbsp;` at a line-wrap point disappears
  cleanly instead of leaving a stray non-breaking space when lines are
  rejoined. Applied per cue-text line inside `_parse_vtt_cues`, before a
  cue's lines are joined — so cleaning happens ahead of dedupe comparison,
  per the revised contract.
- **`_dedupe_consecutive_rollups()`** (generalized, same function name):
  walks cues in consecutive whole-video order against a running `prev_full`
  (the previous *retained* cue's full cleaned text):
  1. `text == prev_full` → exact duplicate (original zero-growth rule) →
     drop.
  2. `text.startswith(prev_full)` → incremental growth → retain only the new
     suffix (`text[len(prev_full):]`, stripped); `prev_full` advances to the
     *full* `text` so later cues in the same growing chain keep comparing
     against the whole accumulated phrase, not just the last suffix kept.
  3. `prev_full.endswith(text)` → a later "settle" cue whose text is already
     fully covered by the tail of the larger previous cue → redundant →
     drop (its content already survived via case 2); `prev_full` unchanged.
  4. Otherwise → unrelated cue → retain in full, `prev_full` becomes `text`.

  Verified by hand against `real_markup/`'s 3-cue chain (cue1 "The budget
  review begins with the water fund"; cue2 = cue1's text + tagged growth;
  cue3 = the settled growth alone): produces exactly 2 retained cues (cue1
  in full, cue2's new suffix only), cue3 dropped as redundant — the shared
  phrase survives exactly once, matching
  `test_ac2_incremental_rollup_no_phrase_level_duplication`.
- Module docstring's "Cue extraction & rollup dedupe" section rewritten to
  document both changes as the binding contract.

No change to file discovery, windowing, `Doc` field mapping, or
`scripts/pull_captions.sh` — the Critical/Important findings were scoped
entirely to cue-text cleaning and dedupe.

## What was implemented

### `onrecord/ingest/youtube.py`

- **File discovery**: `sorted(directory.glob("*.info.json"))` (non-recursive,
  deterministic order). Video id comes from the JSON body's `"id"` field, not
  the filename stem.
- **VTT pairing — landmine avoided**: `_find_vtt()` matches the caption file
  via `directory.iterdir()` + `str.startswith(f"{stem}.")` /
  `str.endswith(".vtt")`, exactly as flagged in
  `.tdd-swarm/reports/T-006-test.md` and the module docstring — never
  `Path.glob`/`fnmatch` with an interpolated stem, since yt-dlp's `[<id>]`
  bracket suffix is a glob character class that would silently match zero
  files (confirmed this would have broken the whole `mixed_batch/` fixture
  before writing `_find_vtt`).
- **VTT cue parsing** (`_parse_vtt_cues`): hand-rolled line-based WebVTT
  parser (no external dependency — none is in `pyproject.toml`). Validates
  the `WEBVTT` header, matches cue timing lines via regex tolerating both
  `HH:MM:SS.mmm` and `MM:SS.mmm` forms, joins multi-line cue text with a
  single space, drops empty cues. Any structural anomaly (missing header,
  unmatched/truncated timing line) raises `ValueError`, which the caller
  treats as "reject the whole video" per AC-5 — verified directly against
  the malformed fixture, which is byte-truncated mid-timestamp
  (`...--> 00:00:` with no closing digits, confirmed via raw byte
  inspection) and correctly fails the timing-line regex match.
- **Rollup dedupe** (`_dedupe_consecutive_rollups`): single pass, drops a cue
  whose cleaned text equals the immediately preceding *retained* cue's text,
  over the whole video's cue stream (not per-window).
- **Windowing** (`_build_window_docs`): `window_index = int(start //
  WINDOW_SECONDS)`; cues bucketed by start time only (a cue spanning a
  boundary is not split); a cue starting exactly at `t=75.0` lands in the
  later window because `75.0 // 75 == 1.0`. Empty windows omitted; windows
  emitted in ascending index order; window text = retained cues' cleaned
  text joined with a single space.
- **Doc field mapping**: `id`, `deep_link` per the ticket's format strings;
  `source_type="county_meeting"`, `venue_type="sworn"`; `date` reformatted
  from `info.json["upload_date"]` (`"YYYYMMDD"` → `"YYYY-MM-DD"`);
  `jurisdiction` read from the `registry_entry` argument (never hardcoded,
  never read from `info.json`); `ticker`/`speaker` = `None`.
- **Skip-and-warn**: missing `.vtt`, malformed `.vtt`, and unreadable
  `info.json` are each caught per-video, logged once at WARNING via
  `logging.getLogger(__name__)` (`onrecord.ingest.youtube`) naming the video
  id/stem, and the loop continues — no exception ever escapes
  `parse_video_dir`.

### `scripts/pull_captions.sh`

`yt-dlp` wrapper taking `<channel_url> <outdir>`:
`--skip-download --write-auto-subs --write-subs --sub-langs 'en.*'
--write-info-json --download-archive "<outdir>/.download-archive.txt"
--sleep-requests 1.5 --ignore-errors`, with an explicit `-o`/`-P` output
template matching yt-dlp's own default (`"%(title)s [%(id)s].%(ext)s"`) so
the file-discovery convention in the parser module docstring holds.

Resumability: the download archive lives inside `<outdir>`, so a re-run
against the same `<outdir>` skips already-pulled video ids.

Per `.tdd-swarm/LESSONS.md`'s unverified-channel-handles entry (registry
`youtube_channels` entries are best-guess, `verified: false`): the script
does **not** use `set -e`. A yt-dlp failure (e.g. an unresolvable channel
handle) is caught, logged as a `WARNING` on stderr naming the channel URL,
and surfaced via yt-dlp's own exit code — never an uncaught stack
trace — treating resolution failure as data an orchestrator looping over
channels can log and continue past.

## Verification performed

```
uv run pytest tests/unit/ingest/test_youtube.py -v   # Round 1: 16 passed
                                                       # Round 2: 19 passed
                                                       # Round 3: 20 passed
bash .tdd-swarm/run-local-gates.sh . tickets/T-006.md # format/lint/unit(34 passed)/spec-lint all green
```

No edits to `tests/` or fixtures in any round. No network calls in any test
path (`pull_captions.sh` tests only stat/read the script's text).

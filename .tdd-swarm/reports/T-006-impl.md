# T-006 Implementation Agent Report — YouTube captions adapter

**Status:** DONE — all 16 frozen tests pass; local gates green.

**Files touched (in-scope only):**
- `onrecord/ingest/youtube.py` — implemented `parse_video_dir`
- `scripts/pull_captions.sh` — new, executable, yt-dlp wrapper

No edits to `tests/` or `tests/fixtures/youtube/**`.

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
uv run pytest tests/unit/ingest/test_youtube.py -v   # 16 passed
bash .tdd-swarm/run-local-gates.sh . tickets/T-006.md # format/lint/unit(30 passed)/spec-lint all green
```

No edits to `tests/` or fixtures. No network calls in any test path
(`pull_captions.sh` tests only stat/read the script's text).

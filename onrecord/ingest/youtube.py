"""YouTube captions adapter (T-006): channel VTT + info.json pairs -> Doc rows.

Two artifacts implement Spec Sec 2.2 T1 / Sec 2.3 for county-meeting video:

1. `scripts/pull_captions.sh <channel_url> <outdir>` (implementer scope, bash):
   a yt-dlp wrapper that pulls English auto/manual captions + metadata for a
   channel with `--download-archive` (resumability -- re-running against the
   same `<outdir>` must skip already-pulled video ids) and `--sleep-requests
   1.5` (politeness). It writes one `<stem>.info.json` + one or more
   `<stem>.<lang>.vtt` per video into `<outdir>` -- see the file-discovery
   convention below for what `<stem>` may look like.

2. `parse_video_dir(directory, registry_entry) -> list[Doc]` (this module,
   pure/offline, zero network): parses every video pair found directly
   inside `directory` into windowed `onrecord.types.Doc` rows.

       def parse_video_dir(
           directory: str | Path,
           registry_entry: dict[str, Any],
       ) -> list[Doc]: ...

   `registry_entry` is one `corpus/registry.yaml` `youtube_channels[i]`
   mapping (at minimum a `jurisdiction` key; see `onrecord.registry.load()`),
   supplied by the caller/orchestrator -- this module never reads the
   registry itself.

File-discovery convention (frozen contract for the implementer):
    - Glob `directory` (non-recursive) for `*.info.json`. Process matches in
      sorted-filename order for deterministic output.
    - For each `<stem>.info.json`, the video id comes from the JSON body's
      `"id"` field -- NOT from `<stem>`. yt-dlp's default output template
      embeds the human title in the filename (e.g. `"Board Mtg - Jun 11 2025
      [LCB0611meet].info.json"`), so `<stem>` is display text, not the id.
    - Its caption file is the lexicographically-first path matching
      `<stem>.*.vtt` in the same directory (tolerates yt-dlp's language-code
      suffixes from `--sub-langs en.*`, e.g. `.en.vtt`, `.en-orig.vtt`).
      **Pitfall**: `<stem>` legitimately contains glob-special characters --
      yt-dlp's own `[<id>]` bracket suffix is a glob character class, so
      `directory.glob(f"{stem}.*.vtt")` silently matches nothing for a
      title like `"Board Mtg [LCB0611meet]"`. Either `glob.escape(stem)`
      first or match via plain `str.startswith`/`endswith` over
      `directory.iterdir()` -- the fixtures under
      `tests/fixtures/youtube/mixed_batch/` use exactly this bracketed
      naming and will silently produce zero Docs for the whole batch if
      this is gotten wrong.
    - No match -> the video has no usable captions. Skip it: log one WARNING
      (via `logging.getLogger(__name__)`) naming the stem/video id, do not
      raise, and continue with the remaining videos (AC-3).
    - A matching `.vtt` that fails to parse cleanly (malformed/truncated --
      e.g. a cue block cut off mid-timestamp) is handled the same way: skip
      the *whole video*, log one WARNING, continue (AC-5). Partial/
      best-effort recovery of a truncated file is explicitly NOT required --
      reject the whole file rather than guess.
    - A `.vtt` with no matching `.info.json` is out of scope for this ticket
      (yt-dlp always writes both together); no special handling required.

Cue extraction & rollup dedupe:
    - Parse every WebVTT cue in file order into `(start_seconds, text)`,
      joining a cue's internal lines with a single space and stripping
      surrounding whitespace; cues with empty text after stripping are
      dropped.
    - Auto-caption "rollup" dedupe: walk cues in order and drop a cue whose
      cleaned text is identical to the immediately preceding *retained*
      cue's cleaned text (AC-2). This is a consecutive-only comparison over
      the whole video's cue stream -- it is not scoped per-window.

Windowing (fixed-width, WINDOW_SECONDS = 75):
    - Window `i` covers `[i * 75, (i + 1) * 75)` seconds of video time.
    - **Boundary rule**: a cue belongs to the window containing its START
      time, regardless of where it ends -- `window_index = int(start //
      75)`. A cue that starts before a boundary and ends after it is NOT
      split; its full text goes to the earlier window. A cue whose start
      lands exactly on a boundary (e.g. t=75.000s) belongs to the LATER
      window.
    - Only windows containing >= 1 retained cue produce a Doc; empty windows
      are omitted (no gap-filling). Emitted in ascending window-index order.
    - A window Doc's text is its retained cues' cleaned text, in cue order,
      joined with a single space and stripped.

Doc field mapping:
    - `id`           = f"yt:{video_id}:seg{window_index:03d}"  (e.g. "seg000")
    - `deep_link`    = f"https://youtube.com/watch?v={video_id}&t={window_index * 75}s"
    - `source_type`  = "county_meeting"
    - `venue_type`   = "sworn"
    - `date`         = info.json's `upload_date` ("YYYYMMDD") reformatted to
                       ISO "YYYY-MM-DD"
    - `jurisdiction` = `registry_entry.get("jurisdiction")` (`None` if absent)
    - `ticker`, `speaker` = None (not applicable to this source)

Zero network: this module never makes HTTP calls; all state comes from files
already on disk. Tests run only against committed fixtures under
`tests/fixtures/youtube/`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from onrecord.types import Doc

WINDOW_SECONDS = 75


def parse_video_dir(directory: str | Path, registry_entry: dict[str, Any]) -> list[Doc]:
    """Parse every `<stem>.info.json` + `<stem>.*.vtt` pair in `directory`.

    See the module docstring for the full frozen contract: file discovery,
    rollup dedupe, 75s windowing + boundary rule, and Doc field mapping.
    Implemented by T-006.
    """
    raise NotImplementedError

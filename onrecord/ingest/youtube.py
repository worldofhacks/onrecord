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
      this is gotten wrong. This module matches via `iterdir()` +
      `str.startswith`/`endswith`, never `Path.glob` with an interpolated
      stem.
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

import json
import logging
import re
from pathlib import Path
from typing import Any

from onrecord.types import Doc

WINDOW_SECONDS = 75

logger = logging.getLogger(__name__)

_INFO_JSON_SUFFIX = ".info.json"

# A WebVTT cue timing line, e.g. "00:01:10.000 --> 00:01:22.000" (hours are
# optional per the WebVTT spec, e.g. "01:10.000 --> 01:22.000").
_TIMESTAMP = r"(?:\d+:)?\d{2}:\d{2}\.\d{3}"
_CUE_TIMING_RE = re.compile(rf"^(?P<start>{_TIMESTAMP})\s*-->\s*(?P<end>{_TIMESTAMP})")


def _parse_ts(ts: str) -> float:
    """Convert a WebVTT timestamp ("[HH:]MM:SS.mmm") to seconds."""
    parts = ts.split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours = "0"
        minutes, seconds = parts
    else:  # pragma: no cover - unreachable given _CUE_TIMING_RE's shape
        raise ValueError(f"malformed timestamp: {ts!r}")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _parse_vtt_cues(text: str) -> list[tuple[float, str]]:
    """Parse WebVTT cue blocks into (start_seconds, cleaned_text) tuples.

    Raises `ValueError` on any malformed/truncated content -- per AC-5 the
    whole file is rejected rather than partially recovered.
    """
    lines = text.splitlines()
    if not lines or not lines[0].strip().startswith("WEBVTT"):
        raise ValueError("missing WEBVTT header")

    cues: list[tuple[float, str]] = []
    i = 1
    n = len(lines)
    while i < n:
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if "-->" not in line:
            # Optional cue-identifier line preceding the timing line.
            i += 1
            continue
        match = _CUE_TIMING_RE.match(line)
        if match is None:
            raise ValueError(f"malformed cue timing line: {line!r}")
        start = _parse_ts(match.group("start"))
        i += 1
        text_lines: list[str] = []
        while i < n and lines[i].strip():
            text_lines.append(lines[i].strip())
            i += 1
        cue_text = " ".join(text_lines).strip()
        if cue_text:
            cues.append((start, cue_text))
        i += 1  # skip the blank separator line, if any
    return cues


def _dedupe_consecutive_rollups(
    cues: list[tuple[float, str]],
) -> list[tuple[float, str]]:
    """Drop a cue whose cleaned text repeats the immediately preceding one.

    Consecutive-only, whole-video-order comparison (AC-2).
    """
    deduped: list[tuple[float, str]] = []
    for start, cue_text in cues:
        if deduped and deduped[-1][1] == cue_text:
            continue
        deduped.append((start, cue_text))
    return deduped


def _format_date(upload_date: str) -> str:
    """Reformat an info.json "YYYYMMDD" upload_date to ISO "YYYY-MM-DD"."""
    if len(upload_date) == 8 and upload_date.isdigit():
        return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
    return upload_date


def _find_vtt(directory: Path, stem: str) -> Path | None:
    """Find `<stem>.*.vtt` in `directory` via exact-stem string matching.

    Deliberately avoids `Path.glob`/`fnmatch` with an interpolated stem --
    yt-dlp stems legitimately contain glob metacharacters (its own `[<id>]`
    bracket suffix is a glob character class), which would silently match
    nothing. Matches instead via plain `str.startswith`/`endswith` over
    `directory.iterdir()`.
    """
    prefix = f"{stem}."
    candidates = sorted(
        p.name
        for p in directory.iterdir()
        if p.is_file() and p.name.startswith(prefix) and p.name.endswith(".vtt")
    )
    return directory / candidates[0] if candidates else None


def _build_window_docs(
    video_id: str,
    cues: list[tuple[float, str]],
    date_iso: str,
    jurisdiction: str | None,
) -> list[Doc]:
    windows: dict[int, list[str]] = {}
    for start, cue_text in cues:
        window_index = int(start // WINDOW_SECONDS)
        windows.setdefault(window_index, []).append(cue_text)

    docs: list[Doc] = []
    for window_index in sorted(windows):
        window_text = " ".join(windows[window_index]).strip()
        docs.append(
            Doc(
                id=f"yt:{video_id}:seg{window_index:03d}",
                text=window_text,
                source_type="county_meeting",
                venue_type="sworn",
                date=date_iso,
                deep_link=(
                    f"https://youtube.com/watch?v={video_id}&t={window_index * WINDOW_SECONDS}s"
                ),
                ticker=None,
                jurisdiction=jurisdiction,
                speaker=None,
            )
        )
    return docs


def parse_video_dir(directory: str | Path, registry_entry: dict[str, Any]) -> list[Doc]:
    """Parse every `<stem>.info.json` + `<stem>.*.vtt` pair in `directory`.

    See the module docstring for the full frozen contract: file discovery,
    rollup dedupe, 75s windowing + boundary rule, and Doc field mapping.
    """
    directory = Path(directory)
    jurisdiction = registry_entry.get("jurisdiction")

    docs: list[Doc] = []
    info_paths = sorted(directory.glob(f"*{_INFO_JSON_SUFFIX}"))
    for info_path in info_paths:
        stem = info_path.name[: -len(_INFO_JSON_SUFFIX)]

        try:
            info = json.loads(info_path.read_text())
        except (OSError, ValueError):
            logger.warning(
                "skipping video %r: unreadable/malformed info.json (%s)", stem, info_path.name
            )
            continue

        video_id = info.get("id") or stem

        vtt_path = _find_vtt(directory, stem)
        if vtt_path is None:
            logger.warning(
                "skipping video %s (%r): no matching .vtt caption file found (no English subs?)",
                video_id,
                stem,
            )
            continue

        try:
            cues = _parse_vtt_cues(vtt_path.read_text())
        except (OSError, ValueError) as exc:
            logger.warning(
                "skipping video %s (%r): malformed/truncated .vtt (%s)", video_id, stem, exc
            )
            continue

        cues = _dedupe_consecutive_rollups(cues)
        if not cues:
            continue

        date_iso = _format_date(str(info.get("upload_date", "")))
        docs.extend(_build_window_docs(video_id, cues, date_iso, jurisdiction))

    return docs

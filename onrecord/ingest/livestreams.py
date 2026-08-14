"""Live & upcoming hearings tracking — T-051.

The registry's channel URLs are curated labels; the REAL channels are
derived from the corpus itself: the newest link-health-alive video per
jurisdiction resolves (via YouTube oembed `author_url`) to the actual
channel, whose `/streams` tab lists live and scheduled hearings. The
operational `track()` writes `artifacts/livestreams.json`; the pure parts
are pinned by tests/unit/ingest/test_livestreams.py.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path

import httpx

from onrecord.types import Doc

logger = logging.getLogger(__name__)

DEFAULT_OUT = Path("artifacts/livestreams.json")
OEMBED_URL = "https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json"
_TRACKED_STATUSES = ("is_live", "is_upcoming")


def newest_alive_video_per_jurisdiction(
    docs: list[Doc], alive_ids: set[str]
) -> dict[str, str]:
    """Per jurisdiction, the video id of the newest county-meeting doc whose
    video is alive. See module docstring / frozen tests."""
    best: dict[str, tuple[str, str]] = {}  # jurisdiction -> (date, vid)
    for doc in docs:
        if doc.source_type != "county_meeting" or not doc.jurisdiction:
            continue
        parts = doc.id.split(":")
        if len(parts) < 3 or parts[0] != "yt":
            continue
        vid = parts[1]
        if vid not in alive_ids:
            continue
        date = doc.date or ""
        if doc.jurisdiction not in best or date > best[doc.jurisdiction][0]:
            best[doc.jurisdiction] = (date, vid)
    return {jur: vid for jur, (_date, vid) in best.items()}


def parse_stream_lines(lines: list[str], jurisdiction: str) -> list[dict]:
    """yt-dlp flat-playlist "id|live_status|title" lines -> tracked
    entries (is_live / is_upcoming only); malformed lines skipped."""
    out: list[dict] = []
    for line in lines:
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        vid, status, title = (p.strip() for p in parts)
        if status not in _TRACKED_STATUSES or not vid:
            continue
        out.append(
            {
                "jurisdiction": jurisdiction,
                "video_id": vid,
                "title": title,
                "status": status,
                "url": f"https://www.youtube.com/watch?v={vid}",
            }
        )
    return out


# Precision over recall, deliberately: this strip feeds a trust product, so
# only clearly hearing-titled streams qualify. Resolved channels can be
# wrong (a news channel that covered one meeting) and municipal channels
# run 24/7 scenery cams -- both fail this lexicon and stay out.
HEARING_TITLE_MARKERS: tuple[str, ...] = (
    "meeting", "session", "council", "board", "commission", "hearing",
    "supervisors", "committee", "workshop", "budget", "planning", "zoning",
    "agenda", "trustees", "aldermen",
)


def filter_hearings(entries: list[dict]) -> list[dict]:
    """Keep only entries whose title contains a hearing marker."""
    out = []
    for entry in entries:
        title = str(entry.get("title", "")).lower()
        if any(marker in title for marker in HEARING_TITLE_MARKERS):
            out.append(entry)
    return out


# --------------------------------------------------------------------------
# Operational tracker (live network; exercised by `make refresh-live`)
# --------------------------------------------------------------------------


def _channel_for_video(client: httpx.Client, vid: str) -> str | None:
    try:
        response = client.get(OEMBED_URL.format(vid=vid), timeout=15.0)
        if response.status_code != 200:
            return None
        return response.json().get("author_url")
    except (httpx.HTTPError, ValueError):
        return None


def _streams_for_channel(channel_url: str, jurisdiction: str) -> list[dict]:
    try:
        result = subprocess.run(
            ["yt-dlp", "--flat-playlist", "--print", "%(id)s|%(live_status)s|%(title)s",
             "--playlist-items", "1:10", channel_url.rstrip("/") + "/streams"],
            capture_output=True, text=True, timeout=90,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []  # no streams tab / channel gone -- a skip, never a failure
    return parse_stream_lines(result.stdout.splitlines(), jurisdiction)


def track(docs: list[Doc], alive_ids: set[str], out_path: str | Path = DEFAULT_OUT,
          checked_at: str = "") -> dict:
    """Resolve every jurisdiction's real channel and collect live/upcoming
    hearings into `out_path`. Returns the written payload."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    anchors = newest_alive_video_per_jurisdiction(docs, alive_ids)
    entries: list[dict] = []
    channels: dict[str, str] = {}
    with httpx.Client(headers={"User-Agent": "onrecord-livestreams"}) as client:
        for jurisdiction, vid in sorted(anchors.items()):
            channel = _channel_for_video(client, vid)
            if not channel:
                continue
            channels[jurisdiction] = channel
            found = filter_hearings(_streams_for_channel(channel, jurisdiction))
            entries.extend(found)
            if found:
                print(f"{jurisdiction}: {len(found)} live/upcoming", flush=True)
            time.sleep(0.2)
    payload = {
        "checked_at": checked_at,
        "jurisdictions_resolved": len(channels),
        "live": [e for e in entries if e["status"] == "is_live"],
        "upcoming": [e for e in entries if e["status"] == "is_upcoming"],
        "channels": channels,
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    return payload

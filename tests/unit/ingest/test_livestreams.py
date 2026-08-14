"""Failing tests for T-051 — live & upcoming hearings tracking.

``newest_alive_video_per_jurisdiction(docs, alive_ids) -> dict`` (pure):
county-meeting docs only; per jurisdiction, the video id (from
`yt:<vid>:segNNN` ids) of the doc with the NEWEST date whose video id is
in `alive_ids`; jurisdictions with no alive video are absent.

``parse_stream_lines(lines, jurisdiction) -> list[dict]`` (pure): yt-dlp
flat-playlist "id|live_status|title" lines -> entries filtered to
live_status in {"is_live", "is_upcoming"}; each
{"jurisdiction", "video_id", "title", "status", "url"
(watch URL)}; malformed lines skipped.
"""

import pytest

try:
    from onrecord.ingest import livestreams
except Exception:  # pragma: no cover - red phase
    livestreams = None

from onrecord.types import Doc


def _attr(name):
    if livestreams is None or not hasattr(livestreams, name):
        pytest.fail(f"onrecord.ingest.livestreams.{name} does not exist yet (T-051 red)")
    return getattr(livestreams, name)


def _doc(vid, seg, jur, date, source="county_meeting"):
    return Doc(id=f"yt:{vid}:seg{seg:03d}", text="t", source_type=source,
               venue_type="public", date=date,
               deep_link=f"https://youtube.com/watch?v={vid}&t=0s",
               jurisdiction=jur)


def test_newest_alive_video_per_jurisdiction():
    docs = [
        _doc("aaa", 0, "Alpha County, VA", "2026-01-01"),
        _doc("bbb", 0, "Alpha County, VA", "2026-06-01"),   # newest but DEAD
        _doc("ccc", 0, "Alpha County, VA", "2026-03-01"),   # newest ALIVE
        _doc("ddd", 0, "Beta County, GA", "2026-02-01"),
        _doc("eee", 0, "Gamma, TX", "2026-05-01"),          # dead, only video
        _doc("fff", 0, None, "2026-05-01"),                 # no jurisdiction
        _doc("ggg", 0, "Delta, OH", "2026-04-01", source="filing"),  # not a meeting
    ]
    alive = {"aaa", "ccc", "ddd"}
    out = _attr("newest_alive_video_per_jurisdiction")(docs, alive)
    assert out == {"Alpha County, VA": "ccc", "Beta County, GA": "ddd"}


def test_parse_stream_lines_filters_and_shapes():
    lines = [
        "v1|is_live|Board of Supervisors — Regular Session",
        "v2|is_upcoming|Zoning Adjustment (08/25/26)",
        "v3|was_live|Last week's session",
        "v4|not_live|Ordinary upload",
        "garbage-without-pipes",
        "v5||untagged",
    ]
    out = _attr("parse_stream_lines")(lines, "Alpha County, VA")
    assert [e["video_id"] for e in out] == ["v1", "v2"]
    live = out[0]
    assert live["status"] == "is_live"
    assert live["jurisdiction"] == "Alpha County, VA"
    assert live["url"] == "https://www.youtube.com/watch?v=v1"
    assert "Regular Session" in live["title"]


def test_filter_hearings_keeps_meetings_drops_cams_and_news():
    fh = _attr("filter_hearings")
    entries = [
        {"title": "Board of Supervisors — Regular Session", "status": "is_live"},
        {"title": "Special Meeting: Board of Zoning Adjustment (08/25/26)",
         "status": "is_upcoming"},
        {"title": "City Council Work Session", "status": "is_upcoming"},
        {"title": "Planning Commission Public Hearing", "status": "is_live"},
        {"title": "🔴LIVE 24/7 Goodyear Ballpark Field Cam", "status": "is_live"},
        {"title": "City of Des Moines Skyline Camera", "status": "is_live"},
        {"title": "Luigi Mangione pleads guilty in federal court", "status": "is_live"},
        {"title": "Budget Committee Workshop", "status": "is_upcoming"},
    ]
    kept = fh(entries)
    assert [e["title"].split(" ")[0] for e in kept] == [
        "Board", "Special", "City", "Planning", "Budget"
    ]

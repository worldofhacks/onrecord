"""Failing tests for T-041 — the Dodge Index (deterministic evasion scoring).

Contract (fixed here):

``DODGE_MARKERS: tuple[str, ...]`` — the frozen, committed marker lexicon.
Lowercase phrases; scoring is case-insensitive substring counting.

``count_markers(text: str) -> int`` (pure) — total occurrences of every
marker in `text`, case-insensitive, non-overlapping per marker.

``dodge_index(docs, min_docs=200) -> list[dict]`` (pure) — `docs` is the
corpus `Doc` list. Only `source_type == "county_meeting"` docs with a
jurisdiction count. Groups by jurisdiction; jurisdictions with fewer than
`min_docs` qualifying docs are EXCLUDED (small-sample noise floor). Rows:
``{"jurisdiction", "docs", "markers", "per_1000", "sample_receipts"}``
sorted by `per_1000` descending, ties by jurisdiction ascending.
`per_1000 = markers / docs * 1000` rounded to 1 decimal.
`sample_receipts` = up to 3 `{"doc_id", "deep_link"}` from marker-bearing
docs, in corpus order. No LLM anywhere — reproducible by construction.
"""

import pytest

try:
    from onrecord.analysis import dodge
except Exception:  # pragma: no cover - red phase
    dodge = None

from onrecord.types import Doc


def _attr(name):
    if dodge is None or not hasattr(dodge, name):
        pytest.fail(f"onrecord.analysis.dodge.{name} does not exist yet (T-041 red)")
    return getattr(dodge, name)


def _doc(i, jurisdiction, text, source_type="county_meeting"):
    return Doc(
        id=f"yt:test:seg{i:03d}", text=text, source_type=source_type,
        venue_type="public", date="2026-01-01",
        deep_link=f"https://youtube.com/watch?v=test&t={i}s",
        jurisdiction=jurisdiction,
    )


def test_marker_lexicon_is_frozen_lowercase_and_nonempty():
    markers = _attr("DODGE_MARKERS")
    assert isinstance(markers, tuple) and len(markers) >= 8
    assert all(m == m.lower() for m in markers)
    assert "no comment" in markers and "get back to you" in markers


def test_count_markers_case_insensitive_multi_hit():
    count = _attr("count_markers")
    text = "I have No Comment. We will get back to you, and again: no comment."
    assert count(text) == 3
    assert count("nothing evasive here at all") == 0


def test_dodge_index_groups_floors_and_ranks():
    count_needed = 3  # use a tiny floor for the fixture
    docs = []
    # Jurisdiction A: 4 meeting docs, 3 markers total -> 750.0 per 1000
    docs.append(_doc(0, "Alpha County, VA", "we will get back to you on that"))
    docs.append(_doc(1, "Alpha County, VA", "no comment. no comment."))
    docs.append(_doc(2, "Alpha County, VA", "the budget passed unanimously"))
    docs.append(_doc(3, "Alpha County, VA", "meeting adjourned"))
    # Jurisdiction B: 3 docs, 1 marker -> 333.3
    docs.append(_doc(4, "Beta County, GA", "cannot comment on pending litigation"))
    docs.append(_doc(5, "Beta County, GA", "roll call vote"))
    docs.append(_doc(6, "Beta County, GA", "minutes approved"))
    # Jurisdiction C: below the floor -> excluded
    docs.append(_doc(7, "Gamma County, TX", "no comment"))
    # Filing docs never count, regardless of jurisdiction
    docs.append(_doc(8, "Alpha County, VA", "no comment", source_type="filing"))

    rows = _attr("dodge_index")(docs, min_docs=count_needed)

    assert [r["jurisdiction"] for r in rows] == ["Alpha County, VA", "Beta County, GA"]
    alpha = rows[0]
    assert alpha["docs"] == 4 and alpha["markers"] == 3
    assert alpha["per_1000"] == 750.0
    assert 1 <= len(alpha["sample_receipts"]) <= 3
    assert alpha["sample_receipts"][0]["doc_id"] == "yt:test:seg000"
    assert alpha["sample_receipts"][0]["deep_link"].startswith("https://")
    beta = rows[1]
    assert beta["per_1000"] == pytest.approx(333.3)


def test_dodge_index_empty_and_no_qualifiers():
    fn = _attr("dodge_index")
    assert fn([], min_docs=200) == []
    lone = [_doc(0, "Solo County, OH", "no comment")]
    assert fn(lone, min_docs=200) == []

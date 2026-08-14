"""Frozen tests — T-060 8-K event typing.

Pins `onrecord.analysis.events8k`: line-anchored `Item N.NN` header
extraction (the decimal item grammar is 8-K-specific), the frozen taxonomy
mapping, and the build-fails-on-unknown-codes contract (AC-3: unknown item
codes are a loud failure, never silently dropped).

Written before implementation (tdd-swarm Iron Law). Spec tags: spec(T-060:AC-n).
"""

import pytest

try:
    from onrecord.analysis import events8k
except Exception:  # pragma: no cover - red phase
    events8k = None

from onrecord.types import Doc


def _attr(name):
    if events8k is None or not hasattr(events8k, name):
        pytest.fail(f"onrecord.analysis.events8k.{name} does not exist yet (T-060 red)")
    return getattr(events8k, name)


def _filing(doc_id, ticker, date, text):
    return Doc(id=doc_id, text=text, source_type="filing", venue_type="sworn",
               date=date, deep_link=f"https://sec.gov/{doc_id}", ticker=ticker)


class TestExtractItems:
    def test_plain_header(self):
        """spec(T-060:AC-1)"""
        extract = _attr("extract_items")
        assert extract("Item 1.01 Entry into a Material Definitive Agreement\ntext") == ["1.01"]

    def test_uppercase_and_trailing_dot(self):
        """spec(T-060:AC-1)"""
        extract = _attr("extract_items")
        assert extract("ITEM 2.03. Creation of a Direct Financial Obligation") == ["2.03"]

    def test_narrow_space_whitespace_variant(self):
        """spec(T-060:AC-1) — real corpus uses U+202F between Item and code."""
        extract = _attr("extract_items")
        assert extract("Item 8.01  Other Events") == ["8.01"]

    def test_multiple_items_in_document_order(self):
        """spec(T-060:AC-1)"""
        extract = _attr("extract_items")
        text = "Item 1.01 Agreement\nsome text\nItem 9.01 Financial Statements"
        assert extract(text) == ["1.01", "9.01"]

    def test_duplicate_headers_deduped(self):
        """spec(T-060:AC-1)"""
        extract = _attr("extract_items")
        text = "Item 7.01 Reg FD\ncontinued\nItem 7.01 Reg FD (continued)"
        assert extract(text) == ["7.01"]

    def test_mid_line_prose_reference_does_not_fire(self):
        """spec(T-060:AC-1) — 'pursuant to Item 1.01 of' in prose is not a header."""
        extract = _attr("extract_items")
        text = "as described pursuant to Item 1.01 of the Company's prior filing"
        assert extract(text) == []

    def test_section_code_lookalike_does_not_fire(self):
        """spec(T-060:AC-1) — zoning-code style references lack the Item prefix."""
        extract = _attr("extract_items")
        assert extract("under section 8.01 of the zoning code") == []


class TestTaxonomy:
    def test_labels_cover_core_codes(self):
        """spec(T-060:AC-3)"""
        labels = _attr("ITEM_LABELS")
        assert labels["1.01"].startswith("Entry into a Material Definitive Agreement")
        assert labels["2.03"].startswith("Creation of a Direct Financial Obligation")
        assert labels["5.02"].startswith("Departure of Directors")
        assert labels["7.01"] == "Regulation FD Disclosure"
        assert labels["8.01"] == "Other Events"


class TestBuildEvents:
    def test_rows_shape_and_scope(self):
        """spec(T-060:AC-2) — filing docs only; rows carry receipts."""
        build = _attr("build_events")
        docs = [
            _filing("edgar:NVDA:0001-26-000001:body", "NVDA", "2026-03-01",
                    "Item 1.01 Entry into a Material Definitive Agreement\n..."),
            _filing("edgar:MSFT:0001-26-000002:body", "MSFT", "2026-04-01",
                    "Item 2.03 Creation of a Direct Financial Obligation\n..."),
            Doc(id="yt:abc:seg001", text="Item 1.01 read aloud in a meeting",
                source_type="county_meeting", venue_type="public",
                date="2026-05-01", deep_link="https://youtube.com/watch?v=abc",
                jurisdiction="Alpha County, VA"),
        ]
        rows = build(docs)
        assert len(rows) == 2  # the county doc never produces an event
        nvda = next(r for r in rows if r["ticker"] == "NVDA")
        assert nvda == {"doc_id": "edgar:NVDA:0001-26-000001:body", "ticker": "NVDA",
                        "date": "2026-03-01", "items": ["1.01"],
                        "deep_link": "https://sec.gov/edgar:NVDA:0001-26-000001:body"}

    def test_unknown_code_fails_loudly(self):
        """spec(T-060:AC-3) — never silently dropped."""
        build = _attr("build_events")
        bad = _filing("edgar:X:1:body", "X", "2026-01-01", "Item 1.99 Made-up Section")
        with pytest.raises(ValueError, match="1.99"):
            build([bad])

    def test_rows_sorted_date_desc(self):
        """spec(T-060:AC-2)"""
        build = _attr("build_events")
        docs = [
            _filing("edgar:A:1:body", "A", "2026-01-01", "Item 8.01 Other Events"),
            _filing("edgar:B:2:body", "B", "2026-06-01", "Item 7.01 Regulation FD Disclosure"),
        ]
        assert [r["ticker"] for r in build(docs)] == ["B", "A"]

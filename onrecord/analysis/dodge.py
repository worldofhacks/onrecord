"""The Dodge Index — deterministic evasion scoring per jurisdiction (T-041).

No LLM anywhere: a frozen marker lexicon, case-insensitive substring
counting, and a per-1000-docs rate with a minimum-doc floor. Every number
is reproducible from the corpus and the lexicon below, and every row
carries sample receipts so the score is auditable, not vibes. Contract
pinned by tests/unit/analysis/test_dodge.py.
"""

from __future__ import annotations

from collections import defaultdict

from onrecord.types import Doc

# The frozen lexicon. Lowercase phrases; matching is case-insensitive.
# Deliberately conservative: each phrase is an explicit deferral/refusal
# formula, not a hedge word — hedges ("maybe", "we'll see") would flood
# the metric with false positives.
DODGE_MARKERS: tuple[str, ...] = (
    "no comment",
    "cannot comment",
    "can't comment",
    "not at liberty",
    "get back to you",
    "take that offline",
    "take this offline",
    "defer to counsel",
    "on advice of counsel",
    "not prepared to answer",
    "decline to answer",
    "we'll circle back",
    "outside the scope of this meeting",
)


def count_markers(text: str) -> int:
    """Total marker occurrences in `text`, case-insensitive,
    non-overlapping per marker phrase."""
    lowered = text.lower()
    return sum(lowered.count(marker) for marker in DODGE_MARKERS)


def dodge_index(docs: list[Doc], min_docs: int = 200) -> list[dict]:
    """Per-jurisdiction evasion rows over county-meeting docs. See module
    docstring / frozen tests for the contract."""
    by_jur: dict[str, dict] = defaultdict(
        lambda: {"docs": 0, "markers": 0, "samples": []}
    )
    for doc in docs:
        if doc.source_type != "county_meeting" or not doc.jurisdiction:
            continue
        bucket = by_jur[doc.jurisdiction]
        bucket["docs"] += 1
        hits = count_markers(doc.text)
        if hits:
            bucket["markers"] += hits
            if len(bucket["samples"]) < 3:
                bucket["samples"].append(
                    {"doc_id": doc.id, "deep_link": doc.deep_link}
                )

    rows = [
        {
            "jurisdiction": jurisdiction,
            "docs": bucket["docs"],
            "markers": bucket["markers"],
            "per_1000": round(bucket["markers"] / bucket["docs"] * 1000, 1),
            "sample_receipts": bucket["samples"],
        }
        for jurisdiction, bucket in by_jur.items()
        if bucket["docs"] >= min_docs
    ]
    rows.sort(key=lambda row: (-row["per_1000"], row["jurisdiction"]))
    return rows

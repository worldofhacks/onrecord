"""8-K event typing — T-060.

Line-anchored `Item N.NN` header extraction over filing docs. The decimal
item grammar is 8-K-specific (10-K/10-Q items carry no decimals), so the
grammar itself selects 8-K events; prose references mid-line ("pursuant to
Item 1.01 of...") never fire. Unknown item codes fail the build loudly
(AC-3) — the taxonomy below is the complete Reg-S-K 8-K item list, so an
unknown code means either a new SEC rule or a parsing defect, both of
which deserve a human.
"""

from __future__ import annotations

import re

from onrecord.types import Doc

__all__ = ["extract_items", "build_events", "ITEM_LABELS"]

# The complete 8-K item taxonomy (Reg S-K; ABS items 6.xx included).
ITEM_LABELS: dict[str, str] = {
    "1.01": "Entry into a Material Definitive Agreement",
    "1.02": "Termination of a Material Definitive Agreement",
    "1.03": "Bankruptcy or Receivership",
    "1.04": "Mine Safety — Shutdowns and Violations",
    "1.05": "Material Cybersecurity Incidents",
    "2.01": "Completion of Acquisition or Disposition of Assets",
    "2.02": "Results of Operations and Financial Condition",
    "2.03": "Creation of a Direct Financial Obligation or Off-Balance-Sheet Arrangement",
    "2.04": "Triggering Events That Accelerate or Increase a Direct Financial Obligation",
    "2.05": "Costs Associated with Exit or Disposal Activities",
    "2.06": "Material Impairments",
    "3.01": "Notice of Delisting or Failure to Satisfy a Listing Rule",
    "3.02": "Unregistered Sales of Equity Securities",
    "3.03": "Material Modification to Rights of Security Holders",
    "4.01": "Changes in Registrant's Certifying Accountant",
    "4.02": "Non-Reliance on Previously Issued Financial Statements",
    "5.01": "Changes in Control of Registrant",
    "5.02": "Departure of Directors or Certain Officers; Election; Compensation",
    "5.03": "Amendments to Articles of Incorporation or Bylaws; Fiscal Year Change",
    "5.04": "Temporary Suspension of Trading Under Employee Benefit Plans",
    "5.05": "Amendments to the Code of Ethics",
    "5.06": "Change in Shell Company Status",
    "5.07": "Submission of Matters to a Vote of Security Holders",
    "5.08": "Shareholder Director Nominations",
    "6.01": "ABS Informational and Computational Material",
    "6.02": "Change of Servicer or Trustee",
    "6.03": "Change in Credit Enhancement or Other External Support",
    "6.04": "Failure to Make a Required Distribution",
    "6.05": "Securities Act Updating Disclosure",
    "6.06": "Static Pool",
    "7.01": "Regulation FD Disclosure",
    "8.01": "Other Events",
    "9.01": "Financial Statements and Exhibits",
}

# Line-anchored, case-insensitive, tolerant of exotic whitespace (the real
# corpus separates "Item" and the code with U+202F narrow no-break spaces).
_HEADER_RE = re.compile(r"^[^\S\n]*item[\s  ]+(\d\.\d\d)\b",
                        re.IGNORECASE | re.MULTILINE)


def extract_items(text: str) -> list[str]:
    """Item codes appearing as line-anchored headers, document order,
    deduped (first occurrence wins)."""
    seen: list[str] = []
    for match in _HEADER_RE.finditer(text):
        code = match.group(1)
        if code not in seen:
            seen.append(code)
    return seen


def build_events(docs: list[Doc]) -> list[dict]:
    """Event rows from filing docs, date descending. Raises ValueError
    naming any item code outside ITEM_LABELS (loud, never dropped)."""
    rows: list[dict] = []
    unknown: set[str] = set()
    for doc in docs:
        if doc.source_type != "filing":
            continue
        items = extract_items(doc.text)
        if not items:
            continue
        unknown.update(code for code in items if code not in ITEM_LABELS)
        rows.append({
            "doc_id": doc.id,
            "ticker": doc.ticker,
            "date": doc.date,
            "items": items,
            "deep_link": doc.deep_link,
        })
    if unknown:
        raise ValueError(
            f"build_events: unknown 8-K item code(s) {sorted(unknown)} — "
            f"extend ITEM_LABELS deliberately or fix the header grammar"
        )
    rows.sort(key=lambda r: str(r["date"] or ""), reverse=True)
    return rows

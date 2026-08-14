"""Promise -> outcome tracking — T-057 (the accountability engine, v1).

Deterministic follow-up trails: for each promise, the SAME jurisdiction's
STRICTLY LATER documents are scanned for three echo signals — quantity
(a T-056 extraction of the same kind and normalized value), entity (a
word-boundary term hit), phrase (a distinctive 4-content-token n-gram of
the quote). Every trail row's `matched_span` is a verbatim substring of
its follow-up document, so trails inherit receipts end to end.

HONESTY PIN (frozen test greps this module): the record can show a promise
was followed up, or that the record has gone quiet — it never adjudicates.
Status enum is exactly {followed_up, quiet, too_recent}; "quiet" requires
more than 90 days of later record with no echo.
"""

from __future__ import annotations

import re
from datetime import date as _date

from onrecord.analysis.quantities import extract_quantities
from onrecord.types import Doc

__all__ = ["match_signals", "build_outcomes", "QUIET_AFTER_DAYS"]

QUIET_AFTER_DAYS = 90
TRAIL_CAP = 5

_STOPWORDS = frozenset(
    "the a an of to in on for and or this that these those will we they it "
    "is are was were be been our its their his her at with by as from".split()
)
_TOKEN_RE = re.compile(r"[A-Za-z0-9$']+")
_PHRASE_WINDOW = 4
# Between phrase tokens, allow short filler words (articles/prepositions)
# so "Pine Log Road widening" also matches "Pine Log Road, the widening".
_FILLER = r"(?:\W+\w{1,3})*\W+"


def _content_tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


def _days_between(earlier: str, later: str) -> int:
    return (_date.fromisoformat(later[:10]) - _date.fromisoformat(earlier[:10])).days


def _quantity_signal(promise_quantities: list[dict], doc_text: str) -> dict | None:
    if not promise_quantities:
        return None
    promised = {(q["kind"], q["value"]) for q in promise_quantities}
    for extraction in extract_quantities(doc_text):
        if (extraction["kind"], extraction["value"]) in promised:
            return {"signal": "quantity", "matched_span": extraction["raw_span"]}
    return None


def _entity_signal(entity_terms: list[str], doc_text: str) -> dict | None:
    for term in entity_terms:
        if not term:
            continue
        match = re.search(rf"\b{re.escape(term)}\b", doc_text)
        if match:
            return {"signal": "entity", "matched_span": match.group(0)}
    return None


def _phrase_signal(quote: str, doc_text: str) -> dict | None:
    tokens = _content_tokens(quote)
    seen: set[tuple[str, ...]] = set()
    for i in range(len(tokens) - _PHRASE_WINDOW + 1):
        window = tuple(tokens[i: i + _PHRASE_WINDOW])
        if window in seen:
            continue
        seen.add(window)
        pattern = _FILLER.join(re.escape(t) for t in window)
        match = re.search(pattern, doc_text, re.IGNORECASE)
        if match:
            return {"signal": "phrase", "matched_span": match.group(0)}
    return None


def match_signals(promise: dict, doc: Doc, entity_terms: list[str]) -> list[dict]:
    """All echo signals of `promise` present in `doc`, priority order
    quantity > entity > phrase; matched_span verbatim in doc.text."""
    quote = str(promise.get("quote", ""))
    signals = [
        _quantity_signal(extract_quantities(quote), doc.text),
        _entity_signal(entity_terms, doc.text),
        _phrase_signal(quote, doc.text),
    ]
    return [s for s in signals if s is not None]


def build_outcomes(
    promises: list[dict],
    docs: list[Doc],
    today: str,
    entity_terms_fn=None,
) -> dict[str, dict]:
    """Per promise_id: {"status", "trail"}. Trails draw only from docs in
    the promise's jurisdiction with a strictly later date; one row per
    matched doc (highest-priority signal), date ascending, capped at
    TRAIL_CAP. `today` is accepted for signature stability; the quiet
    boundary is defined by the record itself (newest later doc), not the
    wall clock."""
    del today
    by_jurisdiction: dict[str, list[Doc]] = {}
    for doc in docs:
        if doc.jurisdiction:
            by_jurisdiction.setdefault(doc.jurisdiction, []).append(doc)
    for rows in by_jurisdiction.values():
        rows.sort(key=lambda d: d.date)

    # Behavior-invariant caches for the full-corpus scan (AC-4's <60s
    # budget): doc-side quantity extractions and content-token sets are
    # computed once per doc; the phrase regex only runs when a window's
    # tokens are all present in the doc's token set (a pure prefilter —
    # the regex remains the deciding check).
    doc_quantities: dict[str, list[dict]] = {}
    doc_tokens: dict[str, frozenset[str]] = {}
    # Every extractable pattern requires one of these substrings (unit
    # keywords / $): a text containing none of them cannot extract, so the
    # six-regex pass is skipped for it. Pure prefilter — the regexes remain
    # the deciding check on hint-positive docs.
    _hints = ("$", "mw", "gw", "kw", "megawatt", "gigawatt", "kilowatt",
              "gallon", "job", "position", "employee", "dollars")

    def _doc_quantities(doc: Doc) -> list[dict]:
        if doc.id not in doc_quantities:
            lowered = doc.text.lower()
            doc_quantities[doc.id] = (
                extract_quantities(doc.text)
                if any(h in lowered for h in _hints)
                else []
            )
        return doc_quantities[doc.id]

    def _doc_tokens(doc: Doc) -> frozenset[str]:
        if doc.id not in doc_tokens:
            doc_tokens[doc.id] = frozenset(_content_tokens(doc.text))
        return doc_tokens[doc.id]

    out: dict[str, dict] = {}
    for promise in promises:
        pid = promise["promise_id"]
        jurisdiction = promise.get("jurisdiction")
        promise_date = str(promise.get("date") or "")
        candidates = [
            d for d in by_jurisdiction.get(jurisdiction, [])
            if promise_date and d.date > promise_date
        ]
        entity_terms = entity_terms_fn(promise) if entity_terms_fn else []
        quote = str(promise.get("quote", ""))
        promised = extract_quantities(quote)
        promised_pairs = {(q["kind"], q["value"]) for q in promised}
        quote_windows = []
        tokens = _content_tokens(quote)
        for i in range(len(tokens) - _PHRASE_WINDOW + 1):
            quote_windows.append(frozenset(tokens[i: i + _PHRASE_WINDOW]))

        trail: list[dict] = []
        for doc in candidates:
            best = None
            if promised_pairs:
                for extraction in _doc_quantities(doc):
                    if (extraction["kind"], extraction["value"]) in promised_pairs:
                        best = {"signal": "quantity",
                                "matched_span": extraction["raw_span"]}
                        break
            if best is None and entity_terms:
                best = _entity_signal(entity_terms, doc.text)
            if best is None and quote_windows:
                tokens_here = _doc_tokens(doc)
                if any(w <= tokens_here for w in quote_windows):
                    best = _phrase_signal(quote, doc.text)
            if best is not None:
                trail.append({
                    "doc_id": doc.id,
                    "date": doc.date,
                    "signal": best["signal"],
                    "matched_span": best["matched_span"],
                    "deep_link": doc.deep_link,
                })
            if len(trail) >= TRAIL_CAP:
                break

        if trail:
            status = "followed_up"
        elif candidates and _days_between(promise_date, candidates[-1].date) > QUIET_AFTER_DAYS:
            status = "quiet"
        else:
            status = "too_recent"
        out[pid] = {"status": status, "trail": trail}
    return out

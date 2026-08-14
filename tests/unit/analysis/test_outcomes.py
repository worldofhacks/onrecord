"""Frozen tests — T-057 promise -> outcome tracking.

Pins `onrecord.analysis.outcomes`: deterministic follow-up trails. Load-
bearing honesty invariants: trails only from the SAME jurisdiction and
STRICTLY LATER docs, every matched_span verbatim in its follow-up doc
(AC-1); the status enum is exactly {followed_up, quiet, too_recent} with
the 90-day boundary pinned, and the module must never emit verdict words
("broken"/"kept") anywhere (AC-2 — the record observes mentions, it does
not adjudicate promises).

Written before implementation (tdd-swarm Iron Law). Spec tags: spec(T-057:AC-n).
"""

import inspect

import pytest

try:
    from onrecord.analysis import outcomes
except Exception:  # pragma: no cover - red phase
    outcomes = None

from onrecord.types import Doc


def _attr(name):
    if outcomes is None or not hasattr(outcomes, name):
        pytest.fail(f"onrecord.analysis.outcomes.{name} does not exist yet (T-057 red)")
    return getattr(outcomes, name)


def _doc(doc_id, jur, date, text):
    return Doc(id=doc_id, text=text, source_type="county_meeting",
               venue_type="public", date=date,
               deep_link=f"https://youtube.com/watch?v={doc_id}&t=0s",
               jurisdiction=jur)


def _promise(pid="d0#p1", jur="Alpha County, VA", date="2026-01-10",
             quote="we will deliver 300 megawatts and 4 million dollars in annual tax revenue",
             ticker=None):
    return {"promise_id": pid, "doc_id": pid.split("#")[0], "date": date,
            "jurisdiction": jur, "ticker": ticker, "quote": quote}


# ---------------------------------------------------------------------------
# AC-1 — candidate scoping and span verbatim
# ---------------------------------------------------------------------------


class TestCandidateScoping:
    def test_only_same_jurisdiction_strictly_later(self):
        """spec(T-057:AC-1)"""
        build = _attr("build_outcomes")
        docs = [
            _doc("early", "Alpha County, VA", "2026-01-05", "300 megawatts discussed"),
            _doc("same-day", "Alpha County, VA", "2026-01-10", "300 megawatts again"),
            _doc("other-jur", "Beta County, GA", "2026-02-01", "300 megawatts elsewhere"),
            _doc("later", "Alpha County, VA", "2026-02-01", "the 300 megawatts project advanced"),
        ]
        result = build([_promise()], docs, today="2026-03-01")
        trail = result["d0#p1"]["trail"]
        assert [t["doc_id"] for t in trail] == ["later"]

    def test_matched_span_is_verbatim_in_followup_doc(self):
        """spec(T-057:AC-1)"""
        build = _attr("build_outcomes")
        follow = _doc("later", "Alpha County, VA", "2026-02-01",
                      "staff confirmed the 300 megawatts interconnection request")
        result = build([_promise()], [follow], today="2026-03-01")
        for row in result["d0#p1"]["trail"]:
            assert row["matched_span"] in follow.text
            assert row["signal"] in ("quantity", "entity", "phrase")


# ---------------------------------------------------------------------------
# AC-3 — the quantity-echo signal
# ---------------------------------------------------------------------------


class TestQuantityEcho:
    def test_same_value_across_unit_forms_fires(self):
        """spec(T-057:AC-3) — 300 megawatts (promise) vs '300 MW' (later)."""
        build = _attr("build_outcomes")
        follow = _doc("later", "Alpha County, VA", "2026-02-01",
                      "the board reviewed the 300 MW substation application")
        result = build([_promise()], [follow], today="2026-03-01")
        signals = {t["signal"] for t in result["d0#p1"]["trail"]}
        assert "quantity" in signals

    def test_different_value_does_not_fire_quantity(self):
        """spec(T-057:AC-3)"""
        build = _attr("build_outcomes")
        follow = _doc("later", "Alpha County, VA", "2026-02-01",
                      "a separate 50 MW facility was proposed")
        result = build([_promise()], [follow], today="2026-03-01")
        signals = {t["signal"] for t in result["d0#p1"]["trail"]}
        assert "quantity" not in signals

    def test_money_echo_fires_on_equal_normalized_value(self):
        """spec(T-057:AC-3) — '$4 million' later matches '4 million dollars' promised."""
        build = _attr("build_outcomes")
        follow = _doc("later", "Alpha County, VA", "2026-02-01",
                      "the $4 million revenue projection appeared in the budget")
        result = build([_promise()], [follow], today="2026-03-01")
        assert any(t["signal"] == "quantity" for t in result["d0#p1"]["trail"])


# ---------------------------------------------------------------------------
# entity + phrase signals
# ---------------------------------------------------------------------------


class TestEntityAndPhrase:
    def test_entity_echo_uses_word_boundaries(self):
        """spec(T-057:AC-1) — term 'Vantage' must not fire inside 'advantageous'."""
        signals_fn = _attr("match_signals")
        promise = _promise(quote="Vantage will fund the road improvements")
        hit = _doc("h", "Alpha County, VA", "2026-02-01", "Vantage returned to the board")
        miss = _doc("m", "Alpha County, VA", "2026-02-01", "an advantageous arrangement")
        assert any(s["signal"] == "entity"
                   for s in signals_fn(promise, hit, entity_terms=["Vantage"]))
        assert not any(s["signal"] == "entity"
                       for s in signals_fn(promise, miss, entity_terms=["Vantage"]))

    def test_phrase_echo_requires_four_content_tokens(self):
        """spec(T-057:AC-1) — distinctive n-gram fires; short/generic overlap doesn't."""
        signals_fn = _attr("match_signals")
        promise = _promise(quote="fund the Pine Log Road widening project this year")
        hit = _doc("h", "Alpha County, VA", "2026-02-01",
                   "an update on the Pine Log Road widening project schedule")
        miss = _doc("m", "Alpha County, VA", "2026-02-01",
                    "the project will fund a study")
        assert any(s["signal"] == "phrase" for s in signals_fn(promise, hit, entity_terms=[]))
        assert not any(s["signal"] == "phrase" for s in signals_fn(promise, miss, entity_terms=[]))


# ---------------------------------------------------------------------------
# AC-2 — status enum, boundary, and the no-verdict pin
# ---------------------------------------------------------------------------


class TestStatus:
    def _build(self, docs, today):
        return _attr("build_outcomes")([_promise()], docs, today=today)["d0#p1"]

    def test_followed_up_when_trail_exists(self):
        """spec(T-057:AC-2)"""
        follow = _doc("later", "Alpha County, VA", "2026-02-01", "300 MW confirmed")
        assert self._build([follow], today="2026-02-15")["status"] == "followed_up"

    def test_quiet_needs_more_than_ninety_days_of_later_record(self):
        """spec(T-057:AC-2) — silent doc at +91d -> quiet; +90d -> too_recent."""
        silent_91 = _doc("s", "Alpha County, VA", "2026-04-11", "unrelated zoning matter")
        silent_90 = _doc("s", "Alpha County, VA", "2026-04-10", "unrelated zoning matter")
        assert self._build([silent_91], today="2026-05-01")["status"] == "quiet"
        assert self._build([silent_90], today="2026-05-01")["status"] == "too_recent"

    def test_no_later_record_at_all_is_too_recent(self):
        """spec(T-057:AC-2) — absence of record is not silence."""
        assert self._build([], today="2026-06-01")["status"] == "too_recent"

    def test_no_verdict_language_in_module(self):
        """spec(T-057:AC-2) — grep-gate: the module never adjudicates."""
        source = inspect.getsource(outcomes)
        for banned in ("broken", "kept", "fulfilled", "violated"):
            assert banned not in source.lower(), f"verdict word {banned!r} in outcomes module"

    def test_trail_capped_at_five(self):
        """spec(T-057:AC-5) — trail rows are bounded for the API."""
        docs = [_doc(f"f{i}", "Alpha County, VA", f"2026-02-{i+1:02d}", "300 MW noted")
                for i in range(8)]
        assert len(self._build(docs, today="2026-03-01")["trail"]) <= 5

    def test_deterministic(self):
        """spec(T-057:AC-4)"""
        follow = _doc("later", "Alpha County, VA", "2026-02-01", "300 MW confirmed")
        build = _attr("build_outcomes")
        a = build([_promise()], [follow], today="2026-03-01")
        b = build([_promise()], [follow], today="2026-03-01")
        assert a == b

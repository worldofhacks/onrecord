"""Frozen tests — T-056 quantified promises.

Pins `onrecord.analysis.quantities`: deterministic quantity extraction over
verbatim promise quotes. Every extraction's `raw_span` must be an exact
substring of the input quote (the verbatim-pin inheritance, AC-1); the
false-positive corpus (AC-2) and unit normalization table (AC-3) are frozen
here; aggregates are reproducible pure functions (AC-4).

Written before implementation (tdd-swarm Iron Law). Spec tags: spec(T-056:AC-n).
"""

import pytest

from onrecord.analysis.quantities import (
    aggregate_quantities,
    extract_quantities,
)


def _spans_in(quote, extractions):
    return all(e["raw_span"] in quote for e in extractions)


# ---------------------------------------------------------------------------
# AC-1 + AC-3 — extraction and normalization
# ---------------------------------------------------------------------------


class TestPowerExtraction:
    def test_plain_megawatts(self):
        """spec(T-056:AC-3)"""
        quote = "the facility will draw 400 megawatts at full build out"
        got = extract_quantities(quote)
        assert len(got) == 1
        e = got[0]
        assert e["kind"] == "power" and e["value"] == 400.0 and e["unit"] == "MW"
        assert e["raw_span"] == "400 megawatts"

    def test_mw_abbreviation_and_gw_scaling(self):
        """spec(T-056:AC-3)"""
        got = extract_quantities("a 1.2 GW campus alongside the 75 MW substation")
        kinds = {(e["value"], e["unit"]) for e in got if e["kind"] == "power"}
        assert (1200.0, "MW") in kinds
        assert (75.0, "MW") in kinds

    def test_kw_scales_down(self):
        """spec(T-056:AC-3)"""
        got = extract_quantities("backup generation of 500 kW on site")
        assert got[0]["value"] == 0.5 and got[0]["unit"] == "MW"

    def test_spelled_number_with_unit(self):
        """spec(T-056:AC-3) — small spelled-number lexicon, precision over recall."""
        got = extract_quantities("we are asking for forty megawatts initially")
        assert len(got) == 1
        assert got[0]["value"] == 40.0 and got[0]["raw_span"] == "forty megawatts"


class TestWaterExtraction:
    def test_gallons_per_day(self):
        """spec(T-056:AC-3)"""
        got = extract_quantities("permitted for 250,000 gallons per day of withdrawal")
        e = got[0]
        assert e["kind"] == "water" and e["value"] == 250000.0 and e["unit"] == "GPD"
        assert e["raw_span"] == "250,000 gallons per day"

    def test_million_gallons_a_day(self):
        """spec(T-056:AC-3)"""
        got = extract_quantities("up to two million gallons a day from the aquifer")
        assert got[0]["value"] == 2_000_000.0 and got[0]["unit"] == "GPD"

    def test_gallons_without_rate_is_total_not_gpd(self):
        """spec(T-056:AC-3) — a bare gallons figure has no rate; unit stays gallons."""
        got = extract_quantities("a storage capacity of 500,000 gallons")
        assert got[0]["unit"] == "GAL"


class TestJobsExtraction:
    def test_plain_jobs(self):
        """spec(T-056:AC-3)"""
        got = extract_quantities("this project brings 300 permanent jobs to the county")
        e = got[0]
        assert e["kind"] == "jobs" and e["value"] == 300.0
        assert e["raw_span"] == "300 permanent jobs"

    def test_positions_alias(self):
        """spec(T-056:AC-3)"""
        got = extract_quantities("staffing of 45 full-time positions")
        assert got[0]["kind"] == "jobs" and got[0]["value"] == 45.0


class TestMoneyExtraction:
    def test_dollar_millions_annual(self):
        """spec(T-056:AC-3) — annual marker sets cadence."""
        got = extract_quantities("generating $4 million in annual tax revenue")
        e = got[0]
        assert e["kind"] == "money" and e["value"] == 4_000_000.0
        assert e["cadence"] == "annual"

    def test_dollar_billions_total(self):
        """spec(T-056:AC-3) — no annual marker -> total."""
        got = extract_quantities("a $2.5 billion capital investment in the region")
        e = got[0]
        assert e["value"] == 2_500_000_000.0 and e["cadence"] == "total"

    def test_spelled_dollar_amount(self):
        """spec(T-056:AC-3)"""
        got = extract_quantities("roughly ten million dollars of infrastructure upgrades")
        assert got[0]["value"] == 10_000_000.0


class TestSpanInvariant:
    def test_every_span_is_verbatim_substring(self):
        """spec(T-056:AC-1) — the load-bearing invariant, over a mixed quote."""
        quote = (
            "we will invest $1.5 billion, create 200 jobs, draw 300 MW and "
            "use 100,000 gallons per day"
        )
        got = extract_quantities(quote)
        assert len(got) == 4
        assert _spans_in(quote, got)

    def test_dysfluent_caption_text_spans_stay_verbatim(self):
        """spec(T-056:AC-1) — caption dysfluency must not break span identity."""
        quote = "the the facility uses uh 50 megawatts of of power"
        got = extract_quantities(quote)
        assert got[0]["raw_span"] == "50 megawatts"
        assert _spans_in(quote, got)


# ---------------------------------------------------------------------------
# AC-2 — the false-positive corpus
# ---------------------------------------------------------------------------


class TestFalsePositiveCorpus:
    @pytest.mark.parametrize(
        "text",
        [
            "approved by a 5-0 vote at the March 2024 meeting",
            "ordinance 2019-14 was adopted",
            "the meeting adjourned at 7:45",
            "located at 400 Pine Log Road",
            "agenda item 3 carried unanimously",
            "the 2025 budget hearing is scheduled",
            "section 8.01 of the zoning code",
            "he served 12 years on the commission",
        ],
        ids=["vote-tally", "ordinance", "clock-time", "address", "agenda-item",
             "year", "code-section", "tenure"],
    )
    def test_does_not_fire(self, text):
        """spec(T-056:AC-2)"""
        assert extract_quantities(text) == []

    def test_bare_numbers_never_extract(self):
        """spec(T-056:AC-2) — a number without a unit keyword is not a quantity."""
        assert extract_quantities("we expect 400 by next year") == []


# ---------------------------------------------------------------------------
# AC-4 — aggregates
# ---------------------------------------------------------------------------


class TestAggregates:
    def _rows(self):
        return [
            {"jurisdiction": "Coweta County, GA", "ticker": "NVDA",
             "quantities": [
                 {"kind": "power", "value": 300.0, "unit": "MW"},
                 {"kind": "money", "value": 4e6, "cadence": "annual"},
             ]},
            {"jurisdiction": "Coweta County, GA", "ticker": None,
             "quantities": [{"kind": "power", "value": 100.0, "unit": "MW"},
                            {"kind": "jobs", "value": 200.0}]},
            {"jurisdiction": "Columbus, OH", "ticker": "NVDA",
             "quantities": [{"kind": "money", "value": 1e9, "cadence": "total"}]},
            {"jurisdiction": "Columbus, OH", "ticker": "MSFT", "quantities": []},
        ]

    def test_by_jurisdiction(self):
        """spec(T-056:AC-4)"""
        agg = aggregate_quantities(self._rows(), by="jurisdiction")
        coweta = agg["Coweta County, GA"]
        assert coweta["promised_mw"] == 400.0
        assert coweta["promised_jobs"] == 200.0
        assert coweta["promised_dollars_annual"] == 4e6
        assert coweta["n_quantified"] == 2
        columbus = agg["Columbus, OH"]
        assert columbus["promised_dollars_total"] == 1e9
        assert columbus["n_quantified"] == 1  # the empty-quantities row doesn't count

    def test_by_ticker_skips_untickered(self):
        """spec(T-056:AC-4)"""
        agg = aggregate_quantities(self._rows(), by="ticker")
        assert set(agg) == {"NVDA", "MSFT"}
        assert agg["NVDA"]["promised_mw"] == 300.0
        assert agg["MSFT"]["n_quantified"] == 0

    def test_deterministic(self):
        """spec(T-056:AC-4) — same input, identical output object."""
        assert aggregate_quantities(self._rows(), by="jurisdiction") == \
            aggregate_quantities(self._rows(), by="jurisdiction")

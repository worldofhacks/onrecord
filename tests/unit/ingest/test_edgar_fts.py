"""Failing tests for T-062 — EDGAR full-text discovery (efts.sec.gov).

``parse_fts_hits(response_json: dict) -> list[dict]`` (pure) — one row per
efts hit: {"accession" (adsh), "form", "file_date", "tickers" (parsed out
of display_names entries like "NVIDIA CORP  (NVDA)  (CIK 0001045810)"),
"cik" (first of ciks), "doc_id" (_id), "states" (biz_states)}; unknown or
missing hit shape raises ValueError naming what's missing (AC-1). Fixture
below is trimmed VERBATIM from a real efts.sec.gov/LATEST/search-index
response (q="hyperscale data center", forms=8-K, fetched 2026-08-14).

``novel_candidates(rows, known_accessions, provenance) -> list[dict]``
(pure) — drops rows whose accession is already in the corpus (AC-2) and
attaches the query provenance {query, forms, window} to each survivor
(AC-3); inputs are not mutated.

``corpus_accessions`` is REUSED from onrecord.ingest.filings_delta (same
function object — not a reimplementation).

``discover(terms, forms, date_from, date_to, known_accessions, *,
max_hits_per_query=..., transport=None)`` — operational sweep: one query
per (term x form) with SEC etiquette (UA header, request gaps,
Retry-After honored), paginated via from= offsets up to a bounded cap
(truncation logged, never silent), deduped across queries by accession
with first provenance winning. Discovery only — nothing enters the
corpus (AC-4).
"""

import logging

import httpx
import pytest

from onrecord.ingest import filings_delta

try:
    from onrecord.ingest import edgar_fts
except Exception:  # pragma: no cover - red phase
    edgar_fts = None


def _attr(name):
    if edgar_fts is None or not hasattr(edgar_fts, name):
        pytest.fail(f"onrecord.ingest.edgar_fts.{name} does not exist yet (T-062 red)")
    return getattr(edgar_fts, name)


# --------------------------------------------------------------------------
# Fixture: trimmed verbatim from a real efts.sec.gov response (2026-08-14)
# --------------------------------------------------------------------------

FIXTURE = {
    "took": 51,
    "timed_out": False,
    "hits": {
        "total": {"value": 3, "relation": "eq"},
        "max_score": 23.526567,
        "hits": [
            {
                "_index": "edgar_file",
                "_id": "0001493152-26-011201:ex99-1.htm",
                "_score": 23.526567,
                "_source": {
                    "ciks": ["0001861622"],
                    "display_names": ["Jet.AI Inc.  (JTAI)  (CIK 0001861622)"],
                    "root_forms": ["8-K"],
                    "file_date": "2026-03-18",
                    "biz_states": ["NV"],
                    "form": "8-K",
                    "adsh": "0001493152-26-011201",
                    "file_type": "EX-99.1",
                },
            },
            {
                "_index": "edgar_file",
                "_id": "0001193125-26-276844:d50837dex991.htm",
                "_score": 18.1,
                "_source": {
                    "ciks": ["0001297996", "0001494877"],
                    "display_names": [
                        "DIGITAL REALTY TRUST, INC.  (DLR, DLR-PJ, DLR-PK, DLR-PL)"
                        "  (CIK 0001297996)",
                        "DIGITAL REALTY TRUST, L.P.  (CIK 0001494877)",
                    ],
                    "root_forms": ["8-K"],
                    "file_date": "2026-06-22",
                    "biz_states": ["TX"],
                    "form": "8-K",
                    "adsh": "0001193125-26-276844",
                    "file_type": "EX-99.1",
                },
            },
            {
                "_index": "edgar_file",
                "_id": "0001104659-26-012343:tm265399d1_ex99-1.htm",
                "_score": 15.9,
                "_source": {
                    "ciks": ["0001918102"],
                    "display_names": ["DEEP FISSION, INC.  (CIK 0001918102)"],
                    "root_forms": ["8-K"],
                    "file_date": "2026-02-10",
                    "biz_states": ["CA"],
                    "form": "8-K",
                    "adsh": "0001104659-26-012343",
                    "file_type": "EX-99.1",
                },
            },
        ],
    },
}


def _fixture():
    import copy

    return copy.deepcopy(FIXTURE)


# --------------------------------------------------------------------------
# parse_fts_hits (AC-1)
# --------------------------------------------------------------------------


def test_parse_fts_hits_maps_real_shape():
    rows = _attr("parse_fts_hits")(_fixture())
    assert len(rows) == 3
    assert rows[0] == {
        "accession": "0001493152-26-011201",
        "form": "8-K",
        "file_date": "2026-03-18",
        "tickers": ["JTAI"],
        "cik": "0001861622",
        "doc_id": "0001493152-26-011201:ex99-1.htm",
        "states": ["NV"],
    }


def test_parse_fts_hits_multi_filer_and_hyphenated_tickers():
    rows = _attr("parse_fts_hits")(_fixture())
    dlr = rows[1]
    assert dlr["accession"] == "0001193125-26-276844"
    assert dlr["tickers"] == ["DLR", "DLR-PJ", "DLR-PK", "DLR-PL"]
    assert dlr["cik"] == "0001297996"  # first filer wins the cik slot
    assert dlr["states"] == ["TX"]


def test_parse_fts_hits_tickerless_display_name():
    rows = _attr("parse_fts_hits")(_fixture())
    deep = rows[2]
    assert deep["tickers"] == []
    assert deep["cik"] == "0001918102"


def test_parse_fts_hits_missing_top_level_hits_is_loud():
    with pytest.raises(ValueError, match="hits"):
        _attr("parse_fts_hits")({"took": 5})


def test_parse_fts_hits_missing_source_is_loud():
    payload = _fixture()
    del payload["hits"]["hits"][0]["_source"]
    with pytest.raises(ValueError, match="_source"):
        _attr("parse_fts_hits")(payload)


@pytest.mark.parametrize("field", ["adsh", "file_date", "ciks", "biz_states"])
def test_parse_fts_hits_missing_source_field_is_loud(field):
    payload = _fixture()
    del payload["hits"]["hits"][1]["_source"][field]
    with pytest.raises(ValueError, match=field):
        _attr("parse_fts_hits")(payload)


def test_parse_fts_hits_missing_both_form_and_root_forms_is_loud():
    payload = _fixture()
    del payload["hits"]["hits"][0]["_source"]["form"]
    del payload["hits"]["hits"][0]["_source"]["root_forms"]
    with pytest.raises(ValueError, match="form"):
        _attr("parse_fts_hits")(payload)


def test_parse_fts_hits_root_forms_fallback_when_form_absent():
    payload = _fixture()
    del payload["hits"]["hits"][0]["_source"]["form"]
    rows = _attr("parse_fts_hits")(payload)
    assert rows[0]["form"] == "8-K"


# --------------------------------------------------------------------------
# novel_candidates (AC-2 dedupe, AC-3 provenance) + corpus_accessions reuse
# --------------------------------------------------------------------------

PROVENANCE = {"query": "data center", "forms": "8-K", "window": "2026-07-01..2026-07-31"}


def _rows():
    return [
        {"accession": "0001493152-26-011201", "form": "8-K", "tickers": ["JTAI"]},
        {"accession": "0001193125-26-276844", "form": "8-K", "tickers": ["DLR"]},
        {"accession": "0001104659-26-012343", "form": "8-K", "tickers": []},
    ]


def test_novel_candidates_known_accessions_never_survive():
    known = {"0001193125-26-276844", "0001104659-26-012343"}
    out = _attr("novel_candidates")(_rows(), known, PROVENANCE)
    assert [row["accession"] for row in out] == ["0001493152-26-011201"]
    assert all(row["accession"] not in known for row in out)


def test_novel_candidates_attaches_provenance_per_row():
    out = _attr("novel_candidates")(_rows(), set(), PROVENANCE)
    assert len(out) == 3
    for row in out:
        assert row["provenance"] == PROVENANCE
        assert row["provenance"] is not PROVENANCE  # copied, not shared


def test_novel_candidates_does_not_mutate_inputs():
    rows = _rows()
    _attr("novel_candidates")(rows, set(), PROVENANCE)
    assert all("provenance" not in row for row in rows)


def test_corpus_accessions_is_reused_from_filings_delta():
    assert _attr("corpus_accessions") is filings_delta.corpus_accessions


# --------------------------------------------------------------------------
# discover — operational sweep (mock transport; no live network in tests)
# --------------------------------------------------------------------------


def _hit(adsh, doc="ex99-1.htm", cik="0000000001", ticker="ACME"):
    name = f"ACME CORP  ({ticker})  (CIK {cik})"
    return {
        "_index": "edgar_file",
        "_id": f"{adsh}:{doc}",
        "_score": 1.0,
        "_source": {
            "ciks": [cik],
            "display_names": [name],
            "root_forms": ["8-K"],
            "form": "8-K",
            "file_date": "2026-07-20",
            "biz_states": ["TX"],
            "adsh": adsh,
            "file_type": "EX-99.1",
        },
    }


def _page(hits, total):
    return {
        "took": 5,
        "timed_out": False,
        "hits": {"total": {"value": total, "relation": "eq"}, "max_score": 1.0, "hits": hits},
    }


@pytest.fixture()
def no_sleep(monkeypatch):
    sleeps = []
    if edgar_fts is not None:
        monkeypatch.setattr(edgar_fts.time, "sleep", sleeps.append)
    return sleeps


def test_discover_queries_every_term_x_form_with_etiquette(no_sleep):
    seen = []

    def handler(request):
        params = request.url.params
        seen.append(
            (
                params["q"],
                params["forms"],
                params["startdt"],
                params["enddt"],
                request.headers.get("User-Agent"),
            )
        )
        return httpx.Response(200, json=_page([], 0))

    out = _attr("discover")(
        ["data center", "hyperscale"],
        ["8-K", "10-K"],
        "2026-07-01",
        "2026-07-31",
        set(),
        transport=httpx.MockTransport(handler),
    )
    assert out == []
    ua = "OnRecord research alexander.miller@challenger.gauntletai.com"
    combos = {(q, f) for q, f, _, _, _ in seen}
    assert combos == {
        ('"data center"', "8-K"),
        ('"data center"', "10-K"),
        ('"hyperscale"', "8-K"),
        ('"hyperscale"', "10-K"),
    }
    assert all(s == "2026-07-01" and e == "2026-07-31" for _, _, s, e, _ in seen)
    assert all(agent == ua for _, _, _, _, agent in seen)
    assert edgar_fts.REQUEST_GAP_S >= 0.2
    assert no_sleep.count(edgar_fts.REQUEST_GAP_S) >= len(seen)  # a gap before every request


def test_discover_paginates_via_from_offsets(no_sleep):
    all_hits = [_hit(f"000000000{i}-26-00000{i}") for i in range(1, 6)]

    def handler(request):
        start = int(request.url.params.get("from", "0"))
        return httpx.Response(200, json=_page(all_hits[start : start + 2], total=5))

    out = _attr("discover")(
        ["data center"],
        ["8-K"],
        "2026-07-01",
        "2026-07-31",
        set(),
        transport=httpx.MockTransport(handler),
    )
    assert [row["accession"] for row in out] == [f"000000000{i}-26-00000{i}" for i in range(1, 6)]
    assert out[0]["provenance"] == {
        "query": "data center",
        "forms": "8-K",
        "window": "2026-07-01..2026-07-31",
    }


def test_discover_cap_is_bounded_and_logged_never_silent(no_sleep, caplog):
    all_hits = [_hit(f"000000000{i}-26-00000{i}") for i in range(1, 6)]

    def handler(request):
        start = int(request.url.params.get("from", "0"))
        return httpx.Response(200, json=_page(all_hits[start : start + 2], total=5))

    with caplog.at_level(logging.WARNING, logger="onrecord.ingest.edgar_fts"):
        out = _attr("discover")(
            ["data center"],
            ["8-K"],
            "2026-07-01",
            "2026-07-31",
            set(),
            max_hits_per_query=3,
            transport=httpx.MockTransport(handler),
        )
    assert len(out) == 3
    assert "truncated" in caplog.text


def test_discover_dedupes_across_queries_first_provenance_wins(no_sleep):
    shared = _hit("0000000001-26-000001")

    def handler(request):
        if request.url.params["q"] == '"alpha"':
            return httpx.Response(200, json=_page([shared], 1))
        return httpx.Response(200, json=_page([shared, _hit("0000000002-26-000002")], 2))

    out = _attr("discover")(
        ["alpha", "beta"],
        ["8-K"],
        "2026-07-01",
        "2026-07-31",
        set(),
        transport=httpx.MockTransport(handler),
    )
    by_accession = {row["accession"]: row for row in out}
    assert len(out) == 2
    assert by_accession["0000000001-26-000001"]["provenance"]["query"] == "alpha"
    assert by_accession["0000000002-26-000002"]["provenance"]["query"] == "beta"


def test_discover_filters_known_accessions(no_sleep):
    def handler(request):
        hits = [_hit("0000000001-26-000001"), _hit("0000000002-26-000002")]
        return httpx.Response(200, json=_page(hits, 2))

    known = {"0000000002-26-000002"}
    out = _attr("discover")(
        ["data center"],
        ["8-K"],
        "2026-07-01",
        "2026-07-31",
        known,
        transport=httpx.MockTransport(handler),
    )
    assert [row["accession"] for row in out] == ["0000000001-26-000001"]


def test_discover_honors_retry_after(no_sleep):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json=_page([_hit("0000000009-26-000009")], 1))

    out = _attr("discover")(
        ["data center"],
        ["8-K"],
        "2026-07-01",
        "2026-07-31",
        set(),
        transport=httpx.MockTransport(handler),
    )
    assert [row["accession"] for row in out] == ["0000000009-26-000009"]
    assert 2.0 in no_sleep  # Retry-After: 2 was honored

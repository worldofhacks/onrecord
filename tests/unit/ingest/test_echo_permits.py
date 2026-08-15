"""Failing tests for T-066 (module layer) — EPA ECHO CWA water permits.

``parse_facilities(json_text: str) -> list[dict]`` (pure) — an echodata
Results.Facilities payload -> normalized rows {facility, permit_id,
county, state, status} (all str). Pinned against REAL responses fetched
2026-08-15 for p_st=VA&p_co=Loudoun: facility rows live under
Results.Facilities and carry CWPName / SourceID / CWPCounty / CWPState /
CWPPermitStatusDesc (None status occurs in 8 of 100 real rows -> "").
Rows without a SourceID are skipped. Any UNKNOWN shape — unparseable
JSON, no Results dict, or Results without a Facilities list — is a LOUD
ValueError, never a quiet [].

REALITY PIN: cwa_rest_services.get_facilities itself returns only a
summary envelope (QueryID + counts, NO facility rows); the rows come
from the cwa_rest_services.get_qid follow-up, whose Results.Facilities
shape is what parse_facilities parses. The summary is parsed by
``parse_query_summary(json_text) -> (query_id, query_rows)`` (loud on
unknown shape too), and the real summary is itself a fixture here — it
must be REJECTED by parse_facilities.

``county_queries(mapping) -> list[(county, state)]`` (pure) — the
data/iso_jurisdictions.json-style keys ("County, ST") -> ordered,
deduplicated query pairs for the operational sweep; malformed keys are
skipped. Jurisdiction join: echo_permits re-exports
iso_queues.join_jurisdictions/load_mapping (identity, not a copy) —
exact match on f"{county}, {state}", misses kept, never fuzzy-matched.
"""

import json

import pytest

try:
    from onrecord.ingest import echo_permits
except Exception:  # pragma: no cover - red phase
    echo_permits = None

ROW_KEYS = {"facility", "permit_id", "county", "state", "status"}


def _attr(name):
    if echo_permits is None or not hasattr(echo_permits, name):
        pytest.fail(f"onrecord.ingest.echo_permits.{name} does not exist yet (T-066 red)")
    return getattr(echo_permits, name)


# Verbatim real get_facilities response (p_st=VA&p_co=Loudoun, 2026-08-15):
# a summary envelope with a QueryID and NO facility rows.
SUMMARY_JSON = (
    '{"Results":{"Message":"Success","Version":"CWA v2017-10-13 1325",'
    '"QueryRows":"100","IndianCountryRows":"0","SVRows":"0","CVRows":"10",'
    '"V3Rows":"25","FEARows":"4","InfFEARows":"29","INSPRows":"33",'
    '"BioCVRows":"0","BioV3Rows":"0","VioLast4QRows":"13",'
    '"TotalPenalties":"$90,878","BadSystemIDs":null,"QueryID":"666"}}'
)

# Facility rows below are real rows from the get_qid page for that QueryID
# (extra fields trimmed but names/values verbatim, incl. a real None status).
# The SourceID-less row is a shape-faithful variant pinning the skip rule.
FACILITIES_JSON = json.dumps({
    "Results": {
        "Message": "Success",
        "QueryRows": "100",
        "QueryID": "666",
        "PageNo": "1",
        "Facilities": [
            {
                "CWPName": "ADAPTIVE CONCRETE SOLUTIONS", "SourceID": "VA0090441",
                "CWPStreet": "44146 WADE DR", "CWPCity": "CHANTILLY",
                "CWPState": "VA", "CWPZip": "20151", "EPASystem": "ICP",
                "Statute": "CWA", "CWPCounty": "Loudoun", "FacLat": "38.9194",
                "CWPPermitStatusDesc": "Terminated",
            },
            {
                "CWPName": "ALDIE WASTEWATER TREATMENT PLANT",
                "SourceID": "VA0089133", "CWPCity": "ALDIE", "CWPState": "VA",
                "EPASystem": "ICP", "Statute": "CWA", "CWPCounty": "Loudoun",
                "CWPPermitStatusDesc": "Effective",
            },
            {
                "CWPName": "CENTRAL INTELLIGENCE AGENCY HQ", "SourceID": "VAU001755",
                "CWPCity": "MCLEAN", "CWPState": "VA", "EPASystem": "ICP",
                "Statute": "CWA", "CWPCounty": "Loudoun",
                "CWPPermitStatusDesc": None,
            },
            {
                "CWPName": "GE AVIATION DOWTY PROPELLERS", "SourceID": "VAR052219",
                "CWPCity": "STERLING", "CWPState": "VA", "EPASystem": "ICP",
                "Statute": "CWA", "CWPCounty": "Loudoun",
                "CWPPermitStatusDesc": "Admin Continued",
            },
            {
                "CWPName": "NO PERMIT ID FACILITY", "SourceID": None,
                "CWPState": "VA", "CWPCounty": "Loudoun",
                "CWPPermitStatusDesc": "Effective",
            },
        ],
    }
})


def test_parse_facilities_normalized_rows():
    rows = _attr("parse_facilities")(FACILITIES_JSON)
    assert len(rows) == 4  # the SourceID-less row is skipped
    assert rows[0] == {
        "facility": "ADAPTIVE CONCRETE SOLUTIONS", "permit_id": "VA0090441",
        "county": "Loudoun", "state": "VA", "status": "Terminated",
    }
    by_id = {r["permit_id"]: r for r in rows}
    assert by_id["VAU001755"]["status"] == ""  # real None status -> ""
    assert by_id["VAR052219"]["status"] == "Admin Continued"


def test_parse_facilities_row_shape_all_str():
    rows = _attr("parse_facilities")(FACILITIES_JSON)
    for row in rows:
        assert set(row) == ROW_KEYS
        assert all(isinstance(v, str) for v in row.values())


def test_parse_facilities_unknown_shape_loud():
    parse = _attr("parse_facilities")
    for bad in (
        "{not json",
        '"just a string"',
        "[]",
        "{}",  # no Results
        '{"Results": "nope"}',  # Results is not a dict
        '{"Results": {"QueryID": "666"}}',  # no Facilities list
        SUMMARY_JSON,  # the REAL get_facilities summary carries no rows
    ):
        with pytest.raises(ValueError):
            parse(bad)


def test_parse_facilities_empty_list_is_empty_not_loud():
    assert _attr("parse_facilities")('{"Results": {"Facilities": []}}') == []


def test_parse_query_summary_real_shape():
    query_id, query_rows = _attr("parse_query_summary")(SUMMARY_JSON)
    assert query_id == "666"
    assert query_rows == 100  # "100" (str in the real feed) -> int


def test_parse_query_summary_unknown_shape_loud():
    parse = _attr("parse_query_summary")
    for bad in (
        "{not json",
        "[]",
        "{}",
        '{"Results": {"Message": "Success"}}',  # no QueryID
        '{"Results": {"QueryID": "666", "QueryRows": "many"}}',  # non-numeric rows
    ):
        with pytest.raises(ValueError):
            parse(bad)


def test_county_queries_from_mapping_keys():
    # exact keys from the committed data/iso_jurisdictions.json (2026-08-15):
    # both spellings of the same county are distinct keys and BOTH swept —
    # the exact-match posture means each feed spelling earns its own query.
    mapping = {
        "Madison, MS": "Madison County, MS",
        "Madison County, MS": "Madison County, MS",
        "Richland Parish, LA": "Richland Parish, LA",
        "Sarpy County, NE": "Sarpy County, NE",
    }
    assert _attr("county_queries")(mapping) == [
        ("Madison", "MS"),
        ("Madison County", "MS"),
        ("Richland Parish", "LA"),
        ("Sarpy County", "NE"),
    ]


def test_county_queries_skips_malformed_keys():
    pairs = _attr("county_queries")(
        {
            "Madison, MS": "Madison County, MS",
            "nocomma": "Broken Key",  # no "County, ST" split -> skipped
            "Loudoun, Virginia": "Loudoun County, VA",  # state must be 2 chars
        }
    )
    assert pairs == [("Madison", "MS")]


def test_join_is_reused_from_iso_queues():
    from onrecord.ingest import iso_queues

    assert _attr("join_jurisdictions") is iso_queues.join_jurisdictions
    assert _attr("load_mapping") is iso_queues.load_mapping


def test_join_jurisdictions_on_echo_rows():
    rows = _attr("parse_facilities")(FACILITIES_JSON)
    mapping = {"Loudoun, VA": "Loudoun County, VA"}
    hits, misses = _attr("join_jurisdictions")(rows, mapping)
    assert len(hits) == 4 and misses == []
    assert {h["jurisdiction"] for h in hits} == {"Loudoun County, VA"}
    assert "jurisdiction" not in rows[0]  # inputs never mutated

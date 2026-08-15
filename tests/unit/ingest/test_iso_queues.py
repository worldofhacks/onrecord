"""Failing tests for T-059 (module layer) — ISO interconnection queues.

``parse_miso(json_text: str) -> list[dict]`` (pure) — MISO giqueue
getprojects JSON (a list of project objects) -> normalized rows
{iso, queue_id, county, state, mw, fuel, status, queue_date, withdrawn}
(all str except mw float, withdrawn bool). Rows without a projectNumber
are skipped; malformed JSON or a non-list payload -> []. queue_date is
the YYYY-MM-DD part of `queueDate`; withdrawn is True when
`withdrawnDate` is set OR applicationStatus == "Withdrawn".

``parse_spp(csv_text: str) -> list[dict]`` (pure) — SPP GenerateActiveCSV
text -> the same normalized shape. The real file carries a
"Last Updated On" preamble line above the header and a leading space in
the " Nearest Town or County" header cell; both are handled. Rows without
a "Generation Interconnection Number" are skipped; a text with no header
row -> []. queue_date normalizes M/D/YYYY "Request Received" to
YYYY-MM-DD; withdrawn is True when "Date Withdrawn" is non-empty; fuel is
"Generation Type", falling back to "Fuel Type" only when empty.

``join_jurisdictions(rows, mapping) -> (hits, misses)`` (pure) — mapping
is {"County, ST": "Jurisdiction Name, ST"}, EXACT match on
f"{county}, {state}" only. Hits are copies with a "jurisdiction" key
added; every other row lands in misses unchanged (never fuzzy-matched,
never dropped); inputs are not mutated.

data/iso_jurisdictions.json — the committed mapping table; every value
must be a real registry jurisdiction and stay within its own state.
"""

import json
from pathlib import Path

import pytest

try:
    from onrecord.ingest import iso_queues
except Exception:  # pragma: no cover - red phase
    iso_queues = None

ROW_KEYS = {
    "iso", "queue_id", "county", "state", "mw", "fuel", "status", "queue_date", "withdrawn",
}


def _attr(name):
    if iso_queues is None or not hasattr(iso_queues, name):
        pytest.fail(f"onrecord.ingest.iso_queues.{name} does not exist yet (T-059 red)")
    return getattr(iso_queues, name)


# Field names and value shapes below are taken from real captures of the
# live feeds (fetched 2026-08-14); whole files are NOT copied in.

MISO_JSON = json.dumps([
    {
        "id": 3211135,
        "projectNumber": "J4179",
        "queueDate": "2025-10-07T20:34:28+00:00",
        "inService": "2030-01-02T05:00:00+00:00",
        "transmissionOwner": "AMERICAN TRANSMISSION COMPANY",
        "county": "Madison",
        "state": "MS",
        "studyCycle": "DPP-2026",
        "svcType": "NRIS",
        "summerNetMW": 735.0,
        "winterNetMW": 735.0,
        "fuelType": "Solar",
        "facilityType": "",
        "applicationStatus": "Active",
        "postGIAStatus": "",
    },
    {
        # withdrawnDate set AND status Withdrawn; multi-county string kept verbatim
        "projectNumber": "J3831",
        "queueDate": "2024-10-08T04:00:00+00:00",
        "withdrawnDate": "2025-12-22T05:00:00+00:00",
        "county": "Kenosha County,Racine County",
        "state": "WI",
        "summerNetMW": 215.0,
        "fuelType": "Hybrid",
        "applicationStatus": "Withdrawn",
    },
    {
        # status Withdrawn with NO withdrawnDate (real: 18 such rows in the capture)
        "projectNumber": "J0001",
        "queueDate": "2019-03-01T05:00:00+00:00",
        "county": "Richland Parish",
        "state": "LA",
        "summerNetMW": 100.5,
        "fuelType": "Wind",
        "applicationStatus": "Withdrawn",
    },
    {
        # no projectNumber -> skipped entirely
        "id": 1,
        "county": "Weld",
        "state": "CO",
        "summerNetMW": 5.0,
        "applicationStatus": "Active",
    },
    {
        # blank county/state kept blank; missing MW -> 0.0; empty date stays ""
        "projectNumber": "J9999",
        "queueDate": "",
        "county": "",
        "state": "",
        "fuelType": "",
        "applicationStatus": "Pending Transfer",
    },
])


def test_parse_miso_normalized_rows():
    rows = _attr("parse_miso")(MISO_JSON)
    assert len(rows) == 4  # the projectNumber-less row is skipped
    assert rows[0] == {
        "iso": "MISO", "queue_id": "J4179", "county": "Madison", "state": "MS",
        "mw": 735.0, "fuel": "Solar", "status": "Active",
        "queue_date": "2025-10-07", "withdrawn": False,
    }
    assert rows[1]["county"] == "Kenosha County,Racine County"  # verbatim, no splitting
    last = rows[3]
    assert (last["queue_id"], last["mw"], last["queue_date"]) == ("J9999", 0.0, "")
    assert last["withdrawn"] is False


def test_parse_miso_withdrawn_flags():
    rows = _attr("parse_miso")(MISO_JSON)
    by_id = {r["queue_id"]: r for r in rows}
    assert by_id["J3831"]["withdrawn"] is True  # withdrawnDate set
    assert by_id["J0001"]["withdrawn"] is True  # status alone is enough
    assert by_id["J4179"]["withdrawn"] is False


def test_parse_miso_malformed():
    parse = _attr("parse_miso")
    assert parse("{not json") == []
    assert parse('{"lastUpdated": "2026-08-14"}') == []  # a dict is not the feed


SPP_CSV = (
    '"Last Updated On",8/14/2026,\n'
    "Generation Interconnection Number,IFS Queue Number, Nearest Town or County,State,"
    "Capacity,MAX Summer MW,MAX Winter MW,Generation Type,Fuel Type,Substation or Line,"
    "Request Received,Date Withdrawn,Status\n"
    '"TI-18-0827","","Weld County","CO","145","145","145","Wind","Wind",'
    '"Redtail 115  Substation","8/27/2018",,"IA FULLY EXECUTED/ON SCHEDULE"\n'
    '"GI-TC-2024-31","","Mayes County","OK","398","398.5","398","Hybrid","Solar/Storage",'
    '"Lincoln - Midway 230  Line","5/29/2024",,"FACILITY STUDY STAGE"\n'
    '"GI-2016-004","","Ouray County","CO","7.2","7.2","7.2","","Photovoltaic",'
    '"Cow Creek 115 Switching Station","2/17/2012","3/4/2019","WITHDRAWN"\n'
    '"TI-08-0502","","Kit Carson County","CO","51","51","51","Wind","Wind",'
    '"Landsman Creek 230 Switching\nStation","5/2/2008",,"IA FULLY EXECUTED/ON SCHEDULE"\n'
    '"","","Nowhere","KS","1","1","1","Wind","Wind","x","1/1/2020",,"DISIS STAGE"\n'
)


def test_parse_spp_normalized_rows():
    rows = _attr("parse_spp")(SPP_CSV)
    assert len(rows) == 4  # the queue-number-less row is skipped
    assert rows[0] == {
        "iso": "SPP", "queue_id": "TI-18-0827", "county": "Weld County", "state": "CO",
        "mw": 145.0, "fuel": "Wind", "status": "IA FULLY EXECUTED/ON SCHEDULE",
        "queue_date": "2018-08-27", "withdrawn": False,
    }
    # quoted embedded newline in "Substation or Line" must not break row parsing
    assert rows[3]["queue_id"] == "TI-08-0502"
    assert rows[3]["queue_date"] == "2008-05-02"


def test_parse_spp_withdrawn_and_fuel():
    rows = _attr("parse_spp")(SPP_CSV)
    by_id = {r["queue_id"]: r for r in rows}
    assert by_id["GI-2016-004"]["withdrawn"] is True  # Date Withdrawn non-empty
    assert by_id["TI-18-0827"]["withdrawn"] is False
    # fuel = Generation Type first; Fuel Type only as fallback when it is empty
    assert by_id["GI-TC-2024-31"]["fuel"] == "Hybrid"
    assert by_id["GI-2016-004"]["fuel"] == "Photovoltaic"
    assert by_id["GI-TC-2024-31"]["mw"] == 398.5


def test_parse_spp_missing_header():
    parse = _attr("parse_spp")
    assert parse("") == []
    assert parse("just,some,csv\n1,2,3\n") == []


def test_row_shape_identical_across_isos():
    miso_rows = _attr("parse_miso")(MISO_JSON)
    spp_rows = _attr("parse_spp")(SPP_CSV)
    for row in miso_rows + spp_rows:
        assert set(row) == ROW_KEYS
        assert isinstance(row["mw"], float)
        assert isinstance(row["withdrawn"], bool)
        for key in ROW_KEYS - {"mw", "withdrawn"}:
            assert isinstance(row[key], str)


def _mk(county, state):
    return {
        "iso": "MISO", "queue_id": "J1", "county": county, "state": state, "mw": 1.0,
        "fuel": "Solar", "status": "Active", "queue_date": "2026-01-01", "withdrawn": False,
    }


def test_join_jurisdictions_hits_and_misses():
    mapping = {"Madison, MS": "Madison County, MS", "Mayes County, OK": "Mayes County, OK"}
    rows = [_mk("Madison", "MS"), _mk("Weld County", "CO"), _mk("", "")]
    hits, misses = _attr("join_jurisdictions")(rows, mapping)
    assert [h["jurisdiction"] for h in hits] == ["Madison County, MS"]
    assert hits[0]["queue_id"] == "J1"
    assert misses == [rows[1], rows[2]]  # unchanged, in order
    assert "jurisdiction" not in rows[0]  # inputs never mutated


def test_join_jurisdictions_never_fuzzy():
    mapping = {"Madison, MS": "Madison County, MS"}
    near_misses = [
        _mk("Madison County", "MS"),   # suffixed variant needs its OWN mapping entry
        _mk("madison", "MS"),          # case differs
        _mk("Madison", "LA"),          # wrong state
        _mk("Madison,", "MS"),         # trailing comma
    ]
    hits, misses = _attr("join_jurisdictions")(near_misses, mapping)
    assert hits == []
    assert misses == near_misses


def test_mapping_file_honest():
    root = Path(__file__).resolve().parents[3]
    mapping = json.loads((root / "data" / "iso_jurisdictions.json").read_text())
    assert mapping, "mapping table must not be empty"

    from onrecord.registry import load
    jurisdictions = {c["jurisdiction"] for c in load()["youtube_channels"]}
    for key, value in mapping.items():
        assert value in jurisdictions, f"{value!r} is not a registry jurisdiction"
        # keys look like "County, ST" and never cross state lines
        assert ", " in key and len(key.rsplit(", ", 1)[1]) == 2, f"bad key {key!r}"
        assert key.rsplit(", ", 1)[1] == value.rsplit(", ", 1)[1], f"state mismatch {key!r}"

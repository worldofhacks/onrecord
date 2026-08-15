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


# ===========================================================================
# T-059 AMENDMENT (2026-08-15) -- ERCOT + CAISO xlsx feeds.
# openpyxl became a project dependency, un-trimming the two xlsx sources.
# Everything ABOVE this banner is the frozen T-059 suite and is unchanged;
# everything below is append-only.
#
# ``parse_ercot(xlsx_bytes: bytes) -> list[dict]`` (pure) -- the ERCOT GIS
# Report workbook, sheet "Project Details - Large Gen" (header row 31 under
# a notes preamble; VERIFIED against GIS_Report_July2026, DocID 1258020955).
# state is always "TX"; withdrawn always False (the sheet holds active
# projects only); status = "GIM Study Phase"; queue_date = "Projected COD"
# (the sheet has no request-received date). ERCOT rows ALONE carry three
# additive keys -- air_permit, ghg_permit, water_availability -- verbatim
# strings, "" when blank, YYYY-MM-DD when the cell is a date.
#
# ``parse_caiso(xlsx_bytes: bytes) -> list[dict]`` (pure) -- CAISO
# PublicQueueReport.xlsx, sheet "Grid GenerationQueue" (header row 4 under
# the report banner; VERIFIED against the 2026-08-14 capture). queue_id =
# "Queue Position" (ints and strings like "643R" both appear); mw = "Net
# MWs to Grid" falling back to "MW-1" when blank; queue_date = "Queue Date"
# (a real filing date); the feed spans CA/NV/AZ/MX and counties come
# UPPERCASE; legend/footer rows carry no Queue Position and are skipped.
#
# ``_ercot_newest_doc_id(json_text: str) -> str`` (pure) -- the MIS listing
# for reportTypeId=15933 mixes Co-located Battery reports into the same
# list, so the picker filters to FriendlyName "GIS_Report*" before taking
# the newest PublishDate. Malformed listing -> "".
#
# Fixture cell values are taken from the real 2026-08 workbook captures;
# whole files are NOT copied in.
# ===========================================================================

ERCOT_EXTRA_KEYS = {"air_permit", "ghg_permit", "water_availability"}


def _xlsx_bytes(sheet_name, grid):
    """In-memory single-sheet workbook -> bytes."""
    import io

    import openpyxl

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = sheet_name
    for row in grid:
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _ercot_xlsx():
    """Sheet mirrors the real GIS Report layout: 30 preamble/notes rows,
    header at row 31, wrapped-header continuation rows with a blank INR,
    then data rows carrying real July-2026 values."""
    from datetime import datetime

    header = [
        "INR", "Project Name", "GIM Study Phase", "Interconnecting Entity", "County",
        "Projected COD", "Fuel", "Technology", "Capacity (MW)", "IA Signed",
        "Air Permit", "GHG Permit", "Water Availability",
    ]
    pad = (
        [[None]] * 6
        + [["GIM Project Details - Large Gen"]]
        + [[None]] * 22
        + [["Project Attributes"]]
    )
    continuation = [
        [None] * 9 + ["Financial Security "],
        [None] * 9 + ["and Notice to "],
        [None],
    ]
    data = [
        ["15INR0064b", "Harald (BearKat Wind B)", "SS Completed, FIS Completed, IA",
         "McCrae Wind Energy II, LLC", "Glasscock", datetime(2026, 12, 3), "WIN", "WT",
         162.1, datetime(2018, 5, 30), "Not Required", "Not Required", "Not Required"],
        ["18INR0009", "Eagle Pines Gas", "SS Completed, FIS Started, No IA", "FGE Power",
         "Cherokee", datetime(2028, 10, 30), "GAS", "CC", 1173.5, None,
         datetime(2017, 2, 14), datetime(2015, 11, 4), None],
        ["21INR0280", "Edgewater Storage", "SS Completed, FIS Started, No IA",
         "Edgewater Battery Storage LLC", "Ellis", datetime(2028, 2, 29), "OTH", "BA",
         50, None, "Not Required", "Not Required", None],
    ]
    return _xlsx_bytes("Project Details - Large Gen", pad + [header] + continuation + data)


def _caiso_xlsx():
    """Sheet mirrors the real PublicQueueReport layout: 3 banner rows,
    header at row 4, real data rows, then the legend/footer block."""
    from datetime import datetime

    header = [
        "Project Name", "Queue Position", "Interconnection Request\nReceive Date",
        "Queue Date", "Application Status", "Study\nProcess", "Fuel-1", "Fuel-2",
        "MW-1", "MW-2", "MW-3", "Net MWs to Grid", "County", "State",
        "Interconnection Agreement \nStatus",
    ]
    banner = [
        [None] * 14 + ["Report Run Date: 08/14/2026"],
        [None, None, None, None, None, "The California ISO Controlled Grid"],
        [None, None, None, None, None, None, "Generating Facility", None, "MWs",
         None, None, None, "Location"],
    ]
    data = [
        ["MONTEZUMA (HIGH WINDS III)", 22, datetime(2003, 11, 18),
         datetime(2003, 11, 18, 8, 0), "ACTIVE", "AMEND 39", "Wind Turbine", "Battery",
         38, 38, None, 38, "SOLANO", "CA", "Executed"],
        ["TULE WIND", 32, datetime(2004, 5, 12), datetime(2004, 5, 24, 7, 0),
         "ACTIVE", "Serial LGIP", "Wind Turbine", "Battery", 127.6, 131.6, None, 193.8,
         "SAN DIEGO", "CA", "Executed"],
        ["NORTH ROSAMOND SOLAR", "643R", datetime(2010, 7, 30),
         datetime(2010, 7, 31, 7, 0), "ACTIVE", "C03", "Solar", "Battery",
         153, 100, None, 153, "KERN", "CA", "Executed"],
        ["AGUA CALIENTE SOLAR 2", 1222, datetime(2016, 3, 1), datetime(2016, 3, 8, 8, 0),
         "ACTIVE", "ISP", "Solar", None, 20, None, None, 20, "MARICOPA", "AZ", None],
        # synthetic twin of TULE WIND with "Net MWs to Grid" blanked: pins the MW-1 fallback
        ["TULE WIND (NET BLANKED)", 9032, datetime(2004, 5, 12), datetime(2004, 5, 24, 7, 0),
         "ACTIVE", "Serial LGIP", "Wind Turbine", "Battery", 127.6, 131.6, None, None,
         "SAN DIEGO", "CA", "Executed"],
        # legend/footer rows from the real sheet bottom: no Queue Position -> skipped
        [None],
        [None, None, "Legend:",
         "● Study Process Key:  Active=project is in study through Construction phases; "
         "Complete=project is in Commercial Operation, Withdrawn=project is withdrawn"],
        ["The contents of these pages are subject to change."],
    ]
    return _xlsx_bytes("Grid GenerationQueue", banner + [header] + data)


def test_parse_ercot_normalized_rows():
    rows = _attr("parse_ercot")(_ercot_xlsx())
    assert len(rows) == 3  # preamble, continuation, and blank rows all skipped
    assert rows[0] == {
        "iso": "ERCOT", "queue_id": "15INR0064b", "county": "Glasscock", "state": "TX",
        "mw": 162.1, "fuel": "WIN", "status": "SS Completed, FIS Completed, IA",
        "queue_date": "2026-12-03", "withdrawn": False,
        "air_permit": "Not Required", "ghg_permit": "Not Required",
        "water_availability": "Not Required",
    }
    by_id = {r["queue_id"]: r for r in rows}
    assert by_id["21INR0280"]["county"] == "Ellis"
    assert by_id["21INR0280"]["mw"] == 50.0  # int capacity cell -> float
    assert all(r["state"] == "TX" for r in rows)
    assert all(r["withdrawn"] is False for r in rows)  # active-projects sheet


def test_parse_ercot_permit_extras():
    rows = _attr("parse_ercot")(_ercot_xlsx())
    eagle = {r["queue_id"]: r for r in rows}["18INR0009"]
    assert eagle["air_permit"] == "2017-02-14"  # date cells -> YYYY-MM-DD
    assert eagle["ghg_permit"] == "2015-11-04"
    assert eagle["water_availability"] == ""  # blank cell -> ""
    assert eagle["queue_date"] == "2028-10-30"  # Projected COD (sheet has no filing date)
    assert eagle["status"] == "SS Completed, FIS Started, No IA"


def test_parse_ercot_malformed():
    parse = _attr("parse_ercot")
    assert parse(b"this is not a workbook") == []
    assert parse(_xlsx_bytes("Summary", [["nothing", "here"]])) == []  # sheet absent
    headerless = _xlsx_bytes("Project Details - Large Gen", [["no", "header"], ["at", "all"]])
    assert parse(headerless) == []


def test_parse_caiso_normalized_rows():
    rows = _attr("parse_caiso")(_caiso_xlsx())
    assert len(rows) == 5  # banner + legend/footer rows carry no Queue Position
    assert rows[0] == {
        "iso": "CAISO", "queue_id": "22", "county": "SOLANO", "state": "CA",
        "mw": 38.0, "fuel": "Wind Turbine", "status": "ACTIVE",
        "queue_date": "2003-11-18", "withdrawn": False,
    }
    by_id = {r["queue_id"]: r for r in rows}
    assert by_id["643R"]["queue_date"] == "2010-07-31"  # string queue positions survive
    assert by_id["1222"] == {
        "iso": "CAISO", "queue_id": "1222", "county": "MARICOPA", "state": "AZ",
        "mw": 20.0, "fuel": "Solar", "status": "ACTIVE",
        "queue_date": "2016-03-08", "withdrawn": False,
    }  # the feed is NOT CA-only: NV/AZ/MX counties appear


def test_parse_caiso_mw_prefers_net_then_mw1():
    rows = _attr("parse_caiso")(_caiso_xlsx())
    by_id = {r["queue_id"]: r for r in rows}
    assert by_id["32"]["mw"] == 193.8  # "Net MWs to Grid" wins over MW-1 (127.6)
    assert by_id["9032"]["mw"] == 127.6  # Net blank -> MW-1 fallback


def test_parse_caiso_malformed():
    parse = _attr("parse_caiso")
    assert parse(b"\x00\x01 garbage") == []
    assert parse(_xlsx_bytes("Wrong Sheet", [["x"]])) == []
    assert parse(_xlsx_bytes("Grid GenerationQueue", [["no", "queue", "position"]])) == []


def test_row_shape_new_isos():
    ercot_rows = _attr("parse_ercot")(_ercot_xlsx())
    caiso_rows = _attr("parse_caiso")(_caiso_xlsx())
    assert ercot_rows and caiso_rows
    for row in caiso_rows:
        assert set(row) == ROW_KEYS  # no additive keys outside ERCOT
    for row in ercot_rows:
        assert set(row) == ROW_KEYS | ERCOT_EXTRA_KEYS
        for key in ERCOT_EXTRA_KEYS:
            assert isinstance(row[key], str)
    for row in ercot_rows + caiso_rows:
        assert isinstance(row["mw"], float)
        assert isinstance(row["withdrawn"], bool)
        for key in ROW_KEYS - {"mw", "withdrawn"}:
            assert isinstance(row[key], str)


# Entry shapes below mirror the real IceDocListJsonWS response (fetched
# 2026-08-15); the GIS_Report_July2026 DocID and PublishDate are verbatim.
ERCOT_LISTING = json.dumps({
    "ListDocsByRptTypeRes": {"DocumentList": [
        {"Document": {"DocID": "1260020000", "PublishDate": "2026-08-10T08:37:03-05:00",
                      "FriendlyName": "Co-located_Battery_Identification_Report_July_2026",
                      "Extension": "xlsx"}},
        {"Document": {"DocID": "1258020955", "PublishDate": "2026-08-03T15:39:49-05:00",
                      "FriendlyName": "GIS_Report_July2026", "Extension": "xlsx"}},
        {"Document": {"DocID": "1245010000", "PublishDate": "2026-07-02T15:02:11-05:00",
                      "FriendlyName": "GIS_Report_June2026", "Extension": "xlsx"}},
        {"NotADocument": True},
    ]}
})


def test_ercot_newest_doc_id_filters_to_gis_report():
    newest = _attr("_ercot_newest_doc_id")
    # 15933 mixes Co-located Battery reports into the listing; the newest
    # GIS_Report must win, NOT the newest document overall
    assert newest(ERCOT_LISTING) == "1258020955"
    assert newest("{not json") == ""
    assert newest(json.dumps({"ListDocsByRptTypeRes": {"DocumentList": []}})) == ""
    assert newest(json.dumps([1, 2])) == ""


def test_join_carries_ercot_permit_keys_through():
    row = dict(_mk("Ellis", "TX"), iso="ERCOT", air_permit="Not Required",
               ghg_permit="", water_availability="2019-12-05")
    hits, misses = _attr("join_jurisdictions")([row], {"Ellis, TX": "Ellis County, TX"})
    assert misses == []
    assert hits[0]["jurisdiction"] == "Ellis County, TX"
    assert hits[0]["air_permit"] == "Not Required"
    assert hits[0]["water_availability"] == "2019-12-05"


def test_mapping_covers_new_feed_counties():
    root = Path(__file__).resolve().parents[3]
    mapping = json.loads((root / "data" / "iso_jurisdictions.json").read_text())
    # observed spellings: ERCOT writes bare county names, CAISO writes UPPERCASE
    assert mapping.get("Ellis, TX") == "Ellis County, TX"
    assert mapping.get("MARICOPA, AZ") == "Maricopa County, AZ"

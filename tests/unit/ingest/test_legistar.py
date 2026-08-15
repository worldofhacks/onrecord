"""Failing tests for T-061 — Legistar hearing coverage (matters + events).

``matter_to_doc(matter: dict, client: str, jurisdiction: str | None)
-> Doc | None`` (pure) — one Legistar Web API matter row -> Doc: id
`legistar:<client>:matter:<MatterId>`, source_type "legistar", venue_type
"public", date = ISO date part of MatterIntroDate, deep_link = the API
record URL (real payloads carry no matter hyperlink field), text =
non-empty MatterFile/MatterName/MatterTitle joined. Malformed rows
(no id / no usable date / no text) -> None, counted by the caller.

``event_to_doc(event: dict, client: str, jurisdiction: str | None)
-> Doc | None`` (pure) — same mapping for events: id
`legistar:<client>:event:<EventId>`, date from EventDate, deep_link =
EventInSiteURL when present (it is, in real payloads) else the API record
URL, text = non-empty EventBodyName/EventComment/EventLocation joined.

``candidate_slugs(jurisdiction: str) -> list[str]`` (pure) — candidate
Legistar client slugs for a registry jurisdiction string: lowercase, no
spaces/punctuation; "X County"/"X Parish" also yields the bare name first.

``verify_identity(page_text: str, jurisdiction: str) -> bool`` (pure) —
precision-first InSite identity check: the page must name the full
jurisdiction (a county page must say "X County") AND show state evidence
(", ST" case-sensitive or the full state name). Guards against slug
collisions: mecklenburg.legistar.com is Charlotte NC (we have Mecklenburg
County, VA) and maricopa.legistar.com is the CITY of Maricopa (we have the
county). Never guess: no state evidence -> False.

Fixtures below are trimmed real rows from
https://webapi.legistar.com/v1/columbus/{matters,events}?$top=3
(fetched 2026-08-15; field names verbatim).
"""

import pytest

try:
    from onrecord.ingest import legistar
except Exception:  # pragma: no cover - red phase
    legistar = None


def _attr(name):
    if legistar is None or not hasattr(legistar, name):
        pytest.fail(f"onrecord.ingest.legistar.{name} does not exist yet (T-061 red)")
    return getattr(legistar, name)


MATTER = {
    "MatterId": 786,
    "MatterGuid": "04E0DF1E-A1E6-4FD7-A3D5-8147FC3C643B",
    "MatterFile": "0749-2003",
    "MatterName": "Rezoning Z02-110,  547 RATHMELL ROAD.",
    "MatterTitle": "To rezone 547 RATHMELL ROAD (43207).",
    "MatterTypeName": "Ordinance",
    "MatterStatusName": "Passed",
    "MatterBodyName": "Zoning Committee",
    "MatterIntroDate": "2003-04-11T00:00:00",
    "MatterAgendaDate": "2003-06-30T00:00:00",
    "MatterPassedDate": "2003-07-01T00:00:00",
    "MatterEnactmentDate": None,
    "MatterNotes": None,
}

EVENT = {
    "EventId": 552,
    "EventGuid": "42BFC9FE-0714-41AA-9408-F9AB671A7D0F",
    "EventBodyId": 19,
    "EventBodyName": "Zoning Committee",
    "EventDate": "2003-06-16T00:00:00",
    "EventTime": "6:30 PM",
    "EventAgendaStatusName": "Final",
    "EventMinutesStatusName": "Final",
    "EventLocation": "City Council Chambers",
    "EventAgendaFile": None,
    "EventMinutesFile": None,
    "EventComment": None,
    "EventInSiteURL": (
        "https://columbus.legistar.com/MeetingDetail.aspx"
        "?LEGID=552&GID=139&G=4F637594-17B0-4E92-8196-37F14328D337"
    ),
    "EventItems": [],
}


def test_matter_to_doc_maps_real_payload():
    doc = _attr("matter_to_doc")(MATTER, "columbus", "Columbus, OH")
    assert doc is not None
    assert doc.id == "legistar:columbus:matter:786"
    assert doc.source_type == "legistar"
    assert doc.venue_type == "public"
    assert doc.date == "2003-04-11"
    assert doc.deep_link == "https://webapi.legistar.com/v1/columbus/matters/786"
    assert doc.text == (
        "0749-2003 — Rezoning Z02-110,  547 RATHMELL ROAD. — "
        "To rezone 547 RATHMELL ROAD (43207)."
    )
    assert doc.jurisdiction == "Columbus, OH"
    assert doc.ticker is None
    assert doc.speaker is None


def test_matter_to_doc_joins_only_nonempty_text_fields():
    matter = dict(MATTER, MatterName=None, MatterFile="")
    doc = _attr("matter_to_doc")(matter, "columbus", "Columbus, OH")
    assert doc is not None
    assert doc.text == "To rezone 547 RATHMELL ROAD (43207)."


def test_matter_to_doc_malformed_rows_are_none():
    fn = _attr("matter_to_doc")
    assert fn({k: v for k, v in MATTER.items() if k != "MatterId"}, "columbus", None) is None
    assert fn(dict(MATTER, MatterIntroDate=None), "columbus", None) is None
    assert fn(dict(MATTER, MatterIntroDate="garbage"), "columbus", None) is None
    assert fn(dict(MATTER, MatterFile=None, MatterName=None, MatterTitle=""), "columbus", None) \
        is None


def test_event_to_doc_maps_real_payload():
    doc = _attr("event_to_doc")(EVENT, "columbus", "Columbus, OH")
    assert doc is not None
    assert doc.id == "legistar:columbus:event:552"
    assert doc.source_type == "legistar"
    assert doc.venue_type == "public"
    assert doc.date == "2003-06-16"
    assert doc.deep_link == EVENT["EventInSiteURL"]
    assert doc.text == "Zoning Committee — City Council Chambers"
    assert doc.jurisdiction == "Columbus, OH"


def test_event_to_doc_deep_link_falls_back_to_api_url():
    doc = _attr("event_to_doc")(dict(EVENT, EventInSiteURL=None), "columbus", None)
    assert doc is not None
    assert doc.deep_link == "https://webapi.legistar.com/v1/columbus/events/552"


def test_event_to_doc_malformed_rows_are_none():
    fn = _attr("event_to_doc")
    assert fn({k: v for k, v in EVENT.items() if k != "EventId"}, "columbus", None) is None
    assert fn(dict(EVENT, EventDate=None), "columbus", None) is None
    assert fn(dict(EVENT, EventBodyName=None, EventComment=None, EventLocation=None),
              "columbus", None) is None


def test_candidate_slugs_bare_name_first_for_counties():
    fn = _attr("candidate_slugs")
    assert fn("Maricopa County, AZ") == ["maricopa", "maricopacounty"]
    assert fn("Columbus, OH") == ["columbus"]
    assert fn("St. Joseph County, IN") == ["stjoseph", "stjosephcounty"]
    assert fn("The Dalles, OR") == ["thedalles"]
    assert fn("Richland Parish, LA") == ["richland", "richlandparish"]


def test_verify_identity_requires_full_name_and_state_evidence():
    fn = _attr("verify_identity")
    # Real trap: mecklenburg.legistar.com is Charlotte, NC — ours is VA.
    assert fn(
        "Mecklenburg County Board of Commissioners, 600 E 4th St, Charlotte, NC 28202",
        "Mecklenburg County, VA",
    ) is False
    # Real trap: maricopa.legistar.com is the CITY of Maricopa, not the county.
    assert fn(
        "Welcome to the City of Maricopa Legislative Center, Maricopa, AZ 85138",
        "Maricopa County, AZ",
    ) is False
    assert fn("Columbus City Council, City Hall, Columbus, OH 43215", "Columbus, OH") is True
    # Real columbus.legistar.com carries the state ONLY in the Granicus
    # banner alt ("Columbus OH Banner") — name-adjacent abbrev is evidence.
    assert fn(
        '<img alt="Columbus OH Banner" src="x"/> Columbus City Council calendar',
        "Columbus, OH",
    ) is True
    # Full state name is evidence too, and punctuation in names is ignored.
    assert fn(
        "St. Joseph County, Indiana — County-City Building, South Bend",
        "St. Joseph County, IN",
    ) is True
    # Lowercase prose ", in" is NOT state evidence (abbrev match is case-sensitive).
    assert fn(
        "St. Joseph County meetings are held, in general, at the main building",
        "St. Joseph County, IN",
    ) is False


def test_confirmed_slugs_stay_derivable_and_registry_shaped():
    """Human-verified confirmations (live clients whose InSite pages carry no
    machine-checkable state marker) must stay consistent with the slug rule:
    every pinned slug is one of its own jurisdiction's candidates."""
    confirmed = _attr("CONFIRMED_SLUGS")
    candidate_fn = _attr("candidate_slugs")
    assert confirmed, "expected at least the hand-verified 2026-08-15 entries"
    for jurisdiction, slug in confirmed.items():
        assert ", " in jurisdiction  # registry jurisdiction shape: "Name, ST"
        assert slug in candidate_fn(jurisdiction)

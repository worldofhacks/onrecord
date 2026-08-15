"""Legistar hearing coverage — T-061 (enrich-C lane).

Granicus Legistar Web API (keyless JSON, OData): per verified client slug,
matters (MatterFile/Name/Title + dates) and events (agendas/minutes) map
to Doc rows with source_type "legistar". Pure parsers are pinned by
tests/unit/ingest/test_legistar.py against real columbus payloads.

Client-slug discovery is precision-first: a live `/bodies` probe alone is
NOT a mapping, because slugs collide across states — mecklenburg.legistar.com
is Charlotte NC (our registry has Mecklenburg County, VA) and
maricopa.legistar.com is the CITY of Maricopa (ours is the county). A hit
must also pass an InSite identity check (full jurisdiction name + state
evidence) before it lands in data/legistar_clients.json; everything else is
logged under "unmapped", never guessed. Corpus entry happens in the
corpus-v3 build lane (T-053), not at serve time.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterator
from pathlib import Path

import httpx

from onrecord.types import Doc

logger = logging.getLogger(__name__)

API_BASE = "https://webapi.legistar.com/v1"
INSITE_URL = "https://{slug}.legistar.com"
HEADERS = {"User-Agent": "OnRecord research alexander.miller@challenger.gauntletai.com"}
REQUEST_GAP_S = 0.25
PAGE_SIZE = 1000
MAX_RETRIES = 3
DEFAULT_CLIENTS_PATH = Path("data/legistar_clients.json")

_JOIN = " — "
_COUNTY_SUFFIXES = (" county", " parish")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_STATE_NAMES = {
    "AL": "alabama", "AZ": "arizona", "GA": "georgia", "IA": "iowa", "IL": "illinois",
    "IN": "indiana", "LA": "louisiana", "MO": "missouri", "MS": "mississippi",
    "NC": "north carolina", "ND": "north dakota", "NE": "nebraska", "NV": "nevada",
    "OH": "ohio", "OK": "oklahoma", "OR": "oregon", "SC": "south carolina",
    "TN": "tennessee", "TX": "texas", "UT": "utah", "VA": "virginia", "WA": "washington",
    "WI": "wisconsin", "WY": "wyoming",
}


def _iso_date(value: object) -> str:
    """ISO date part of a Legistar timestamp ("2003-04-11T00:00:00"); "" if unusable."""
    if not isinstance(value, str):
        return ""
    date = value.split("T", 1)[0]
    return date if _ISO_DATE.fullmatch(date) else ""


def _joined(row: dict, fields: tuple[str, ...]) -> str:
    parts = (str(row.get(field) or "").strip() for field in fields)
    return _JOIN.join(part for part in parts if part)


def matter_to_doc(matter: dict, client: str, jurisdiction: str | None) -> Doc | None:
    """One Legistar matter row -> Doc; malformed -> None (caller counts).

    deep_link is the API record URL: real matter payloads carry no
    hyperlink field (verified against columbus 2026-08-15)."""
    matter_id = matter.get("MatterId")
    if not isinstance(matter_id, int):
        return None
    date = _iso_date(matter.get("MatterIntroDate"))
    text = _joined(matter, ("MatterFile", "MatterName", "MatterTitle"))
    if not date or not text:
        return None
    return Doc(
        id=f"legistar:{client}:matter:{matter_id}",
        text=text,
        source_type="legistar",
        venue_type="public",
        date=date,
        deep_link=f"{API_BASE}/{client}/matters/{matter_id}",
        jurisdiction=jurisdiction,
    )


def event_to_doc(event: dict, client: str, jurisdiction: str | None) -> Doc | None:
    """One Legistar event row -> Doc; malformed -> None (caller counts).

    deep_link prefers the human EventInSiteURL (present in real payloads),
    falling back to the API record URL."""
    event_id = event.get("EventId")
    if not isinstance(event_id, int):
        return None
    date = _iso_date(event.get("EventDate"))
    text = _joined(event, ("EventBodyName", "EventComment", "EventLocation"))
    if not date or not text:
        return None
    insite = event.get("EventInSiteURL")
    deep_link = insite if isinstance(insite, str) and insite else (
        f"{API_BASE}/{client}/events/{event_id}"
    )
    return Doc(
        id=f"legistar:{client}:event:{event_id}",
        text=text,
        source_type="legistar",
        venue_type="public",
        date=date,
        deep_link=deep_link,
        jurisdiction=jurisdiction,
    )


def _flat(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def candidate_slugs(jurisdiction: str) -> list[str]:
    """Candidate Legistar client slugs for a registry jurisdiction string.

    Lowercase, punctuation/spaces stripped; "X County"/"X Parish" tries the
    bare name first (live clients are usually bare: columbus, maricopa)."""
    name = jurisdiction.split(",", 1)[0].strip().lower()
    slugs = []
    for suffix in _COUNTY_SUFFIXES:
        if name.endswith(suffix):
            slugs.append(_flat(name[: -len(suffix)]))
    slugs.append(_flat(name))
    return [slug for slug in slugs if slug]


def verify_identity(page_text: str, jurisdiction: str) -> bool:
    """Precision-first InSite identity check for a probed slug.

    The page must contain the FULL jurisdiction name (so a county page must
    say "X County" — kills city-of-maricopa) AND state evidence: the full
    state name, ", ST" (case-sensitive, so prose ", in" never counts), or a
    name-adjacent abbrev like the Granicus banner alt "Columbus OH Banner"
    (kills Charlotte-NC mecklenburg). No evidence -> False, never guessed."""
    name, _, state = jurisdiction.rpartition(",")
    name, state = name.strip(), state.strip().upper()
    if not name or _flat(name) not in _flat(page_text):
        return False
    state_name = _STATE_NAMES.get(state, "")
    if state_name and state_name in page_text.lower():
        return True
    if re.search(rf",\s*{state}\b", page_text):
        return True
    words = re.findall(r"[a-z0-9]+", name.lower())
    name_pattern = r"[^a-zA-Z0-9]{1,3}".join(re.escape(word) for word in words)
    return re.search(rf"(?i:{name_pattern})[\s,]{{1,3}}{state}\b", page_text) is not None


# Human-verified confirmations (2026-08-15): live clients whose InSite pages
# name the jurisdiction but carry no machine-checkable state marker, verified
# by hand against page evidence — sanantonio: "City of San Antonio" banner +
# "City Council of San Antonio" bodies; mesa: "City of Mesa" banner; wake:
# wakegov.com links + "Wake County Justice Center" meeting location. Rejected
# after the same review: mecklenburg (Charlotte NC), maricopa (CITY of
# Maricopa), douglascounty (", CO 80134"), madison (City of Madison, WI).
CONFIRMED_SLUGS: dict[str, str] = {
    "Mesa, AZ": "mesa",
    "San Antonio, TX": "sanantonio",
    "Wake County, NC": "wake",
}


# --------------------------------------------------------------------------
# Operational discovery + fetcher (live network; results committed as data)
# --------------------------------------------------------------------------


def _probe(client: httpx.Client, slug: str) -> bool:
    """True iff /v1/<slug>/bodies?$top=1 answers 200 with a JSON list."""
    try:
        response = client.get(f"{API_BASE}/{slug}/bodies", params={"$top": 1})
    except httpx.HTTPError:
        return False
    if response.status_code != 200:
        return False
    try:
        return isinstance(response.json(), list)
    except ValueError:
        return False


def _insite_identity_ok(client: httpx.Client, slug: str, jurisdiction: str) -> bool:
    try:
        response = client.get(INSITE_URL.format(slug=slug))
    except httpx.HTTPError:
        return False
    return response.status_code == 200 and verify_identity(response.text, jurisdiction)


def discover_clients(
    jurisdictions: list[str],
    out_path: str | Path = DEFAULT_CLIENTS_PATH,
    confirmed: dict[str, str] | None = None,
) -> dict:
    """Probe candidate slugs for every registry jurisdiction and write
    {jurisdiction: slug} for identity-verified hits, misses under
    "unmapped", to `out_path`. Returns the written payload.

    `confirmed` (default CONFIRMED_SLUGS) bypasses the InSite page check —
    but never the live probe — for hand-verified mappings."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    confirmed = CONFIRMED_SLUGS if confirmed is None else confirmed
    mapped: dict[str, str] = {}
    unmapped: list[str] = []
    with httpx.Client(headers=HEADERS, timeout=30.0, follow_redirects=True) as client:
        for jurisdiction in jurisdictions:
            hit: str | None = None
            pinned = confirmed.get(jurisdiction)
            if pinned:
                time.sleep(REQUEST_GAP_S)
                hit = pinned if _probe(client, pinned) else None
            else:
                for slug in candidate_slugs(jurisdiction):
                    time.sleep(REQUEST_GAP_S)
                    if not _probe(client, slug):
                        continue
                    time.sleep(REQUEST_GAP_S)
                    if _insite_identity_ok(client, slug, jurisdiction):
                        hit = slug
                        break
                    logger.info("legistar discovery: %s live but failed identity for %r",
                                slug, jurisdiction)
            if hit:
                mapped[jurisdiction] = hit
                print(f"{jurisdiction}: {hit}", flush=True)
            else:
                unmapped.append(jurisdiction)
    payload: dict = dict(sorted(mapped.items()))
    payload["unmapped"] = sorted(unmapped)
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def _get_with_retry(client: httpx.Client, url: str, params: dict) -> httpx.Response | None:
    """GET with etiquette: >=REQUEST_GAP_S between requests, Retry-After honored."""
    for _attempt in range(MAX_RETRIES):
        time.sleep(REQUEST_GAP_S)
        try:
            response = client.get(url, params=params)
        except httpx.HTTPError as exc:
            logger.debug("legistar GET %s: %s", url, type(exc).__name__)
            return None
        if response.status_code in (429, 503):
            retry_after = response.headers.get("Retry-After", "")
            try:
                pause = min(float(retry_after), 120.0) if retry_after else 2.0
            except ValueError:
                pause = 2.0
            time.sleep(pause)
            continue
        if response.status_code != 200:
            return None
        return response
    return None


def _pages(client: httpx.Client, url: str, filter_expr: str) -> Iterator[dict]:
    """OData paging: $top=PAGE_SIZE, $skip advancing until a short page."""
    skip = 0
    while True:
        params = {"$top": PAGE_SIZE, "$skip": skip, "$filter": filter_expr}
        response = _get_with_retry(client, url, params)
        if response is None:
            return
        try:
            rows = response.json()
        except ValueError:
            return
        if not isinstance(rows, list) or not rows:
            return
        yield from rows
        if len(rows) < PAGE_SIZE:
            return
        skip += PAGE_SIZE


def pull_client(client: str, since: str, jurisdiction: str | None = None) -> list[Doc]:
    """Pull all matters (MatterIntroDate >= since) and events (EventDate >=
    since) for one verified client slug; malformed rows counted + logged.
    Feeds the corpus-v3 build lane — never the serve path."""
    docs: list[Doc] = []
    skipped = 0
    with httpx.Client(headers=HEADERS, timeout=30.0) as http:
        lanes = (
            (f"{API_BASE}/{client}/matters", f"MatterIntroDate ge datetime'{since}'",
             matter_to_doc),
            (f"{API_BASE}/{client}/events", f"EventDate ge datetime'{since}'", event_to_doc),
        )
        for url, filter_expr, to_doc in lanes:
            for row in _pages(http, url, filter_expr):
                doc = to_doc(row, client, jurisdiction)
                if doc is None:
                    skipped += 1
                else:
                    docs.append(doc)
    if skipped:
        logger.info("legistar %s: %d malformed rows skipped", client, skipped)
    return docs

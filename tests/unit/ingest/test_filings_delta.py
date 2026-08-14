"""Failing tests for T-052 — filings delta ingest (EDGAR Atom polling).

``parse_edgar_atom(xml_text: str) -> list[dict]`` (pure) — one row per
Atom <entry>: {"accession", "form", "filing_date", "filing_href"};
malformed XML or DTD/entity declarations -> [] (same XXE posture as
T-038); entries missing an accession are skipped.

``corpus_accessions(doc_ids: list[str]) -> set[str]`` (pure) — the
accessions already in the corpus, from `edgar:<accession>:<section>` ids;
non-edgar ids ignored.

``new_filings(entries, known_accessions, since, forms=("8-K","10-K",
"10-Q")) -> list[dict]`` (pure) — entries filtered to wanted forms,
filing_date >= since, and accession not already known; deduped by
accession (first wins), sorted by filing_date ascending.
"""

import pytest

try:
    from onrecord.ingest import filings_delta
except Exception:  # pragma: no cover - red phase
    filings_delta = None


def _attr(name):
    if filings_delta is None or not hasattr(filings_delta, name):
        pytest.fail(f"onrecord.ingest.filings_delta.{name} does not exist yet (T-052 red)")
    return getattr(filings_delta, name)


ATOM = """<?xml version="1.0" encoding="ISO-8859-1" ?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <category label="form type" scheme="https://www.sec.gov/" term="8-K" />
    <content type="text/xml">
      <accession-number>0001045810-26-000060</accession-number>
      <filing-date>2026-07-02</filing-date>
      <filing-href>https://www.sec.gov/Archives/edgar/data/1045810/000104581026000060/index.htm</filing-href>
      <filing-type>8-K</filing-type>
    </content>
  </entry>
  <entry>
    <category label="form type" scheme="https://www.sec.gov/" term="4" />
    <content type="text/xml">
      <accession-number>0001045810-26-000061</accession-number>
      <filing-date>2026-07-03</filing-date>
      <filing-href>https://www.sec.gov/x</filing-href>
      <filing-type>4</filing-type>
    </content>
  </entry>
  <entry>
    <category label="form type" scheme="https://www.sec.gov/" term="10-Q" />
    <content type="text/xml">
      <filing-date>2026-07-04</filing-date>
      <filing-href>https://www.sec.gov/y</filing-href>
      <filing-type>10-Q</filing-type>
    </content>
  </entry>
</feed>"""


def test_parse_edgar_atom_rows_and_skips():
    rows = _attr("parse_edgar_atom")(ATOM)
    assert len(rows) == 2  # the accession-less 10-Q entry is skipped
    assert rows[0] == {
        "accession": "0001045810-26-000060", "form": "8-K",
        "filing_date": "2026-07-02",
        "filing_href": "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000060/index.htm",
    }
    assert rows[1]["form"] == "4"


def test_parse_edgar_atom_malformed_and_dtd():
    parse = _attr("parse_edgar_atom")
    assert parse("<not-xml") == []
    assert parse("<?xml version='1.0'?><!DOCTYPE x [<!ENTITY e 'v'>]><feed>&e;</feed>") == []


def test_corpus_accessions_extraction():
    fn = _attr("corpus_accessions")
    ids = ["edgar:0000320193-24-000123:item1a", "edgar:0000320193-24-000123:item7",
           "edgar:0001045810-26-000060:body", "yt:abc:seg001"]
    assert fn(ids) == {"0000320193-24-000123", "0001045810-26-000060"}


def test_new_filings_filters_dedupes_sorts():
    entries = [
        {"accession": "A3", "form": "8-K", "filing_date": "2026-07-05", "filing_href": "h3"},
        {"accession": "A1", "form": "8-K", "filing_date": "2026-07-01", "filing_href": "h1"},
        {"accession": "A1", "form": "8-K", "filing_date": "2026-07-01", "filing_href": "dup"},
        # form 4 belongs to T-038's lane, never this one
        {"accession": "A2", "form": "4", "filing_date": "2026-07-02", "filing_href": "h2"},
        # before `since`
        {"accession": "A4", "form": "10-Q", "filing_date": "2026-06-01", "filing_href": "h4"},
        {"accession": "KNOWN", "form": "8-K", "filing_date": "2026-07-06", "filing_href": "h5"},
    ]
    out = _attr("new_filings")(entries, {"KNOWN"}, since="2026-07-01")
    assert [e["accession"] for e in out] == ["A1", "A3"]

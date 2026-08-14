"""Failing tests for T-038 — Form 4 (insider transaction) ingestion.

Contract (fixed here, T-038):

``parse_form4_xml(xml_text: str, ticker: str, accession: str,
filing_url: str) -> list[dict]`` (pure, no I/O)

- Parses one SEC ownershipDocument XML into transaction rows:
  ``{"ticker", "cik", "filer_name", "filer_title", "is_officer",
  "is_director", "transaction_date", "code", "shares",
  "price_per_share", "value", "shares_owned_after", "filing_url",
  "accession"}``.
- One row per ``nonDerivativeTransaction`` (derivative table ignored in
  v1). ``value = shares * price_per_share`` rounded to 2 decimals;
  a missing/zero price yields ``price_per_share = 0.0`` and
  ``value = 0.0`` (grants/awards).
- Malformed XML or a document with no transactions -> ``[]``, never a
  raise.

``cik_for_ticker(ticker: str, mapping: dict) -> str | None``

- ``mapping`` is SEC company_tickers.json's parsed shape
  (``{"0": {"cik_str": 320193, "ticker": "AAPL", ...}, ...}``); returns
  the zero-padded 10-digit CIK string or None. Matching is
  case-insensitive and maps dotted tickers to SEC's dashed form
  (``BRK.B`` -> ``BRK-B``).
"""

import pytest

try:
    from onrecord.ingest import form4
except Exception:  # pragma: no cover - red phase
    form4 = None


def _attr(name):
    if form4 is None or not hasattr(form4, name):
        pytest.fail(f"onrecord.ingest.form4.{name} does not exist yet (T-038 red)")
    return getattr(form4, name)


FORM4_SALE_XML = """<?xml version="1.0"?>
<ownershipDocument>
  <issuer>
    <issuerCik>0001045810</issuerCik>
    <issuerTradingSymbol>NVDA</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0001234567</rptOwnerCik>
      <rptOwnerName>HUANG JEN HSUN</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>1</isDirector>
      <isOfficer>1</isOfficer>
      <officerTitle>President and CEO</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-06-02</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>120000</value></transactionShares>
        <transactionPricePerShare><value>135.50</value></transactionPricePerShare>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>75000000</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-06-03</value></transactionDate>
      <transactionCoding><transactionCode>A</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>5000</value></transactionShares>
        <transactionPricePerShare><value></value></transactionPricePerShare>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>75005000</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""


def test_parse_form4_sale_and_award_rows():
    rows = _attr("parse_form4_xml")(
        FORM4_SALE_XML, "NVDA", "0001045810-26-000123",
        "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000123/form4.xml",
    )
    assert len(rows) == 2

    sale = rows[0]
    assert sale["ticker"] == "NVDA"
    assert sale["cik"] == "0001045810"
    assert sale["filer_name"] == "HUANG JEN HSUN"
    assert sale["filer_title"] == "President and CEO"
    assert sale["is_officer"] is True and sale["is_director"] is True
    assert sale["transaction_date"] == "2026-06-02"
    assert sale["code"] == "S"
    assert sale["shares"] == 120000.0
    assert sale["price_per_share"] == 135.50
    assert sale["value"] == pytest.approx(16260000.0)
    assert sale["shares_owned_after"] == 75000000.0
    assert sale["accession"] == "0001045810-26-000123"
    assert sale["filing_url"].startswith("https://www.sec.gov/")

    award = rows[1]
    assert award["code"] == "A"
    assert award["price_per_share"] == 0.0 and award["value"] == 0.0


def test_parse_form4_malformed_and_empty_yield_no_rows():
    parse = _attr("parse_form4_xml")
    assert parse("<not-even-xml", "NVDA", "acc", "url") == []
    assert parse("<?xml version='1.0'?><ownershipDocument/>", "NVDA", "a", "u") == []


def test_cik_for_ticker_padding_case_and_dotted_mapping():
    cik_for = _attr("cik_for_ticker")
    mapping = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 1067983, "ticker": "BRK-B", "title": "Berkshire"},
    }
    assert cik_for("AAPL", mapping) == "0000320193"
    assert cik_for("aapl", mapping) == "0000320193"
    assert cik_for("BRK.B", mapping) == "0001067983"
    assert cik_for("ZZZZ", mapping) is None


def test_parse_form4_rejects_dtd_and_entity_declarations():
    # XXE / billion-laughs guard: any DTD or entity declaration is rejected
    # outright (genuine SEC ownershipDocuments never carry one).
    parse = _attr("parse_form4_xml")
    laughs = (
        "<?xml version='1.0'?><!DOCTYPE lolz [<!ENTITY lol 'lol'>]>"
        "<ownershipDocument>&lol;</ownershipDocument>"
    )
    assert parse(laughs, "NVDA", "acc", "url") == []

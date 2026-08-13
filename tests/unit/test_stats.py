"""Failing tests for T-017 — `GET /api/stats` (hero-strip live corpus
numbers).

Encodes tickets/T-017.md AC-1..AC-3. `onrecord/api.py` and its frozen sibling
test files (`tests/unit/test_api.py` T-013, `tests/unit/test_serve.py`
T-015) already exist and are untouched by this ticket/file — every AC here
targets NEW behavior (a new `/api/stats` route) layered on top of that
existing module, so — like `test_serve.py` (T-015) and unlike `test_api.py`
(T-013, which targeted a brand-new module) — no "module not implemented yet"
import guard is needed: `onrecord.api` is directly importable, and a
genuinely-missing route just 404s, a normal RED test failure rather than a
collection error. This file is NEW and does not touch `test_api.py` or
`test_serve.py` in any way (per the ticket's explicit file scope).

Run with:
    uv run pytest tests/unit/test_stats.py -v

Contracts pinned here (Test Agent design decisions noted explicitly where
the ticket underspecifies a seam; the ticket's own AC-1..AC-3 text is
authoritative where it speaks directly)
-----------------------------------------------------------------------

**Env vars**: only `ONRECORD_INDEX` is exercised (re-read fresh at ASGI
*startup* time, mirroring `onrecord/api.py`'s existing convention — see
`tests/unit/test_api.py`'s and `tests/unit/test_serve.py`'s module
docstrings' "AC-5"/"Env vars" sections — so per-test `monkeypatch.setenv(...)`
before `with TestClient(api_module.app) as client:` works). `/api/stats` is
index-dependent only (the ticket's shape is entirely derived from the loaded
index — no registry, no corpus/prices env involved), so `ONRECORD_UI_DIR`/
`ONRECORD_CORPUS`/`ONRECORD_PRICES_CACHE` are never set by this file's
tests — mirrors how `test_api.py`'s own AC-5 tests for `/api/search` and
`/api/tickers` only ever set `ONRECORD_INDEX`.

**GET /api/stats response shape**: `{"documents": int, "jurisdictions": int,
"tickers": int, "sources": {<source_type>: int, ...}, "corpus_version":
str}`, exact top-level key set (mirrors every other pinned endpoint in
`test_api.py` — the UI parses these directly per the ticket's hero-strip
wiring goal, extra undocumented keys would be a silent contract break).
- `documents` = `index.doc_count()`.
- `jurisdictions` = count of *distinct non-null* `Doc.jurisdiction` values
  across every doc in the index (the ticket's own wording, verbatim).
- `tickers` = count of *distinct non-null* `Doc.ticker` values (same).
- `sources` (**Test Agent design decision**: the ticket's own prose example
  shows three illustrative keys — `county_meeting`, `filing`, `docket` — but
  AC-1's fixture deliberately uses only 2 source types and asks for "exactly
  those counts". Read literally + consistent with how `jurisdictions`/
  `tickers` are pinned as exactly the *observed* distinct-value counts (never
  padded to some larger universe of possible values), `sources` is pinned
  here as exactly the `{source_type: count}` breakdown of source types
  actually present in the index — no zero-valued placeholder keys for
  unused/hypothetical source types like a `"docket"` that no ingestion
  adapter in this repo currently ever emits (`grep source_type=\" onrecord/
  -r` only ever finds `county_meeting`/`earnings_call`/`filing` as real
  values) — counts across all keys sum to `documents`.
- `corpus_version` (**Test Agent design decision**: the ticket's own example
  shows a literal `"corpus_version": "v1"` string — distinct from
  `onrecord/eval/run.py`'s unrelated `_corpus_version()` helper, which
  returns the placeholder `"unversioned"` for a different history-row
  schema entirely (T-005) and has no manifest-driven versioning to reuse.
  No corpus-version manifest exists anywhere in this repo yet, so the
  ticket's literal example is read as a stable constant this ticket
  introduces, not a value computed from index/corpus state) — asserted as
  the exact literal string `"v1"`.

**AC-2 — caching seam** (Test Agent design decision, per the ticket's own
"assert via monkeypatched counter or timing-free seam" hint): stats must be
computed once and reused, not recounted by every request — verified here by
monkeypatching `InvertedIndex.get_doc` (the same public per-doc accessor
`/api/tickers`'s existing implementation already loops over via
`index.get_doc(i)` for `i in range(index.doc_count())`, immediately above
this route in `onrecord/api.py` — the natural, established way to enumerate
every doc's metadata in this codebase) to count invocations, wrapping the
real implementation so behavior is unchanged. The seam is deliberately
timing-free and agnostic to *when* the one-time count happens — computed
eagerly at ASGI startup (the ticket's own "computed once at startup after
index load" phrasing) or lazily memoized on first request both satisfy the
test equally: it asserts the running call count is > 0 after the first
`/api/stats` request (proving the counting seam is actually wired to
whatever iteration strategy the implementation uses — a 0 count here means
the seam needs adjusting, not that the assertion should be weakened) and
UNCHANGED after a second request (proving no recount happened), plus that
both responses are byte-identical JSON.

**AC-3 — missing index**: `ONRECORD_INDEX` pointing at a directory that does
not exist → `/api/stats` 503s with the SAME flat-JSON error shape
`test_api.py`'s AC-5 section already pins for `/api/search`/`/api/tickers`
(`{"error": "<message mentioning the index>"}`, exact key set `{"error"}`,
never an `HTTPException`-wrapped `{"detail": ...}`) — the ticket's own
"Missing index → 503 flat {"error": ...} like the other data endpoints"
wording, read as reusing `onrecord/api.py`'s existing
`_missing_index_response()` helper verbatim. `GET /health` is unaffected
(always 200, `{"status": "ok"}`), proven in the same test by hitting both
routes against the same missing-index client.

Extension — the T-024 unlock (transitional re-pin #3)
--------------------------------------------------------
Trigger: the `corpus_version` decision recorded above ("No corpus-version
manifest exists anywhere in this repo yet, so the ticket's literal example
is read as a stable constant this ticket introduces") was TRANSITIONAL by
construction — it pinned a hard-coded `"v1"` only because T-018 had not yet
shipped a manifest. T-018 since landed `onrecord.ingest.build_corpus
.read_manifest` + a `manifest.json` written into BOTH the snapshot and the
index dir, and corpus-v2 exists. `.tdd-swarm/LESSONS.md`'s wave-4 rule
makes T-024, the unlocking merge, the place to re-pin it; this file is
otherwise frozen and no other test in it changed.

**Re-pin #3 — `corpus_version`** (`test_stats_returns_exact_counts_and
_corpus_version`, the `== "v1"` literal). SUPERSEDES the `corpus_version`
bullet above:

- `corpus_version` is `read_manifest(<the index dir>)["corpus_version"]`.
  The index dir is the same `ONRECORD_INDEX` the stats themselves come
  from, so the number and the version on the UI's hero strip always
  describe the SAME artifact.
- Any failure — no manifest, a manifest that is not readable/parseable, or
  a manifest without the `corpus_version` key — is the literal
  `"unversioned"`, NEVER a fabricated `"v1"` (orchestrator adjudication of
  plan-review I-12: `/api/stats` and the scoreboard must agree on the
  fallback, and a wrong-but-confident version string on the hero strip is
  worse than an honest "unversioned"). This is exactly the contract
  `onrecord/eval/run.py::_corpus_version` and `tests/unit/test_sweep.py`'s
  frozen `"unversioned"` trio already hold, so the three agree by
  construction rather than by coincidence.
- Read at ASGI startup alongside the counts and cached with them (AC-2's
  no-recount pin is unchanged and still covers the whole payload).

Confirmed RED against the current implementation (throwaway verification
patch added `/api/stats` returning the pinned shape + the
`InvertedIndex.get_doc`-counting cache seam, all three tests went GREEN,
then the patch was reverted — `/api/stats` does not exist in
`onrecord/api.py` as committed, so all three tests below currently fail
with a 404 from the SPA catch-all route, not a collection error).
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from onrecord.index.inverted import InvertedIndex  # noqa: E402
from onrecord.ingest.build_corpus import MANIFEST_FILENAME  # noqa: E402
from onrecord.types import Doc  # noqa: E402

# --------------------------------------------------------------------------
# Helpers (not tests)
# --------------------------------------------------------------------------


def _api_module():
    import onrecord.api as api_module

    return api_module


def _build_index(tmp_path: Path, docs: list[Doc], name: str = "index") -> Path:
    """Build a real InvertedIndex (real analyzer) and save it to a fresh
    tmp dir; return that dir. Mirrors tests/unit/test_api.py's and
    tests/unit/test_serve.py's identical helper."""
    index = InvertedIndex.build(docs)
    index_dir = tmp_path / name
    index.save(index_dir)
    return index_dir


def _write_manifest(index_dir: Path, payload) -> None:
    """Write a corpus-version manifest into an index dir, exactly where
    T-018's `build_corpus` writes one (`MANIFEST_FILENAME`, imported rather
    than re-spelled so a rename cannot silently decouple the two).

    `payload` is written verbatim, so a test can hand it a dict, a
    non-object JSON value, or (as raw `str`) deliberately corrupt bytes --
    the three shapes `read_manifest`'s tolerant contract collapses to
    `None`. Re-pin #3, see the module docstring's Extension section."""
    index_dir.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(payload)
    (index_dir / MANIFEST_FILENAME).write_text(text, encoding="utf-8")


@contextlib.contextmanager
def _client(api_module, monkeypatch, *, index_dir: Path):
    """Point ONRECORD_INDEX at `index_dir` (present or deliberately absent)
    and open a TestClient context -- re-runs onrecord.api's ASGI startup
    handler, which re-reads the env var at call time (module docstring's
    "Env vars" section) for this per-test swapping to work at all. Mirrors
    tests/unit/test_serve.py's `_client` helper, trimmed to the single env
    seam `/api/stats` actually depends on."""
    monkeypatch.setenv("ONRECORD_INDEX", str(index_dir))
    with TestClient(api_module.app) as client:
        yield client


# 3 jurisdictions (Doc.ticker always None on these -- county-meeting docs
# don't carry a ticker in this corpus, matching test_api.py's AC1_DOCS
# convention), 12 docs total, distribution 5/4/3 across the 3 jurisdictions
# -- deliberately uneven so a bug that just divides doc_count by 3 (or
# similar) can't accidentally pass.
_JURISDICTION_COUNTS = {
    "Loudoun County, VA": 5,
    "Fairfax County, VA": 4,
    "Arlington County, VA": 3,
}

# 4 tickers (Doc.jurisdiction always None on these -- filing docs don't
# carry a jurisdiction), 8 docs total, 2 each.
_TICKER_COUNTS = {
    "VST": 2,
    "NEE": 2,
    "DUK": 2,
    "SO": 2,
}

EXPECTED_DOCUMENTS = 20  # 12 county_meeting + 8 filing
EXPECTED_JURISDICTIONS = 3
EXPECTED_TICKERS = 4
EXPECTED_SOURCES = {"county_meeting": 12, "filing": 8}


def _make_stats_docs() -> list[Doc]:
    """20 docs across 3 jurisdictions, 4 tickers, 2 source types (AC-1's
    literal fixture spec). Each doc carries EITHER a jurisdiction (county
    meetings) OR a ticker (filings), never both -- deliberately exercising
    the "distinct NON-NULL" wording in both directions: the jurisdiction
    count must land at exactly 3 despite 8 docs having `jurisdiction=None`,
    and the ticker count must land at exactly 4 despite 12 docs having
    `ticker=None`."""
    docs: list[Doc] = []
    doc_num = 0
    for jurisdiction, count in _JURISDICTION_COUNTS.items():
        for _ in range(count):
            doc_num += 1
            docs.append(
                Doc(
                    id=f"cm-{doc_num}",
                    text=f"county meeting segment {doc_num} discussing substation buildout",
                    source_type="county_meeting",
                    venue_type="sworn",
                    date=f"2025-01-{doc_num:02d}",
                    deep_link=f"https://youtube.com/watch?v=cm{doc_num}",
                    ticker=None,
                    jurisdiction=jurisdiction,
                )
            )
    for ticker, count in _TICKER_COUNTS.items():
        for _ in range(count):
            doc_num += 1
            docs.append(
                Doc(
                    id=f"fil-{doc_num}",
                    text=f"filing section {doc_num} discussing operations and risk factors",
                    source_type="filing",
                    venue_type="coached",
                    date=f"2025-02-{doc_num:02d}",
                    deep_link=f"https://sec.gov/edgar/fil{doc_num}",
                    ticker=ticker,
                    jurisdiction=None,
                )
            )
    assert len(docs) == EXPECTED_DOCUMENTS
    return docs


# --------------------------------------------------------------------------
# AC-1 -- exact counts + corpus_version from a tmp index
# --------------------------------------------------------------------------


def test_stats_returns_exact_counts_and_corpus_version(tmp_path, monkeypatch):
    # spec(T-017:AC-1) + spec(T-024:AC-8) -- TRANSITIONAL RE-PIN #3, landed
    # at the T-024 unlocking merge per .tdd-swarm/LESSONS.md's wave-4 rule
    # and the T-013R/T-014R precedent (the Test Agent edits this otherwise
    # frozen file, for this pin only; no other test here changed).
    #
    # WAS: `assert body["corpus_version"] == "v1"` -- a hard-coded literal,
    # pinned that way only because no corpus-version manifest existed
    # anywhere in the repo at T-017's freeze.
    #
    # NOW: T-018 shipped `read_manifest` + a manifest.json in every index
    # dir, and corpus-v2 exists, so the value is READ from the manifest in
    # the same index dir the counts come from. The fixture below writes a
    # "v2" manifest and asserts it is reflected; the "v1" literal is gone
    # (the old assertion is REMOVED, not kept alongside the new one), and
    # the fallback lives in its own tests directly below.
    api_module = _api_module()
    index_dir = _build_index(tmp_path, _make_stats_docs())
    _write_manifest(
        index_dir,
        {
            "corpus_version": "v2",
            "created_at": "2026-08-12T00:00:00+00:00",
            "doc_count": EXPECTED_DOCUMENTS,
            "source_counts": EXPECTED_SOURCES,
        },
    )

    with _client(api_module, monkeypatch, index_dir=index_dir) as client:
        resp = client.get("/api/stats")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {
        "documents",
        "jurisdictions",
        "tickers",
        "sources",
        "corpus_version",
    }, f"unexpected top-level key set: {sorted(body.keys())}"

    assert body["documents"] == EXPECTED_DOCUMENTS
    assert body["jurisdictions"] == EXPECTED_JURISDICTIONS, (
        "must count DISTINCT NON-NULL jurisdiction values only -- 8 of the 20 docs have "
        "jurisdiction=None and must not be counted as a 4th distinct value"
    )
    assert body["tickers"] == EXPECTED_TICKERS, (
        "must count DISTINCT NON-NULL ticker values only -- 12 of the 20 docs have "
        "ticker=None and must not be counted as a 5th distinct value"
    )
    assert body["sources"] == EXPECTED_SOURCES
    assert sum(body["sources"].values()) == EXPECTED_DOCUMENTS
    assert body["corpus_version"] == "v2", (
        "corpus_version comes from T-018's read_manifest on the INDEX dir -- the same artifact "
        "the counts above describe -- never a hard-coded literal"
    )


@pytest.mark.parametrize(
    ("label", "payload"),
    [
        ("missing-manifest", None),
        ("manifest-without-the-key", {"doc_count": 20, "created_at": "2026-08-12T00:00:00+00:00"}),
        ("corrupt-json", "{not valid json at all"),
        ("json-that-is-not-an-object", "[1, 2, 3]"),
    ],
)
def test_stats_corpus_version_falls_back_to_unversioned(tmp_path, monkeypatch, label, payload):
    # spec(T-024:AC-8) -- the honest fallback, in every shape read_manifest's
    # tolerant contract collapses to None (plus the readable-but-keyless
    # manifest T-018's own IMPORTANT-1 calls out). NEVER a fabricated "v1":
    # a wrong-but-confident version string on the hero strip is worse than
    # an honest "unversioned" (orchestrator adjudication of plan-review
    # I-12), and this is the literal onrecord/eval/run.py::_corpus_version
    # and tests/unit/test_sweep.py's frozen trio already use, so /api/stats
    # and the scoreboard agree by construction.
    api_module = _api_module()
    index_dir = _build_index(tmp_path, _make_stats_docs())
    if payload is not None:
        _write_manifest(index_dir, payload)

    with _client(api_module, monkeypatch, index_dir=index_dir) as client:
        resp = client.get("/api/stats")

    assert resp.status_code == 200
    body = resp.json()
    assert body["corpus_version"] == "unversioned", label
    # the rest of the payload is unaffected by a missing/unusable manifest
    assert body["documents"] == EXPECTED_DOCUMENTS
    assert body["sources"] == EXPECTED_SOURCES


# --------------------------------------------------------------------------
# AC-2 -- caching: a second request does not recount
# --------------------------------------------------------------------------


def test_stats_second_request_does_not_recount(tmp_path, monkeypatch):
    # spec(T-017:AC-2)
    api_module = _api_module()
    index_dir = _build_index(tmp_path, _make_stats_docs())

    call_count = {"n": 0}
    real_get_doc = InvertedIndex.get_doc

    def _counting_get_doc(self, id):
        call_count["n"] += 1
        return real_get_doc(self, id)

    # Patched BEFORE the TestClient context is entered below, so it's
    # already active through ASGI startup -- covers both a
    # computed-at-startup implementation and a lazy-memoized-on-first-
    # request one equally (module docstring's "AC-2" section).
    monkeypatch.setattr(InvertedIndex, "get_doc", _counting_get_doc)

    with _client(api_module, monkeypatch, index_dir=index_dir) as client:
        first_resp = client.get("/api/stats")
        count_after_first = call_count["n"]
        assert count_after_first > 0, (
            "expected at least one InvertedIndex.get_doc call while computing stats (mirrors "
            "the per-doc enumeration /api/tickers already uses) -- a 0 count here means this "
            "test's counting seam isn't wired to whatever iteration strategy /api/stats uses"
        )

        second_resp = client.get("/api/stats")
        count_after_second = call_count["n"]

    assert first_resp.status_code == 200
    assert second_resp.status_code == 200
    assert second_resp.json() == first_resp.json()
    assert count_after_second == count_after_first, (
        f"a second /api/stats request must not recount the corpus -- InvertedIndex.get_doc "
        f"call count grew from {count_after_first} to {count_after_second}"
    )


# --------------------------------------------------------------------------
# AC-3 -- missing index -> 503 flat error; /health unaffected
# --------------------------------------------------------------------------


def test_stats_503_when_index_missing_but_health_still_ok(tmp_path, monkeypatch):
    # spec(T-017:AC-3)
    api_module = _api_module()
    missing_index_dir = tmp_path / "no_such_index"
    assert not missing_index_dir.exists()

    with _client(api_module, monkeypatch, index_dir=missing_index_dir) as client:
        health_resp = client.get("/health")
        stats_resp = client.get("/api/stats")

    assert health_resp.status_code == 200
    assert health_resp.json().get("status") == "ok"

    assert stats_resp.status_code == 503
    body = stats_resp.json()
    assert set(body.keys()) == {"error"}
    assert isinstance(body["error"], str)
    assert "index" in body["error"].lower()

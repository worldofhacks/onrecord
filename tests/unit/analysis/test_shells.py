"""Frozen tests — T-058 LLC shell resolution v1 (curated, receipt-backed).

Pins `onrecord.analysis.shells`: deterministic candidate mining, co-occurrence
evidence lists, and the curated-link loader. Load-bearing honesty invariants:
the loader rejects any curated row whose receipt doc is missing or does not
verbatim-contain the shell name (AC-1); the mining false-positive corpus never
fires (AC-2); and there is NO auto-link path — evidence rows carry no
confidence, and absent a curated row nothing resolves (AC-3). The shipped
data/shell_links.json is an empty list: curated rows require owner review.

Written before implementation (tdd-swarm Iron Law). Spec tags: spec(T-058:AC-n).
"""

import json
from pathlib import Path

import pytest

try:
    from onrecord.analysis import shells
except Exception:  # pragma: no cover - red phase
    shells = None

from onrecord.types import Doc

REPO_ROOT = Path(__file__).resolve().parents[3]
SHIPPED_LINKS = REPO_ROOT / "data" / "shell_links.json"


def _attr(name):
    if shells is None or not hasattr(shells, name):
        pytest.fail(f"onrecord.analysis.shells.{name} does not exist yet (T-058 red)")
    return getattr(shells, name)


def _doc(doc_id, text, jur="Alpha County, VA", date="2026-01-10",
         source_type="county_meeting"):
    return Doc(id=doc_id, text=text, source_type=source_type,
               venue_type="public", date=date,
               deep_link=f"https://youtube.com/watch?v={doc_id}&t=0s",
               jurisdiction=jur)


# ---------------------------------------------------------------------------
# AC-2 — mining: pattern grammar
# ---------------------------------------------------------------------------


class TestMiningGrammar:
    def test_project_codename_extracts(self):
        """spec(T-058:AC-2) — 'Project <Name>' with a distinctive codename."""
        mine = _attr("mine_shell_candidates")
        docs = [
            _doc("d1", "The applicant introduced Project Sail to the board.",
                 jur="Alpha County, VA", date="2026-01-10"),
            _doc("d2", "Project Sail returned for a rezoning hearing.",
                 jur="Beta County, GA", date="2026-02-01"),
        ]
        rows = mine(docs)
        by_name = {r["name"]: r for r in rows}
        assert "Project Sail" in by_name
        row = by_name["Project Sail"]
        assert row["jurisdictions"] == ["Alpha County, VA", "Beta County, GA"]
        assert row["first_seen"] == "2026-01-10"
        assert row["n_docs"] == 2
        assert row["sample_receipts"][0] == {
            "doc_id": "d1", "deep_link": "https://youtube.com/watch?v=d1&t=0s"}

    def test_project_two_word_codename(self):
        """spec(T-058:AC-2)"""
        mine = _attr("mine_shell_candidates")
        rows = mine([_doc("d1", "staff met with Project Blue Sky representatives")])
        assert "Project Blue Sky" in {r["name"] for r in rows}

    def test_entity_suffix_extracts(self):
        """spec(T-058:AC-2) — '<Name> LLC|Holdings|Partners|Properties|Ventures'."""
        mine = _attr("mine_shell_candidates")
        docs = [
            _doc("d1", "the parcel was acquired by Sail Holdings LLC in March"),
            _doc("d2", "counsel appeared on behalf of Redwood Partners"),
            _doc("d3", "a proffer was signed with Bluebird Properties yesterday"),
        ]
        names = {r["name"] for r in mine(docs)}
        assert "Sail Holdings LLC" in names
        assert "Redwood Partners" in names
        assert "Bluebird Properties" in names

    def test_entity_name_up_to_three_words(self):
        """spec(T-058:AC-2)"""
        mine = _attr("mine_shell_candidates")
        rows = mine([_doc("d1", "an application filed by Quantum Loop Digital Ventures")])
        assert "Quantum Loop Digital Ventures" in {r["name"] for r in rows}


# ---------------------------------------------------------------------------
# AC-2 — mining: the frozen false-positive corpus (must never fire)
# ---------------------------------------------------------------------------


class TestMiningFalsePositives:
    FALSE_POSITIVE_TEXTS = [
        "The Project Manager presented the quarterly budget.",
        "Project Timeline was reviewed and approved by staff.",
        "the project will proceed as planned next spring",
        "The applicant's LLC was not named in the filing.",
        "LLC formation documents were requested by the clerk.",
        "Pine Log Road runs north of the proposed site.",
        "John Smith spoke during the public comment period.",
        "Supervisor Jane Doe asked about traffic impacts.",
        # Mangled names: the real name word was ALLCAPS or lowercased, so
        # only suffix words survive — never propose "Holdings LLC" as a name.
        "STACK Holdings LLC presented the site plan.",
        "Properties LLC was the listed owner of record.",
    ]

    def test_false_positive_corpus_yields_nothing(self):
        """spec(T-058:AC-2)"""
        mine = _attr("mine_shell_candidates")
        docs = [_doc(f"fp{i}", text) for i, text in enumerate(self.FALSE_POSITIVE_TEXTS)]
        assert mine(docs) == []

    def test_generic_project_word_trimmed_not_named(self):
        """spec(T-058:AC-2) — 'Project Sail Update' proposes 'Project Sail' only."""
        mine = _attr("mine_shell_candidates")
        names = {r["name"] for r in mine([_doc("d1", "the Project Sail Update was tabled")])}
        assert "Project Sail" in names
        assert "Project Sail Update" not in names


# ---------------------------------------------------------------------------
# AC-2 — mining: scoping, caps, reproducibility
# ---------------------------------------------------------------------------


class TestMiningScope:
    def test_only_county_meeting_docs_are_mined(self):
        """spec(T-058:AC-2) — shells are proposed from the county record only."""
        mine = _attr("mine_shell_candidates")
        docs = [_doc("d1", "Project Sail was discussed", source_type="earnings_call")]
        assert mine(docs) == []

    def test_sample_receipts_capped_at_three(self):
        """spec(T-058:AC-2)"""
        mine = _attr("mine_shell_candidates")
        docs = [_doc(f"d{i}", "Project Sail appeared again", date=f"2026-01-{i+1:02d}")
                for i in range(5)]
        row = next(r for r in mine(docs) if r["name"] == "Project Sail")
        assert row["n_docs"] == 5
        assert len(row["sample_receipts"]) == 3
        assert row["first_seen"] == "2026-01-01"

    def test_reproducible_from_corpus_alone(self):
        """spec(T-058:AC-2)"""
        mine = _attr("mine_shell_candidates")
        docs = [
            _doc("d1", "Project Sail and Sail Holdings LLC were both named"),
            _doc("d2", "Redwood Partners appeared for Project Sail"),
        ]
        assert mine(docs) == mine(docs)


# ---------------------------------------------------------------------------
# link_evidence — co-occurrence receipts, evidence lists ONLY
# ---------------------------------------------------------------------------


class TestLinkEvidence:
    COMPANY_TERMS = {"NVDA": ["Nvidia", "NVIDIA Corporation"],
                     "MSFT": ["Microsoft"]}

    def _candidates(self):
        return [{"name": "Project Sail"}]

    def test_cooccurrence_requires_both_names_in_same_doc(self):
        """spec(T-058:AC-2)"""
        link = _attr("link_evidence")
        docs = [
            _doc("both", "Nvidia counsel confirmed Project Sail is theirs"),
            _doc("shell-only", "Project Sail requested a permit"),
            _doc("company-only", "Nvidia reported record earnings"),
        ]
        rows = link(self._candidates(), docs, self.COMPANY_TERMS)
        assert len(rows) == 1
        row = rows[0]
        assert row["shell"] == "Project Sail"
        assert row["ticker"] == "NVDA"
        assert row["n_cooccurrence_docs"] == 1
        assert [r["doc_id"] for r in row["receipts"]] == ["both"]

    def test_word_boundary_and_case_sensitive(self):
        """spec(T-058:AC-2) — proper nouns match exactly: no substring, no
        case-folding."""
        link = _attr("link_evidence")
        docs = [
            _doc("lower", "nvidia mentioned project sail informally"),
            _doc("embedded", "the Nvidiazone forum discussed Project Sailing"),
        ]
        assert link(self._candidates(), docs, self.COMPANY_TERMS) == []

    def test_ranked_by_cooccurrence_and_receipts_capped(self):
        """spec(T-058:AC-2)"""
        link = _attr("link_evidence")
        docs = [_doc(f"n{i}", "Nvidia and Project Sail together",
                     date=f"2026-01-{i+1:02d}") for i in range(4)]
        docs.append(_doc("m1", "Microsoft and Project Sail together"))
        rows = link(self._candidates(), docs, self.COMPANY_TERMS)
        assert [(r["ticker"], r["n_cooccurrence_docs"]) for r in rows] == [
            ("NVDA", 4), ("MSFT", 1)]
        assert len(rows[0]["receipts"]) == 3

    def test_evidence_rows_carry_no_link_assertion(self):
        """spec(T-058:AC-3) — evidence lists only: no confidence, no resolution."""
        link = _attr("link_evidence")
        docs = [_doc("both", "Nvidia counsel confirmed Project Sail is theirs")]
        row = link(self._candidates(), docs, self.COMPANY_TERMS)[0]
        assert set(row) == {"shell", "ticker", "n_cooccurrence_docs", "receipts"}


# ---------------------------------------------------------------------------
# AC-1 — the curated-link loader and its verbatim pin
# ---------------------------------------------------------------------------


def _links_file(tmp_path, rows):
    path = tmp_path / "shell_links.json"
    path.write_text(json.dumps(rows))
    return path


VALID_ROW = {"shell": "Project Sail", "ticker": "NVDA", "receipts": ["d1"],
             "confidence": "confirmed",
             "note": "counsel named the parent on the record"}


class TestLoader:
    def _docs_by_id(self, text="Nvidia counsel confirmed Project Sail is theirs"):
        return {"d1": _doc("d1", text)}

    def test_valid_row_loads(self, tmp_path):
        """spec(T-058:AC-1)"""
        load = _attr("load_shell_links")
        path = _links_file(tmp_path, [VALID_ROW])
        assert load(path, self._docs_by_id()) == [VALID_ROW]

    def test_rejects_missing_receipt_doc(self, tmp_path):
        """spec(T-058:AC-1) — corrupt fixture: receipt doc_id not in corpus."""
        load = _attr("load_shell_links")
        row = dict(VALID_ROW, receipts=["ghost-doc"])
        path = _links_file(tmp_path, [row])
        with pytest.raises(ValueError, match="Project Sail"):
            load(path, self._docs_by_id())

    def test_rejects_receipt_without_verbatim_shell(self, tmp_path):
        """spec(T-058:AC-1) — corrupt fixture: doc exists but never says the
        shell name."""
        load = _attr("load_shell_links")
        path = _links_file(tmp_path, [VALID_ROW])
        docs = self._docs_by_id(text="Nvidia counsel discussed Project Sale instead")
        with pytest.raises(ValueError, match="Project Sail"):
            load(path, docs)

    def test_verbatim_means_case_sensitive(self, tmp_path):
        """spec(T-058:AC-1) — 'project sail' is not 'Project Sail'."""
        load = _attr("load_shell_links")
        path = _links_file(tmp_path, [VALID_ROW])
        docs = self._docs_by_id(text="nvidia counsel confirmed project sail is theirs")
        with pytest.raises(ValueError, match="Project Sail"):
            load(path, docs)

    def test_rejects_unknown_confidence(self, tmp_path):
        """spec(T-058:AC-1)"""
        load = _attr("load_shell_links")
        row = dict(VALID_ROW, confidence="likely")
        path = _links_file(tmp_path, [row])
        with pytest.raises(ValueError, match="Project Sail"):
            load(path, self._docs_by_id())

    def test_rejects_row_with_no_receipts(self, tmp_path):
        """spec(T-058:AC-1) — every link carries receipts."""
        load = _attr("load_shell_links")
        row = dict(VALID_ROW, receipts=[])
        path = _links_file(tmp_path, [row])
        with pytest.raises(ValueError, match="Project Sail"):
            load(path, self._docs_by_id())


# ---------------------------------------------------------------------------
# AC-3 — no auto-link path: absent a curated row, nothing resolves
# ---------------------------------------------------------------------------


class TestNoAutoLink:
    def test_shipped_links_file_is_an_empty_list(self):
        """spec(T-058:AC-3) — curated rows require owner review; v1 ships none."""
        assert json.loads(SHIPPED_LINKS.read_text()) == []

    def test_empty_links_file_resolves_nothing_despite_strong_evidence(self):
        """spec(T-058:AC-3) — mining + evidence alone can never produce a
        resolved link; resolution flows only from the curated file."""
        mine = _attr("mine_shell_candidates")
        link = _attr("link_evidence")
        load = _attr("load_shell_links")
        docs = [_doc(f"d{i}", "Nvidia counsel confirmed Project Sail is theirs",
                     date=f"2026-01-{i+1:02d}") for i in range(10)]
        candidates = mine(docs)
        evidence = link(candidates, docs, {"NVDA": ["Nvidia"]})
        assert evidence, "sanity: the evidence really is strong"
        resolved = load(SHIPPED_LINKS, {d.id: d for d in docs})
        assert resolved == []

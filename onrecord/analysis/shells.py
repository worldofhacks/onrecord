"""LLC shell resolution v1 — T-058 (curated, receipt-backed).

Datacenter developers appear in county hearings behind project shells
("Project Sail", "Sail Holdings LLC") while the real party appears in SEC
filings or later coverage. v1 is deliberately CURATED, not inferred:
`mine_shell_candidates` proposes names via deterministic patterns over the
county record, `link_evidence` lists co-occurrence receipts per (shell,
ticker) pair, and only a human-reviewed row in data/shell_links.json ever
asserts a link. The loader verbatim-pins every curated receipt at load:
each receipt doc must exist and contain the shell name exactly.

HONESTY PIN (frozen tests gate this module): there is NO auto-link path.
Mining and evidence rows carry no confidence and assert nothing; absent a
curated row a shell can only render as unresolved — which is itself useful
civic information. Precision over recall throughout: a name extracts only
when a deterministic pattern anchors it, and a small closed stoplist keeps
office nouns ("Project Manager") out of the candidate pool.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from onrecord.types import Doc

__all__ = [
    "mine_shell_candidates",
    "link_evidence",
    "load_shell_links",
    "write_shell_candidates",
]

MINED_SOURCE_TYPE = "county_meeting"
SAMPLE_RECEIPTS_CAP = 3
EVIDENCE_RECEIPTS_CAP = 3

# A "capitalized word" is strictly Xxxx — ALLCAPS and mixed-case tokens stay
# unextracted (precision over recall; acronyms are rarely shell codenames).
_CAP_WORD = r"[A-Z][a-z]+"

# "Project <Name>", Name = 1-2 capitalized words ("Project Sail",
# "Project Blue Sky"). Lowercase "the project will" never matches.
_PROJECT_RE = re.compile(rf"\bProject\s+({_CAP_WORD}(?:\s+{_CAP_WORD})?)\b")

# "<Name> LLC|Holdings|Partners|Properties|Ventures", Name = 1-3 capitalized
# words, suffixes may chain ("Sail Holdings LLC"). Bare "LLC" never matches:
# at least one capitalized name word must precede the suffix.
_SUFFIX = r"(?:LLC|Holdings|Partners|Properties|Ventures)"
_ENTITY_RE = re.compile(
    rf"\b({_CAP_WORD}(?:\s+{_CAP_WORD}){{0,2}})((?:\s+{_SUFFIX})+)"
)

# Closed stoplist of office nouns that follow "Project" in meeting minutes.
# A trailing stoplist word is trimmed ("Project Sail Update" -> "Project
# Sail"); a candidate whose entire name is generic is rejected outright
# ("Project Manager", "Project Timeline"). Frozen tests pin this corpus.
_GENERIC_PROJECT_WORDS = frozenset({
    "Agreement", "Application", "Applications", "Approval", "Approvals",
    "Area", "Areas", "Budget", "Budgets", "Coordinator", "Coordinators",
    "Cost", "Costs", "Description", "Director", "Directors", "Document",
    "Documents", "Engineer", "Engineers", "File", "Files", "Manager",
    "Managers", "Management", "Meeting", "Meetings", "Name", "Names",
    "Number", "Numbers", "Overview", "Phase", "Phases", "Plan", "Plans",
    "Planning", "Report", "Reports", "Review", "Reviews", "Schedule",
    "Schedules", "Scope", "Site", "Sites", "Status", "Summary", "Team",
    "Teams", "Timeline", "Timelines", "Update", "Updates",
})

# Sentence-position capitalization pollutes entity names ("Tonight Sail
# Holdings LLC presented"). Leading determiners/prepositions/titles are
# trimmed off the name portion; corporate suffixes cannot stand alone.
_LEADING_STOP = frozenset({
    "The", "This", "That", "These", "Those", "A", "An", "And", "Or", "But",
    "In", "On", "At", "By", "For", "Of", "To", "With", "From", "As",
    "Our", "Their", "His", "Her", "Its", "Mr", "Mrs", "Ms", "Dr",
})

# Caption transcripts mangle names ("STACK Holdings LLC" -> ALLCAPS name word
# never matches _CAP_WORD). A candidate whose every name word is itself a
# corporate suffix ("Holdings LLC") is a mangled fragment, not a name.
_SUFFIX_WORDS = frozenset({"LLC", "Holdings", "Partners", "Properties", "Ventures"})


def _project_names(text: str) -> set[str]:
    names: set[str] = set()
    for match in _PROJECT_RE.finditer(text):
        words = match.group(1).split()
        while words and words[-1] in _GENERIC_PROJECT_WORDS:
            words = words[:-1]
        if words:
            names.add("Project " + " ".join(words))
    return names


def _entity_names(text: str) -> set[str]:
    names: set[str] = set()
    for match in _ENTITY_RE.finditer(text):
        words = match.group(1).split()
        while words and words[0] in _LEADING_STOP:
            words = words[1:]
        if words and not all(w in _SUFFIX_WORDS for w in words):
            names.add(" ".join(words) + match.group(2))
    return names


def mine_shell_candidates(docs: list[Doc]) -> list[dict]:
    """Candidate shell names from the county record, case-preserved.

    Rows: {name, jurisdictions (sorted), first_seen (min doc date), n_docs,
    sample_receipts (up to 3 {doc_id, deep_link})}, ordered by n_docs
    descending then name. Proposals only — candidates assert nothing.
    """
    county = sorted(
        (d for d in docs if d.source_type == MINED_SOURCE_TYPE),
        key=lambda d: (d.date, d.id),
    )
    hits: dict[str, list[Doc]] = {}
    for doc in county:
        for name in _project_names(doc.text) | _entity_names(doc.text):
            rows = hits.setdefault(name, [])
            if not any(d.id == doc.id for d in rows):
                rows.append(doc)

    out = []
    for name, matched in hits.items():
        out.append({
            "name": name,
            "jurisdictions": sorted({d.jurisdiction for d in matched if d.jurisdiction}),
            "first_seen": matched[0].date,
            "n_docs": len(matched),
            "sample_receipts": [
                {"doc_id": d.id, "deep_link": d.deep_link}
                for d in matched[:SAMPLE_RECEIPTS_CAP]
            ],
        })
    out.sort(key=lambda r: (-r["n_docs"], r["name"]))
    return out


def _word_bounded(term: str, text: str) -> bool:
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def link_evidence(
    candidates: list[dict],
    docs: list[Doc],
    company_terms: dict[str, list[str]],
) -> list[dict]:
    """Co-occurrence receipts per (candidate, ticker) pair — evidence ONLY.

    A doc is a receipt when its text contains BOTH the shell name and any of
    the ticker's name variants (word-boundary, case-sensitive — these are
    proper nouns). Rows: {shell, ticker, n_cooccurrence_docs, receipts (up
    to 3 {doc_id, deep_link})}, ranked by n_cooccurrence_docs descending
    then (shell, ticker). NO auto-linking: rows carry no confidence and are
    input to human curation, never to resolution.
    """
    ordered = sorted(docs, key=lambda d: (d.date, d.id))
    out = []
    for candidate in candidates:
        shell = candidate["name"]
        shell_docs = [d for d in ordered if _word_bounded(shell, d.text)]
        if not shell_docs:
            continue
        for ticker, terms in company_terms.items():
            receipts = [
                d for d in shell_docs
                if any(term and _word_bounded(term, d.text) for term in terms)
            ]
            if not receipts:
                continue
            out.append({
                "shell": shell,
                "ticker": ticker,
                "n_cooccurrence_docs": len(receipts),
                "receipts": [
                    {"doc_id": d.id, "deep_link": d.deep_link}
                    for d in receipts[:EVIDENCE_RECEIPTS_CAP]
                ],
            })
    out.sort(key=lambda r: (-r["n_cooccurrence_docs"], r["shell"], r["ticker"]))
    return out


def load_shell_links(path: str | Path, docs_by_id: dict[str, Doc]) -> list[dict]:
    """Load the curated alias table — the ONLY path by which a shell resolves.

    Rows: {shell, ticker, receipts: [doc_id...], confidence:
    "confirmed"|"reported", note}. Every receipt is verbatim-pinned at load:
    the doc must exist in `docs_by_id` and its text must contain the shell
    name exactly (case-sensitive). Any violation raises ValueError naming
    the row — a corrupt curated table must never load partially.
    """
    with Path(path).open() as fh:
        rows = json.load(fh)
    if not isinstance(rows, list):
        raise ValueError(f"shell_links file {path!s} must be a JSON list")

    out: list[dict] = []
    for i, row in enumerate(rows):
        label = f"shell_links row {i} ({row.get('shell')!r} -> {row.get('ticker')!r})"
        shell = row.get("shell")
        if not shell or not row.get("ticker"):
            raise ValueError(f"{label}: shell and ticker are required")
        if row.get("confidence") not in ("confirmed", "reported"):
            raise ValueError(
                f"{label}: confidence must be 'confirmed' or 'reported', "
                f"got {row.get('confidence')!r}"
            )
        receipts = row.get("receipts") or []
        if not receipts:
            raise ValueError(f"{label}: every curated link carries at least one receipt")
        for doc_id in receipts:
            doc = docs_by_id.get(doc_id)
            if doc is None:
                raise ValueError(f"{label}: receipt doc {doc_id!r} is not in the corpus")
            if shell not in doc.text:
                raise ValueError(
                    f"{label}: receipt doc {doc_id!r} does not contain the "
                    f"shell name verbatim"
                )
        out.append(row)
    return out


def write_shell_candidates(docs: list[Doc], path: str | Path) -> list[dict]:
    """Mine candidates and write the proposals artifact (built at runtime,
    e.g. artifacts/shell_candidates.json — never committed). Returns the rows."""
    rows = mine_shell_candidates(docs)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w") as fh:
        json.dump(rows, fh, indent=2)
        fh.write("\n")
    return rows

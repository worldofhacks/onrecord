"""Grounded answer pipeline — prompt, citations, claim grounding, refusal (T-023).

The authoritative contract lives in `tests/unit/rag/test_answer.py`'s module
docstring (frozen suite) and in tickets/T-023.md — read both before touching
this file. What is implemented here:

- `build_prompt(question, chunks)`: numbered context blocks `[1]..[m]` in chunk
  order, 1-based (plan-review I-7 — the citation parser's validity range is
  defined by exactly this numbering). Each block is MARKER-FIRST: the `[i]`
  marker opens the block, followed by that chunk's date/venue metadata and
  `deep_link` on the same line, then the chunk text verbatim. The instructions
  confine the model to the provided context, ask for inline `[n]` markers,
  require PROSE-ONLY answers (2026-08-12 amendment — see below), and name the
  literal `INSUFFICIENT_CONTEXT` sentinel. Deterministic: identical input ->
  identical string (`answer()` is pinned to send exactly this prompt).
- `answer(question, chunks, generate_fn, *, min_confidence, retrieval_scores)`:
  returns EXACTLY the PINNED-FOR-THURSDAY dict frozen in
  tests/unit/test_api.py — `{answer_id, text, citations, retrieved, grounding,
  refusal}`. Extra top-level keys are a contract break (the UI's Ask view,
  T-028, parses this directly). Generation is injected, never constructed here:
  `generate_fn` is the seam every frozen test drives.
- `default_generator(*, transport=...)`: the real Claude-family generator over
  httpx (`transport=` injects an `httpx.MockTransport` in tests — zero live
  network in the suite). Keyless -> `GeneratorNotConfigured`.
- `resolved_generator_model()`: THE single source of the generator model id
  (plan-review I-8). T-026's cross-family gate consumes this value as an
  explicit parameter wired at eval time — there is no second env lookup
  anywhere in the epic. Both sources (env override + module constant) are read
  at CALL time, never snapshotted at import, because T-026 may change them
  in-process.

**Two refusal paths, and only two.** (1) Retrieval confidence, decided BEFORE
generation: empty chunks, or `max(retrieval_scores) < min_confidence`. The
generator is provably never called on this path — spending a generation call on
a known refusal is the exact cost the deterministic gate exists to avoid.
(2) The generation-side sentinel: the model emitted `INSUFFICIENT_CONTEXT`.
The raw sentinel NEVER reaches user-facing `text` — it is the pipeline's
internal protocol signal, and T-028 renders `text` verbatim. An answer that is
merely uncited is UNGROUNDED, not a refusal.

**Claim segmentation is imported, never reimplemented** — `split_claims`
(T-027) is the single segmentation authority shared with T-026's faithfulness
judge, which is what makes grounding counts and judged claims segment
identically (locked consistency decision). Grounding runs over the RETURNED
text, i.e. AFTER dangling-marker stripping: for `"[7] [9]"` over 3 chunks the
claims VANISH under stripping, so the honest report is 0/0, not 0/1.

**AMENDMENT (2026-08-12, T-027 adjudication)** — the prompt instructs
prose-only answers because segmentation deliberately does not merge
enumerators (a merge rule was proven structurally incompatible with T-027's
frozen count invariant). An enumerated answer SHATTERS into junk claims that
ground pessimistically (`"1. Dominion filed. [1]"` -> `["1.", "Dominion
filed. [1]"]`), so the mitigation lives here, at the source. Conservative by
design: junk claims depress grounding rather than risk a false "grounded"
receipt (.tdd-swarm/LESSONS.md, 2026-08-12).

Marker handling, in the pinned order:
- A DANGLING marker (`n` outside the closed interval `[1, len(chunks)]`, both
  ends included — `[0]` is dangling, `[len(chunks)]` is valid) is stripped from
  `text` and cited by nothing. Stripping removes the marker ONLY, never its
  surrounding whitespace: welding `"hearing. [7] Dominion filed. [1]"` into
  `"hearing.Dominion filed. [1]"` turns two claims into one and silently
  upgrades a half-uncited answer to `"grounded"` — a false receipt.
- An UNTERMINATED marker (`[2` with no closing bracket — a max_tokens cutoff,
  plan-review M-6) is NOT a marker: it stays literal text and supports nothing.
- Every VALID marker survives into `text` unchanged; the pinned contract calls
  `text` "prose with inline [n] citation markers" and T-028 renders them as the
  clickable receipts.

Whether a citation is FAITHFUL (the chunk actually entails the claim) is
T-026's LLM-judge territory. Grounding here is the deterministic
marker-coverage layer only (locked split).

Generator model (research-required per the ticket; verified against the current
Anthropic model catalog at implementation time, not from memory):
`claude-opus-5` is the current Opus-tier id and the documented default. It
classifies as `anthropic` under the orchestrator's canonical family map
(`claude*`), which T-026's fail-closed `classify_family` requires — an id it
cannot classify is "unknown" and silently disables faithfulness scoring at eval
time. Operators may override with `ONRECORD_GENERATOR_MODEL`; the override is
passed through VERBATIM (a Bedrock/gateway-shaped `us.anthropic.claude-...` id
is `anthropic` under the same map and is a legitimate override — rewriting it
would hand T-026 an id the operator never configured).

Request shape: the raw Messages API over httpx. Raw HTTP rather than the
`anthropic` SDK because the SDK is not a project dependency and this ticket's
file scope is this file alone; httpx is already the epic's HTTP seam
(`OpenAIEmbeddingProvider(..., transport=...)`, T-021), and the frozen tests
pin `default_generator(transport=...)` against `httpx.MockTransport`. Thinking
is left ON (adaptive is the default on this model) with `effort` dialled down
for what is a routine extractive-synthesis task: disabling thinking on this
model can leak `<thinking>` tags into the visible response, which would land
verbatim in user-facing `text`. Response `content` is a list of blocks and may
include thinking blocks, so only `type == "text"` blocks are joined — never
`content[0]`.

Secret hygiene (.tdd-swarm/LESSONS.md, T-014, 2026-08-11): a prior ticket
leaked an API key because the leak check only inspected the module's own
logger while the actual leak came from a LIBRARY logger (httpx logs full
request URLs at INFO). So `ANTHROPIC_API_KEY` never enters a log record, an
exception message, or a repr: library loggers are silenced for the duration of
every keyed request, transport errors are never re-emitted verbatim (they can
carry request headers), and the key lives only in a closure — never on a
formatted object.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import time
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import httpx

from onrecord.rag.claims import split_claims

if TYPE_CHECKING:
    from onrecord.rag.chunking import Chunk

_log = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Configuration surface
# --------------------------------------------------------------------------

# The generator model id in use when ONRECORD_GENERATOR_MODEL is unset. Must
# classify as `anthropic` under the orchestrator's canonical family map
# (claude* | anthropic.* | us.anthropic.* | eu.anthropic.*) or T-026's
# fail-closed cross-family gate refuses it. Read through
# `resolved_generator_model()`, never directly -- that function is the single
# model-id source the rest of the epic consumes.
DEFAULT_GENERATOR_MODEL = "claude-opus-5"

_MODEL_ENV_VAR = "ONRECORD_GENERATOR_MODEL"
_API_KEY_ENV_VAR = "ANTHROPIC_API_KEY"

# The literal the prompt asks for and the generation-side refusal path detects.
# Deliberately PRIVATE: nothing outside this module consumes it, so exporting it
# would mint a gratuitous new id space -- but a single constant keeps the
# instruction and the detector from drifting apart, which would silently
# disable the whole refusal path.
_SENTINEL = "INSUFFICIENT_CONTEXT"

# `citations[].snippet` and `retrieved[].snippet` share one derivation so the
# UI's two renderers stay consistent.
_SNIPPET_LEN = 160

# A citation marker is a bracketed run of digits. An UNTERMINATED `[2` does not
# match, which is exactly the pinned behaviour: a max_tokens cutoff is ordinary
# text, not a citation.
_MARKER_RE = re.compile(r"\[(\d+)\]")

# --------------------------------------------------------------------------
# Anthropic Messages API (raw HTTP -- see the module docstring)
# --------------------------------------------------------------------------

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_REQUEST_TIMEOUT = 120.0
# Headroom for a short grounded answer plus adaptive thinking, which counts
# against the same ceiling. A truncated generation degrades gracefully here (an
# unterminated `[n` is treated as literal text), so this is a cost bound, not a
# correctness one.
_MAX_TOKENS = 8192
# Grounded extraction over <=10 retrieved blocks is routine work; effort is the
# cost lever that keeps thinking on (see the module docstring).
_EFFORT = "low"
_MAX_RETRIES = 3  # retries beyond the initial attempt
_BACKOFF_BASE = 0.05  # seconds; tests that don't monkeypatch time.sleep still run fast
_LIBRARY_LOGGER_NAMES = ("httpx", "httpcore", "anthropic")


class GeneratorNotConfigured(Exception):
    """Raised when the default generator cannot be constructed because required
    configuration (the API key) is missing. T-024 maps this to a 503 rung.
    Never silently substitute a fake -- fakes are test-injected only."""


class GenerationError(RuntimeError):
    """A generation request failed (transport error, exhausted retries, a
    non-retryable status, or an unreadable response). Deliberately
    credential-free -- see the module's secret-hygiene note."""


# --------------------------------------------------------------------------
# Prompt assembly
# --------------------------------------------------------------------------

_INSTRUCTIONS = f"""\
You are answering a question about public records for a receipts-first research
tool. Use only the numbered context blocks below. Never rely on outside
knowledge, and never assert a detail the blocks do not state.

Cite as you write: append a marker of the form [n] to every sentence, where n is
the number of the context block supporting it. A sentence supported by two
blocks carries one marker for each. Never cite a block number that is not listed
below.

Write the answer as continuous prose. Do not use bulleted or numbered lists,
headings, tables, or enumerations of any kind -- plain paragraphs only.

If the context blocks do not contain enough information to answer the question,
reply with exactly {_SENTINEL} and nothing else.\
"""


def _block_metadata(chunk: Chunk) -> str:
    """The provenance line that opens a block: date/venue metadata plus the
    chunk's deep link, so the model can see which link belongs to which
    numbered block (spec §5 -- every citation is a deep link)."""
    fields = [chunk.date, chunk.source_type, chunk.venue_type]
    if chunk.jurisdiction:
        fields.append(chunk.jurisdiction)
    if chunk.ticker:
        fields.append(f"ticker {chunk.ticker}")
    fields.append(chunk.deep_link)
    return " | ".join(field for field in fields if field)


def build_prompt(question: str, chunks: list[Chunk]) -> str:
    """Assemble the generation prompt: 1-based numbered context blocks, then
    the question.

    Blocks are MARKER-FIRST (`[i]` opens its block, metadata and deep_link
    follow on the same line, chunk text after) -- the shape the ticket's
    "numbered context blocks `[1]..[m]`" describes and the one the frozen tests
    pin. Chunk texts are included VERBATIM; prompt size is bounded by
    construction (k <= 10 chunks of ~75s caption windows / EDGAR sections).

    The instructions never spell a block number as a digit (they talk about
    `[n]`, with a literal n), so the only `[digits]` in the prompt are the block
    markers themselves.
    """
    parts: list[str] = [_INSTRUCTIONS, "", "CONTEXT"]
    for i, chunk in enumerate(chunks, start=1):
        parts.extend(("", f"[{i}] {_block_metadata(chunk)}", chunk.text))
    parts.extend(("", "QUESTION", question, "", "ANSWER (prose only, [n] markers inline):"))
    return "\n".join(parts)


# --------------------------------------------------------------------------
# Deterministic post-processing
# --------------------------------------------------------------------------


def _strip_dangling_markers(text: str, chunk_count: int) -> str:
    """Remove out-of-range `[n]` markers, and ONLY those markers.

    Surrounding whitespace is deliberately left alone: removing it welds the
    neighbouring sentences into one claim, which reports a half-uncited answer
    as fully grounded (the false-receipt failure mode LESSONS 2026-08-12 ranks
    as worse than junk claims).
    """

    def _replace(match: re.Match[str]) -> str:
        n = int(match.group(1))
        return match.group(0) if 1 <= n <= chunk_count else ""

    return _MARKER_RE.sub(_replace, text)


def _valid_marker_ns(text: str, chunk_count: int) -> list[int]:
    """Valid marker numbers in first-appearance order, duplicates collapsed.

    First appearance, never sorted: sorting produces plausible-looking output
    while silently reordering the receipts away from the prose that cites them.
    """
    seen: list[int] = []
    for match in _MARKER_RE.finditer(text):
        n = int(match.group(1))
        if 1 <= n <= chunk_count and n not in seen:
            seen.append(n)
    return seen


def _citations(text: str, chunks: list[Chunk]) -> list[dict[str, Any]]:
    citations = []
    for n in _valid_marker_ns(text, len(chunks)):
        chunk = chunks[n - 1]
        citations.append(
            {
                "n": n,
                # The CHUNK id, not a constituent doc id: a windowed chunk's
                # `doc_ids[0]` is an id T-028's deep-link resolution and T-026's
                # judge cannot line up with the retrieved block.
                "doc_id": chunk.chunk_id,
                "deep_link": chunk.deep_link,
                "snippet": chunk.text[:_SNIPPET_LEN],
            }
        )
    return citations


def _retrieved(chunks: list[Chunk], scores: list[float], cited_ids: set[str]) -> list[dict]:
    """The 9-key /api/search result shape plus `cited` (no `speaker` -- locked
    in tests/unit/test_api.py; dumping every Chunk field breaks the shared
    shape the UI parses)."""
    return [
        {
            "doc_id": chunk.chunk_id,
            "score": score,
            "snippet": chunk.text[:_SNIPPET_LEN],
            "date": chunk.date,
            "source_type": chunk.source_type,
            "venue_type": chunk.venue_type,
            "jurisdiction": chunk.jurisdiction,
            "ticker": chunk.ticker,
            "deep_link": chunk.deep_link,
            "cited": chunk.chunk_id in cited_ids,
        }
        for chunk, score in zip(chunks, scores, strict=True)
    ]


def _grounding(text: str, chunk_count: int) -> dict[str, Any]:
    """Claim-level grounding over the RETURNED text.

    Claims come from the shared segmentation authority (T-027), never a private
    sentence splitter, and are computed AFTER dangling-marker stripping -- a
    text whose claims vanish under stripping honestly reports 0/0.
    """
    claims = split_claims(text)
    supported = sum(
        1
        for claim in claims
        if any(1 <= int(raw) <= chunk_count for raw in _MARKER_RE.findall(claim))
    )
    total = len(claims)
    if total > 0 and supported == total:
        status = "grounded"
    elif supported > 0:
        status = "partial"
    else:
        status = "ungrounded"
    return {"status": status, "supported_claims": supported, "total_claims": total}


# --------------------------------------------------------------------------
# Refusal
# --------------------------------------------------------------------------

# Short words and question scaffolding carry no search signal; the suggestions
# are meant to name what the user actually asked about.
_STOPWORDS = frozenset(
    {
        "about",
        "after",
        "again",
        "against",
        "because",
        "been",
        "before",
        "being",
        "between",
        "could",
        "does",
        "doing",
        "during",
        "each",
        "from",
        "have",
        "having",
        "here",
        "into",
        "just",
        "more",
        "most",
        "only",
        "other",
        "over",
        "same",
        "should",
        "some",
        "such",
        "tell",
        "than",
        "that",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "told",
        "under",
        "until",
        "very",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "will",
        "with",
        "would",
        "your",
    }
)

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]+")

_NO_RECORDS_TEXT = (
    "I can't answer that from the records on hand -- nothing retrieved is a close "
    "enough match to cite."
)
_LOW_CONFIDENCE_TEXT = (
    "I can't answer that with confidence -- the retrieved records aren't a close "
    "enough match to cite."
)
_SENTINEL_TEXT = "I can't answer that from the retrieved records -- they don't cover the question."

_NO_RECORDS_REASON = (
    "no records were retrieved for this question, so no passage was relevant enough "
    "to ground an answer"
)
_SENTINEL_REASON = "the model judged the retrieved context insufficient to answer this question"


def _question_terms(question: str, limit: int = 3) -> list[str]:
    """The question's distinctive content words, longest first.

    Longest-first favours the specific over the generic ("Chesterfield" before
    "plant"), which is what makes a reformulation hint useful rather than
    boilerplate.
    """
    seen: set[str] = set()
    terms: list[str] = []
    for word in _WORD_RE.findall(question):
        key = word.lower()
        if len(key) < 4 or key in _STOPWORDS or key in seen:
            continue
        seen.add(key)
        terms.append(word)
    terms.sort(key=len, reverse=True)
    return terms[:limit]


def _refusal_suggestions(question: str) -> list[str]:
    """2-3 reformulation hints DERIVED FROM THE QUESTION (ticket Context).

    A hard-coded boilerplate list ("try again later") satisfies a bare count
    check and helps nobody -- at least one hint names what the user asked about.
    """
    terms = _question_terms(question)
    if not terms:
        return [
            "Rephrase with the specific organization, venue, or filing you have in mind.",
            "Add a date range or a jurisdiction to narrow the search.",
        ]
    suggestions = [f"Search for {terms[0]} on its own first, then narrow to the specific claim."]
    if len(terms) > 1:
        suggestions.append(
            f"Name the venue or filing where {terms[1]} would appear -- a board meeting, "
            "a hearing, or an annual report."
        )
    suggestions.append(
        f"Add a date range or jurisdiction alongside {terms[-1]} to focus the search."
    )
    return suggestions


def _refusal_response(
    question: str,
    chunks: list[Chunk],
    scores: list[float],
    *,
    text: str,
    reason: str,
) -> dict[str, Any]:
    """The pinned response shape for both refusal paths.

    The retrieved blocks are still reported (with their real scores) so the UI
    can show the user WHY the pipeline declined -- but nothing is cited, and a
    decline sentence asserts nothing about the corpus, so grounding is 0/0.
    """
    return {
        "answer_id": uuid.uuid4().hex,
        "text": text,
        "citations": [],
        "retrieved": _retrieved(chunks, scores, cited_ids=set()),
        "grounding": {"status": "ungrounded", "supported_claims": 0, "total_claims": 0},
        "refusal": {"reason": reason, "suggestions": _refusal_suggestions(question)},
    }


# --------------------------------------------------------------------------
# The pipeline
# --------------------------------------------------------------------------


def _resolve_scores(chunks: list[Chunk], retrieval_scores: list[float] | None) -> list[float]:
    """Scores aligned 1:1 with `chunks`, coerced to float.

    When `retrieval_scores` is None the score is the pinned placeholder `0.0`
    (plan-review M-4 -- never an invented value). A length mismatch is a loud
    ValueError: silently zip-truncating mis-attributes every score to the wrong
    chunk in the UI's retrieved panel.
    """
    if retrieval_scores is None:
        return [0.0] * len(chunks)
    if len(retrieval_scores) != len(chunks):
        raise ValueError(
            f"retrieval_scores has {len(retrieval_scores)} entries but {len(chunks)} chunk(s) "
            "were given -- scores map 1:1 onto chunks, in order"
        )
    # float(), not the raw value: /api/search pins this key as a JSON float and
    # the UI's two panels share the renderer.
    return [float(score) for score in retrieval_scores]


def answer(
    question: str,
    chunks: list[Chunk],
    generate_fn: Callable[[str], str],
    *,
    min_confidence: float | None = None,
    retrieval_scores: list[float] | None = None,
) -> dict[str, Any]:
    """Answer `question` from `chunks`, returning the pinned /api/answer dict.

    `generate_fn` is INJECTED (generation is non-deterministic, so every frozen
    test drives a fake through this seam). This function reads NO environment:
    the confidence threshold arrives as a parameter, and an env fallback would
    make the same call behave differently in two processes.

    Raises ValueError when `retrieval_scores` is given with a length that does
    not match `chunks`.
    """
    scores = _resolve_scores(chunks, retrieval_scores)

    # --- Refusal path 1: retrieval confidence, decided BEFORE generation. ---
    if not chunks:
        return _refusal_response(
            question, chunks, scores, text=_NO_RECORDS_TEXT, reason=_NO_RECORDS_REASON
        )
    if min_confidence is not None and retrieval_scores is not None:
        best = max(scores)
        # STRICTLY less than: a score AT the threshold clears the gate. `<=`
        # would refuse on the boundary and quietly shrink recall once T-025
        # tunes the threshold onto a real score distribution.
        if best < min_confidence:
            return _refusal_response(
                question,
                chunks,
                scores,
                text=_LOW_CONFIDENCE_TEXT,
                reason=(
                    f"the best retrieval score ({best:.4g}) is below the configured minimum "
                    f"confidence ({min_confidence:.4g}), so no passage is a close enough match "
                    "to cite"
                ),
            )

    generated = generate_fn(build_prompt(question, chunks))

    # --- Refusal path 2: the generation-side sentinel. ---
    # "Containing", not equality: the likelier shape is the model wrapping the
    # sentinel in a sentence. `text` is a human-facing decline, never the raw
    # protocol token.
    if _SENTINEL in generated:
        return _refusal_response(
            question, chunks, scores, text=_SENTINEL_TEXT, reason=_SENTINEL_REASON
        )

    # --- Citation post-processing, then grounding over the RETURNED text. ---
    text = _strip_dangling_markers(generated, len(chunks))
    citations = _citations(text, chunks)
    cited_ids = {citation["doc_id"] for citation in citations}
    return {
        "answer_id": uuid.uuid4().hex,
        "text": text,
        "citations": citations,
        "retrieved": _retrieved(chunks, scores, cited_ids),
        "grounding": _grounding(text, len(chunks)),
        # An uncited answer is UNGROUNDED, not a refusal: the only two refusal
        # paths are retrieval confidence and the generation sentinel.
        "refusal": None,
    }


# --------------------------------------------------------------------------
# The default generator
# --------------------------------------------------------------------------


def resolved_generator_model() -> str:
    """The generator model id actually in use -- the SINGLE source of truth.

    T-026's cross-family gate consumes this value as an explicit parameter
    wired at eval time; there is no second env lookup anywhere in the epic.
    Both sources are read on EVERY call (never cached at import), because T-026
    may set or change the override in-process. An operator's override is passed
    through verbatim -- no normalisation, no stripping of a region prefix.
    """
    override = os.environ.get(_MODEL_ENV_VAR)
    if override and override.strip():
        return override
    return DEFAULT_GENERATOR_MODEL


@contextlib.contextmanager
def _silenced_library_loggers():
    """Silence httpx/httpcore/anthropic for the duration of a keyed request.

    LESSONS T-014: a secret-leak check must cover LIBRARY loggers, not just
    this module's own -- httpx logs full request URLs at INFO.
    `Logger.disabled = True` makes `isEnabledFor` return False unconditionally
    regardless of level or propagation, so no record is created at all.
    """
    loggers = [logging.getLogger(name) for name in _LIBRARY_LOGGER_NAMES]
    previous = [(lg.level, lg.disabled) for lg in loggers]
    for lg in loggers:
        lg.setLevel(logging.CRITICAL + 1)
        lg.disabled = True
    try:
        yield
    finally:
        for lg, (level, disabled) in zip(loggers, previous, strict=True):
            lg.setLevel(level)
            lg.disabled = disabled


def _extract_text(payload: dict[str, Any]) -> str:
    """Join the response's TEXT blocks.

    `content` is a list of blocks and thinking is on by default on this model,
    so it may also carry thinking blocks -- reading `content[0]` would return
    the wrong one (or empty text, since thinking display defaults to omitted).
    """
    if payload.get("stop_reason") == "refusal":
        raise GenerationError("generation was declined by the model (stop_reason=refusal)")
    blocks = payload.get("content") or []
    return "".join(
        block.get("text", "")
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
    )


def _generate(prompt: str, *, api_key: str, transport: httpx.BaseTransport | None) -> str:
    headers = {
        "x-api-key": api_key,
        "anthropic-version": _ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    body = {
        "model": resolved_generator_model(),
        "max_tokens": _MAX_TOKENS,
        "output_config": {"effort": _EFFORT},
        "messages": [{"role": "user", "content": prompt}],
    }

    with _silenced_library_loggers(), httpx.Client(transport=transport) as client:
        for attempt in range(_MAX_RETRIES + 1):
            more_retries_left = attempt < _MAX_RETRIES
            try:
                response = client.post(
                    _ANTHROPIC_URL, headers=headers, json=body, timeout=_REQUEST_TIMEOUT
                )
            except httpx.HTTPError:
                # Never re-emit a transport error's own text: it can carry the
                # request headers, credential included.
                if more_retries_left:
                    time.sleep(_BACKOFF_BASE * (2**attempt))
                    continue
                raise GenerationError(
                    "generation request to Anthropic failed: transport error"
                ) from None

            if response.status_code == 200:
                try:
                    payload = response.json()
                except ValueError:
                    raise GenerationError(
                        "generation request to Anthropic failed: response was not JSON"
                    ) from None
                return _extract_text(payload)

            if (response.status_code == 429 or response.status_code >= 500) and more_retries_left:
                _log.warning(
                    "generation request returned HTTP %s; retrying (attempt %d of %d)",
                    response.status_code,
                    attempt + 1,
                    _MAX_RETRIES,
                )
                time.sleep(_BACKOFF_BASE * (2**attempt))
                continue

            raise GenerationError(
                f"generation request to Anthropic failed: HTTP {response.status_code}"
            )

    # Unreachable: the loop above always returns or raises.
    raise GenerationError("generation request to Anthropic failed: retries exhausted")


def default_generator(*, transport: httpx.BaseTransport | None = None) -> Callable[[str], str]:
    """Build the real `generate_fn` -- a `Callable[[str], str]` over the
    Anthropic Messages API.

    Construction performs NO network I/O; `transport=` injects an
    `httpx.MockTransport` in tests. The key is resolved once, at construction,
    and lives only in the returned closure -- it is never stored on a formatted
    object, so no repr can surface it.

    Raises GeneratorNotConfigured when ANTHROPIC_API_KEY is absent or blank.
    """
    api_key = os.environ.get(_API_KEY_ENV_VAR)
    if not api_key or not api_key.strip():
        raise GeneratorNotConfigured(
            f"{_API_KEY_ENV_VAR} is not set -- export {_API_KEY_ENV_VAR} to enable the "
            "default Claude generator (key provisioning is owner open question #2)"
        )

    def generate(prompt: str) -> str:
        return _generate(prompt, api_key=api_key, transport=transport)

    return generate

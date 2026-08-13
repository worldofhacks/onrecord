"""Cross-family faithfulness judge — claim verdicts, hand-label validation
gate, faithfulness runner (T-026).

The authoritative contract lives in `tests/unit/rag/test_judge.py`'s module
docstring (frozen suite, 79 functions / 208 cases) — read it in full before
touching this file. Summary of what's implemented here:

- `classify_family(model_id) -> str` — THE canonical id -> family map
  (orchestrator ruling, locked): `anthropic` (`claude*`, plus the Bedrock
  dotted forms `anthropic.*` / `us.anthropic.*` / `eu.anthropic.*`),
  `openai` (`gpt*`, `chatgpt*`, and the o-series `o1*`/`o3*`/`o4*` only —
  NOT a bare `o*`, which would mislabel `olmo-*`/`openrouter/auto`),
  `google` (`gemini*`, `models/gemini*`), `mistral` (`mistral*`,
  `open-mistral*`, `open-mixtral*`), else `unknown` — including empty
  strings, whitespace, `None`, and every non-hosted-shaped id (`voyage*`,
  an embeddings vendor, is never a judge/generator family). This is public
  API and the single authority other modules must import rather than
  re-derive (LESSONS T-003/T-004).
- `assert_cross_family(generator_model, judge_model) -> None` — raises
  `CrossFamilyViolation` when the two ids classify to the same family OR
  either is `unknown` (fail closed: an unverifiable pairing never silently
  counts).
- `build_judge_prompt(question, claim, chunks) -> str` — one claim per call
  (claim-level, spec §5), evidence chunks numbered `[1]..[m]` in list order
  (1-based, mirrors T-023's `build_prompt`), strict JSON output protocol.
- `parse_verdict(raw) -> {"verdict", "evidence_chunk"}` — tolerant
  extraction of the FIRST brace-balanced JSON object in `raw` (string-aware,
  so braces inside quoted values never desync the scan); a strict enum
  match on `verdict` (case/whitespace normalized, but never a substring
  match — "partially supported" is `unparseable`, never `supported`); a
  malformed/absent `evidence_chunk` becomes `None` without destroying an
  otherwise-valid verdict. NEVER raises — judge flakiness is data.
- `judge_answer(question, answer_text, chunks, judge_fn) -> dict` — claims
  via `onrecord.rag.claims.split_claims` (T-027, the single segmentation
  authority shared with T-023's grounding, so judged claims and the
  grounding denominator count identically for the same text); a `judge_fn`
  call that RAISES is caught (`except Exception`, never `BaseException` —
  a `KeyboardInterrupt` mid-run must still stop it) and recorded as verdict
  `"error"`, and the run continues (plan-review M-8: prior verdicts are
  never lost). `unparseable` and `error` both count NOT supported.
  `faithfulness = supported / total`, `0.0` when `total == 0`.
- `load_labels(path, include_examples=False) -> list[dict]` — schema-
  validating JSONL loader for `evalsets/faithfulness_labels.jsonl`; every
  row is validated (including example rows — they document the schema),
  errors are `ValueError`s naming the 1-based line number and the
  offending/missing field; `"example-"` is a PREFIX filter, excluded by
  default.
- `validate_judge(judge_fn, labels, judge_model, generator_model,
  min_agreement=0.8, validation_path=DEFAULT_VALIDATION_PATH) -> dict` —
  runs `assert_cross_family` FIRST (zero judge calls on a same-family or
  unknown pairing); a raising `judge_fn` is recorded as verdict `"error"`
  (a disagreement, since it can never equal a human verdict) and the run
  continues (a paid, human-labelled validation run must not be discarded
  by one transport blip); on `agreement >= min_agreement` writes the
  7-key validation artifact (adds `min_agreement` to the ticket's key set
  — the audit trail for a caller-lowered bar, decision 16) and creates
  parent directories as needed; empty `labels` raises `ValueError` (a
  "validation" over zero rows must never report a number).
- `run_faithfulness(answers, judge_fn, judge_model, generator_model,
  validation_path=DEFAULT_VALIDATION_PATH) -> dict` — THE verdicts-don't-
  count gate. Re-runs `assert_cross_family(generator_model, judge_model)`
  BEFORE reading the artifact or making any judge call (decision 15,
  closes test-review C-1: the artifact alone can never license a
  same-family run at run time). Then requires a validation artifact with
  `passed: true`, a matching `judge_model`, and `agreement >=` the SPEC
  floor of 0.8 — enforced against the artifact's OWN recorded agreement
  regardless of what `min_agreement` the validation run used (decision 16,
  closes review C-2) — else raises `JudgeNotValidated`. On success appends
  `{"timestamp", "git_sha", "corpus_version", "kind": "faithfulness",
  "metrics": {"mean_faithfulness", "per_answer"}}` to
  `artifacts/rag_eval.jsonl` (append-only, shared sidecar with T-025's
  runner; row shape pinned identically in both tickets' Context, not a
  code import) and returns the appended row. `mean_faithfulness` is the
  MEAN OF PER-ANSWER faithfulness (macro), not the micro total-supported/
  total-claims average. `corpus_version` is read via `ONRECORD_INDEX`
  (falling back to `artifacts/index`) through T-018's `read_manifest` —
  verbatim the mechanism already frozen for `onrecord.eval.run
  ._corpus_version`, so the two artifact writers never disagree about
  which corpus a number describes.
- `default_judge(model=None, transport=None)` — OpenAI chat-completions
  adapter over httpx (`transport=` injects an `httpx.MockTransport`, same
  seam as `onrecord/rag/embeddings.py`, `ingest/fmp.py`, `ingest/edgar.py`,
  `ingest/prices.py`). `OPENAI_API_KEY` absent/blank -> typed
  `JudgeNotConfigured` naming the var. Retries 429/5xx with backoff, bounded
  well inside the house precedent (`_JUDGE_MAX_RETRIES = 3`, i.e. <= 4
  requests per call).
- `resolved_judge_model() -> str` — `ONRECORD_JUDGE_MODEL` env, else
  `DEFAULT_JUDGE_MODEL`; read ONLY here (never a second env lookup
  elsewhere in this module), mirroring T-023's `resolved_generator_model`.
- `_resolve_generator_model()` / `_resolve_answers()` — `main()`'s TWO lazy
  seams (mirrors T-025's `_resolve_answer_fn`, plan-review I-9): T-022
  (retrieval), T-023 (generation) and T-025 (the QA set + loader) are all
  same-wave and unmerged during this ticket's implementation, so their
  imports live INSIDE these function bodies, never at module scope — a
  module-level import would be a collection error in the wave-9 worktree.
  `_resolve_answers()`'s real composition is genuinely eval-land / post-
  merge wiring (like `onrecord.eval.run._real_pipeline_retrieve`):
  untestable here, monkeypatched in every test that reaches `main()`.

Model identity plumbing (plan-review I-8 — one source of truth): every
function that needs model ids takes them as EXPLICIT parameters
(`generator_model`, `judge_model`). This module performs NO generator-side
env lookup — the generator id's single source is T-023's
`resolved_generator_model()`, reached only through the `_resolve_generator_
model()` seam above.

DEFAULT_JUDGE_MODEL (RESEARCH-REQUIRED AT PROVISIONING, ticket DoD): the
literal value below is a placeholder that satisfies the frozen contract (a
non-empty, openai-family, non-Claude id) so local/CI runs — which always
inject a fake `judge_fn` — stay fully deterministic. The owner must verify
the current, live model id (and its pricing) before this ships against a
real `OPENAI_API_KEY` — never taken from training-data memory.

Secret hygiene (LESSONS.md T-014, locked): the key must never appear in any
log record, exception, or repr. `default_judge`'s adapter silences the
`httpx`/`httpcore`/`openai` loggers for the duration of every keyed request
(`_silenced_library_loggers`, the identical mechanism `embeddings.py`
already uses), never places the key in an exception message or `repr`, and
never re-emits a transport error's own text verbatim (it can carry request
headers, including `Authorization`).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx

from onrecord.ingest.build_corpus import read_manifest
from onrecord.rag.claims import split_claims

# --------------------------------------------------------------------------
# Typed errors
# --------------------------------------------------------------------------


class CrossFamilyViolation(Exception):
    """Raised by `assert_cross_family` when the generator/judge pairing is
    same-family or unverifiable (fail closed)."""


class JudgeNotValidated(Exception):
    """Raised by `run_faithfulness` when no passing validation artifact for
    THIS judge/generator pairing exists — the verdicts-don't-count gate."""


class JudgeNotConfigured(Exception):
    """Raised by `default_judge` when `OPENAI_API_KEY` is absent/blank.
    Never silently substitute a fake — fakes are test-injected only."""


class JudgeRequestError(RuntimeError):
    """A judge request failed (transport error or exhausted retries).
    Deliberately credential-free (LESSONS T-014) — never re-emits a
    transport error's own text, which can carry request headers."""


# --------------------------------------------------------------------------
# AC-1 — classify_family / assert_cross_family
# --------------------------------------------------------------------------

# THE canonical id -> family map (orchestrator ruling, locked — see module
# docstring). Prefixes are mutually exclusive by construction, so match
# order carries no meaning here.
_FAMILY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("us.anthropic.", "anthropic"),
    ("eu.anthropic.", "anthropic"),
    ("anthropic.", "anthropic"),
    ("claude", "anthropic"),
    ("gpt", "openai"),
    ("chatgpt", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
    ("models/gemini", "google"),
    ("gemini", "google"),
    ("open-mistral", "mistral"),
    ("open-mixtral", "mistral"),
    ("mistral", "mistral"),
)


def classify_family(model_id: str | None) -> str:
    """The single family-classification authority (locked, decision 17).

    Returns one of `"anthropic"`, `"openai"`, `"google"`, `"mistral"`, or
    `"unknown"` (fail-closed default — never raises on a bad input; `None`,
    non-str, and empty/whitespace-only ids all classify `"unknown"`).
    """
    if not isinstance(model_id, str):
        return "unknown"
    stripped = model_id.strip()
    if not stripped:
        return "unknown"
    for prefix, family in _FAMILY_PREFIXES:
        if stripped.startswith(prefix):
            return family
    return "unknown"


def assert_cross_family(generator_model: str | None, judge_model: str | None) -> None:
    """Raise `CrossFamilyViolation` unless `generator_model` and
    `judge_model` classify to two DIFFERENT, KNOWN families. Fail closed
    (ticket Context): same family, or either `unknown`, always raises."""
    generator_family = classify_family(generator_model)
    judge_family = classify_family(judge_model)
    is_unknown = judge_family == "unknown" or generator_family == "unknown"
    if is_unknown or judge_family == generator_family:
        raise CrossFamilyViolation(
            f"generator model {generator_model!r} (family={generator_family!r}) and judge "
            f"model {judge_model!r} (family={judge_family!r}) are not a verifiably "
            f"cross-family pairing — refusing (fail closed, spec Sec 5 cross-family "
            f"requirement)"
        )


# --------------------------------------------------------------------------
# AC-3 — build_judge_prompt / parse_verdict
# --------------------------------------------------------------------------

VERDICT_ENUM: tuple[str, ...] = ("supported", "unsupported", "contradicted")


def build_judge_prompt(question: str, claim: str, chunks: list[str]) -> str:
    """The claim-level judge prompt (ticket Context / AC-3): the question,
    ONE claim, and the evidence chunks numbered `[1]..[m]` in list order
    (1-based — decision 2, mirrors T-023's `build_prompt`), followed by the
    STRICT output-protocol instructions `parse_verdict`'s enum enforces.
    """
    lines = [
        "You are a strict fact-checking judge. Decide whether the CLAIM below is "
        "supported, unsupported, or contradicted by the numbered EVIDENCE chunks. Base "
        "your verdict ONLY on the evidence provided -- do not use outside knowledge.",
        "",
        f"QUESTION: {question}",
        f"CLAIM: {claim}",
        "",
        "EVIDENCE:",
    ]
    for i, chunk in enumerate(chunks, start=1):
        lines.append(f"[{i}] {chunk}")
    lines.extend(
        [
            "",
            "Respond with a single JSON object and nothing else, in this exact shape:",
            '{"verdict": "supported" | "unsupported" | "contradicted", '
            '"evidence_chunk": <evidence chunk number or null>}',
            "verdict must be exactly one of: supported, unsupported, contradicted.",
            "evidence_chunk is the number of the evidence chunk that most directly "
            "determines your verdict, or null if none does.",
        ]
    )
    return "\n".join(lines)


def _first_balanced_json_object(text: str) -> str | None:
    """Return the FIRST brace-balanced `{...}` substring of `text`, or None.

    String-aware: characters inside a JSON string literal (respecting `\\`
    escapes) never affect brace counting, so an object embedded in prose or
    wrapped in an array is still recovered even when the surrounding text
    (or the object's own string values) contains stray braces. Only the
    very first `{` is tried — no forward rescan if it fails to balance
    (the conservative reading; see test_judge.py "DELIBERATELY NOT
    PINNED").
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def parse_verdict(raw: str) -> dict:
    """Tolerant extraction of the judge's verdict — NEVER raises (AC-2):
    judge flakiness is data, not a crash. See module docstring decision 3
    (test_judge.py) for the exact normalization/strictness split."""
    try:
        candidate = _first_balanced_json_object(raw)
        if candidate is None:
            return {"verdict": "unparseable", "evidence_chunk": None}
        parsed = json.loads(candidate)
        if not isinstance(parsed, dict):
            return {"verdict": "unparseable", "evidence_chunk": None}
        verdict = parsed.get("verdict")
        if not isinstance(verdict, str):
            return {"verdict": "unparseable", "evidence_chunk": None}
        normalized = verdict.strip().lower()
        if normalized not in VERDICT_ENUM:
            return {"verdict": "unparseable", "evidence_chunk": None}
        evidence_chunk = parsed.get("evidence_chunk")
        if isinstance(evidence_chunk, bool) or not isinstance(evidence_chunk, int):
            evidence_chunk = None
        return {"verdict": normalized, "evidence_chunk": evidence_chunk}
    except Exception:
        return {"verdict": "unparseable", "evidence_chunk": None}


# --------------------------------------------------------------------------
# AC-3 — judge_answer
# --------------------------------------------------------------------------


def judge_answer(
    question: str, answer_text: str, chunks: list[str], judge_fn: Callable[[str], str]
) -> dict:
    """Per-claim verdicts + faithfulness math (AC-3).

    Claims come from `split_claims` (T-027, the single segmentation
    authority) — never re-rolled — so `total` is the SAME denominator
    T-023's grounding uses for identical text. A `judge_fn` call that
    RAISES is failures-as-data (plan-review M-8): caught with
    `except Exception` (never `BaseException` — a `KeyboardInterrupt`
    during a long paid eval run must still stop it, decision 13), recorded
    as verdict `"error"`, and the run continues — prior verdicts are never
    discarded. `unparseable` and `error` both count NOT supported.
    """
    claims = split_claims(answer_text)
    results = []
    supported = 0
    for claim in claims:
        prompt = build_judge_prompt(question, claim, chunks)
        try:
            raw = judge_fn(prompt)
        except Exception:
            results.append({"claim": claim, "verdict": "error", "evidence_chunk": None})
            continue
        parsed = parse_verdict(raw)
        verdict = parsed["verdict"]
        results.append(
            {"claim": claim, "verdict": verdict, "evidence_chunk": parsed["evidence_chunk"]}
        )
        if verdict == "supported":
            supported += 1

    total = len(claims)
    faithfulness = supported / total if total else 0.0
    return {
        "claims": results,
        "supported": supported,
        "total": total,
        "faithfulness": faithfulness,
    }


# --------------------------------------------------------------------------
# AC-6 — labels loader
# --------------------------------------------------------------------------

_REQUIRED_LABEL_FIELDS: tuple[str, ...] = (
    "label_id",
    "question",
    "answer_text",
    "chunk_texts",
    "claim",
    "human_verdict",
)
_HUMAN_VERDICT_ENUM: tuple[str, ...] = VERDICT_ENUM  # supported/unsupported/contradicted only


def _require_nonempty_str(row: dict, field: str, path, lineno: int) -> None:
    value = row[field]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} line {lineno}: {field!r} must be a non-empty string")


def _validate_label_row(row: dict, lineno: int, path) -> None:
    for field in _REQUIRED_LABEL_FIELDS:
        if field not in row:
            raise ValueError(f"{path} line {lineno}: missing required field {field!r}")

    for field in ("label_id", "question", "answer_text", "claim"):
        _require_nonempty_str(row, field, path, lineno)

    chunk_texts = row["chunk_texts"]
    if not isinstance(chunk_texts, list) or not all(isinstance(c, str) for c in chunk_texts):
        raise ValueError(f"{path} line {lineno}: 'chunk_texts' must be a list of strings")

    human_verdict = row["human_verdict"]
    if human_verdict not in _HUMAN_VERDICT_ENUM:
        raise ValueError(
            f"{path} line {lineno}: 'human_verdict' must be one of {_HUMAN_VERDICT_ENUM}, "
            f"got {human_verdict!r}"
        )


def load_labels(path: str | Path, include_examples: bool = False) -> list[dict]:
    """Schema-validating loader for `evalsets/faithfulness_labels.jsonl`
    (decision 4). Rows are returned VERBATIM (extra annotation keys pass
    through). Every line is validated — including `"example-"`-prefixed
    rows, since the committed examples document the schema and a broken
    one must fail loudly. A malformed row raises `ValueError` naming the
    1-based physical LINE number and the offending/missing field; a
    missing file raises `FileNotFoundError`.

    `include_examples=False` (default) excludes rows whose `label_id`
    starts with the literal PREFIX `"example-"` — a substring match would
    silently drop a real hand label like `"counterexample-1"`.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"faithfulness labels file not found: {path}")

    rows: list[dict] = []
    for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path} line {lineno}: not valid JSON ({exc})") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path} line {lineno}: row is not a JSON object")
        _validate_label_row(row, lineno, path)
        rows.append(row)

    if include_examples:
        return rows
    return [row for row in rows if not row["label_id"].startswith("example-")]


# --------------------------------------------------------------------------
# AC-4 — validate_judge
# --------------------------------------------------------------------------

SPEC_MIN_AGREEMENT = 0.8  # spec Sec 5's hand-label agreement bar
DEFAULT_VALIDATION_PATH = "artifacts/judge_validation.json"


def validate_judge(
    judge_fn: Callable[[str], str],
    labels: list[dict],
    judge_model: str,
    generator_model: str,
    min_agreement: float = SPEC_MIN_AGREEMENT,
    validation_path: str | Path = DEFAULT_VALIDATION_PATH,
) -> dict:
    """Validate `judge_fn` against hand `labels` (AC-4). Runs
    `assert_cross_family` FIRST — a same-family or unknown pairing costs
    ZERO judge calls. Empty `labels` raises `ValueError` (decision 8):
    until the owner lands the ~10 real hand labels, `load_labels()`
    returns `[]`, and a silent `0.0`/`passed: False` would read as "the
    judge is bad" rather than "there is no label set yet".

    A raising `judge_fn` is recorded as verdict `"error"` (decision 7) —
    which can never agree with a human verdict, so it counts as a
    disagreement — and the run continues (a paid, human-labelled
    validation run must not be discarded by one transport blip).

    On `agreement >= min_agreement`, writes the validation artifact (the
    ticket's 6 keys plus `min_agreement` — decision 16) to
    `validation_path`, creating parent directories as needed. A FAILING
    validation writes no artifact — the artifact IS the "verdicts count"
    token.
    """
    assert_cross_family(generator_model, judge_model)
    if not labels:
        raise ValueError(
            "validate_judge requires at least one label (labels is empty) — "
            "evalsets/faithfulness_labels.jsonl ships example-only until the owner lands "
            "the real hand labels"
        )

    disagreements = []
    agreements = 0
    for label in labels:
        prompt = build_judge_prompt(label["question"], label["claim"], label["chunk_texts"])
        try:
            raw = judge_fn(prompt)
        except Exception:
            judge_verdict = "error"
        else:
            judge_verdict = parse_verdict(raw)["verdict"]

        if judge_verdict == label["human_verdict"]:
            agreements += 1
        else:
            disagreements.append(
                {
                    "label_id": label["label_id"],
                    "human_verdict": label["human_verdict"],
                    "judge_verdict": judge_verdict,
                }
            )

    n = len(labels)
    agreement = agreements / n
    passed = agreement >= min_agreement

    if passed:
        path = Path(validation_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "judge_model": judge_model,
            "generator_model": generator_model,
            "agreement": agreement,
            "passed": passed,
            "n": n,
            "min_agreement": min_agreement,
        }
        path.write_text(json.dumps(payload), encoding="utf-8")

    return {"agreement": agreement, "passed": passed, "n": n, "disagreements": disagreements}


# --------------------------------------------------------------------------
# AC-5 — run_faithfulness
# --------------------------------------------------------------------------

DEFAULT_INDEX_PATH = "artifacts/index"
DEFAULT_RAG_EVAL_PATH = "artifacts/rag_eval.jsonl"


def _git_sha() -> str:
    """Best-effort HEAD SHA; verbatim the mechanism already frozen for
    `onrecord.eval.run._git_sha` (decision 10)."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, timeout=10
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def _corpus_version() -> str:
    """Reads the corpus-version manifest (T-018) via `ONRECORD_INDEX`
    (falling back to `DEFAULT_INDEX_PATH`) — verbatim the mechanism already
    frozen for `onrecord.eval.run._corpus_version` (decision 10), so the
    two artifact writers never disagree about which corpus a number
    describes. Any failure falls back to `"unversioned"`, never raises."""
    index_path = os.environ.get("ONRECORD_INDEX", DEFAULT_INDEX_PATH)
    manifest = read_manifest(index_path)
    if manifest is None:
        return "unversioned"
    return manifest.get("corpus_version", "unversioned")


def _load_validation_artifact(path: Path) -> dict:
    """Read + structurally validate the validation artifact. Raises
    `JudgeNotValidated` on ANY problem (missing file, corrupt JSON, wrong
    top-level type, or a missing/mistyped required field) — never a raw
    `JSONDecodeError`/`KeyError` escaping to the caller, and never a silent
    pass on an unusable artifact."""
    if not path.exists():
        raise JudgeNotValidated(
            f"no judge validation artifact found at {path} -- run validate_judge first "
            f"(spec Sec 5: the judge's verdicts do not count until it is validated)"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JudgeNotValidated(
            f"judge validation artifact at {path} is unreadable: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise JudgeNotValidated(f"judge validation artifact at {path} is not a JSON object")
    if "passed" not in payload or not isinstance(payload["passed"], bool):
        raise JudgeNotValidated(
            f"judge validation artifact at {path} is missing a boolean 'passed' field"
        )
    if "judge_model" not in payload:
        raise JudgeNotValidated(
            f"judge validation artifact at {path} is missing the 'judge_model' field"
        )
    agreement = payload.get("agreement")
    if not isinstance(agreement, (int, float)) or isinstance(agreement, bool):
        raise JudgeNotValidated(
            f"judge validation artifact at {path} is missing a numeric 'agreement' field"
        )
    return payload


def run_faithfulness(
    answers: list[dict],
    judge_fn: Callable[[str], str],
    judge_model: str,
    generator_model: str,
    validation_path: str | Path = DEFAULT_VALIDATION_PATH,
) -> dict:
    """THE verdicts-don't-count gate (AC-5). Re-runs
    `assert_cross_family(generator_model, judge_model)` BEFORE reading the
    validation artifact or making any judge call (decision 15, closes
    test-review C-1) — the artifact alone can never license a same-family
    run at run time. Then requires a validation artifact recording
    `passed: true`, a `judge_model` matching THIS run's, and an `agreement`
    at or above the SPEC floor of `SPEC_MIN_AGREEMENT` (decision 16, closes
    review C-2 — enforced against the artifact's own recorded value, never
    the `min_agreement` the validation run happened to use). Any failure
    raises `JudgeNotValidated` and appends nothing.

    On success, judges every row in `answers` (rows:
    `{"qa_id", "question", "answer_text", "chunk_texts"}` — decision 9),
    appends `{"timestamp", "git_sha", "corpus_version", "kind":
    "faithfulness", "metrics": {"mean_faithfulness", "per_answer"}}` to
    `artifacts/rag_eval.jsonl` (append-only; never truncated), and returns
    the appended row. `mean_faithfulness` is the MEAN OF PER-ANSWER
    faithfulness (macro), not the micro total-supported/total-claims
    average.
    """
    assert_cross_family(generator_model, judge_model)

    payload = _load_validation_artifact(Path(validation_path))
    if not payload["passed"]:
        raise JudgeNotValidated(
            f"judge validation artifact at {validation_path} recorded passed=False -- "
            f"verdicts do not count until the judge passes validation"
        )
    if payload["judge_model"] != judge_model:
        raise JudgeNotValidated(
            f"judge validation artifact at {validation_path} validated judge_model="
            f"{payload['judge_model']!r}, but this run requested judge_model={judge_model!r} "
            f"-- re-validate the judge you are actually running"
        )
    if payload["agreement"] < SPEC_MIN_AGREEMENT:
        raise JudgeNotValidated(
            f"judge validation artifact at {validation_path} recorded agreement="
            f"{payload['agreement']!r}, below the spec floor of {SPEC_MIN_AGREEMENT} -- "
            f"verdicts do not count"
        )

    per_answer = []
    for row in answers:
        result = judge_answer(row["question"], row["answer_text"], row["chunk_texts"], judge_fn)
        per_answer.append(
            {
                "qa_id": row["qa_id"],
                "faithfulness": result["faithfulness"],
                "supported": result["supported"],
                "total": result["total"],
            }
        )
    mean_faithfulness = (
        sum(entry["faithfulness"] for entry in per_answer) / len(per_answer) if per_answer else 0.0
    )

    eval_row = {
        "timestamp": datetime.now(UTC).isoformat(),
        "git_sha": _git_sha(),
        "corpus_version": _corpus_version(),
        "kind": "faithfulness",
        "metrics": {"mean_faithfulness": mean_faithfulness, "per_answer": per_answer},
    }

    eval_path = Path(DEFAULT_RAG_EVAL_PATH)
    eval_path.parent.mkdir(parents=True, exist_ok=True)
    with eval_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(eval_row) + "\n")

    return eval_row


# --------------------------------------------------------------------------
# AC-7 — default_judge (OpenAI chat-completions adapter) + model plumbing
# --------------------------------------------------------------------------

# RESEARCH-REQUIRED AT PROVISIONING (ticket DoD): verify the current, live
# OpenAI model id and its pricing before this ships against a real
# OPENAI_API_KEY -- never taken from training-data memory. This placeholder
# satisfies the frozen contract (non-empty, openai-family, non-Claude) and
# keeps every frozen test (which always injects a fake judge_fn or a
# MockTransport) fully deterministic and keyless.
DEFAULT_JUDGE_MODEL = "gpt-4o-mini"

_OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
_JUDGE_MAX_RETRIES = 3  # retries beyond the initial attempt (<= 4 requests/call)
_JUDGE_BACKOFF_BASE = 0.05  # seconds; tests that don't monkeypatch time.sleep still run fast
_LIBRARY_LOGGER_NAMES = ("httpx", "httpcore", "openai")


def resolved_judge_model() -> str:
    """This module's own judge id: `ONRECORD_JUDGE_MODEL` env, else
    `DEFAULT_JUDGE_MODEL` (decision 11). Read ONLY here — `default_judge`
    consumes this resolver rather than reading the env itself a second
    time, mirroring T-023's `resolved_generator_model`."""
    env = os.environ.get("ONRECORD_JUDGE_MODEL")
    return env if env else DEFAULT_JUDGE_MODEL


@contextlib.contextmanager
def _silenced_library_loggers():
    """Silence httpx/httpcore/openai loggers for the duration of a keyed
    request (LESSONS T-014: a secret-leak check must cover library
    loggers, not just this module's own). Identical mechanism to
    `onrecord/rag/embeddings.py`'s `_silenced_library_loggers`.

    `Logger.disabled = True` makes `isEnabledFor` return False
    unconditionally regardless of level or propagation, so no log record
    is ever created for these loggers while the context is active.
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


class _OpenAIChatJudge:
    """A `judge_fn` callable posting one chat-completion request per call.

    `transport=` injects an `httpx.MockTransport` — zero live network in
    every frozen test. Retries 429/5xx with exponential backoff, bounded
    at `_JUDGE_MAX_RETRIES` beyond the initial attempt (well inside the
    MockTransport status-queue budgets the frozen suite exercises).
    """

    def __init__(self, model: str, api_key: str, transport: httpx.BaseTransport | None) -> None:
        self._model = model
        self._api_key = api_key
        self._transport = transport

    def __repr__(self) -> str:
        # Deliberately excludes the key (LESSONS T-014): a default repr
        # that embeds it would land it in every log line that
        # interpolates the judge.
        return f"_OpenAIChatJudge(model={self._model!r})"

    def __call__(self, prompt: str) -> str:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        body = {"model": self._model, "messages": [{"role": "user", "content": prompt}]}

        with _silenced_library_loggers(), httpx.Client(transport=self._transport) as client:
            for attempt in range(_JUDGE_MAX_RETRIES + 1):
                more_retries_left = attempt < _JUDGE_MAX_RETRIES
                try:
                    response = client.post(_OPENAI_CHAT_URL, headers=headers, json=body)
                except httpx.HTTPError:
                    # Never re-emit a transport error's own text verbatim
                    # -- it can carry request headers, including
                    # Authorization.
                    if more_retries_left:
                        time.sleep(_JUDGE_BACKOFF_BASE * (2**attempt))
                        continue
                    raise JudgeRequestError(
                        "judge request to OpenAI failed: transport error"
                    ) from None

                if response.status_code == 200:
                    payload = response.json()
                    return payload["choices"][0]["message"]["content"]

                if (response.status_code == 429 or response.status_code >= 500) and (
                    more_retries_left
                ):
                    time.sleep(_JUDGE_BACKOFF_BASE * (2**attempt))
                    continue

                raise JudgeRequestError(
                    f"judge request to OpenAI failed: HTTP {response.status_code}"
                )

        # Unreachable: the loop above always returns or raises.
        raise JudgeRequestError("judge request to OpenAI failed: retries exhausted")


def default_judge(
    model: str | None = None, transport: httpx.BaseTransport | None = None
) -> Callable[[str], str]:
    """The default `judge_fn` — an OpenAI chat-completions adapter
    (decision 14). `OPENAI_API_KEY` absent/blank raises `JudgeNotConfigured`
    naming the variable; never silently falls back to a fake (fakes are
    test-injected only, via `transport=`). `model` overrides
    `resolved_judge_model()` when given.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or not str(api_key).strip():
        raise JudgeNotConfigured(
            "OPENAI_API_KEY is not set -- set the OPENAI_API_KEY environment variable to "
            "configure the faithfulness judge"
        )
    resolved_model = model if model is not None else resolved_judge_model()
    return _OpenAIChatJudge(resolved_model, api_key, transport)


# --------------------------------------------------------------------------
# CLI — main() and its two lazy seams (decision 12)
# --------------------------------------------------------------------------


def _resolve_generator_model() -> str:
    """Lazy seam (decision 12): imports T-023's `resolved_generator_model`
    INSIDE the function body so `onrecord.rag.judge` stays importable with
    no T-023 present (T-023 is same-wave and unmerged during this ticket's
    implementation — a module-level import would be a collection error in
    the wave-9 worktree). `main()` uses this seam rather than any env
    lookup of its own (plan-review I-8, one source of truth)."""
    from onrecord.rag.answer import resolved_generator_model

    return resolved_generator_model()


DEFAULT_QA_PATH = "evalsets/qa.jsonl"
DEFAULT_CORPUS_SNAPSHOT = "corpus/v1/corpus.jsonl.gz"


def _resolve_answers() -> list[dict]:
    """The real answers pipeline for `main()` — the second documented LAZY
    seam (decision 12, same mechanism/justification as T-025's
    `_resolve_answer_fn`, plan-review I-9). T-022 (retrieval), T-023
    (generation) and T-025 (the QA set + loader) are all same-wave and
    unmerged during this ticket's implementation, so every import lives
    inside this function body.

    Composes them into the `run_faithfulness` answers-row shape
    (decision 9): loads `evalsets/qa.jsonl` (T-025's `load_qa`), retrieves
    chunks per question via the real hybrid pipeline (T-022's
    `hybrid_search` over a chunked corpus snapshot + embedding store), and
    generates a real answer via T-023's `answer()` / `default_generator()`.
    Untestable in this ticket — mirrors the
    `onrecord.eval.run._real_pipeline_retrieve` precedent — exercised only
    post-wave-9-merge and post-provisioning by the orchestrator's eval run;
    every test that reaches `main()` monkeypatches this seam directly.
    """
    from onrecord.index.inverted import InvertedIndex
    from onrecord.ingest.build_corpus import load_corpus_snapshot
    from onrecord.rag.answer import answer, default_generator
    from onrecord.rag.chunking import chunk_corpus
    from onrecord.rag.embeddings import EmbeddingStore, get_provider
    from onrecord.rag.qa_eval import load_qa
    from onrecord.rag.retrieve import hybrid_search

    index = InvertedIndex.load(os.environ.get("ONRECORD_INDEX", DEFAULT_INDEX_PATH))
    docs = load_corpus_snapshot(os.environ.get("ONRECORD_CORPUS_SNAPSHOT", DEFAULT_CORPUS_SNAPSHOT))
    chunks = chunk_corpus(docs)
    provider = get_provider()
    store = EmbeddingStore.load(
        os.environ.get("ONRECORD_EMBED_STORE", f"artifacts/embeddings/{provider.model}")
    )
    generate_fn = default_generator()

    rows = []
    for qa_row in load_qa(os.environ.get("ONRECORD_QA_PATH", DEFAULT_QA_PATH)):
        results = hybrid_search(index, store, chunks, qa_row["question"], provider)
        cited_ids = {result.doc_id for result in results}
        result_chunks = [chunk for chunk in chunks if chunk.chunk_id in cited_ids]
        generated = answer(qa_row["question"], result_chunks, generate_fn)
        rows.append(
            {
                "qa_id": qa_row["qa_id"],
                "question": qa_row["question"],
                "answer_text": generated["text"],
                "chunk_texts": [chunk.text for chunk in result_chunks],
            }
        )
    return rows


def main() -> int:
    """CLI entrypoint: resolve the generator id via the lazy seam, the
    judge id via `resolved_judge_model()`, real answers via the lazy
    `_resolve_answers()` seam, and run the verdicts-don't-count gate."""
    generator_model = _resolve_generator_model()
    judge_model = resolved_judge_model()
    try:
        judge_fn = default_judge()
        answers = _resolve_answers()
        row = run_faithfulness(answers, judge_fn, judge_model, generator_model)
    except (JudgeNotConfigured, JudgeNotValidated, CrossFamilyViolation) as exc:
        sys.stderr.write(f"onrecord.rag.judge: {exc}\n")
        return 1
    sys.stdout.write(json.dumps(row) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

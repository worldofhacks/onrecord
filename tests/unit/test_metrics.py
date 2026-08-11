"""Failing tests for T-005 — IR-metrics harness (precision@k, recall@k, MRR, NDCG)
plus the `onrecord.eval.run` runner.

Encodes tickets/T-005.md AC-1..AC-5. Frozen after the Test Agent hands off: do
not edit this file to make an implementation pass — fix the implementation
(onrecord/eval/metrics.py, onrecord/eval/run.py) instead. `NotImplementedError`
(metrics.py stubs) and `AttributeError` (run.py's `run` does not exist yet) are
the CORRECT failure signatures tonight — that is the RED state this ticket is
built to produce.

Run with:
    uv run pytest tests/unit/test_metrics.py -v

## Metric conventions (ticket text + this file's necessary tie-breaks)

- Binary relevance (precision/recall/MRR): a doc id counts as relevant iff
  `relevant.get(doc_id, 0) >= 1`. A doc id missing from `relevant` entirely is
  therefore indistinguishable from one present with grade 0 — both
  non-relevant. (Duplicate doc ids inside `relevant` are impossible by
  construction since it is a `dict`; no test for that.)
- Graded relevance (NDCG): gain at rank i (1-indexed) is the raw grade
  (0/1/2), discount is `log2(i+1)`. `DCG@k = sum(rel_i / log2(i+1) for i in
  1..min(k, len(ranked)))`. `IDCG@k` is the DCG of the top-k of `relevant`'s
  grades sorted descending (grade-0 entries never affect the ideal ordering's
  DCG regardless of position). `NDCG@k = DCG@k / IDCG@k`, defined as `0.0`
  when `IDCG@k == 0` (no positive-grade doc in `relevant`) — ticket-specified.
- AC-4 ("k beyond result list length ... missing ranks as non-relevant"):
  for `precision_at_k`, the denominator stays `k` even when `k > len(ranked)`
  — positions past the end of `ranked` are non-relevant padding, they do not
  shrink the denominator to `len(ranked)`. `ranked[:k]` is always a safe
  no-op slice for `k` beyond the list, so no metric raises for this case.
- k=0 guard (Test-Agent-pinned; not explicit in the ticket): `precision_at_k`,
  `recall_at_k`, and `ndcg_at_k` (the three `k`-taking functions; `mrr` takes
  no `k`) must not raise `ZeroDivisionError` for `k=0` — by convention they
  return `0.0` ("no items considered" is vacuously non-relevant/no gain).
  For `ndcg_at_k` this already falls out of the `IDCG=0.0 -> NDCG=0.0` rule
  above (`IDCG@0` is trivially the empty-sum `0.0`), so it needs no separate
  mechanism, only a test confirming it.
- `recall_at_k` zero-total-relevant convention (Test-Agent-pinned): if
  `relevant` contains no entry with grade >= 1 (including an empty dict),
  `recall_at_k` returns `0.0` rather than raising `ZeroDivisionError`
  (mirrors the NDCG "0 when the ideal is 0" rule).

## `onrecord.eval.run.run` injection contract (Test-Agent-pinned per the
## orchestrator's ISOLATION RULE — `onrecord/eval/run.py` is this ticket's
## scope but its `run()` signature was not frozen by T-001, only `metrics.py`
## was, so this is fixed here, the same way T-001's Test Agent fixed the
## un-pinned `registry.yaml` schema)

```python
def run(
    judgments_path: str | Path,
    retrieve_fn: Callable[[str], list[str]] | None = None,
    history_path: str | Path = "artifacts/scoreboard.jsonl",
    k_values: dict[str, list[int]] | None = None,
) -> int: ...
```

- `judgments_path`: a JSONL file, one row per (query, doc) judgment:
  `{query_id, query, criterion, doc_id, grade}`. Rows sharing a `query_id`
  are grouped into that query's `relevant: dict[doc_id, grade]`.
- `retrieve_fn(query: str) -> list[str]`: called once per unique query, with
  the judgment row's `query` text field (not `query_id`), to obtain a ranked
  doc-id list for that query. `None` means the real boolean-retrieval
  pipeline — untestable in this ticket, covered by Wave-3 T-010.
- `history_path`: a JSONL file; on a successful metrics computation (i.e.
  `judgments_path` was loadable) exactly one row
  `{timestamp, git_sha, corpus_version, metrics}` is appended. Not written to
  when `judgments_path` is missing.
- `k_values`: optional override of which `k`s are scored per metric; when
  `None`, the ticket-mandated default set is used (P@5, P@10, R@10, R@50,
  MRR, NDCG@10 — the exact metrics named in tickets/T-005.md's Context).
  Both omitting the kwarg and passing `k_values=None` explicitly must work.
- Return value (an `int`; `run()` does not call `sys.exit` itself — `main()`
  is expected to do `return run(...)`, and the module's existing
  `if __name__ == "__main__": sys.exit(main())` footer forwards that to the
  process exit code):
  - `0` if mean NDCG@10 across queries is `>= 0.5`
  - `1` if mean NDCG@10 across queries is `< 0.5` (the red gate; this is the
    expected outcome of the real, un-injected pipeline tonight, but the gate
    logic itself must be a real function of the computed metrics — an
    always-return-1 shortcut is a gate-weakening anti-pattern the exit-0 test
    below exists to catch)
  - `2` if `judgments_path` does not exist, after writing a clear message
    naming the missing file to stderr
- Prints a human-readable scoreboard to stdout: per-query rows keyed by
  `query_id` carrying all six metric labels (`P@5`, `P@10`, `R@10`, `R@50`,
  `MRR`, `NDCG@10` — verbatim tokens from the ticket text), plus a means
  section/row using those same labels.
- `metrics` (the history row's 4th key) is pinned to
  `{"per_query": {query_id: {label: float, ...}, ...}, "mean": {label: float,
  ...}}`, keyed by the same six literal metric-label tokens as the
  scoreboard. This is Test-Agent-pinned (post-review hardening, see
  `.tdd-swarm/reports/T-005-testreview.md`): an unstructured/unverified
  `metrics` blob let a hardcoded-zero scoreboard and a globally-merged (not
  per-`query_id`) relevance dict both pass silently — both are now caught by
  asserting hand-computed values straight out of this dict.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from pathlib import Path

import pytest

import onrecord.eval.run as evalrun
from onrecord.eval.metrics import mrr, ndcg_at_k, precision_at_k, recall_at_k

# --------------------------------------------------------------------------
# AC-1 — precision@k / recall@k
# --------------------------------------------------------------------------


def test_precision_at_2_is_one_half():
    # spec(T-005:AC-1)
    ranked = ["a", "b", "c", "d"]
    relevant = {"a": 1, "c": 2, "x": 1}
    assert precision_at_k(ranked, relevant, 2) == pytest.approx(0.5)


def test_recall_at_2_is_one_third():
    # spec(T-005:AC-1)
    ranked = ["a", "b", "c", "d"]
    relevant = {"a": 1, "c": 2, "x": 1}
    assert recall_at_k(ranked, relevant, 2) == pytest.approx(1 / 3)


def test_precision_recall_binary_threshold_grade_zero_is_nonrelevant():
    # spec(T-005:AC-1) -- grade 0 present in `relevant` must NOT count as
    # relevant for precision/recall (binary relevance = grade >= 1)
    ranked = ["a", "b"]
    relevant = {"a": 0, "b": 1}
    assert precision_at_k(ranked, relevant, 2) == pytest.approx(0.5)
    assert recall_at_k(ranked, relevant, 2) == pytest.approx(1.0)


def test_precision_recall_doc_absent_from_relevant_dict_is_nonrelevant():
    # spec(T-005:AC-1) -- a ranked doc id with no key at all in `relevant`
    # is treated identically to one present with grade 0
    ranked = ["a", "zzz"]
    relevant = {"a": 1}
    assert precision_at_k(ranked, relevant, 2) == pytest.approx(0.5)
    assert recall_at_k(ranked, relevant, 2) == pytest.approx(1.0)


# --------------------------------------------------------------------------
# AC-2 — MRR
# --------------------------------------------------------------------------


def test_mrr_first_relevant_at_rank_three_is_one_third():
    # spec(T-005:AC-2)
    ranked = ["n1", "n2", "d3", "n4"]
    relevant = {"d3": 1}
    assert mrr(ranked, relevant) == pytest.approx(1 / 3)


def test_mrr_no_relevant_in_ranking_is_zero():
    # spec(T-005:AC-2)
    ranked = ["n1", "n2"]
    relevant = {"z9": 1}
    assert mrr(ranked, relevant) == pytest.approx(0.0)


def test_mrr_first_relevant_at_rank_one_is_one():
    # spec(T-005:AC-2)
    ranked = ["r1", "n2", "n3"]
    relevant = {"r1": 2}
    assert mrr(ranked, relevant) == pytest.approx(1.0)


def test_mrr_binary_threshold_grade_zero_is_nonrelevant():
    # spec(T-005:AC-2) -- grade 0 present in `relevant` is skipped when
    # finding the first relevant rank
    ranked = ["g0", "g1"]
    relevant = {"g0": 0, "g1": 1}
    assert mrr(ranked, relevant) == pytest.approx(0.5)


# --------------------------------------------------------------------------
# AC-3 — NDCG@k
# --------------------------------------------------------------------------


def test_ndcg_at_2_ideal_order_is_one():
    # spec(T-005:AC-3) -- ranked==ideal order (grades sorted desc: c=2, a=1),
    # so DCG@2/IDCG@2 collapses to the literal ticket value 1.0
    ranked = ["c", "a"]
    relevant = {"a": 1, "c": 2}
    assert ndcg_at_k(ranked, relevant, 2) == pytest.approx(1.0)


def test_ndcg_at_2_reversed_order_is_less_than_one():
    # spec(T-005:AC-3)
    ranked = ["a", "c"]  # reversed vs. the ideal [c, a]
    relevant = {"a": 1, "c": 2}
    idcg = 2 / math.log2(2) + 1 / math.log2(3)
    dcg = 1 / math.log2(2) + 2 / math.log2(3)
    expected = dcg / idcg
    result = ndcg_at_k(ranked, relevant, 2)
    assert result == pytest.approx(expected)
    assert result < 1.0


# --------------------------------------------------------------------------
# AC-4 — k larger than the ranked list: no exception, missing ranks are
# treated as non-relevant / zero gain
# --------------------------------------------------------------------------


def test_precision_recall_k_beyond_ranked_list_length_no_exception():
    # spec(T-005:AC-4)
    ranked = ["a", "b"]
    relevant = {"a": 1, "b": 0, "c": 1}
    k = 5
    # found relevant among ranked[:5] == ranked == ["a","b"]: only "a" (grade
    # 1) counts; denominator stays k=5, not len(ranked)=2
    assert precision_at_k(ranked, relevant, k) == pytest.approx(0.2)
    # total relevant (grade>=1) across `relevant` = {"a","c"} = 2; found = 1
    assert recall_at_k(ranked, relevant, k) == pytest.approx(0.5)


def test_mrr_k_beyond_ranked_list_length_is_not_applicable_but_no_exception():
    # spec(T-005:AC-4) -- mrr takes no k, but confirms a short ranked list
    # relative to a larger relevant set does not raise
    ranked = ["a"]
    relevant = {"a": 1, "b": 1, "c": 1}
    assert mrr(ranked, relevant) == pytest.approx(1.0)


def test_ndcg_k_beyond_ranked_list_length_no_exception():
    # spec(T-005:AC-4)
    ranked = ["p", "q"]  # only 2 docs, but k=5
    relevant = {"p": 2, "q": 0, "r": 1}  # "r" never appears in `ranked`
    k = 5
    dcg = 2 / math.log2(2) + 0 / math.log2(3)  # ranks 3-5 pad with 0 gain
    idcg = 2 / math.log2(2) + 1 / math.log2(3)  # ideal: p(2), r(1); q(0) inert
    assert ndcg_at_k(ranked, relevant, k) == pytest.approx(dcg / idcg)


# --------------------------------------------------------------------------
# Empty ranked list edge case
# --------------------------------------------------------------------------


def test_precision_recall_mrr_ndcg_empty_ranked_list():
    # spec(T-005:AC-4) -- empty ranking must not raise; treated as all-miss
    relevant = {"a": 1}
    assert precision_at_k([], relevant, 3) == pytest.approx(0.0)
    assert recall_at_k([], relevant, 3) == pytest.approx(0.0)
    assert mrr([], relevant) == pytest.approx(0.0)
    assert ndcg_at_k([], relevant, 3) == pytest.approx(0.0)


# --------------------------------------------------------------------------
# k=0 guard
# --------------------------------------------------------------------------


def test_precision_recall_ndcg_k_zero_guard():
    # spec(T-005:AC-4) -- k=0 must not raise ZeroDivisionError; returns 0.0
    ranked = ["a", "b"]
    relevant = {"a": 1, "b": 1}
    assert precision_at_k(ranked, relevant, 0) == pytest.approx(0.0)
    assert recall_at_k(ranked, relevant, 0) == pytest.approx(0.0)
    assert ndcg_at_k(ranked, relevant, 0) == pytest.approx(0.0)


# --------------------------------------------------------------------------
# NDCG = 0 when IDCG = 0 (no positive-grade doc in `relevant`)
# --------------------------------------------------------------------------


def test_ndcg_zero_when_no_relevant_docs_judged_at_all():
    # spec(T-005:AC-3)
    assert ndcg_at_k(["a", "b"], {}, 5) == pytest.approx(0.0)


def test_ndcg_zero_when_all_judged_grades_are_zero():
    # spec(T-005:AC-3)
    assert ndcg_at_k(["a", "b"], {"a": 0, "b": 0}, 5) == pytest.approx(0.0)


def test_recall_zero_when_no_relevant_docs_judged_at_all():
    # spec(T-005:AC-1) -- mirrors the NDCG "0 when ideal is 0" convention
    assert recall_at_k(["a", "b"], {}, 5) == pytest.approx(0.0)
    assert recall_at_k(["a", "b"], {"a": 0, "b": 0}, 5) == pytest.approx(0.0)


# ==========================================================================
# AC-5 — `onrecord.eval.run.run` (dependency-injected runner)
#
# `evalrun.run` is accessed as an attribute (never `from onrecord.eval.run
# import run` at module scope) because `run` does not exist on the frozen
# stub yet — a top-level `from ... import run` would raise ImportError at
# collection time and take down every other test in this file with it.
# Accessing it lazily inside each test body means the (currently correct)
# AttributeError is a normal, isolated per-test failure instead.
#
# The fixture has THREE queries (q1/q2 all-hit, q3 all-miss under the "good"
# retriever) deliberately, not two: with only two identical-NDCG queries,
# mean/max/min/first-query aggregation are indistinguishable, so a runner
# that aggregates the wrong way (or ignores `query_id` grouping and scores
# every query against one globally-merged relevance dict) still passes. Three
# queries with different outcomes (1.0, 1.0, 0.0 -> mean 2/3) make `mean`
# the only aggregate that satisfies the hand-computed assertions below.
# ==========================================================================


def _write_judgments(path: Path, rows: list[dict]) -> None:
    with path.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


_JUDGMENT_ROWS = [
    {"query_id": "q1", "query": "alpha", "criterion": "mentions alpha", "doc_id": "d1", "grade": 2},
    {"query_id": "q1", "query": "alpha", "criterion": "mentions alpha", "doc_id": "d2", "grade": 1},
    {"query_id": "q1", "query": "alpha", "criterion": "mentions alpha", "doc_id": "d3", "grade": 0},
    {"query_id": "q2", "query": "beta", "criterion": "mentions beta", "doc_id": "e1", "grade": 1},
    {"query_id": "q2", "query": "beta", "criterion": "mentions beta", "doc_id": "e2", "grade": 2},
    {"query_id": "q3", "query": "gamma", "criterion": "mentions gamma", "doc_id": "f1", "grade": 2},
    {"query_id": "q3", "query": "gamma", "criterion": "mentions gamma", "doc_id": "f2", "grade": 1},
]


def _fake_retrieve_bad(query: str) -> list[str]:
    """Returns doc ids that never appear in the judgments -> NDCG@10 == 0."""
    return ["zzz1", "zzz2", "zzz3"]


def _fake_retrieve_good(query: str) -> list[str]:
    """q1/q2: ideal (grade-descending) order -> NDCG@10 == 1.0 each.
    q3: a doc that was never judged -> NDCG@10 == 0.0. Mean NDCG@10 == 2/3.
    """
    return {
        "alpha": ["d1", "d2", "d3"],
        "beta": ["e2", "e1"],
        "gamma": ["zzz9"],
    }[query]


@pytest.fixture
def judgments_file(tmp_path: Path) -> Path:
    path = tmp_path / "judgments.jsonl"
    _write_judgments(path, _JUDGMENT_ROWS)
    return path


def test_run_scoreboard_prints_all_metrics_per_query_and_means(judgments_file, tmp_path, capsys):
    # spec(T-005:AC-5)
    history_path = tmp_path / "scoreboard.jsonl"
    exit_code = evalrun.run(
        judgments_file,
        retrieve_fn=_fake_retrieve_good,
        history_path=history_path,
    )
    out = capsys.readouterr().out

    assert "q1" in out, f"scoreboard missing query_id 'q1':\n{out}"
    assert "q2" in out, f"scoreboard missing query_id 'q2':\n{out}"
    assert "q3" in out, f"scoreboard missing query_id 'q3':\n{out}"
    for label in ("P@5", "P@10", "R@10", "R@50", "MRR", "NDCG@10"):
        assert label in out, f"scoreboard missing metric label {label!r}:\n{out}"
    assert "mean" in out.lower(), f"scoreboard missing a means row/section:\n{out}"

    assert exit_code == 0


def test_run_appends_history_row_with_git_sha_and_corpus_version(judgments_file, tmp_path):
    # spec(T-005:AC-5)
    history_path = tmp_path / "scoreboard.jsonl"
    evalrun.run(
        judgments_file,
        retrieve_fn=_fake_retrieve_good,
        history_path=history_path,
        k_values=None,
    )

    assert history_path.exists(), "history_path was not created"
    lines = [line for line in history_path.read_text().splitlines() if line.strip()]
    assert lines, "history_path has no rows appended"
    row = json.loads(lines[-1])

    for key in ("timestamp", "git_sha", "corpus_version", "metrics"):
        assert key in row, f"history row missing key {key!r}: {row}"

    assert isinstance(row["git_sha"], str) and re.fullmatch(r"[0-9a-fA-F]{7,40}", row["git_sha"]), (
        f"git_sha does not look like a real git SHA: {row['git_sha']!r}"
    )
    assert isinstance(row["metrics"], dict) and row["metrics"], "metrics must be a non-empty object"


def test_run_history_row_has_hand_computed_per_query_and_mean_metrics(judgments_file, tmp_path):
    # spec(T-005:AC-5) -- post-review hardening (I-1/I-2): pins real numbers,
    # not just key presence, so a hardcoded-zero scoreboard AND a runner that
    # scores every query against one globally-merged relevance dict (instead
    # of grouping judgments by query_id) both fail. q1: ranked=[d1,d2,d3] vs
    # {d1:2,d2:1,d3:0} -- top-10 slice is the whole (3-doc) list, 2 of the 3
    # are relevant (grade>=1): P@5=2/5=0.4, P@10=2/10=0.2, R@10=R@50=2/2=1.0,
    # first relevant at rank 1 -> MRR=1.0, ranked==ideal order -> NDCG@10=1.0.
    # q2 is symmetric (also 2/2 relevant, ideal order) -> identical numbers.
    # q3: ranked=["zzz9"], a doc never judged, vs {f1:2,f2:1} -- 0 found ->
    # P@5=P@10=R@10=R@50=MRR=NDCG@10=0.0. Mean over the three queries:
    # P@5=0.8/3=4/15, P@10=0.4/3=2/15, R@10=R@50=MRR=NDCG@10=2/3.
    history_path = tmp_path / "scoreboard.jsonl"
    evalrun.run(judgments_file, retrieve_fn=_fake_retrieve_good, history_path=history_path)

    row = json.loads(history_path.read_text().splitlines()[-1])
    per_query = row["metrics"]["per_query"]
    mean = row["metrics"]["mean"]

    for qid in ("q1", "q2"):
        pq = per_query[qid]
        assert pq["P@5"] == pytest.approx(0.4), f"{qid} P@5: {pq}"
        assert pq["P@10"] == pytest.approx(0.2), f"{qid} P@10: {pq}"
        assert pq["R@10"] == pytest.approx(1.0), f"{qid} R@10: {pq}"
        assert pq["R@50"] == pytest.approx(1.0), f"{qid} R@50: {pq}"
        assert pq["MRR"] == pytest.approx(1.0), f"{qid} MRR: {pq}"
        assert pq["NDCG@10"] == pytest.approx(1.0), f"{qid} NDCG@10: {pq}"

    q3 = per_query["q3"]
    assert q3["P@5"] == pytest.approx(0.0), f"q3 P@5: {q3}"
    assert q3["P@10"] == pytest.approx(0.0), f"q3 P@10: {q3}"
    assert q3["R@10"] == pytest.approx(0.0), f"q3 R@10: {q3}"
    assert q3["R@50"] == pytest.approx(0.0), f"q3 R@50: {q3}"
    assert q3["MRR"] == pytest.approx(0.0), f"q3 MRR: {q3}"
    assert q3["NDCG@10"] == pytest.approx(0.0), f"q3 NDCG@10: {q3}"

    assert mean["P@5"] == pytest.approx(4 / 15), f"mean P@5: {mean}"
    assert mean["P@10"] == pytest.approx(2 / 15), f"mean P@10: {mean}"
    assert mean["R@10"] == pytest.approx(2 / 3), f"mean R@10: {mean}"
    assert mean["R@50"] == pytest.approx(2 / 3), f"mean R@50: {mean}"
    assert mean["MRR"] == pytest.approx(2 / 3), f"mean MRR: {mean}"
    assert mean["NDCG@10"] == pytest.approx(2 / 3), f"mean NDCG@10: {mean}"


def test_run_appends_second_row_without_truncating_first(judgments_file, tmp_path):
    # spec(T-005:AC-5) -- post-review hardening (I-4): the ticket and design
    # spec both call this an *append*-only history file; a writer that opens
    # history_path with "w" (truncating) instead of "a" must fail here.
    history_path = tmp_path / "scoreboard.jsonl"

    evalrun.run(judgments_file, retrieve_fn=_fake_retrieve_bad, history_path=history_path)
    first_lines = [line for line in history_path.read_text().splitlines() if line.strip()]
    assert len(first_lines) == 1, f"expected 1 row after the first run(), got {len(first_lines)}"
    first_row = json.loads(first_lines[0])

    evalrun.run(judgments_file, retrieve_fn=_fake_retrieve_good, history_path=history_path)
    lines = [line for line in history_path.read_text().splitlines() if line.strip()]
    assert len(lines) == 2, f"expected 2 rows after a second run(), got {len(lines)}: {lines}"
    assert json.loads(lines[0]) == first_row, (
        "the first history row must survive a second run() call unchanged"
    )


def test_run_exits_1_when_mean_ndcg_at_10_below_half_red_gate(judgments_file, tmp_path):
    # spec(T-005:AC-5) -- RED tonight by design: a retrieve_fn that never
    # surfaces a judged doc drives mean NDCG@10 to 0.0 (< 0.5)
    history_path = tmp_path / "scoreboard.jsonl"
    exit_code = evalrun.run(
        judgments_file,
        retrieve_fn=_fake_retrieve_bad,
        history_path=history_path,
    )
    assert exit_code == 1


def test_run_exits_0_when_mean_ndcg_at_10_meets_threshold(judgments_file, tmp_path):
    # spec(T-005:AC-5) -- guards against a gate-weakening shortcut that
    # hardcodes exit 1 regardless of the actual computed metrics: a
    # retrieve_fn returning the ideal ranking must earn exit 0
    history_path = tmp_path / "scoreboard.jsonl"
    exit_code = evalrun.run(
        judgments_file,
        retrieve_fn=_fake_retrieve_good,
        history_path=history_path,
    )
    assert exit_code == 0


def test_run_exit_code_boundary_mean_ndcg_exactly_half_is_green(tmp_path):
    # spec(T-005:AC-5) -- post-review hardening (m-5): the ticket says "exit
    # 1 if mean NDCG@10 < 0.5", so exactly 0.5 must NOT trigger the red gate.
    # Two single-doc queries, one hit (NDCG@10=1.0) and one miss (0.0), give
    # a mean of exactly 0.5.
    judgments_path = tmp_path / "boundary_judgments.jsonl"
    _write_judgments(
        judgments_path,
        [
            {"query_id": "b1", "query": "one", "criterion": "c", "doc_id": "x1", "grade": 1},
            {"query_id": "b2", "query": "two", "criterion": "c", "doc_id": "x2", "grade": 1},
        ],
    )

    def boundary_retrieve(query: str) -> list[str]:
        return {"one": ["x1"], "two": ["nomatch"]}[query]

    history_path = tmp_path / "scoreboard.jsonl"
    exit_code = evalrun.run(
        judgments_path, retrieve_fn=boundary_retrieve, history_path=history_path
    )
    assert exit_code == 0


def test_run_exits_2_with_clear_message_when_judgments_file_missing(tmp_path, capsys):
    # spec(T-005:AC-5)
    missing = tmp_path / "does_not_exist.jsonl"
    history_path = tmp_path / "scoreboard.jsonl"

    exit_code = evalrun.run(
        missing,
        retrieve_fn=_fake_retrieve_good,
        history_path=history_path,
    )

    assert exit_code == 2
    err = capsys.readouterr().err.lower()
    assert "judgments" in err, f"stderr does not mention the judgments file:\n{err}"
    assert str(missing) in err or "not found" in err or "missing" in err, (
        f"stderr does not clearly say the file is missing:\n{err}"
    )
    assert not history_path.exists(), (
        "history_path should not be written to when judgments_path is missing"
    )


def test_main_delegates_to_run_and_forwards_its_exit_code(monkeypatch):
    # spec(T-005:AC-5) -- post-review hardening (I-5): AC-5's literal subject
    # is `python -m onrecord.eval.run` / `main()`, which the rest of this
    # file never exercises (it only calls the injectable `run()` directly).
    # Pins `main()` as a real delegation to `run()` -- today's stub
    # (`main()` just writes "not implemented" and returns 1, ignoring `run`
    # entirely) must fail this.
    sentinel = 7
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return sentinel

    monkeypatch.setattr(evalrun, "run", fake_run)
    result = evalrun.main()

    assert calls, "main() must call run() (module-level onrecord.eval.run.run)"
    assert result == sentinel, "main() must return run()'s exit code, not a hardcoded value"


def test_main_entrypoint_exits_2_when_default_judgments_file_missing(tmp_path):
    # spec(T-005:AC-5) -- post-review hardening (I-5): a hermetic smoke test
    # of the literal `python -m onrecord.eval.run` entry point AC-5 names.
    # Run with cwd=tmp_path (no evalsets/judgments.jsonl present anywhere
    # under it) so the default judgments path can't resolve -- must exit 2,
    # exactly like the direct run() call in
    # test_run_exits_2_with_clear_message_when_judgments_file_missing.
    result = subprocess.run(
        [sys.executable, "-m", "onrecord.eval.run"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2, (
        f"'python -m onrecord.eval.run' with no default judgments file present "
        f"should exit 2, got {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "judgments" in result.stderr.lower(), (
        f"stderr does not mention the missing judgments file:\n{result.stderr}"
    )

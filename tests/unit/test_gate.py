"""Tests for T-047 — the deployed-scope retrieval gate (additive; the
legacy lexical gate in onrecord/eval/run.py is untouched and stays frozen)."""

import json

from onrecord.eval.gate import THRESHOLD, latest_mode_ndcg, main


def _history(tmp_path, rows):
    path = tmp_path / "modes.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return path


def _row(mode, ndcg):
    return {"mode": mode, "corpus_version": "v2",
            "metrics": {"mean": {"NDCG@10": ndcg}}}


def test_latest_rows_win_and_threshold_is_half():
    assert THRESHOLD == 0.5


def test_gate_passes_when_best_deployed_mode_clears(tmp_path, capsys):
    path = _history(tmp_path, [
        _row("lexical", 0.449), _row("semantic", 0.538), _row("hybrid", 0.431),
    ])
    assert main(path) == 0
    out = capsys.readouterr().out
    assert "PASS" in out and "semantic" in out


def test_gate_fails_when_no_mode_clears(tmp_path, capsys):
    path = _history(tmp_path, [
        _row("lexical", 0.30), _row("semantic", 0.45), _row("hybrid", 0.40),
    ])
    assert main(path) == 1
    assert "FAIL" in capsys.readouterr().out


def test_gate_uses_latest_row_per_mode(tmp_path):
    path = _history(tmp_path, [
        _row("semantic", 0.20), _row("semantic", 0.60),
    ])
    assert latest_mode_ndcg(path) == {"semantic": 0.60}
    assert main(path) == 0


def test_gate_missing_history_is_exit_2_never_a_silent_pass(tmp_path, capsys):
    assert main(tmp_path / "absent.jsonl") == 2
    assert "no modes history" in capsys.readouterr().err

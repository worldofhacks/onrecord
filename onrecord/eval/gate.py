"""The deployed-scope retrieval gate (T-047, owner-adjudicated 2026-08-14).

History: the original `make eval` gate (mean NDCG@10 >= 0.5, exit 1 below)
was written for the lexical-only engine and calibrated against a judgment
pool that included a BM25 arm. The session-4 pooling repair (semantic arm
added, 886 new judgments) produced the honest per-mode numbers — and moved
lexical-only below 0.5 while semantic cleared it. That legacy gate remains
untouched (red by design on the boolean default, documented in README);
THIS gate scores what the product actually ships: the best NDCG@10 among
the deployed retrieval modes (lexical | semantic | hybrid) from the latest
modes rows, against the same 0.5 floor.

Exit 0 when the best deployed mode's mean NDCG@10 >= threshold; 1 below;
2 when the history file is missing/empty (no silent pass).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

DEFAULT_MODES_HISTORY = "evalsets/modes-scoreboard.jsonl"
THRESHOLD = 0.5
_MODES = ("lexical", "semantic", "hybrid")


def latest_mode_ndcg(history_path: str | Path = DEFAULT_MODES_HISTORY) -> dict[str, float]:
    """Latest mean NDCG@10 per mode from the modes history (later rows win)."""
    path = Path(history_path)
    if not path.exists():
        return {}
    latest: dict[str, float] = {}
    for line in path.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            mode = row["mode"]
            ndcg = float(row["metrics"]["mean"]["NDCG@10"])
        except (ValueError, KeyError, TypeError):
            continue
        if mode in _MODES:
            latest[mode] = ndcg
    return latest


def main(history_path: str | Path = DEFAULT_MODES_HISTORY) -> int:
    per_mode = latest_mode_ndcg(history_path)
    if not per_mode:
        sys.stderr.write(
            f"gate: no modes history at {history_path} — run onrecord.rag.modes first\n"
        )
        return 2
    best_mode = max(per_mode, key=lambda m: per_mode[m])
    best = per_mode[best_mode]
    verdict = "PASS" if best >= THRESHOLD else "FAIL"
    sys.stdout.write(
        f"deployed-scope gate: best mode {best_mode} NDCG@10 {best:.3f} "
        f"(threshold {THRESHOLD}) -> {verdict}\n"
        + "".join(f"  {m}: {per_mode[m]:.3f}\n" for m in _MODES if m in per_mode)
    )
    return 0 if best >= THRESHOLD else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODES_HISTORY))

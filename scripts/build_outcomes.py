"""Operational lane for T-057: build artifacts/promise_outcomes.json.

Wires TESTED functions only (build_outcomes); run via `make refresh-outcomes`.
Entity-echo terms arrive with T-058's alias table — v1 passes none.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from onrecord.analysis.outcomes import build_outcomes
from onrecord.ingest.build_corpus import load_corpus_snapshot

promises = [
    json.loads(line)
    for line in open("evalsets/promises.jsonl", encoding="utf-8")
    if line.strip()
]
docs = load_corpus_snapshot("corpus/v2/corpus.jsonl.gz")
outcomes = build_outcomes(promises, docs, today=datetime.now(UTC).date().isoformat())
out = Path("artifacts/promise_outcomes.json")
out.parent.mkdir(parents=True, exist_ok=True)
statuses: dict[str, int] = {}
for o in outcomes.values():
    statuses[o["status"]] = statuses.get(o["status"], 0) + 1
out.write_text(json.dumps({
    "generated_at": datetime.now(UTC).isoformat(timespec="minutes"),
    "corpus": "corpus/v2/corpus.jsonl.gz",
    "statuses": statuses,
    "outcomes": outcomes,
}, indent=None) + "\n", encoding="utf-8")
print(f"wrote {out}: {statuses}")

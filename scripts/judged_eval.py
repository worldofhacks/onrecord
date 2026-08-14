#!/usr/bin/env python3
"""T-042: the judged-eval headline run (repo-canonical; run with
`uv run python scripts/judged_eval.py` — needs both API keys + artifacts).
Deployed retrieval config (hybrid,
fusion_depth=2000, k=8), claude generation, validated gpt-5-mini judge.

- qa.jsonl (answerable): generate -> judge every claim -> per-answer
  faithfulness + mean; false-refusal rate (refusals on answerable).
- unanswerable.jsonl: generate -> refusal correctness rate.
Output: evalsets/judged-eval-2026-08-14.json
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os

os.chdir(Path(__file__).resolve().parents[1])

from onrecord.index.inverted import InvertedIndex  # noqa: E402
from onrecord.rag.answer import answer, default_generator, resolved_generator_model  # noqa: E402
from onrecord.rag.embeddings import EmbeddingStore, get_provider  # noqa: E402
from onrecord.rag.judge import DEFAULT_JUDGE_MODEL, default_judge, judge_answer  # noqa: E402
from onrecord.rag.modes import _load_identity_chunks  # noqa: E402
from onrecord.rag.retrieve import hybrid_search  # noqa: E402

print("loading index/store/chunks...", flush=True)
index = InvertedIndex.load("artifacts/index")
chunks_all = _load_identity_chunks(index)
store = EmbeddingStore.load("artifacts/embeddings")
provider = get_provider()
generate = default_generator()
judge_fn = default_judge()
chunk_by_id = {c.chunk_id: c for c in chunks_all}

def answer_for(question: str):
    hits = hybrid_search(index, store, chunks_all, question, provider, k=8, fusion_depth=2000)
    chunks = [chunk_by_id[h.doc_id] for h in hits if h.doc_id in chunk_by_id]
    scores = [h.score for h in hits]
    t0 = time.time()
    result = answer(question, chunks, generate, retrieval_scores=scores)
    return result, chunks, time.time() - t0

report = {"generator": resolved_generator_model(), "judge": DEFAULT_JUDGE_MODEL,
          "judge_validation_ref": "evalsets/judge-validation-2026-08-13.json",
          "retrieval": "hybrid k=8 fusion_depth=2000 (deployed config)",
          "per_qa": [], "unanswerable": []}

faiths, false_refusals = [], 0
for line in open("evalsets/qa.jsonl"):
    qa = json.loads(line)
    q = qa["question"]
    result, chunks, secs = answer_for(q)
    if result["refusal"] is not None:
        false_refusals += 1
        report["per_qa"].append({"qa_id": qa["qa_id"], "refused": True, "secs": round(secs, 1)})
        print(f"{qa['qa_id']}: FALSE-REFUSAL", flush=True)
        continue
    verdicts = judge_answer(q, result["text"], [c.text for c in chunks], judge_fn)
    faith = verdicts.get("faithfulness", 0.0)
    faiths.append(faith)
    report["per_qa"].append({"qa_id": qa["qa_id"], "faithfulness": round(faith, 3),
                             "claims": verdicts.get("total"), "secs": round(secs, 1),
                             "grounding": result["grounding"]["status"]})
    print(f"{qa['qa_id']}: faithfulness {faith:.2f} "
          f"({verdicts.get('total')} claims, {secs:.0f}s)", flush=True)

refused_right = 0
unans_rows = [json.loads(line) for line in open("evalsets/unanswerable.jsonl")]
for row in unans_rows:
    q = row["question"]
    result, _chunks, secs = answer_for(q)
    ok = result["refusal"] is not None
    refused_right += ok
    report["unanswerable"].append({"id": row.get("qa_id") or row.get("id"),
                                   "refused": ok, "secs": round(secs, 1)})
    label = "REFUSED (correct)" if ok else "ANSWERED (miss)"
    print(f"unanswerable {row.get('qa_id') or row.get('id')}: {label}", flush=True)

n_qa = len(report["per_qa"])
report["summary"] = {
    "faithfulness_mean": round(sum(faiths) / max(len(faiths), 1), 4),
    "answered_qa": len(faiths), "qa_total": n_qa,
    "false_refusal_rate": round(false_refusals / max(n_qa, 1), 4),
    "refusal_rate_on_unanswerable": round(refused_right / max(len(unans_rows), 1), 4),
}
Path("evalsets/judged-eval-2026-08-14.json").write_text(json.dumps(report, indent=2) + "\n")
print("SUMMARY:", json.dumps(report["summary"]), flush=True)

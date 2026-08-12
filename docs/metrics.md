# Metrics runs

Boolean baseline (red): `ONRECORD_INDEX=artifacts/index make eval`
BM25 run:
```bash
ONRECORD_INDEX=artifacts/index uv run python -c "
from onrecord.index.inverted import InvertedIndex
from onrecord.search.ranked import ranked_search
from onrecord.eval.run import run
idx = InvertedIndex.load('artifacts/index')
run('evalsets/judgments.jsonl', retrieve_fn=lambda q: [r.doc_id for r in ranked_search(idx, q, k=50)])"
```
Both append to `artifacts/scoreboard.jsonl`; the committed history lives at `evalsets/scoreboard.jsonl`.

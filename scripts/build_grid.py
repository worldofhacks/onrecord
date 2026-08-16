"""Operational lane for T-059: build artifacts/iso_queues.json.

Wires TESTED functions only; run via `make refresh-grid`. CAISO/ERCOT are
explicit scope trims (xlsx feeds; openpyxl not a dependency) — sources
lists exactly what was fetched, never more.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from onrecord.ingest.iso_queues import (
    fetch_caiso,
    fetch_ercot,
    fetch_miso,
    fetch_spp,
    join_jurisdictions,
    load_mapping,
)

mapping = load_mapping()
rows = fetch_miso() + fetch_spp() + fetch_ercot() + fetch_caiso()  # normalized rows
hits, misses = join_jurisdictions(rows, mapping)
out = Path("artifacts/iso_queues.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({
    "fetched_at": datetime.now(UTC).isoformat(timespec="minutes"),
    "sources": ["miso", "spp", "ercot", "caiso"],
    "rows": hits,
    "misses_count": len(misses),
}) + "\n", encoding="utf-8")
print(f"wrote {out}: {len(hits)} joined rows, {len(misses)} misses")

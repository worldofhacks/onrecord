"""Living-data refresh lane — daily artifact freshener (T-053 follow-on).

Wires TESTED ingest functions only; run via `make refresh-corpus` (locally
or .github/workflows/refresh-data.yml). Refreshes the fast-moving
artifacts — filings delta, EDGAR FTS candidates, legistar delta, grid
queues, livestreams — WITHOUT touching corpus/index/embeddings: those move
only through the versioned-swap runbook in tickets/T-053.md (swaps carry
re-pool obligations and invalidate demo-verified state).

Every step is failure-isolated: a failing step logs and the run continues;
the process exit code is 1 iff any step failed. Per-step counts/status land
in artifacts/refresh-report.json.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from onrecord import registry
from onrecord.ingest import form4
from onrecord.ingest.build_corpus import load_corpus_snapshot
from onrecord.ingest.edgar_fts import discover
from onrecord.ingest.filings_delta import corpus_accessions, new_filings, poll_feeds
from onrecord.ingest.legistar import pull_client
from onrecord.ingest.livestreams import track
from onrecord.types import Doc

logger = logging.getLogger("refresh_corpus")

CORPUS_PATH = Path(os.environ.get("ONRECORD_CORPUS", "corpus/v3/corpus.jsonl.gz"))
LINKHEALTH_PATH = Path("evalsets/linkhealth-2026-08-14.jsonl")
LEGISTAR_CLIENTS_PATH = Path("data/legistar_clients.json")
DELTA_WINDOW_DAYS = 30

FILINGS_DELTA_OUT = Path("artifacts/filings_delta.jsonl")
FTS_CANDIDATES_OUT = Path("artifacts/edgar_fts_candidates.json")
LEGISTAR_DELTA_OUT = Path("artifacts/legistar_delta.jsonl")
REPORT_OUT = Path("artifacts/refresh-report.json")

# Same discovery sweep the corpus-v3 build reviewed (artifacts/v3/
# edgar_fts_candidates.json params), narrowed to a rolling window.
FTS_TERMS: tuple[str, ...] = ("data center", "hyperscale", "colocation")
FTS_FORMS: tuple[str, ...] = ("8-K", "10-K", "10-Q")


class StepSkipped(Exception):
    """A step's environmental precondition is missing; skip, don't fail."""


_DOCS: list[Doc] | None = None


def _corpus_docs() -> list[Doc]:
    """The CURRENT corpus snapshot (env ONRECORD_CORPUS), loaded once."""
    global _DOCS
    if _DOCS is None:
        docs = load_corpus_snapshot(CORPUS_PATH)
        if not docs:
            raise RuntimeError(f"corpus snapshot missing or empty: {CORPUS_PATH}")
        _DOCS = docs
    return _DOCS


def _window_start() -> str:
    return (datetime.now(UTC).date() - timedelta(days=DELTA_WINDOW_DAYS)).isoformat()


def _manifest_since() -> str:
    """Filings-delta cutoff: the corpus manifest's created_at date (filings
    newer than the snapshot), falling back to the rolling window."""
    manifest_path = CORPUS_PATH.parent / "manifest.json"
    try:
        created_at = json.loads(manifest_path.read_text())["created_at"]
        return str(created_at)[:10]
    except (OSError, ValueError, KeyError):
        return _window_start()


def step_filings_delta() -> dict:
    """T-052 lane: per-CIK EDGAR Atom feeds vs corpus accessions."""
    known = corpus_accessions([doc.id for doc in _corpus_docs()])
    symbols = [t["symbol"] for t in registry.load()["tickers"]]
    with httpx.Client() as client:
        time.sleep(form4.REQUEST_GAP_S)
        response = client.get(
            form4.SEC_TICKER_MAP_URL, headers=form4.SEC_HEADERS, timeout=30.0
        )
        response.raise_for_status()
        ticker_map = response.json()
    ciks_by_ticker: dict[str, str] = {}
    no_cik: list[str] = []
    for symbol in symbols:
        cik = form4.cik_for_ticker(symbol, ticker_map)
        if cik is None:
            no_cik.append(symbol)
        else:
            ciks_by_ticker[symbol] = cik
    entries = poll_feeds(ciks_by_ticker)
    since = _manifest_since()
    rows = new_filings(entries, known, since)
    FILINGS_DELTA_OUT.parent.mkdir(parents=True, exist_ok=True)
    with FILINGS_DELTA_OUT.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    return {
        "tickers_polled": len(ciks_by_ticker),
        "tickers_without_cik": no_cik,
        "feed_entries": len(entries),
        "known_corpus_accessions": len(known),
        "since": since,
        "new_filings": len(rows),
        "out": str(FILINGS_DELTA_OUT),
    }


def step_edgar_fts() -> dict:
    """T-062 lane: efts.sec.gov discovery, last-30-days window. Candidates
    are owner-reviewable only — nothing auto-enters the corpus (AC-4)."""
    known = corpus_accessions([doc.id for doc in _corpus_docs()])
    date_from = _window_start()
    date_to = datetime.now(UTC).date().isoformat()
    candidates = discover(FTS_TERMS, FTS_FORMS, date_from, date_to, known)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "params": {
            "terms": list(FTS_TERMS),
            "forms": list(FTS_FORMS),
            "date_from": date_from,
            "date_to": date_to,
        },
        "counts": {"novel": len(candidates)},
        "candidates": candidates,
    }
    FTS_CANDIDATES_OUT.parent.mkdir(parents=True, exist_ok=True)
    FTS_CANDIDATES_OUT.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    return {
        "window": f"{date_from}..{date_to}",
        "novel_candidates": len(candidates),
        "out": str(FTS_CANDIDATES_OUT),
    }


def step_legistar_delta() -> dict:
    """T-061 lane: matters + events per verified client slug, since 30d ago."""
    clients = json.loads(LEGISTAR_CLIENTS_PATH.read_text(encoding="utf-8"))
    since = _window_start()
    per_client: dict[str, int] = {}
    LEGISTAR_DELTA_OUT.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with LEGISTAR_DELTA_OUT.open("w", encoding="utf-8") as fh:
        for jurisdiction, slug in sorted(clients.items()):
            if jurisdiction == "unmapped":
                continue
            docs = pull_client(slug, since, jurisdiction)
            per_client[slug] = len(docs)
            total += len(docs)
            for doc in docs:
                row = {k: v for k, v in asdict(doc).items() if v is not None}
                fh.write(json.dumps(row, sort_keys=True) + "\n")
    return {
        "since": since,
        "docs": total,
        "per_client": per_client,
        "out": str(LEGISTAR_DELTA_OUT),
    }


def step_grid() -> dict:
    """T-059 lane. build_grid.py runs its lane at import time, so reuse is
    via subprocess (same interpreter), not import."""
    proc = subprocess.run(
        [sys.executable, "scripts/build_grid.py"],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if proc.stdout.strip():
        print(proc.stdout.strip(), flush=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"build_grid.py exited {proc.returncode}: {proc.stderr.strip()[-400:]}"
        )
    payload = json.loads(Path("artifacts/iso_queues.json").read_text(encoding="utf-8"))
    return {
        "rows": len(payload.get("rows", [])),
        "misses_count": payload.get("misses_count"),
        "out": "artifacts/iso_queues.json",
    }


def step_livestreams() -> dict:
    """T-051 lane: the `make refresh-live` retrack — real channels resolved
    from the newest link-health-alive video per jurisdiction."""
    if shutil.which("yt-dlp") is None:
        raise StepSkipped(
            "yt-dlp not on PATH — retracking would overwrite artifacts/livestreams.json "
            "with empty results"
        )
    alive: set[str] = set()
    for line in LINKHEALTH_PATH.open(encoding="utf-8"):
        if not line.strip():
            continue
        row = json.loads(line)
        if row["status"] == "alive":
            alive.add(row["video_id"])
    payload = track(
        _corpus_docs(), alive, checked_at=datetime.now(UTC).isoformat(timespec="minutes")
    )
    return {
        "alive_ids": len(alive),
        "jurisdictions_resolved": payload["jurisdictions_resolved"],
        "live": len(payload["live"]),
        "upcoming": len(payload["upcoming"]),
        "out": "artifacts/livestreams.json",
    }


def step_form4_hint() -> dict:
    """Form 4 stays manual: T-038's pull is heavy but resumable and deduped
    by accession — run it deliberately, not on a daily timer."""
    print("form4 refresh is manual (heavy; resumable): run `make refresh-form4`", flush=True)
    return {"status": "manual", "make_target": "refresh-form4"}


STEPS: tuple[tuple[str, object], ...] = (
    ("filings_delta", step_filings_delta),
    ("edgar_fts", step_edgar_fts),
    ("legistar_delta", step_legistar_delta),
    ("grid", step_grid),
    ("livestreams", step_livestreams),
    ("form4", step_form4_hint),
)


def main() -> int:
    ran_at = datetime.now(UTC).isoformat(timespec="seconds")
    steps_report: dict[str, dict] = {}
    failed: list[str] = []
    for name, fn in STEPS:
        print(f"[{name}] starting", flush=True)
        started = time.monotonic()
        try:
            result = fn()  # type: ignore[operator]
        except StepSkipped as exc:
            logger.warning("[%s] skipped: %s", name, exc)
            steps_report[name] = {"status": "skipped", "reason": str(exc)}
            continue
        except Exception as exc:
            logger.exception("[%s] failed", name)
            failed.append(name)
            steps_report[name] = {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
            continue
        entry = {"status": "ok", **result}
        entry["seconds"] = round(time.monotonic() - started, 1)
        steps_report[name] = entry
        print(f"[{name}] {entry}", flush=True)

    report = {
        "ran_at": ran_at,
        "corpus": str(CORPUS_PATH),
        "steps": steps_report,
        "failed_steps": failed,
    }
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {REPORT_OUT}; failed steps: {failed or 'none'}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    sys.exit(main())

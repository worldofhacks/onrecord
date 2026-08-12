"""Embeddings — provider adapter, content-hash cache, fp16 store, brute-force
cosine (T-021).

The authoritative contract lives in `tests/unit/rag/test_embeddings.py`'s
module docstring (frozen suite) — read it in full before touching this file.
Summary of what's implemented here:

- `EmbeddingProvider` (Protocol): `model: str`, `dim: int`,
  `embed(texts) -> np.ndarray` (float32, shape `(len(texts), dim)`, row
  order == input order).
- `OpenAIEmbeddingProvider`: POSTs `/v1/embeddings` via httpx, batches at
  <=512 texts/request, retries 429/5xx with backoff, bearer auth from
  `OPENAI_API_KEY` when no `api_key` is given. Missing key raises
  `ProviderNotConfigured` at construction. See "Secret hygiene" below.
- `PROVIDERS` / `get_provider(name=None)`: registry + env-driven factory
  (`ONRECORD_EMBED_PROVIDER`, `ONRECORD_EMBED_MODEL`). Never returns a fake
  silently — an unconfigured provider always raises.
- `content_hash(model, dim, text)`: the frozen cache key,
  `sha256(f"{model}\\n{dim}\\n{text}")` hexdigest. `dim` is part of the key
  so a model whose `dimensions` parameter changes cannot poison the cache
  at the same model name (plan-review M-9).
- `EmbeddingStore`: the on-disk cache + packed matrix.
  * Storage is PER-CHUNK (orchestrator ruling on test-review C-1): one
    matrix row per `chunk_id`, `entries.json` maps
    `chunk_id -> {"row": int, "content_hash": str}` under a `{"model",
    "dim", "entries"}` header. De-duplication happens at the API-CALL
    level inside `embed_corpus` — identical content_hash within a run, or
    already in the store, gets its vector COPIED into the new chunk's row;
    the provider is never billed twice for identical text.
  * Alignment is ID-KEYED, never positional: `rows_for(chunk_ids)` /
    `entry_for(chunk_id)` are the only supported ways to resolve a row.
  * `matrix.npy` is `N x dim`, fp16, L2-normalized rows (normalized once at
    ingest so cosine reduces to a dot product).
  * `save` is atomic (temp files + `os.replace`); `load` validates
    structural integrity (row-count/duplicate/out-of-range/dtype/identity)
    and raises a typed `CorruptStore` naming the defect, or
    `StoreIdentityMismatch` when an explicit `model=`/`dim=` disagrees with
    the persisted identity.
  * `embed_corpus` checkpoints: with `checkpoint_dir` set, it embeds in
    batches of at most `checkpoint_every` newly-needed items and saves
    after every batch (including a trailing partial one), so a crash or
    provider outage resumes from cache instead of forcing a paid
    re-embed.
- `cosine_top_k(store, query_vec, k, block_rows=8192)`: blocked fp16->fp32
  dot product (query is normalized too), deterministic ties broken by
  ascending row index.

Memory / cost estimates (ticket-required, research-required pricing caveat
— verify live provider pricing at provisioning time and record ACTUALS in
docs/cost-analysis.md):
    ~265K chunks at identity chunking.
    1536-d (text-embedding-3-small): 265,000 * 1536 * 2 B ~= 0.78 GB fp16
        resident (+ <= 8192*1536*4 B ~= 50 MB fp32 per block during
        scoring — blocking keeps the transient bounded).
    1024-d (Voyage class): ~= 0.52 GB.
    Brute-force query ~= 0.8 GFLOP -> est. 50-150 ms/query in numpy.
    Cost: ~$30-80 for a full ~265K-chunk freeze (orchestrator-measured
        corpus growth vs. a stale $3-8 @ 24-40K-chunk estimate; a token-math
        cross-check at published small-model rates suggests materially
        lower, $1.5-12 — pricing is research-required at provisioning
        time). Budget approval is an owner open question.
    Under the spec's ~300K brute-force threshold, hnswlib/ANN is a scope
        cut for this ticket (documented, not implemented).

Secret hygiene (LESSONS.md T-014, required reading): a prior ticket leaked
an API key because a secret-leak check only inspected the module's own
logger while the actual leak came from a LIBRARY logger (httpx logs full
request URLs at INFO). This module's OpenAI adapter therefore silences the
`httpx`/`httpcore`/`openai` loggers for the duration of every keyed
request (`_silenced_library_loggers`), never places the key in an
exception message or `repr`/`str`, and never re-emits a transport error's
own text verbatim (it can carry request headers, including
`Authorization`) — it always wraps failures in a fresh, credential-free
message.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Protocol

import httpx
import numpy as np

# --------------------------------------------------------------------------
# Provider boundary
# --------------------------------------------------------------------------


class EmbeddingProvider(Protocol):
    """Structural contract every embedding provider (real or test double)
    must satisfy."""

    model: str
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray:
        """Embed `texts`, returning float32 rows in input order,
        shape `(len(texts), self.dim)`."""
        ...


class ProviderNotConfigured(Exception):
    """Raised when a provider cannot be constructed because required
    configuration (e.g. an API key) is missing. Never silently substitute a
    fake — fakes are test-injected only."""


class EmbeddingRequestError(RuntimeError):
    """A provider request failed (transport error or exhausted retries).
    Deliberately credential-free — see the module's secret-hygiene note."""


_OPENAI_URL = "https://api.openai.com/v1/embeddings"
_OPENAI_BATCH_SIZE = 512
_OPENAI_MAX_RETRIES = 3  # retries beyond the initial attempt (2-5 total requests)
_OPENAI_BACKOFF_BASE = 0.05  # seconds; tests that don't monkeypatch time.sleep still run fast

# Known dims for OpenAI's published embedding models. `dim` must be known at
# construction with no network call (plan-review M-4), so an unrecognized
# model name still gets a usable default.
_OPENAI_MODEL_DIMS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}
_OPENAI_DEFAULT_DIM = 1536

_LIBRARY_LOGGER_NAMES = ("httpx", "httpcore", "openai")


@contextlib.contextmanager
def _silenced_library_loggers():
    """Silence httpx/httpcore/openai loggers for the duration of a keyed
    request (LESSONS T-014: a secret-leak check must cover library loggers,
    not just this module's own — httpx logs full request URLs at INFO).

    `Logger.disabled = True` makes `isEnabledFor` return False
    unconditionally regardless of level or propagation, so no log record is
    ever created for these loggers while the context is active.
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


class OpenAIEmbeddingProvider:
    """OpenAI-shaped embeddings adapter over httpx (`transport=` injects a
    `httpx.MockTransport` in tests — zero live network in this suite)."""

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        resolved_key = api_key if api_key else os.environ.get("OPENAI_API_KEY")
        if not resolved_key or not str(resolved_key).strip():
            raise ProviderNotConfigured(
                "OPENAI_API_KEY is not set (and no api_key was provided) — set the "
                "OPENAI_API_KEY environment variable or pass api_key= explicitly"
            )
        self.model = model
        self.dim = _OPENAI_MODEL_DIMS.get(model, _OPENAI_DEFAULT_DIM)
        self._api_key = resolved_key
        self._transport = transport

    def __repr__(self) -> str:
        # Deliberately excludes the key (LESSONS T-014): a default
        # dataclass/attrs-style repr would embed it and land it in every
        # log line that interpolates the provider.
        return f"OpenAIEmbeddingProvider(model={self.model!r}, dim={self.dim})"

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        batches = [
            texts[i : i + _OPENAI_BATCH_SIZE] for i in range(0, len(texts), _OPENAI_BATCH_SIZE)
        ]
        with httpx.Client(transport=self._transport) as client:
            rows = [self._embed_batch(client, batch) for batch in batches]
        return np.concatenate(rows, axis=0)

    def _embed_batch(self, client: httpx.Client, batch: list[str]) -> np.ndarray:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        body = {"model": self.model, "input": batch}

        with _silenced_library_loggers():
            for attempt in range(_OPENAI_MAX_RETRIES + 1):
                more_retries_left = attempt < _OPENAI_MAX_RETRIES
                try:
                    response = client.post(_OPENAI_URL, headers=headers, json=body)
                except httpx.HTTPError:
                    # Never re-emit a transport error's own text verbatim
                    # (decision 11 / review I-7) — it can carry request
                    # headers, including Authorization.
                    if more_retries_left:
                        time.sleep(_OPENAI_BACKOFF_BASE * (2**attempt))
                        continue
                    raise EmbeddingRequestError(
                        "embedding request to OpenAI failed: transport error"
                    ) from None

                if response.status_code == 200:
                    payload = response.json()
                    ordered = sorted(payload["data"], key=lambda item: item["index"])
                    return np.array([item["embedding"] for item in ordered], dtype=np.float32)

                if (response.status_code == 429 or response.status_code >= 500) and (
                    more_retries_left
                ):
                    time.sleep(_OPENAI_BACKOFF_BASE * (2**attempt))
                    continue

                raise EmbeddingRequestError(
                    f"embedding request to OpenAI failed: HTTP {response.status_code}"
                )

        # Unreachable: the loop above always returns or raises.
        raise EmbeddingRequestError("embedding request to OpenAI failed: retries exhausted")


PROVIDERS: dict[str, type] = {"openai": OpenAIEmbeddingProvider}


def get_provider(name: str | None = None) -> EmbeddingProvider:
    """Resolve an `EmbeddingProvider` by name (else `ONRECORD_EMBED_PROVIDER`,
    default "openai"), with a model override via `ONRECORD_EMBED_MODEL`.

    Never silently returns a fake — an unconfigured provider (e.g. a missing
    API key) raises `ProviderNotConfigured` (locked decision; fakes are
    test-injected only).
    """
    resolved_name = name or os.environ.get("ONRECORD_EMBED_PROVIDER", "openai")
    if resolved_name not in PROVIDERS:
        raise ProviderNotConfigured(
            f"unknown embedding provider {resolved_name!r}; registered providers: "
            f"{sorted(PROVIDERS)}"
        )
    provider_cls = PROVIDERS[resolved_name]
    model_override = os.environ.get("ONRECORD_EMBED_MODEL")
    kwargs = {"model": model_override} if model_override else {}
    return provider_cls(**kwargs)


# --------------------------------------------------------------------------
# Content-hash cache key
# --------------------------------------------------------------------------


def content_hash(model: str, dim: int, text: str) -> str:
    """The frozen cache key: `sha256(f"{model}\\n{dim}\\n{text}")` hexdigest.

    Public API (plan-review I-4) — downstream tickets import this instead of
    re-deriving the formula by hand. `dim` is part of the key so a model
    whose `dimensions` parameter changes cannot poison the cache at the same
    model name (plan-review M-9).
    """
    return hashlib.sha256(f"{model}\n{dim}\n{text}".encode()).hexdigest()


def _normalize_to_fp16(vector: np.ndarray) -> np.ndarray:
    """L2-normalize once at ingest (float32 math) then pack to fp16."""
    vector = np.asarray(vector, dtype=np.float32)
    norm = np.linalg.norm(vector)
    normalized = vector / norm if norm > 0 else vector
    return normalized.astype(np.float16)


# --------------------------------------------------------------------------
# Store integrity errors
# --------------------------------------------------------------------------


class CorruptStore(Exception):
    """A persisted embedding store failed integrity validation at load
    (row-count mismatch, duplicate/out-of-range row index, wrong dtype,
    missing identity, or malformed JSON)."""


class StoreIdentityMismatch(Exception):
    """A store's persisted `(model, dim)` identity disagrees with the
    caller's expectation — either an explicit `load(dir, model=, dim=)` or
    an `embed_corpus` call against a provider of a different `(model, dim)`
    than the store already holds. Not subclassed from `CorruptStore`
    (decision 4): the store itself isn't corrupt, the caller pointed a
    query at the wrong one."""


# --------------------------------------------------------------------------
# EmbeddingStore
# --------------------------------------------------------------------------


class EmbeddingStore:
    """The content-hash cache + fp16 packed matrix.

    Storage is per-chunk: one matrix row per `chunk_id`. Alignment is
    ID-KEYED — resolve rows via `rows_for(chunk_ids)` / `entry_for
    (chunk_id)`, never by position (row order is first-appearance order
    across ALL embed runs ever made against this store).
    """

    def __init__(self) -> None:
        self.model: str | None = None
        self.dim: int | None = None
        self._rows: list[np.ndarray] = []
        self._entries: dict[str, dict[str, int | str]] = {}
        self._hash_to_row: dict[str, int] = {}

    @property
    def matrix(self) -> np.ndarray:
        if not self._rows:
            return np.zeros((0, self.dim or 0), dtype=np.float16)
        return np.stack(self._rows).astype(np.float16)

    def rows_for(self, chunk_ids: list[str]) -> list[int | None]:
        """Resolve `chunk_ids` to matrix rows. Absent ids map to `None`.

        Keyed by `chunk_id`, NEVER by content hash — storage is per-chunk
        (orchestrator ruling), so a content hash can identify several rows.
        """
        return [
            self._entries[chunk_id]["row"] if chunk_id in self._entries else None
            for chunk_id in chunk_ids
        ]

    def entry_for(self, chunk_id: str) -> dict[str, int | str] | None:
        entry = self._entries.get(chunk_id)
        if entry is None:
            return None
        return {"row": entry["row"], "content_hash": entry["content_hash"]}

    def embed_corpus(
        self,
        pairs: list[tuple[str, str]],
        provider: EmbeddingProvider,
        *,
        checkpoint_dir: str | Path | None = None,
        checkpoint_every: int = 4096,
    ) -> None:
        """Embed `(chunk_id, text)` pairs, appending only chunks not already
        in the store. A text whose `content_hash` already has a vector
        (earlier in this run, or already in the store) is COPIED into the
        new chunk's row — the provider is never billed twice for identical
        text, and each `chunk_id` still gets its own row.

        With `checkpoint_dir` set, embeds in batches of at most
        `checkpoint_every` newly-needed texts and saves after every batch
        (including a trailing partial one), so a crash mid-run resumes from
        cache instead of re-paying for already-embedded text.
        """
        if not pairs:
            return

        if self.model is None and self.dim is None:
            self.model, self.dim = provider.model, provider.dim
        elif (provider.model, provider.dim) != (self.model, self.dim):
            raise StoreIdentityMismatch(
                f"embed_corpus called with provider identity (model={provider.model!r}, "
                f"dim={provider.dim}) but the store was already built with "
                f"(model={self.model!r}, dim={self.dim})"
            )

        work_items = [
            (chunk_id, text, content_hash(self.model, self.dim, text))
            for chunk_id, text in pairs
            if chunk_id not in self._entries
        ]
        if not work_items:
            return

        checkpoint_path = Path(checkpoint_dir) if checkpoint_dir is not None else None
        group_size = checkpoint_every if checkpoint_path is not None else len(work_items)

        for start in range(0, len(work_items), group_size):
            group = work_items[start : start + group_size]
            self._embed_group(group, provider)
            if checkpoint_path is not None:
                self.save(checkpoint_path)

    def _embed_group(self, group: list[tuple[str, str, str]], provider: EmbeddingProvider) -> None:
        """Resolve one group of work items: dedupe novel hashes at the
        API-call level, embed only what's genuinely new, then append one row
        per chunk in the group's original order."""
        hash_order: list[str] = []
        unique_texts: list[str] = []
        seen_in_group: set[str] = set()
        for _chunk_id, text, h in group:
            if h in self._hash_to_row or h in seen_in_group:
                continue
            seen_in_group.add(h)
            hash_order.append(h)
            unique_texts.append(text)

        fresh_vectors: dict[str, np.ndarray] = {}
        if unique_texts:
            embedded = provider.embed(unique_texts)
            for h, vector in zip(hash_order, embedded, strict=True):
                fresh_vectors[h] = vector

        for chunk_id, _text, h in group:
            if h in fresh_vectors:
                vector = _normalize_to_fp16(fresh_vectors[h])
            else:
                vector = self._rows[self._hash_to_row[h]].copy()
            row = len(self._rows)
            self._rows.append(vector)
            self._entries[chunk_id] = {"row": row, "content_hash": h}
            self._hash_to_row.setdefault(h, row)

    def save(self, directory: str | Path) -> None:
        """Atomically persist this store to `directory` (created if
        needed): write both files to temp names, then `os.replace` — an
        exception mid-write (e.g. `np.save` raising after writing the
        matrix) leaves any previously-saved store fully loadable.
        """
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        payload = {"model": self.model, "dim": self.dim, "entries": self._entries}

        matrix_tmp = directory / "matrix.npy.tmp"
        entries_tmp = directory / "entries.json.tmp"

        with open(matrix_tmp, "wb") as fh:
            np.save(fh, self.matrix)
        entries_tmp.write_text(json.dumps(payload), encoding="utf-8")

        os.replace(matrix_tmp, directory / "matrix.npy")
        os.replace(entries_tmp, directory / "entries.json")

    @classmethod
    def load(
        cls, directory: str | Path, *, model: str | None = None, dim: int | None = None
    ) -> EmbeddingStore:
        """Load a store from `directory`, validating structural integrity.

        Raises a `FileNotFoundError`-derived error when the directory or
        either file is absent, `CorruptStore` on any integrity violation,
        and `StoreIdentityMismatch` when the given `model=`/`dim=` (both
        optional) disagree with the persisted identity.
        """
        directory = Path(directory)
        if not directory.is_dir():
            raise FileNotFoundError(f"embedding store directory not found: {directory}")

        matrix_path = directory / "matrix.npy"
        entries_path = directory / "entries.json"
        if not matrix_path.exists():
            raise FileNotFoundError(f"embedding store missing matrix.npy: {matrix_path}")
        if not entries_path.exists():
            raise FileNotFoundError(f"embedding store missing entries.json: {entries_path}")

        try:
            raw = json.loads(entries_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CorruptStore(
                f"embedding store entries.json is not valid JSON ({entries_path}): {exc}"
            ) from exc

        if not isinstance(raw, dict) or "model" not in raw:
            raise CorruptStore(
                f"embedding store entries.json is missing the 'model' identity field "
                f"({entries_path})"
            )
        if "dim" not in raw:
            raise CorruptStore(
                f"embedding store entries.json is missing the 'dim' identity field ({entries_path})"
            )
        if "entries" not in raw:
            raise CorruptStore(
                f"embedding store entries.json is missing the 'entries' field ({entries_path})"
            )

        stored_model = raw["model"]
        stored_dim = raw["dim"]
        raw_entries = raw["entries"]

        matrix = np.load(matrix_path)
        if matrix.dtype != np.float16:
            raise CorruptStore(
                f"embedding store matrix.npy has dtype {matrix.dtype}, expected float16 "
                f"({matrix_path})"
            )
        if len(raw_entries) != matrix.shape[0]:
            raise CorruptStore(
                f"embedding store entries/matrix row-count mismatch: entries.json has "
                f"{len(raw_entries)} entries but matrix.npy has {matrix.shape[0]} rows"
            )

        resolved_entries: dict[str, dict[str, int | str]] = {}
        seen_rows: set[int] = set()
        for chunk_id, entry in raw_entries.items():
            if not isinstance(entry, dict) or "row" not in entry or "content_hash" not in entry:
                raise CorruptStore(
                    f"embedding store entries.json has a malformed entry for chunk "
                    f"{chunk_id!r}: {entry!r}"
                )
            row = entry["row"]
            if not isinstance(row, int) or row < 0 or row >= matrix.shape[0]:
                raise CorruptStore(
                    f"embedding store entries.json has an out-of-range row index for "
                    f"chunk {chunk_id!r}: {row!r} (matrix.npy has {matrix.shape[0]} rows)"
                )
            if row in seen_rows:
                raise CorruptStore(
                    f"embedding store entries.json has a duplicate row index {row} "
                    f"referenced by chunk {chunk_id!r}"
                )
            seen_rows.add(row)
            resolved_entries[chunk_id] = {"row": row, "content_hash": entry["content_hash"]}

        if model is not None and model != stored_model:
            raise StoreIdentityMismatch(
                f"embedding store identity mismatch: store was built with model="
                f"{stored_model!r}, expected model={model!r}"
            )
        if dim is not None and dim != stored_dim:
            raise StoreIdentityMismatch(
                f"embedding store identity mismatch: store was built with dim="
                f"{stored_dim!r}, expected dim={dim!r}"
            )

        store = cls()
        store.model = stored_model
        store.dim = stored_dim
        store._rows = [matrix[i] for i in range(matrix.shape[0])]
        store._entries = resolved_entries
        for chunk_id, entry in resolved_entries.items():
            store._hash_to_row.setdefault(entry["content_hash"], entry["row"])
        return store


# --------------------------------------------------------------------------
# Brute-force cosine top-k
# --------------------------------------------------------------------------


def cosine_top_k(
    store: EmbeddingStore, query_vec_f32: np.ndarray, k: int, block_rows: int = 8192
) -> list[tuple[int, float]]:
    """Cosine similarity of `query_vec_f32` against every row in `store`,
    top-`k` by score descending, ties broken by ascending row index.

    Blocked fp16->fp32 dot product (the query is normalized too, matching
    the store's rows which are normalized once at ingest) — `block_rows`
    bounds the transient fp32 memory, never changes the result.
    """
    query = np.asarray(query_vec_f32, dtype=np.float32)
    norm = np.linalg.norm(query)
    if norm > 0:
        query = query / norm

    matrix = store.matrix
    n_rows = matrix.shape[0]
    k = min(k, n_rows)

    scores = np.empty(n_rows, dtype=np.float32)
    for start in range(0, n_rows, block_rows):
        end = min(start + block_rows, n_rows)
        block = matrix[start:end].astype(np.float32)
        scores[start:end] = block @ query

    order = sorted(range(n_rows), key=lambda row: (-scores[row], row))[:k]
    return [(row, float(scores[row])) for row in order]

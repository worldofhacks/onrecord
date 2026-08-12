# onrecord — single-service deployment (FastAPI serves the API + the
# static UI; see onrecord/api.py and tickets/T-015.md). Railway builds this
# image directly (railway.json: {"build": {"builder": "DOCKERFILE"}}).

FROM python:3.12-slim

# Install uv (single static binary — no network access needed beyond this
# COPY --from, and no pip/pipx bootstrap required).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy dependency manifests first so `uv sync` is Docker-layer-cached
# across rebuilds that only touch application code.
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --no-install-project --frozen

# Now copy the rest of the repo (onrecord/, ui/, corpus/v1/corpus.jsonl.gz,
# etc.) and do a final sync to install the project itself.
COPY . .
RUN uv sync --no-dev --frozen

# Railway injects $PORT at runtime; default it for local `docker run`.
ENV PORT=8000
EXPOSE 8000

# Container-scoped default: the merged corpus snapshot is baked into the
# image at exactly this path (corpus/v1/corpus.jsonl.gz is git-tracked,
# not .dockerignore'd) -- so every deploy from THIS image bootstraps its
# index automatically on a cold start (ONRECORD_INDEX missing/unbuilt),
# with no extra Railway env var configuration required. This is
# image-local only: onrecord/api.py's own default for ONRECORD_CORPUS
# stays unset (post-review fix, .tdd-swarm/reports/T-015-review.md
# Important-1 "deploy-trap" — see README.md's Deploy section), so local
# runs / the frozen test suite are unaffected; override this at deploy
# time (Railway env var) to point at a different snapshot if ever needed.
ENV ONRECORD_CORPUS=corpus/v1/corpus.jsonl.gz

# Bind 0.0.0.0 (never 127.0.0.1 — Railway's proxy connects externally) on
# $PORT, per tickets/T-015.md's Deploy contract (see also README.md).
CMD ["sh", "-c", "uvicorn onrecord.api:app --host 0.0.0.0 --port ${PORT:-8000}"]

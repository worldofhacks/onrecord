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

# corpus-v2 deploy artifacts, fetched at build time from the repo's public
# v2-artifacts release: `railway up`'s upload path caps context size well
# under the ~2.4GB these weigh (Cloudflare 413), and the embedding store
# cannot be rebuilt in-container without keys and a ~$1.50 re-bill. Single
# RUN layer per fetch so the tarball bytes are never stored, only the
# extracted tree. Placed before the code COPY so code-only changes reuse
# this layer from cache.
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
RUN mkdir -p artifacts corpus/v2 \
 && curl -fsSL https://github.com/worldofhacks/onrecord/releases/download/v2-artifacts/index-v2.tar.gz | tar -xz -C artifacts \
 && curl -fsSL https://github.com/worldofhacks/onrecord/releases/download/v2-artifacts/embeddings-v2.tar.gz | tar -xz -C artifacts \
 && curl -fsSL https://github.com/worldofhacks/onrecord/releases/download/v2-artifacts/corpus-v2.jsonl.gz -o corpus/v2/corpus.jsonl.gz

# Now copy the rest of the repo (onrecord/, ui/, corpus/v1/corpus.jsonl.gz,
# etc.) and do a final sync to install the project itself.
COPY . .
RUN uv sync --no-dev --frozen

# Railway injects $PORT at runtime; default it for local `docker run`.
ENV PORT=8000
EXPOSE 8000

# Container-scoped defaults: the corpus-v2 snapshot, prebuilt index, and
# embedding store are fetched into the image at exactly these paths by the
# release-asset RUN layer above -- so every deploy from THIS image serves
# corpus-v2 with zero cold-start index build and no extra Railway env var
# configuration required (keyless deploys stay green: lexical search and
# the UI work with no API keys; answer/semantic degrade to clean 503s).
# corpus/v1/corpus.jsonl.gz also remains baked (git-tracked) as the
# fallback snapshot. This is
# image-local only: onrecord/api.py's own default for ONRECORD_CORPUS
# stays unset (post-review fix, .tdd-swarm/reports/T-015-review.md
# Important-1 "deploy-trap" — see README.md's Deploy section), so local
# runs / the frozen test suite are unaffected; override this at deploy
# time (Railway env var) to point at a different snapshot if ever needed.
ENV ONRECORD_CORPUS=corpus/v2/corpus.jsonl.gz
ENV ONRECORD_INDEX=artifacts/index
ENV ONRECORD_EMBED_STORE=artifacts/embeddings

# Bind 0.0.0.0 (never 127.0.0.1 — Railway's proxy connects externally) on
# $PORT, per tickets/T-015.md's Deploy contract (see also README.md).
CMD ["sh", "-c", "uv run uvicorn onrecord.api:app --host 0.0.0.0 --port ${PORT:-8000}"]

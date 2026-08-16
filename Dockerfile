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

# corpus-v3 deploy artifacts (309,662 docs; T-053 swap 2026-08-15), fetched at build time from the repo's public
# v2-artifacts release: `railway up`'s upload path caps context size well
# under the ~2.4GB these weigh (Cloudflare 413), and the embedding store
# cannot be rebuilt in-container without keys and a ~$1.50 re-bill. Single
# RUN layer per fetch so the tarball bytes are never stored, only the
# extracted tree. Placed before the code COPY so code-only changes reuse
# this layer from cache.
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
# Download to a file with resume-on-retry (-C - against GitHub's
# range-supporting CDN), then extract: a plain `curl | tar` pipe cannot
# survive a mid-stream reset, and one killed the first deploy attempt
# (curl exit 56 at ~half of the 799MB embeddings asset). The temp file is
# removed inside the same RUN, so it never lands in a committed layer.
RUN mkdir -p artifacts corpus/v3 \
 && curl -fSL --retry 5 --retry-delay 5 --retry-all-errors -C - -o /tmp/a.tgz https://github.com/worldofhacks/onrecord/releases/download/v3-artifacts/index-v3.tar.gz \
 && tar -xzf /tmp/a.tgz -C artifacts && rm /tmp/a.tgz \
 && curl -fSL --retry 5 --retry-delay 5 --retry-all-errors -C - -o /tmp/a.tgz https://github.com/worldofhacks/onrecord/releases/download/v3-artifacts/embeddings-3large-v3.tar.gz \
 && tar -xzf /tmp/a.tgz -C artifacts && rm /tmp/a.tgz \
 && curl -fSL --retry 5 --retry-delay 5 --retry-all-errors -C - -o corpus/v3/corpus.jsonl.gz https://github.com/worldofhacks/onrecord/releases/download/v3-artifacts/corpus-v3.jsonl.gz

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
ENV ONRECORD_CORPUS=corpus/v3/corpus.jsonl.gz
ENV ONRECORD_INDEX=artifacts/index
# T-054 embedding upgrade: the image ships the text-embedding-3-large @
# 3072 store (semantic NDCG@10 0.5505 vs 0.4614 on the honest five-arm
# pool). ONRECORD_EMBED_MODEL must match the store identity or query-time
# embeds arrive at 1536 dims and semantic_search rejects the store.
ENV ONRECORD_EMBED_STORE=artifacts/embeddings-3large
ENV ONRECORD_EMBED_MODEL=text-embedding-3-large
# The UI Score view's history: a curated, git-tracked lineage (day-1
# boolean 0.000 through the deployed 3-large best-mode row) instead of the
# legacy artifacts/scoreboard.jsonl, whose asset-baked copy went stale the
# moment the store swapped (T-055 follow-up).
ENV ONRECORD_SCOREBOARD=evalsets/scoreboard-ui.jsonl

# Bind 0.0.0.0 (never 127.0.0.1 — Railway's proxy connects externally) on
# $PORT, per tickets/T-015.md's Deploy contract (see also README.md).
CMD ["sh", "-c", "uv run uvicorn onrecord.api:app --host 0.0.0.0 --port ${PORT:-8000}"]

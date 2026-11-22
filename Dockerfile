# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# curl is used for HEALTHCHECK, install uv via pip to avoid external GHCR auth issues
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.11.19

WORKDIR /app

# 1) Dependencies only — cached until uv.lock / pyproject.toml change
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project

# 2) Bake the embedding model into the image (cached until the script or EMBEDDING_MODEL changes);
#    at runtime Hugging Face stays offline, so no model download and no internet needed for it.
ARG EMBEDDING_MODEL=sdadas/mmlw-roberta-base
COPY scripts/download_models.py scripts/download_models.py
RUN EMBEDDING_MODEL=${EMBEDDING_MODEL} python scripts/download_models.py
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

# 3) Project code
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

RUN mkdir -p /app/storage

EXPOSE 8501
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1
CMD ["python", "-m", "app.bootstrap"]

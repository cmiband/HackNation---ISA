# syntax=docker/dockerfile:1
FROM python:3.13-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# curl is used for HEALTHCHECK, install uv via pip to avoid external GHCR auth issues
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.9.27

WORKDIR /app

# 1) Dependencies only — cached until uv.lock / pyproject.toml change
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project

# 2) Model download script (lightweight stub for Step 1)
COPY scripts/download_models.py scripts/download_models.py
RUN python scripts/download_models.py

# 3) Project code
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

RUN mkdir -p /app/storage

EXPOSE 8501
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1
CMD ["python", "-m", "app.bootstrap"]

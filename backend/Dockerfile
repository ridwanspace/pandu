# ── Build stage: resolve and install with uv ─────────────────────────────────
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

# Optional heavy extras (e.g. --build-arg EXTRAS="--extra parsing --extra rerank-local")
ARG EXTRAS=""

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev ${EXTRAS}

COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
COPY evals ./evals
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev ${EXTRAS}

# ── Runtime stage: slim, non-root ────────────────────────────────────────────
FROM python:3.13-slim-bookworm

RUN groupadd -r pandu && useradd -r -g pandu pandu
WORKDIR /app

COPY --from=builder --chown=pandu:pandu /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1

USER pandu
EXPOSE 8000
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]

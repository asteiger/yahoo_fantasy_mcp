# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install dependencies first so they cache independently of source changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project

COPY pyproject.toml uv.lock README.md LICENSE ./
COPY yahoo_fantasy_mcp ./yahoo_fantasy_mcp
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable


FROM python:3.12-slim

RUN useradd --create-home --uid 1000 app \
    && mkdir /data \
    && chown app:app /data

COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Mount a host directory containing oauth2.json here. The server resolves the
# default --oauth2-file relative to this directory and writes refreshed tokens
# back to it.
WORKDIR /data
VOLUME /data

USER app

ENTRYPOINT ["yahoo-fantasy-mcp"]

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev --no-install-project 2>/dev/null || uv sync --no-dev --no-install-project

COPY python/ ./python/

# Runtime
FROM python:3.12-slim-bookworm

WORKDIR /app

RUN useradd -u 999 -m lyume

COPY --from=builder --chown=lyume:lyume /app/.venv /app/.venv
COPY --chown=lyume:lyume python/ ./python/

ENV PATH="/app/.venv/bin:$PATH"

USER lyume

EXPOSE 1235

CMD ["python", "-m", "uvicorn", "memory_proxy:app", "--host", "0.0.0.0", "--port", "1235"]

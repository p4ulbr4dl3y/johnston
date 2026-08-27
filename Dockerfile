FROM python:3.13-slim
# git is required by tests (git diff/checkpoint/shell) and by tools at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
# Run tests as a non-root user so readonly/permission tests get real EACCES.
RUN useradd -m -u 1000 appuser
COPY . .
RUN chown -R appuser:appuser /app && uv sync --group dev --no-cache
USER appuser

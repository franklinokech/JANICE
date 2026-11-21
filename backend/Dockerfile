# syntax=docker/dockerfile:1

# ---------- Stage 1: build the virtual environment ----------
FROM python:3.13-slim-trixie AS builder

# uv binary from the official image (pinned version)
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install dependencies first: this layer is cached until uv.lock changes
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

# Then copy the code
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# ---------- Stage 2: the small runtime image ----------
FROM python:3.13-slim-trixie AS runtime

# Run as an unprivileged user, never as root
RUN groupadd --system janice \
 && useradd --system --gid janice --no-create-home janice

WORKDIR /app
COPY --from=builder --chown=janice:janice /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=janice.settings.prod

USER janice
EXPOSE 8000

# Docker marks the container unhealthy if the API or its database is down
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health/', timeout=2)"]

CMD ["uvicorn", "janice.asgi:application", "--host", "0.0.0.0", "--port", "8000"]

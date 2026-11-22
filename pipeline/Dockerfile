# syntax=docker/dockerfile:1

# JANICE pipeline image: Dagster code location, webserver and daemon.
# One image, three commands (see compose.yaml):
#   pipeline          dagster code-server start ... (default CMD; runs execute here)
#   dagster-webserver dagster-webserver ...
#   dagster-daemon    dagster-daemon run ...
# The health check is set per service in compose.yaml, because the three
# commands need different checks.

# ---------- Stage 1: build the virtual environment ----------
FROM python:3.13-slim-trixie AS builder

# uv binary from the official image (pinned version, same as the backend)
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install dependencies first: this layer is cached until uv.lock changes
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

# Then copy the code (.dockerignore keeps out .venv, tests, dbt output, secrets)
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# dbt's manifest, built now so containers start without parsing.
# dbt parse needs no database (profiles.yml has no-secret defaults).
RUN .venv/bin/dbt parse --project-dir dbt --profiles-dir dbt --quiet \
 && rm -rf dbt/logs

# ---------- Stage 2: the small runtime image ----------
# Same base as the builder: packages built on trixie need trixie's libraries
FROM python:3.13-slim-trixie AS runtime

# Run as an unprivileged user, never as root. Its home is /app, which it
# owns, so dbt and Dagster can write their small state files there
RUN groupadd --system janice \
 && useradd --system --gid janice --home-dir /app --no-create-home janice

WORKDIR /app
COPY --from=builder --chown=janice:janice /app /app
COPY --chown=janice:janice deploy/dagster.yaml deploy/workspace.yaml /opt/dagster/home/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DAGSTER_HOME=/opt/dagster/home \
    JANICE_DATA_DIR=/data \
    DAGSTER_POSTGRES_DB=dagster \
    POSTGRES_PORT=5432

# Hashed staging files and synthetic data dictionaries live in /data, a volume
RUN mkdir -p /data && chown janice:janice /data /opt/dagster/home

USER janice
EXPOSE 4000

CMD ["dagster", "code-server", "start", "--host", "0.0.0.0", "--port", "4000", \
     "--module-name", "janice_pipeline.definitions"]

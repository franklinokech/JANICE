# 2. Use uv for Python dependency management

Date: 2026-11-21

## Status

Accepted

## Context

The backend needs reproducible installs across laptops, CI, Docker images and
servers. Options considered: pip with requirements files, Poetry, uv.

## Decision

Use uv. Dependencies are declared in `backend/pyproject.toml` and locked in
`backend/uv.lock`, which is always committed. CI and Docker install with
`uv sync --locked`; production images use `--no-dev`.

## Consequences

- Every environment installs identical versions; `--locked` fails if the lock
  file is stale.
- uv also manages the Python version (`.python-version`) and tools
  (`uv tool install`, `uvx`).
- The GitHub Python `.gitignore` template ignores `uv.lock` by default; that
  line must stay removed.

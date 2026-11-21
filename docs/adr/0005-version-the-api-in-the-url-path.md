# 5. Version the API in the URL path

Date: 2026-11-21

## Status

Accepted

## Context

The API will be used by the Vue app, the MCP server and possibly external
clients. Breaking changes must not break existing clients.

## Decision

Use DRF `URLPathVersioning`: all endpoints live under `/api/v1/`. Only
listed versions are allowed; others return 404. Adding fields or endpoints is
not breaking and stays in `v1`; removing or changing them requires `v2`, with
`v1` kept for at least six months.

## Consequences

- The version is visible in every URL and log line.
- Clients pin a version explicitly.
- Each breaking change needs deliberate versioning work.

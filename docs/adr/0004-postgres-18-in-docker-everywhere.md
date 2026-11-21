# 4. Use Postgres 18, in Docker, in every environment

Date: 2026-11-21

## Status

Accepted

## Context

JANICE's warehouse and its row-level security depend on Postgres features.
SQLite was used briefly during the first increment. Postgres 19 had just been
released; backup tools and extensions typically lag a new major version.

## Decision

Use Postgres 18 via the official Docker image in development, CI (service
container) and on servers. Tests run against Postgres, not SQLite.

## Consequences

- Behaviour is identical across environments; RLS can be tested in CI.
- Developers need Docker running to run backend tests.
- Major Postgres upgrades require a planned dump and restore; Dependabot is
  configured to ignore them.

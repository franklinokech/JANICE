# 9. Use Dagster for pipeline orchestration

Date: 2026-11-21

## Status

Accepted

## Context

The pipeline runs a REDCap extract (R), identifier hashing, a Postgres load
and dbt, in order, nightly, with retries, and the CIN data managers need to see
what is fresh and what failed. Cron offers no lineage, history or UI.

## Decision

Use open-source Dagster, self-hosted, in the `pipeline/` project. Pipeline
steps are assets; settings use `dg.Config`. Local development uses the `dg`
CLI (`dg dev`, `dg check defs`, `dg launch`), which supersedes `dagster dev`.

## Consequences

- Data managers get a UI showing asset freshness, run history and logs.
- dbt models can become Dagster assets (dagster-dbt); R runs as a subprocess.
- On servers, Dagster needs a webserver, a daemon and Postgres storage.
- Prefect announced its acquisition of Dagster Labs in July 2026 and said Dagster
  keeps its name, licence and roadmap; review at each major upgrade.

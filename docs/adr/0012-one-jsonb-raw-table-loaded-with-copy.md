# 12. Load every project into one JSONB table, with psycopg COPY

- **Status:** Accepted
- **Date:** 2026-11-22
- **Deciders:** Franklin Okech

## Context

Staging writes one DuckDB file per project, with one text column per REDCap field (526 columns for neonatal). Projects differ in structure, the number of projects is open-ended (ADR 0010), and data dictionaries change over time. The warehouse's `raw` schema has to accept all of this without a code or schema change every time a field or project is added.

The design doc planned to load with DuckDB's `postgres` extension. DuckDB downloads that extension from its own servers the first time it's used. That would need internet access from the KWTRP servers and in CI, or bundling the extension into the image.

## Decision

- **One table for all projects:** `raw.redcap_records`. It has one row per record, or per repeat instance, keyed by `(project, record_id, event, repeat_instrument, repeat_instance)`. The key parts a project doesn't use are blank: classic projects have no events, and projects without repeating instruments have no repeat columns. All other fields go in a `data` JSONB column, with blank values left out.
- **Load with psycopg's `COPY`,** streaming from the staging file in batches of 1,000 rows. psycopg is the same driver the backend uses.
- **One transaction per project:** delete that project's rows, copy the new ones, and record the load in `raw.loads`. Readers see the old rows or the new ones, never a mix, and other projects are untouched.
- **The loader creates the `raw` schema and tables** if they're missing, under an advisory lock, so two projects loading at once can't race.

## Consequences

- A new project or a changed data dictionary needs no warehouse change. dbt picks fields out with `data->>'field'` in one small `stg_<project>` model per project, which also casts types.
- Record IDs can repeat across projects safely, because the project is part of the key.
- No extension download, so it works offline, in CI and on locked-down servers.
- JSONB costs some storage and needs dbt to do the column extraction. At CIN volumes (tens to hundreds of thousands of rows) that's acceptable, and a GIN index can be added if dbt needs one.
- For now each load replaces the whole project. Incremental runs will upsert on the same key, which is why the key is the full REDCap row identity.

## Alternatives considered

- **One wide table per project (`raw.<project>`, one column per field).** It mirrors REDCap, but needs schema changes whenever a dictionary changes, and comes close to Postgres's 1,600-column limit on large projects.
- **DuckDB `postgres` extension.** Neat, but it needs a runtime download, or an image that bundles it, and it's harder to stream in controlled batches.
- **Entity-attribute-value (one row per field value).** Fully generic, but about 500 times more rows, and every dbt model would need to pivot.

# 13. Define each indicator once, in its dbt model's YAML

- **Status:** Accepted
- **Date:** 2026-11-22
- **Deciders:** Franklin Okech

## Context

QI indicators need a precise definition that clinicians can read and approve:
- numerator and denominator
- exclusions
- how missing data is treated
- version and approval status

The same definition must drive three things: the SQL that computes the indicator, the catalogue the MCP server gives the model, and the documentation used for sign-off and the evaluation paper. Kept in separate places (a Word document, a spreadsheet, the SQL), these copies drift apart, and nobody can tell which one is right.

## Decision

- Each indicator's definition lives in **its dbt model's YAML** (`config.meta`), next to the SQL. It covers:
  - `indicator_id`, name, version, status (draft, approved, retired), and `approved_by` and `approved_on`
  - unit, type and desired direction
  - definition, numerator and denominator (each naming its column), exclusions, documentation completeness and breakdowns
  - REDCap fields, rationale and references
- `janice_pipeline.indicators.catalogue` validates the definitions with a strict schema:
  - unknown keys are refused
  - an approved indicator must name who approved it and when
  - the numerator and denominator must be columns of the model
  - indicator IDs must be unique
- `uv run janice-indicators` renders one Markdown page per indicator, plus an index, into `docs/indicators/`. A test fails if those pages are out of date, so CI catches a definition changed without its pages.
- **Rules shared by all indicators** live in a hand-written `docs/indicators/README.md` and are signed off once by the indicator review group.

## Consequences

- One source of truth: the definition a clinician approves is the one the code uses, and every change goes through a reviewed pull request with a version bump.
- Clinicians read plain Markdown pages, not YAML or SQL.
- The MCP server can read the same definitions, through the dbt manifest or this module, without a second catalogue.
- Developers must re-run `janice-indicators` after changing a definition. The test makes forgetting visible.

## Alternatives considered

- **A separate indicator document** (Word or Google Docs): easy for clinicians to edit, but it drifts from the code, and nothing checks that it matches.
- **A dbt seed (CSV) catalogue:** queryable in the warehouse, but awkward for long text, and separate from the model it describes.
- **One ADR per indicator:** ADRs record architectural decisions that are hard to reverse. Indicator definitions are expected to change and be re-approved, and their audience is clinicians.

# JANICE pipeline

Data pipeline code: synthetic data now; REDCap extract, hashing, loading and
Dagster orchestration to follow.

## Setup and tests

```bash
uv sync
uv run pytest
```

## Synthetic data

Generate a synthetic REDCap export (same shape as a real flat CSV export)
from a data dictionary:

```bash
uv run janice-synthetic --dictionary path/to/dictionary.csv \
  --records 500 --seed 1 --out path/to/synthetic.csv
```

- Accepts the dictionary downloaded from REDCap (Project Setup → Data
  Dictionary) or the API metadata export.
- Identifiers are always `SYNTHETIC-nnnnnn`; the same seed gives the same data.
- Keep dictionaries and generated files outside the repository.

Not yet handled: branching logic, repeating instruments, and cross-field
rules (e.g. discharge after admission).

## Dagster

```bash
uv run dg check defs    # validate the definitions
uv run dg list defs     # list assets
uv run dg dev           # local UI at http://localhost:3000
```

Assets so far: `synthetic_redcap_export` (group `synthetic`).

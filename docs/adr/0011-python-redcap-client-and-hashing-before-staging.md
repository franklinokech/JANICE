# 11. Extract with our own Python REDCap client, and hash before staging

- **Status:** Accepted
- **Date:** 2026-11-22
- **Deciders:** Franklin Okech
- **Supersedes:** the redquack extract in the original design (and any earlier ADR choosing it)

## Context

The original design extracted data with redquack, an R package that copies REDCap data into DuckDB in chunks. Identifiers were then hashed inside DuckDB, so the staging file briefly held cleartext identifiers on an encrypted volume.

The rest of the pipeline is Python (Dagster, hashing, tests). With redquack, the pipeline image would need R as well, the extract would run as a subprocess, and it would be tested separately. A JANICE API token was available for each project.

## Decision

1. **Extract with a small Python client** (`janice_pipeline.redcap.RedcapClient`, built on httpx). It covers exactly what JANICE needs:
   - the data dictionary
   - record IDs
   - records in batches of 500
   - incremental export with `dateRangeBegin`, sent in the REDCap server's time zone (UTC on the KWTRP server)

   The token travels only in an HTTPS POST body, and never appears in logs, errors or `repr()`.
2. **Hash before staging.** Each batch is hashed in memory with HMAC-SHA256 before it is written. Flagged free-text and checkbox fields are dropped. No file, including the DuckDB staging file, ever holds cleartext identifiers, and a test checks this.

## Consequences

- One language and one container image for the pipeline. The client is tested with a fake REDCap server (`httpx.MockTransport`), with no network or token.
- Cleartext identifiers exist only in memory, one batch at a time. There is no cleartext file to encrypt, clean up or describe in the DPIA, and the staging files can be excluded from backups because every run rebuilds them.
- JANICE maintains its own client, but its scope is small, and REDCap's API is stable.
- Each staging table is rebuilt in one transaction, so a failed run leaves the previous table intact.

## Alternatives considered

- **redquack (R) into DuckDB, then hash in DuckDB.** Mature chunked transfer, but it adds R to the image and a subprocess boundary, and briefly puts cleartext on disk.
- **PyCap or other Python REDCap libraries.** Broader than needed, and they still leave batching, time zones and token handling for JANICE to verify.

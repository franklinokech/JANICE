"""Dagster asset that stages each REDCap unit into DuckDB, identifiers hashed.

One asset, ``redcap_staging``, with one partition per unit (neonatal,
paediatrics, maternity), so each unit can be run, retried and watched on its own.

Secrets never enter Dagster's config, where the UI would show them: the REDCap
tokens and the hashing key are read from the environment when the run starts.

Where records come from is a resource:
- RedcapSourceResource: the real REDCap API (staging and production servers).
- SyntheticSourceResource: synthetic records built from a data dictionary
  (laptops and CI, where real data is not allowed).
"""

import os
from pathlib import Path

import dagster as dg

from janice_pipeline.privacy.hashing import MIN_KEY_BYTES
from janice_pipeline.redcap.client import DEFAULT_SERVER_TIMEZONE, RedcapClient
from janice_pipeline.staging.duckdb_stage import (
    DEFAULT_BATCH_SIZE,
    UNITS,
    RecordSource,
    stage_unit,
)
from janice_pipeline.synthetic.dictionary import read_data_dictionary
from janice_pipeline.synthetic.records import generate_records

HASH_KEY_ENV = "JANICE_HASH_KEY"
UNIT_PARTITIONS = dg.StaticPartitionsDefinition(sorted(UNITS))


class RecordSourceResource(dg.ConfigurableResource):
    """Where a unit's records come from."""

    def for_unit(self, unit: str) -> RecordSource:
        raise NotImplementedError


class RedcapSourceResource(RecordSourceResource):
    """The real REDCap API. Tokens come from REDCAP_TOKEN_<UNIT> at run time."""

    api_url: str
    server_timezone: str = DEFAULT_SERVER_TIMEZONE

    def for_unit(self, unit: str) -> RecordSource:
        variable = f"REDCAP_TOKEN_{unit.upper()}"
        token = os.environ.get(variable, "")
        if not token:
            raise dg.Failure(f"No REDCap token for {unit}: set {variable} in the environment")
        return RedcapClient(self.api_url, token, server_timezone=self.server_timezone)


class SyntheticSourceResource(RecordSourceResource):
    """Synthetic records from <dictionary_dir>/<unit>_dictionary.csv. No real data."""

    dictionary_dir: str
    records: int = 1000
    seed: int = 42

    def for_unit(self, unit: str) -> RecordSource:
        path = Path(self.dictionary_dir) / f"{unit}_dictionary.csv"
        if not path.exists():
            raise dg.Failure(f"No data dictionary for {unit}: expected {path}")
        fields = read_data_dictionary(path)
        _, rows = generate_records(fields, count=self.records, seed=self.seed)
        return _InMemorySource(fields, rows)


class _InMemorySource:
    def __init__(self, fields, rows):
        self._fields, self._rows = fields, rows

    def export_metadata(self):
        return self._fields

    def export_record_ids(self, record_id_field):
        return [row[record_id_field] for row in self._rows]

    def export_records(self, record_ids, *, batch_size):
        wanted = set(record_ids)
        rows = [row for row in self._rows if row[self._fields[0].name] in wanted]
        for start in range(0, len(rows), batch_size):
            yield rows[start : start + batch_size]


class StagingResource(dg.ConfigurableResource):
    """Where staged tables are written, and how identifiers are protected."""

    data_dir: str
    keep_in_clear: list[str] = ["hosp_id"]
    batch_size: int = DEFAULT_BATCH_SIZE

    def db_path(self, unit: str) -> Path:
        """One DuckDB file per unit: DuckDB allows one writer per file, so units
        staged at the same time must never share one."""
        return Path(self.data_dir) / f"staging_{unit}.duckdb"

    def hash_key(self) -> bytes:
        """The HMAC key from JANICE_HASH_KEY (64 hex characters), read at run time."""
        value = os.environ.get(HASH_KEY_ENV, "")
        if not value:
            raise dg.Failure(f"No hashing key: set {HASH_KEY_ENV} in the environment")
        try:
            key = bytes.fromhex(value)
        except ValueError:
            key = b""
        if len(key) < MIN_KEY_BYTES:
            raise dg.Failure(
                f"{HASH_KEY_ENV} must be at least {MIN_KEY_BYTES * 2} hex characters "
                f"({MIN_KEY_BYTES * 2 * 4} bits), e.g. from secrets.token_hex(32)"
            )
        return key


@dg.asset(
    partitions_def=UNIT_PARTITIONS,
    group_name="ingestion",
    description="One REDCap unit staged in DuckDB as raw_<unit>. Flagged identifiers are "
    "hashed (or dropped, for free text and checkboxes) before anything is written.",
    kinds={"python", "duckdb"},
)
def redcap_staging(
    context: dg.AssetExecutionContext,
    source: RecordSourceResource,
    staging: StagingResource,
) -> dg.MaterializeResult:
    unit = context.partition_key
    db_path = staging.db_path(unit)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    result = stage_unit(
        source.for_unit(unit),
        unit=unit,
        db_path=db_path,
        key=staging.hash_key(),
        keep_in_clear=set(staging.keep_in_clear),
        batch_size=staging.batch_size,
    )
    context.log.info(f"Staged {result.records} {unit} records into {result.table}")
    return dg.MaterializeResult(
        metadata={
            "table": result.table,
            "records": result.records,
            "rows": result.rows,
            "columns": result.columns,
            "path": dg.MetadataValue.path(str(db_path)),
        }
    )

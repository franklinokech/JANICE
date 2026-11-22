"""Dagster asset that stages each registered REDCap project into DuckDB.

One asset, ``redcap_staging``, with one partition per project in the registry
(projects/projects.yaml), so each project can be run, retried and watched on
its own. Adding a project to the registry adds a partition: no code changes.

Secrets never enter Dagster's config, where the UI would show them: REDCap
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
from janice_pipeline.projects.registry import Project
from janice_pipeline.redcap.client import RedcapClient
from janice_pipeline.staging.duckdb_stage import DEFAULT_BATCH_SIZE, RecordSource, stage_project
from janice_pipeline.synthetic.dictionary import read_data_dictionary
from janice_pipeline.synthetic.records import generate_records

HASH_KEY_ENV = "JANICE_HASH_KEY"
API_URL_ENV = "REDCAP_API_URL"


class RecordSourceResource(dg.ConfigurableResource):
    """Where a project's records come from."""

    def for_project(self, project: Project) -> RecordSource:
        raise NotImplementedError


class RedcapSourceResource(RecordSourceResource):
    """The real REDCap API. Each project's token comes from its env variable at run time."""

    default_api_url: str = ""

    def for_project(self, project: Project) -> RecordSource:
        url = project.api_url or self.default_api_url
        if not url:
            raise dg.Failure(
                f"No REDCap API URL for {project.key}: set api_url in the registry "
                f"or {API_URL_ENV} in the environment"
            )
        token = os.environ.get(project.token_variable, "")
        if not token:
            raise dg.Failure(
                f"No REDCap token for {project.key}: set {project.token_variable} "
                "in the environment"
            )
        return RedcapClient(url, token, server_timezone=project.server_timezone)


class SyntheticSourceResource(RecordSourceResource):
    """Synthetic records from <dictionary_dir>/<project dictionary>. No real data."""

    dictionary_dir: str
    records: int = 1000
    seed: int = 42

    def for_project(self, project: Project) -> RecordSource:
        path = Path(self.dictionary_dir) / project.dictionary_filename
        if not path.exists():
            raise dg.Failure(f"No data dictionary for {project.key}: expected {path}")
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
    """Where staged tables are written, and the key that protects identifiers."""

    data_dir: str
    batch_size: int = DEFAULT_BATCH_SIZE

    def db_path(self, project_key: str) -> Path:
        """One DuckDB file per project: DuckDB allows one writer per file, so
        projects staged at the same time must never share one."""
        return Path(self.data_dir) / f"staging_{project_key}.duckdb"

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


def project_partitions(projects: list[Project]) -> dg.StaticPartitionsDefinition:
    """One partition per project, in registry order. Shared by every per-project asset."""
    return dg.StaticPartitionsDefinition([project.key for project in projects])


def build_staging_asset(projects: list[Project]) -> dg.AssetsDefinition:
    """The staging asset, with one partition per project."""
    by_key = {project.key: project for project in projects}

    @dg.asset(
        name="redcap_staging",
        partitions_def=project_partitions(projects),
        group_name="ingestion",
        description="One REDCap project staged in DuckDB as raw_<project>. Flagged "
        "identifiers are hashed (or dropped, for free text and checkboxes) before anything "
        "is written; each project's site field stays readable.",
        kinds={"python", "duckdb"},
    )
    def redcap_staging(
        context: dg.AssetExecutionContext,
        source: RecordSourceResource,
        staging: StagingResource,
    ) -> dg.MaterializeResult:
        project = by_key[context.partition_key]
        db_path = staging.db_path(project.key)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        result = stage_project(
            source.for_project(project),
            project_key=project.key,
            db_path=db_path,
            key=staging.hash_key(),
            keep_in_clear=project.clear_fields,
            required_fields={project.site_field},
            batch_size=staging.batch_size,
        )
        context.log.info(f"Staged {result.records} {project.key} records into {result.table}")
        return dg.MaterializeResult(
            metadata={
                "table": result.table,
                "records": result.records,
                "rows": result.rows,
                "columns": result.columns,
                "site_field": project.site_field,
                "path": dg.MetadataValue.path(str(db_path)),
            }
        )

    return redcap_staging

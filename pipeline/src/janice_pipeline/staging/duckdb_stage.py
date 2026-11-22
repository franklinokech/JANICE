"""Stage one REDCap project into a local DuckDB file, identifiers already hashed.

Each batch of records is hashed in memory (privacy.hashing.protect_row) before
it is written, so cleartext identifiers never reach the disk. Every value is
stored as text, exactly as REDCap sent it; typing is dbt's job, with tests.

A run replaces the project's table inside one transaction: if any batch fails,
the previous table is left as it was.

Incremental runs pass ``changed_since`` and stage only the records created or
changed since then. The file records what it holds in a one-row table,
_stage_info (mode "full" or "changes", started_at, changed_since), so the load
knows whether to replace the whole project or only those records, and which
watermark to keep for the next run. Incremental runs also list the records
deleted in REDCap since the same moment (_deleted_records), hashed like the
staged record IDs when the project flags its record ID, so the load can remove
them.
"""

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import duckdb

from janice_pipeline.privacy.hashing import fields_to_protect, hash_identifier, protect_row
from janice_pipeline.projects.registry import PROJECT_KEY_PATTERN
from janice_pipeline.synthetic.dictionary import Field

DEFAULT_BATCH_SIZE = 500


class RecordSource(Protocol):
    """What staging needs from REDCap: RedcapClient, or a fake in tests."""

    def export_metadata(self) -> list[Field]: ...

    def export_record_ids(
        self, record_id_field: str, *, changed_since: datetime | None = None
    ) -> list[str]: ...

    def export_records(
        self, record_ids: Sequence[str], *, batch_size: int
    ) -> Iterator[list[dict[str, str]]]: ...

    def export_deleted_record_ids(self, since: datetime) -> list[str]: ...


@dataclass(frozen=True)
class StageResult:
    project: str
    table: str
    records: int  # distinct record IDs
    rows: int  # rows written; more than records when instruments repeat
    columns: int
    mode: str = "full"  # "full" or "changes"
    deleted: int = 0  # records deleted in REDCap since changed_since


def stage_project(
    source: RecordSource,
    *,
    project_key: str,
    db_path: Path,
    key: bytes,
    keep_in_clear: set[str] = frozenset(),
    required_fields: set[str] = frozenset(),
    batch_size: int = DEFAULT_BATCH_SIZE,
    changed_since: datetime | None = None,
) -> StageResult:
    """Export one project's records, hash identifiers, write raw_<project_key>.

    Every record, or with ``changed_since`` only those created or changed
    since then. ``required_fields`` must exist in the project's data
    dictionary (e.g. its site field); if any is missing, nothing is written.
    """
    # Checked here too, not only in the registry: the key becomes a table name
    if not re.fullmatch(PROJECT_KEY_PATTERN, project_key):
        raise ValueError(f"Unsafe project key {project_key!r}")
    table = f"raw_{project_key}"
    mode = "full" if changed_since is None else "changes"
    # Taken before the first request: records changed while this run reads
    # REDCap are then caught by the next run
    started_at = datetime.now(UTC)

    fields = source.export_metadata()
    missing = sorted(set(required_fields) - {f.name for f in fields})
    if missing:
        raise ValueError(f"Project {project_key} has no field(s) {missing} in its data dictionary")
    record_id_field = fields[0].name
    if changed_since is None:
        record_ids = source.export_record_ids(record_id_field)
        deleted_ids: list[str] = []  # a full load replaces the project anyway
    else:
        record_ids = source.export_record_ids(record_id_field, changed_since=changed_since)
        deleted_ids = source.export_deleted_record_ids(changed_since)
        # Match the staged record IDs, which are hashed if the project flags them
        id_field = fields[0]
        if id_field.name in fields_to_protect(fields, keep_in_clear):
            deleted_ids = [hash_identifier(i, key, id_field) for i in deleted_ids]

    con = duckdb.connect(str(db_path))
    try:
        con.begin()
        con.execute(f"DROP TABLE IF EXISTS {table}")
        columns: list[str] | None = None
        rows = 0
        for batch in source.export_records(record_ids, batch_size=batch_size):
            protected = [protect_row(row, fields, key, keep_in_clear) for row in batch]
            if not protected:
                continue
            if columns is None:
                columns = list(protected[0])
                _create_table(con, table, columns)
            _insert(con, table, columns, protected)
            rows += len(protected)
        if columns is None:
            columns = [record_id_field]
            _create_table(con, table, columns)
        con.execute("DROP TABLE IF EXISTS _deleted_records")
        con.execute("CREATE TABLE _deleted_records (record_id VARCHAR)")
        if deleted_ids:
            con.executemany("INSERT INTO _deleted_records VALUES (?)", [[i] for i in deleted_ids])
        con.execute("DROP TABLE IF EXISTS _stage_info")
        con.execute(
            "CREATE TABLE _stage_info AS SELECT ?::VARCHAR AS mode, "
            "?::TIMESTAMPTZ AS started_at, ?::TIMESTAMPTZ AS changed_since",
            [mode, started_at, changed_since],
        )
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()

    return StageResult(
        project=project_key,
        table=table,
        records=len(record_ids),
        rows=rows,
        columns=len(columns),
        mode=mode,
        deleted=len(deleted_ids),
    )


def _quote(name: str) -> str:
    """A column name as a DuckDB identifier, safe whatever REDCap calls it."""
    return '"' + name.replace('"', '""') + '"'


def _create_table(con: duckdb.DuckDBPyConnection, table: str, columns: list[str]) -> None:
    column_sql = ", ".join(f"{_quote(c)} VARCHAR" for c in columns)
    con.execute(f"CREATE TABLE {table} ({column_sql})")


def _insert(
    con: duckdb.DuckDBPyConnection, table: str, columns: list[str], rows: list[dict[str, str]]
) -> None:
    for row in rows:
        if row.keys() != set(columns):
            raise ValueError("REDCap returned different columns in a later batch")
    placeholders = ", ".join("?" for _ in columns)
    con.executemany(
        # Safe: table comes from a checked project key and placeholders are only "?"
        f"INSERT INTO {table} VALUES ({placeholders})",  # noqa: S608
        [[row[c] for c in columns] for row in rows],
    )

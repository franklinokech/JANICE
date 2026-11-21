"""Stage one REDCap unit into a local DuckDB file, identifiers already hashed.

Each batch of records is hashed in memory (privacy.hashing.protect_row) before
it is written, so cleartext identifiers never reach the disk. Every value is
stored as text, exactly as REDCap sent it; typing is dbt's job, with tests.

A run replaces the unit's table inside one transaction: if any batch fails,
the previous table is left as it was.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import duckdb

from janice_pipeline.privacy.hashing import protect_row
from janice_pipeline.synthetic.dictionary import Field

# The unit names a table, so only these values are ever accepted
UNITS = frozenset({"neonatal", "paediatrics", "maternity"})
DEFAULT_BATCH_SIZE = 500


class RecordSource(Protocol):
    """What staging needs from REDCap: RedcapClient, or a fake in tests."""

    def export_metadata(self) -> list[Field]: ...

    def export_record_ids(self, record_id_field: str) -> list[str]: ...

    def export_records(
        self, record_ids: Sequence[str], *, batch_size: int
    ) -> Iterator[list[dict[str, str]]]: ...


@dataclass(frozen=True)
class StageResult:
    unit: str
    table: str
    records: int  # distinct record IDs
    rows: int  # rows written; more than records when instruments repeat
    columns: int


def stage_unit(
    source: RecordSource,
    *,
    unit: str,
    db_path: Path,
    key: bytes,
    keep_in_clear: set[str] = frozenset(),
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> StageResult:
    """Export every record of one unit, hash identifiers, write raw_<unit>."""
    if unit not in UNITS:
        raise ValueError(f"Unknown unit {unit!r}; expected one of {sorted(UNITS)}")
    table = f"raw_{unit}"

    fields = source.export_metadata()
    record_id_field = fields[0].name
    record_ids = source.export_record_ids(record_id_field)

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
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()

    return StageResult(
        unit=unit, table=table, records=len(record_ids), rows=rows, columns=len(columns)
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
        # Safe: table comes from UNITS and placeholders are only "?"; values are bound
        f"INSERT INTO {table} VALUES ({placeholders})",  # noqa: S608
        [[row[c] for c in columns] for row in rows],
    )

"""Load a project's staging table into the Postgres warehouse.

Every project lands in ONE table, <schema>.redcap_records (schema "raw" by
default): one row per record, or per repeat instance, keyed by
(project, record_id, event, repeat_instrument, repeat_instance), with all other
fields in a JSONB column. A new project, or a changed data dictionary, needs no
change here; dbt picks the fields it needs out of ``data``.

A load replaces one project's rows inside one transaction, so readers see the
old rows or the new ones, never a mix, and other projects are untouched. A
staging file holding only changed records (mode "changes", see _stage_info)
replaces just those records, every row of each, so a removed repeat instance
disappears too, and removes the records it lists as deleted in REDCap
(_deleted_records). Each load stores the run's start time in
<schema>.watermarks, so the next run asks REDCap only for what changed since.
Each load is recorded in <schema>.loads, and each project's settings that dbt
needs (which field in ``data`` holds its site) are kept in <schema>.projects.

Values arrive already hashed (staging hashes before writing), and blank values
are left out of ``data``: REDCap exports a blank for "not filled in", and
data->>'field' is NULL either way.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import duckdb
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from janice_pipeline.projects.registry import PROJECT_KEY_PATTERN

DEFAULT_SCHEMA = "raw"
SCHEMA_PATTERN = r"^[a-z_][a-z0-9_]{0,62}$"
FETCH_SIZE = 1000

# REDCap's own columns that identify a row, rather than hold data. Classic
# projects have no events, and projects without repeating instruments have no
# repeat columns: those parts of the key are then blank.
EVENT = "redcap_event_name"
REPEAT_INSTRUMENT = "redcap_repeat_instrument"
REPEAT_INSTANCE = "redcap_repeat_instance"
KEY_COLUMNS = (EVENT, REPEAT_INSTRUMENT, REPEAT_INSTANCE)

# Serialises table creation, so two projects loading at once cannot both try
# to create the same table
DDL_LOCK_ID = 0x4A414E49  # "JANI"


@dataclass(frozen=True)
class PostgresSettings:
    host: str
    port: int
    dbname: str
    user: str
    password: str = field(repr=False)  # never printed or logged

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "PostgresSettings":
        """The same POSTGRES_* variables the backend uses."""
        missing = [
            v for v in ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD") if not env.get(v)
        ]
        if missing:
            raise ValueError(f"Set {', '.join(missing)} in the environment")
        return cls(
            host=env.get("POSTGRES_HOST", "localhost"),
            port=int(env.get("POSTGRES_PORT", "5432")),
            dbname=env["POSTGRES_DB"],
            user=env["POSTGRES_USER"],
            password=env["POSTGRES_PASSWORD"],
        )

    def connect_kwargs(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "dbname": self.dbname,
            "user": self.user,
            "password": self.password,
        }


@dataclass(frozen=True)
class LoadResult:
    project: str
    records: int  # distinct record IDs
    rows: int  # rows loaded; more than records when instruments repeat
    mode: str = "full"  # "full" or "changes"
    deleted: int = 0  # records removed because they were deleted in REDCap


def load_project(
    staging_db: Path,
    *,
    project_key: str,
    settings: PostgresSettings,
    site_field: str,
    schema: str = DEFAULT_SCHEMA,
) -> LoadResult:
    """Replace one project's rows in <schema>.redcap_records with its staging table.

    ``site_field`` is recorded in <schema>.projects, so dbt can read each
    project's site from the right field in ``data``.
    """
    if not re.fullmatch(PROJECT_KEY_PATTERN, project_key):
        raise ValueError(f"Unsafe project key {project_key!r}")
    if not re.fullmatch(SCHEMA_PATTERN, schema):
        raise ValueError(f"Unsafe schema name {schema!r}")
    table = f"raw_{project_key}"

    with duckdb.connect(str(staging_db), read_only=True) as staging:
        tables = {row[0] for row in staging.execute("SHOW TABLES").fetchall()}
        if table not in tables:
            raise ValueError(f"No staging table {table} in {staging_db}")
        columns = [row[0] for row in staging.execute(f"DESCRIBE {table}").fetchall()]
        record_id_column = columns[0]  # stage_project writes the record ID first
        mode, started_at = _stage_info(staging, tables)
        deleted_ids = (
            [row[0] for row in staging.execute("SELECT record_id FROM _deleted_records").fetchall()]
            if "_deleted_records" in tables
            else []
        )
        staged_ids = [
            row[0]
            for row in staging.execute(
                f'SELECT DISTINCT "{record_id_column}" FROM {table}'  # noqa: S608 (checked key)
            ).fetchall()
        ]
        # Deleted in REDCap and not created again since: these leave for good
        removed = sorted(set(deleted_ids) - set(staged_ids)) if mode == "changes" else []
        # Last query on this connection: a DuckDB connection holds one result
        # at a time, and the copy below streams from this one
        cursor = staging.execute(f"SELECT * FROM {table}")  # noqa: S608 (checked key)

        with psycopg.connect(**settings.connect_kwargs()) as pg, pg.transaction():
            _ensure_tables(pg, schema)
            if mode == "full":
                pg.execute(
                    sql.SQL("DELETE FROM {}.redcap_records WHERE project = %s").format(
                        sql.Identifier(schema)
                    ),
                    (project_key,),
                )
            else:
                # Deleted records go; changed records go too and are copied back
                # below, so a record deleted and created again keeps its new rows
                pg.execute(
                    sql.SQL(
                        "DELETE FROM {}.redcap_records WHERE project = %s AND record_id = ANY(%s)"
                    ).format(sql.Identifier(schema)),
                    (project_key, deleted_ids + staged_ids),
                )
            records: set[str] = set()
            rows = 0
            copy_sql = sql.SQL(
                "COPY {}.redcap_records "
                "(project, record_id, event, repeat_instrument, repeat_instance, data) "
                "FROM STDIN"
            ).format(sql.Identifier(schema))
            with pg.cursor().copy(copy_sql) as copy:
                while batch := cursor.fetchmany(FETCH_SIZE):
                    for values in batch:
                        row = dict(zip(columns, values, strict=True))
                        record_id = row.pop(record_id_column)
                        key = [row.pop(c, "") or "" for c in KEY_COLUMNS]
                        data = {k: v for k, v in row.items() if v not in (None, "")}
                        copy.write_row((project_key, record_id, *key, Jsonb(data)))
                        records.add(record_id)
                        rows += 1
            pg.execute(
                sql.SQL(
                    "INSERT INTO {}.loads (project, records, rows, mode, deleted) "
                    "VALUES (%s, %s, %s, %s, %s)"
                ).format(sql.Identifier(schema)),
                (project_key, len(records), rows, mode, len(removed)),
            )
            if started_at is not None:
                pg.execute(
                    sql.SQL(
                        "INSERT INTO {}.watermarks (project, watermark, mode) VALUES (%s, %s, %s) "
                        "ON CONFLICT (project) DO UPDATE SET watermark = EXCLUDED.watermark, "
                        "mode = EXCLUDED.mode, updated_at = now()"
                    ).format(sql.Identifier(schema)),
                    (project_key, started_at, mode),
                )
            pg.execute(
                sql.SQL(
                    "INSERT INTO {}.projects (project, site_field) VALUES (%s, %s) "
                    "ON CONFLICT (project) DO UPDATE "
                    "SET site_field = EXCLUDED.site_field, updated_at = now()"
                ).format(sql.Identifier(schema)),
                (project_key, site_field),
            )

    return LoadResult(
        project=project_key, records=len(records), rows=rows, mode=mode, deleted=len(removed)
    )


def read_watermark(
    settings: PostgresSettings, project_key: str, *, schema: str = DEFAULT_SCHEMA
) -> datetime | None:
    """When the last successful load's staging run started, or None (load everything)."""
    if not re.fullmatch(SCHEMA_PATTERN, schema):
        raise ValueError(f"Unsafe schema name {schema!r}")
    with psycopg.connect(**settings.connect_kwargs()) as pg:
        exists = pg.execute("SELECT to_regclass(%s)", (f"{schema}.watermarks",)).fetchone()[0]
        if exists is None:
            return None  # nothing has ever been loaded
        row = pg.execute(
            sql.SQL("SELECT watermark FROM {}.watermarks WHERE project = %s").format(
                sql.Identifier(schema)
            ),
            (project_key,),
        ).fetchone()
    return row[0] if row else None


def _stage_info(staging: duckdb.DuckDBPyConnection, tables: set[str]):
    """(mode, started_at) from the staging file. Files staged before incremental
    loading have no _stage_info: they hold every record, start time unknown."""
    if "_stage_info" not in tables:
        return "full", None
    mode, started_at = staging.execute("SELECT mode, started_at FROM _stage_info").fetchone()
    if mode not in ("full", "changes"):
        raise ValueError(f"Unknown staging mode {mode!r}")
    return mode, started_at


def _ensure_tables(pg: psycopg.Connection, schema: str) -> None:
    pg.execute("SELECT pg_advisory_xact_lock(%s)", (DDL_LOCK_ID,))
    name = sql.Identifier(schema)
    pg.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(name))
    pg.execute(
        sql.SQL(
            """
            CREATE TABLE IF NOT EXISTS {}.redcap_records (
                project           text        NOT NULL,
                record_id         text        NOT NULL,
                event             text        NOT NULL DEFAULT '',
                repeat_instrument text        NOT NULL DEFAULT '',
                repeat_instance   text        NOT NULL DEFAULT '',
                data              jsonb       NOT NULL,
                loaded_at         timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (project, record_id, event, repeat_instrument, repeat_instance)
            )
            """
        ).format(name)
    )
    pg.execute(
        sql.SQL(
            """
            CREATE TABLE IF NOT EXISTS {}.loads (
                id        bigserial   PRIMARY KEY,
                project   text        NOT NULL,
                records   integer     NOT NULL,
                rows      integer     NOT NULL,
                loaded_at timestamptz NOT NULL DEFAULT now()
            )
            """
        ).format(name)
    )
    pg.execute(
        sql.SQL(
            """
            CREATE TABLE IF NOT EXISTS {}.projects (
                project    text        PRIMARY KEY,
                site_field text        NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT now()
            )
            """
        ).format(name)
    )
    # Added with incremental loading; ADD COLUMN IF NOT EXISTS upgrades
    # warehouses created before it
    pg.execute(sql.SQL("ALTER TABLE {}.loads ADD COLUMN IF NOT EXISTS mode text").format(name))
    pg.execute(
        sql.SQL("ALTER TABLE {}.loads ADD COLUMN IF NOT EXISTS deleted integer").format(name)
    )
    pg.execute(
        sql.SQL(
            """
            CREATE TABLE IF NOT EXISTS {}.watermarks (
                project    text        PRIMARY KEY,
                watermark  timestamptz NOT NULL,
                mode       text        NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT now()
            )
            """
        ).format(name)
    )

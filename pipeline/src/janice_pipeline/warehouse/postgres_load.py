"""Load a project's staging table into the Postgres warehouse.

Every project lands in ONE table, <schema>.redcap_records (schema "raw" by
default): one row per record, or per repeat instance, keyed by
(project, record_id, event, repeat_instrument, repeat_instance), with all other
fields in a JSONB column. A new project, or a changed data dictionary, needs no
change here; dbt picks the fields it needs out of ``data``.

A load replaces one project's rows inside one transaction, so readers see the
old rows or the new ones, never a mix, and other projects are untouched. Each
load is recorded in <schema>.loads, and each project's settings that dbt needs
(which field in ``data`` holds its site) are kept in <schema>.projects.

Values arrive already hashed (staging hashes before writing), and blank values
are left out of ``data``: REDCap exports a blank for "not filled in", and
data->>'field' is NULL either way.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
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
        cursor = staging.execute(f"SELECT * FROM {table}")  # noqa: S608 (checked key)

        with psycopg.connect(**settings.connect_kwargs()) as pg, pg.transaction():
            _ensure_tables(pg, schema)
            pg.execute(
                sql.SQL("DELETE FROM {}.redcap_records WHERE project = %s").format(
                    sql.Identifier(schema)
                ),
                (project_key,),
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
                sql.SQL("INSERT INTO {}.loads (project, records, rows) VALUES (%s, %s, %s)").format(
                    sql.Identifier(schema)
                ),
                (project_key, len(records), rows),
            )
            pg.execute(
                sql.SQL(
                    "INSERT INTO {}.projects (project, site_field) VALUES (%s, %s) "
                    "ON CONFLICT (project) DO UPDATE "
                    "SET site_field = EXCLUDED.site_field, updated_at = now()"
                ).format(sql.Identifier(schema)),
                (project_key, site_field),
            )

    return LoadResult(project=project_key, records=len(records), rows=rows)


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

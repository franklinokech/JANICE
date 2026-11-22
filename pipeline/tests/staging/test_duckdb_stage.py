"""Tests for staging a REDCap project into DuckDB.

A fake REDCap (FakeSource) serves synthetic records, so no network, token or
real patient data is needed. The rule these tests protect: identifiers are
hashed in memory, batch by batch, so cleartext never reaches the DuckDB file.
"""

from datetime import UTC, datetime, timedelta

import duckdb
import pytest

from janice_pipeline.privacy.hashing import hash_identifier
from janice_pipeline.staging.duckdb_stage import stage_project
from janice_pipeline.synthetic.dictionary import fields_from_rows
from janice_pipeline.synthetic.records import generate_records

KEY = b"k" * 32  # a fake 32-byte hashing key, for tests only

FIELDS = fields_from_rows(
    [
        {"field_name": "record_id", "form_name": "admission", "field_type": "text"},
        {
            "field_name": "hosp_id",
            "form_name": "admission",
            "field_type": "text",
            "identifier": "y",
        },
        {
            "field_name": "ip_number",
            "form_name": "admission",
            "field_type": "text",
            "identifier": "y",
        },
        {
            "field_name": "outcome",
            "form_name": "discharge",
            "field_type": "radio",
            "select_choices_or_calculations": "1, Alive | 2, Died",
        },
    ]
)


class FakeSource:
    """Stands in for RedcapClient, serving synthetic records."""

    def __init__(self, count=5, fail_on_batch=None):
        _, self.rows = generate_records(FIELDS, count=count, seed=1)
        self.fail_on_batch = fail_on_batch
        self.batch_sizes = []

    def export_metadata(self):
        return FIELDS

    def export_record_ids(self, record_id_field):
        return [row[record_id_field] for row in self.rows]

    def export_records(self, record_ids, *, batch_size):
        for number, start in enumerate(range(0, len(record_ids), batch_size), start=1):
            if number == self.fail_on_batch:
                raise RuntimeError("REDCap went away")
            batch = record_ids[start : start + batch_size]
            self.batch_sizes.append(len(batch))
            yield [row for row in self.rows if row["record_id"] in batch]


def query(db_path, sql):
    with duckdb.connect(str(db_path), read_only=True) as con:
        return con.execute(sql).fetchall()


def test_every_record_is_staged_in_the_projects_raw_table(tmp_path):
    db = tmp_path / "staging.duckdb"

    result = stage_project(FakeSource(count=5), project_key="neonatal", db_path=db, key=KEY)

    assert result.records == 5
    assert result.rows == 5
    assert query(db, "SELECT count(*) FROM raw_neonatal") == [(5,)]


def test_records_are_fetched_in_batches(tmp_path):
    source = FakeSource(count=5)

    stage_project(
        source, project_key="neonatal", db_path=tmp_path / "s.duckdb", key=KEY, batch_size=2
    )

    assert source.batch_sizes == [2, 2, 1]


def test_flagged_identifiers_are_hashed_before_they_reach_duckdb(tmp_path):
    db = tmp_path / "staging.duckdb"
    source = FakeSource(count=3)

    stage_project(source, project_key="neonatal", db_path=db, key=KEY)

    staged = {r[0] for r in query(db, "SELECT ip_number FROM raw_neonatal")}
    cleartext = {row["ip_number"] for row in source.rows}
    assert staged.isdisjoint(cleartext)
    assert staged == {hash_identifier(value, KEY) for value in cleartext}


def test_fields_kept_in_clear_are_not_hashed(tmp_path):
    # hosp_id is flagged in REDCap but must stay readable: it is how rows are
    # filtered by site
    db = tmp_path / "staging.duckdb"
    source = FakeSource(count=3)

    stage_project(source, project_key="neonatal", db_path=db, key=KEY, keep_in_clear={"hosp_id"})

    staged = {r[0] for r in query(db, "SELECT hosp_id FROM raw_neonatal")}
    assert staged == {row["hosp_id"] for row in source.rows}


def test_all_values_are_stored_as_text(tmp_path):
    # Typing (dates, numbers) is dbt's job, with tests; staging keeps exactly
    # what REDCap sent
    db = tmp_path / "staging.duckdb"
    stage_project(FakeSource(), project_key="neonatal", db_path=db, key=KEY)

    types = {r[1] for r in query(db, "DESCRIBE raw_neonatal")}
    assert types == {"VARCHAR"}


def test_a_rerun_replaces_the_table_rather_than_adding_duplicates(tmp_path):
    db = tmp_path / "staging.duckdb"
    stage_project(FakeSource(count=5), project_key="neonatal", db_path=db, key=KEY)

    stage_project(FakeSource(count=3), project_key="neonatal", db_path=db, key=KEY)

    assert query(db, "SELECT count(*) FROM raw_neonatal") == [(3,)]


def test_a_failed_run_leaves_the_previous_table_untouched(tmp_path):
    db = tmp_path / "staging.duckdb"
    stage_project(FakeSource(count=5), project_key="neonatal", db_path=db, key=KEY)

    with pytest.raises(RuntimeError, match="REDCap went away"):
        stage_project(
            FakeSource(count=5, fail_on_batch=2),
            project_key="neonatal",
            db_path=db,
            key=KEY,
            batch_size=2,
        )

    # All or nothing: half a run never replaces a whole one
    assert query(db, "SELECT count(*) FROM raw_neonatal") == [(5,)]


def test_only_safe_project_keys_are_accepted(tmp_path):
    # The key names a table, so it must never be arbitrary text, even if a
    # caller skips the registry's own check
    with pytest.raises(ValueError, match="project key"):
        stage_project(
            FakeSource(),
            project_key="neonatal; DROP TABLE x",
            db_path=tmp_path / "s.duckdb",
            key=KEY,
        )


def test_a_project_without_its_site_field_is_refused(tmp_path):
    # Without the site field, rows could not be limited to the sites a user may see
    db = tmp_path / "staging.duckdb"

    with pytest.raises(ValueError, match="facility_code"):
        stage_project(
            FakeSource(),
            project_key="neonatal",
            db_path=db,
            key=KEY,
            required_fields={"facility_code"},
        )

    assert not db.exists() or query(db, "SELECT count(*) FROM duckdb_tables()") == [(0,)]


def test_a_project_with_no_records_gives_an_empty_table(tmp_path):
    db = tmp_path / "staging.duckdb"

    result = stage_project(FakeSource(count=0), project_key="maternity", db_path=db, key=KEY)

    assert result.records == 0
    assert query(db, "SELECT count(*) FROM raw_maternity") == [(0,)]


# --- Incremental staging ---------------------------------------------------
# With changed_since, only records created or changed since then are staged,
# and the file records what it holds (_stage_info), so the load knows whether
# to replace the whole project or only those records.


class ChangedSource(FakeSource):
    """Returns only the first two records as changed, and remembers the time asked for."""

    def export_record_ids(self, record_id_field, changed_since=None):
        self.changed_since = changed_since
        ids = [row[record_id_field] for row in self.rows]
        return ids if changed_since is None else ids[:2]

    def export_deleted_record_ids(self, since):
        return []


def stage_info(db_path):
    return query(db_path, "SELECT mode, changed_since, started_at FROM _stage_info")


def test_a_full_stage_records_its_mode_and_start_time(tmp_path):
    db = tmp_path / "staging.duckdb"
    before = datetime.now(UTC)

    stage_project(FakeSource(count=3), project_key="neonatal", db_path=db, key=KEY)

    ((mode, changed_since, started_at),) = stage_info(db)
    assert (mode, changed_since) == ("full", None)
    assert before - timedelta(seconds=1) <= started_at <= datetime.now(UTC)


def test_an_incremental_stage_holds_only_changed_records(tmp_path):
    db = tmp_path / "staging.duckdb"
    source = ChangedSource(count=5)
    since = datetime(2026, 11, 20, 23, 0, tzinfo=UTC)

    result = stage_project(source, project_key="neonatal", db_path=db, key=KEY, changed_since=since)

    assert source.changed_since == since
    assert result.records == 2
    assert query(db, "SELECT count(*) FROM raw_neonatal") == [(2,)]
    ((mode, changed_since, _),) = stage_info(db)
    assert (mode, changed_since) == ("changes", since)


def test_the_start_time_is_taken_before_reading_redcap(tmp_path):
    # Records changed while the export runs must be caught by the next run,
    # so the watermark is the moment before the first request
    db = tmp_path / "staging.duckdb"
    source = FakeSource(count=1)
    seen = {}
    original = source.export_metadata

    def export_metadata():
        seen["at"] = datetime.now(UTC)
        return original()

    source.export_metadata = export_metadata
    stage_project(source, project_key="neonatal", db_path=db, key=KEY)

    ((_, _, started_at),) = stage_info(db)
    assert started_at <= seen["at"]


class SourceWithDeletions(ChangedSource):
    def export_deleted_record_ids(self, since):
        self.deleted_since = since
        return ["9", "8"]


def deleted(db_path):
    return [r[0] for r in query(db_path, "SELECT record_id FROM _deleted_records ORDER BY 1")]


def test_an_incremental_stage_lists_records_deleted_since_the_same_time(tmp_path):
    db = tmp_path / "staging.duckdb"
    source = SourceWithDeletions(count=3)
    since = datetime(2026, 11, 20, 23, 0, tzinfo=UTC)

    stage_project(source, project_key="neonatal", db_path=db, key=KEY, changed_since=since)

    assert source.deleted_since == since
    assert deleted(db) == ["8", "9"]


def test_deleted_ids_are_hashed_like_staged_ids_when_the_record_id_is_flagged(tmp_path):
    # Otherwise a deleted record's hashed rows could never be found and removed
    id_field = {"field_name": "record_id", "form_name": "admission", "field_type": "text"}
    flagged_id = [*fields_from_rows([{**id_field, "identifier": "y"}]), *FIELDS[1:]]
    source = SourceWithDeletions(count=1)
    source.export_metadata = lambda: flagged_id
    db = tmp_path / "staging.duckdb"

    stage_project(
        source, project_key="neonatal", db_path=db, key=KEY,
        changed_since=datetime(2026, 11, 20, tzinfo=UTC),
    )  # fmt: skip

    assert deleted(db) == sorted([hash_identifier("9", KEY), hash_identifier("8", KEY)])


def test_a_full_stage_lists_no_deletions(tmp_path):
    # A full load replaces the whole project, which removes deleted records anyway
    db = tmp_path / "staging.duckdb"

    stage_project(SourceWithDeletions(count=2), project_key="neonatal", db_path=db, key=KEY)

    assert deleted(db) == []

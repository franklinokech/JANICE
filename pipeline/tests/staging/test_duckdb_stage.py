"""Tests for staging a REDCap unit into DuckDB.

A fake REDCap (FakeSource) serves synthetic records, so no network, token or
real patient data is needed. The rule these tests protect: identifiers are
hashed in memory, batch by batch, so cleartext never reaches the DuckDB file.
"""

import duckdb
import pytest

from janice_pipeline.privacy.hashing import hash_identifier
from janice_pipeline.staging.duckdb_stage import stage_unit
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


def test_every_record_is_staged_in_the_units_raw_table(tmp_path):
    db = tmp_path / "staging.duckdb"

    result = stage_unit(FakeSource(count=5), unit="neonatal", db_path=db, key=KEY)

    assert result.records == 5
    assert result.rows == 5
    assert query(db, "SELECT count(*) FROM raw_neonatal") == [(5,)]


def test_records_are_fetched_in_batches(tmp_path):
    source = FakeSource(count=5)

    stage_unit(source, unit="neonatal", db_path=tmp_path / "s.duckdb", key=KEY, batch_size=2)

    assert source.batch_sizes == [2, 2, 1]


def test_flagged_identifiers_are_hashed_before_they_reach_duckdb(tmp_path):
    db = tmp_path / "staging.duckdb"
    source = FakeSource(count=3)

    stage_unit(source, unit="neonatal", db_path=db, key=KEY)

    staged = {r[0] for r in query(db, "SELECT ip_number FROM raw_neonatal")}
    cleartext = {row["ip_number"] for row in source.rows}
    assert staged.isdisjoint(cleartext)
    assert staged == {hash_identifier(value, KEY) for value in cleartext}


def test_fields_kept_in_clear_are_not_hashed(tmp_path):
    # hosp_id is flagged in REDCap but must stay readable: it is how rows are
    # filtered by site
    db = tmp_path / "staging.duckdb"
    source = FakeSource(count=3)

    stage_unit(source, unit="neonatal", db_path=db, key=KEY, keep_in_clear={"hosp_id"})

    staged = {r[0] for r in query(db, "SELECT hosp_id FROM raw_neonatal")}
    assert staged == {row["hosp_id"] for row in source.rows}


def test_all_values_are_stored_as_text(tmp_path):
    # Typing (dates, numbers) is dbt's job, with tests; staging keeps exactly
    # what REDCap sent
    db = tmp_path / "staging.duckdb"
    stage_unit(FakeSource(), unit="neonatal", db_path=db, key=KEY)

    types = {r[1] for r in query(db, "DESCRIBE raw_neonatal")}
    assert types == {"VARCHAR"}


def test_a_rerun_replaces_the_table_rather_than_adding_duplicates(tmp_path):
    db = tmp_path / "staging.duckdb"
    stage_unit(FakeSource(count=5), unit="neonatal", db_path=db, key=KEY)

    stage_unit(FakeSource(count=3), unit="neonatal", db_path=db, key=KEY)

    assert query(db, "SELECT count(*) FROM raw_neonatal") == [(3,)]


def test_a_failed_run_leaves_the_previous_table_untouched(tmp_path):
    db = tmp_path / "staging.duckdb"
    stage_unit(FakeSource(count=5), unit="neonatal", db_path=db, key=KEY)

    with pytest.raises(RuntimeError, match="REDCap went away"):
        stage_unit(
            FakeSource(count=5, fail_on_batch=2), unit="neonatal", db_path=db, key=KEY, batch_size=2
        )

    # All or nothing: half a run never replaces a whole one
    assert query(db, "SELECT count(*) FROM raw_neonatal") == [(5,)]


def test_only_known_units_are_accepted(tmp_path):
    # The unit names a table, so it must never come from arbitrary text
    with pytest.raises(ValueError, match="unit"):
        stage_unit(
            FakeSource(), unit="neonatal; DROP TABLE x", db_path=tmp_path / "s.duckdb", key=KEY
        )


def test_a_project_with_no_records_gives_an_empty_table(tmp_path):
    db = tmp_path / "staging.duckdb"

    result = stage_unit(FakeSource(count=0), unit="maternity", db_path=db, key=KEY)

    assert result.records == 0
    assert query(db, "SELECT count(*) FROM raw_maternity") == [(0,)]

"""Tests for the Dagster staging asset: one partition per registered project.

A fake source resource serves synthetic records, so these tests need no
network, token or real data. The hashing key comes from the environment,
as it will in production, set here with monkeypatch.
"""

import subprocess
import sys

import dagster as dg
import duckdb
import pytest

from janice_pipeline.orchestration.staging import (
    RecordSourceResource,
    RedcapSourceResource,
    StagingResource,
    SyntheticSourceResource,
    build_staging_asset,
)
from janice_pipeline.projects.registry import Project
from janice_pipeline.synthetic.dictionary import fields_from_rows
from janice_pipeline.synthetic.records import generate_records

FAKE_KEY_HEX = "ab" * 32  # a fake 32-byte key, for tests only
FAKE_TOKEN = "0123456789ABCDEF0123456789ABCDEF"  # noqa: S105  # gitleaks:allow (fake test token)

PROJECTS = [
    Project(key="neonatal", site_field="hosp_id"),
    Project(key="kilifi_nbu", site_field="facility_code", token_env="KILIFI_TOKEN"),  # noqa: S106
]

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
    ]
)


class FakeSource:
    def __init__(self, count):
        _, self.rows = generate_records(FIELDS, count=count, seed=1)

    def export_metadata(self):
        return FIELDS

    def export_record_ids(self, record_id_field):
        return [row[record_id_field] for row in self.rows]

    def export_records(self, record_ids, *, batch_size):
        for start in range(0, len(self.rows), batch_size):
            yield self.rows[start : start + batch_size]


class FakeSourceResource(RecordSourceResource):
    count: int = 7

    def for_project(self, project):
        return FakeSource(self.count)


def materialize(tmp_path, project="neonatal", projects=PROJECTS):
    return dg.materialize(
        [build_staging_asset(projects)],
        partition_key=project,
        resources={
            "source": FakeSourceResource(),
            "staging": StagingResource(data_dir=str(tmp_path)),
        },
        raise_on_error=False,
    )


def failure_message(result):
    return str(result.get_step_failure_events()[0].event_specific_data)


def test_staging_a_project_writes_its_table_and_reports_counts(tmp_path, monkeypatch):
    monkeypatch.setenv("JANICE_HASH_KEY", FAKE_KEY_HEX)

    result = materialize(tmp_path)

    assert result.success
    (m,) = result.asset_materializations_for_node("redcap_staging")
    assert m.metadata["records"].value == 7
    assert m.metadata["table"].value == "raw_neonatal"
    with duckdb.connect(str(tmp_path / "staging_neonatal.duckdb"), read_only=True) as con:
        assert con.execute("SELECT count(*) FROM raw_neonatal").fetchone() == (7,)


def test_there_is_one_partition_per_registered_project():
    asset = build_staging_asset(PROJECTS)

    assert sorted(asset.partitions_def.get_partition_keys()) == ["kilifi_nbu", "neonatal"]


def test_the_projects_site_field_stays_readable(tmp_path, monkeypatch):
    monkeypatch.setenv("JANICE_HASH_KEY", FAKE_KEY_HEX)
    project = Project(key="neonatal", site_field="hosp_id")

    materialize(tmp_path, projects=[project])

    with duckdb.connect(str(tmp_path / "staging_neonatal.duckdb"), read_only=True) as con:
        sites = {r[0] for r in con.execute("SELECT hosp_id FROM raw_neonatal").fetchall()}
        ip_numbers = {r[0] for r in con.execute("SELECT ip_number FROM raw_neonatal").fetchall()}
    assert all(s.startswith("SYNTHETIC-") for s in sites)  # kept in clear
    assert not any(i.startswith("SYNTHETIC-") for i in ip_numbers)  # hashed


def test_a_project_whose_site_field_is_missing_fails_clearly(tmp_path, monkeypatch):
    # kilifi_nbu says its site is in facility_code, which the dictionary lacks
    monkeypatch.setenv("JANICE_HASH_KEY", FAKE_KEY_HEX)

    result = materialize(tmp_path, project="kilifi_nbu")

    assert not result.success
    assert "facility_code" in failure_message(result)


def test_each_project_has_its_own_staging_file(tmp_path):
    staging = StagingResource(data_dir=str(tmp_path))

    assert staging.db_path("neonatal") != staging.db_path("kilifi_nbu")


# A separate process that opens a DuckDB file for writing and holds it until
# its stdin closes, like another Dagster run staging a project
HOLD_FILE = (
    "import duckdb, sys; con = duckdb.connect(sys.argv[1]); "
    "print('held', flush=True); sys.stdin.read()"
)


def test_a_project_can_be_staged_while_another_project_is_running(tmp_path, monkeypatch):
    # Dagster runs each partition in its own process, and DuckDB lets only one
    # process write to a file at a time: with one shared file, two of three failed
    monkeypatch.setenv("JANICE_HASH_KEY", FAKE_KEY_HEX)
    other_file = StagingResource(data_dir=str(tmp_path)).db_path("kilifi_nbu")
    holder = subprocess.Popen(  # noqa: S603 (fixed command, test only)
        [sys.executable, "-c", HOLD_FILE, str(other_file)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "held"
        result = materialize(tmp_path, project="neonatal")
    finally:
        holder.stdin.close()
        holder.wait(timeout=30)

    assert result.success


def test_a_missing_hashing_key_fails_the_run_with_a_clear_message(tmp_path, monkeypatch):
    monkeypatch.delenv("JANICE_HASH_KEY", raising=False)

    result = materialize(tmp_path)

    assert not result.success
    assert "JANICE_HASH_KEY" in failure_message(result)


def test_a_short_hashing_key_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("JANICE_HASH_KEY", "ab" * 8)

    result = materialize(tmp_path)

    assert not result.success
    assert "64 hex" in failure_message(result)


def test_a_missing_redcap_token_names_the_projects_variable(monkeypatch):
    monkeypatch.delenv("KILIFI_TOKEN", raising=False)
    source = RedcapSourceResource(default_api_url="https://redcap.example.org/api/")

    with pytest.raises(dg.Failure, match="KILIFI_TOKEN"):
        source.for_project(PROJECTS[1])


def test_redcap_source_reads_the_token_from_the_environment(monkeypatch):
    monkeypatch.setenv("REDCAP_TOKEN_NEONATAL", FAKE_TOKEN)
    source = RedcapSourceResource(default_api_url="https://redcap.example.org/api/")

    client = source.for_project(PROJECTS[0])

    # The token is in the environment, never in Dagster's config or logs
    assert FAKE_TOKEN not in repr(client)
    assert FAKE_TOKEN not in str(source)


def test_a_projects_own_api_url_and_time_zone_are_used(monkeypatch):
    monkeypatch.setenv("REDCAP_TOKEN_NEONATAL", FAKE_TOKEN)
    project = Project(
        key="neonatal",
        site_field="hosp_id",
        api_url="https://redcap.other.example.org/api/",
        server_timezone="Africa/Nairobi",
    )
    source = RedcapSourceResource(default_api_url="https://redcap.example.org/api/")

    client = source.for_project(project)

    assert client.url == "https://redcap.other.example.org/api/"
    assert str(client.server_timezone) == "Africa/Nairobi"


def test_a_project_with_no_api_url_anywhere_fails_clearly(monkeypatch):
    monkeypatch.setenv("REDCAP_TOKEN_NEONATAL", FAKE_TOKEN)
    source = RedcapSourceResource()

    with pytest.raises(dg.Failure, match="REDCAP_API_URL"):
        source.for_project(PROJECTS[0])


def test_synthetic_source_uses_the_projects_dictionary(small_dictionary):
    small_dictionary.rename(small_dictionary.parent / "neonatal_dictionary.csv")
    source = SyntheticSourceResource(dictionary_dir=str(small_dictionary.parent), records=4)

    project_source = source.for_project(PROJECTS[0])
    ids = project_source.export_record_ids(project_source.export_metadata()[0].name)

    assert ids == ["1", "2", "3", "4"]


def test_synthetic_source_says_which_dictionary_is_missing(tmp_path):
    source = SyntheticSourceResource(dictionary_dir=str(tmp_path))

    with pytest.raises(dg.Failure, match="kilifi_nbu_dictionary.csv"):
        source.for_project(PROJECTS[1])

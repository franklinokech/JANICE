"""Tests for the project registry: which REDCap projects JANICE stages.

The registry is a YAML file in the repository, so every change is reviewed in
a pull request. It holds no secrets: only the *name* of each token's
environment variable.
"""

import textwrap

import pytest

from janice_pipeline.projects.registry import ProjectRegistryError, load_projects


def write(tmp_path, text):
    path = tmp_path / "projects.yaml"
    path.write_text(textwrap.dedent(text))
    return path


def test_projects_are_loaded_in_file_order(tmp_path):
    path = write(
        tmp_path,
        """
        projects:
          - key: neonatal
            site_field: hosp_id
          - key: kilifi_nbu
            site_field: facility_code
        """,
    )

    assert [p.key for p in load_projects(path)] == ["neonatal", "kilifi_nbu"]


def test_defaults_follow_the_existing_conventions(tmp_path):
    path = write(tmp_path, "projects:\n  - key: neonatal\n    site_field: hosp_id\n")

    (project,) = load_projects(path)

    assert project.token_variable == "REDCAP_TOKEN_NEONATAL"  # noqa: S105 (a name, not a token)
    assert project.dictionary_filename == "neonatal_dictionary.csv"
    assert project.server_timezone == "UTC"
    assert project.api_url is None  # falls back to REDCAP_API_URL


def test_each_project_has_its_own_site_field_and_fields_kept_in_clear(tmp_path):
    path = write(
        tmp_path,
        """
        projects:
          - key: kilifi_nbu
            site_field: facility_code
            keep_in_clear: [ward]
            token_env: KILIFI_TOKEN
            api_url: https://redcap.kilifi.example.org/api/
            server_timezone: Africa/Nairobi
        """,
    )

    (project,) = load_projects(path)

    assert project.clear_fields == {"facility_code", "ward"}
    assert project.token_variable == "KILIFI_TOKEN"  # noqa: S105 (a name, not a token)
    assert project.api_url == "https://redcap.kilifi.example.org/api/"


def test_disabled_projects_are_left_out(tmp_path):
    path = write(
        tmp_path,
        """
        projects:
          - key: neonatal
            site_field: hosp_id
          - key: old_pilot
            site_field: hosp_id
            enabled: false
        """,
    )

    assert [p.key for p in load_projects(path)] == ["neonatal"]


@pytest.mark.parametrize(
    "key",
    ["Neonatal", "neo-natal", "1neonatal", "neonatal; DROP TABLE x", "", "n" * 41],
)
def test_keys_must_be_safe_table_names(tmp_path, key):
    # The key becomes a table name (raw_<key>) and a file name
    path = write(tmp_path, f'projects:\n  - key: "{key}"\n    site_field: hosp_id\n')

    with pytest.raises(ProjectRegistryError, match="key"):
        load_projects(path)


def test_duplicate_keys_are_refused(tmp_path):
    path = write(
        tmp_path,
        """
        projects:
          - key: neonatal
            site_field: hosp_id
          - key: neonatal
            site_field: hosp_id
        """,
    )

    with pytest.raises(ProjectRegistryError, match="neonatal"):
        load_projects(path)


def test_a_misspelt_setting_is_refused_rather_than_ignored(tmp_path):
    # "keep_in_cleer" silently ignored would leave a field hashed by mistake
    path = write(
        tmp_path,
        """
        projects:
          - key: neonatal
            site_field: hosp_id
            keep_in_cleer: [ward]
        """,
    )

    with pytest.raises(ProjectRegistryError, match="keep_in_cleer"):
        load_projects(path)


def test_site_field_is_required(tmp_path):
    path = write(tmp_path, "projects:\n  - key: neonatal\n")

    with pytest.raises(ProjectRegistryError, match="site_field"):
        load_projects(path)


def test_api_urls_must_use_https(tmp_path):
    path = write(
        tmp_path,
        """
        projects:
          - key: neonatal
            site_field: hosp_id
            api_url: http://redcap.example.org/api/
        """,
    )

    with pytest.raises(ProjectRegistryError, match="https"):
        load_projects(path)


def test_unknown_time_zones_are_refused(tmp_path):
    path = write(
        tmp_path,
        """
        projects:
          - key: neonatal
            site_field: hosp_id
            server_timezone: Mars/Olympus
        """,
    )

    with pytest.raises(ProjectRegistryError, match="Mars/Olympus"):
        load_projects(path)


def test_a_registry_with_no_enabled_projects_is_refused(tmp_path):
    path = write(
        tmp_path,
        "projects:\n  - key: neonatal\n    site_field: hosp_id\n    enabled: false\n",
    )

    with pytest.raises(ProjectRegistryError, match="no enabled projects"):
        load_projects(path)


def test_errors_name_the_file(tmp_path):
    path = write(tmp_path, "projects: [")

    with pytest.raises(ProjectRegistryError, match="projects.yaml"):
        load_projects(path)


def test_the_repositorys_own_registry_is_valid():
    # The file Dagster loads in every environment
    projects = load_projects()

    assert {"neonatal", "paediatrics", "maternity"} <= {p.key for p in projects}

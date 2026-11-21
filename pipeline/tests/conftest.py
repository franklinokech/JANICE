"""Shared helpers for synthetic data tests."""

import csv

import pytest

HEADERS = ["field_name", "form_name", "field_type", "select_choices_or_calculations", "identifier"]


@pytest.fixture
def small_dictionary(tmp_path):
    """A two-form data dictionary in API metadata format, written to a temporary file."""
    path = tmp_path / "dictionary.csv"
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(HEADERS)
        writer.writerows(
            [
                ["record_id", "admission", "text", "", ""],
                ["ip_number", "admission", "text", "", "y"],
                ["danger_signs", "admission", "checkbox", "1, Convulsions | 2, Coma", ""],
                ["outcome", "discharge", "radio", "1, Alive | 2, Died", ""],
            ]
        )
    return path

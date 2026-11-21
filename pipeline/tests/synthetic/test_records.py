"""Tests for building complete synthetic REDCap records from a data dictionary."""

from janice_pipeline.synthetic.dictionary import read_data_dictionary
from janice_pipeline.synthetic.records import generate_records


def test_one_row_per_record_numbered_from_one(small_dictionary):
    fields = read_data_dictionary(small_dictionary)

    columns, rows = generate_records(fields, count=5, seed=1)

    assert columns[0] == "record_id"
    assert [row["record_id"] for row in rows] == ["1", "2", "3", "4", "5"]


def test_columns_follow_redcap_export_order(small_dictionary):
    # Dictionary order, checkbox options expanded, and a <form>_complete
    # status column after each form's fields, as in a REDCap export
    fields = read_data_dictionary(small_dictionary)

    columns, _ = generate_records(fields, count=1, seed=1)

    assert columns == [
        "record_id",
        "ip_number",
        "danger_signs___1",
        "danger_signs___2",
        "admission_complete",
        "outcome",
        "discharge_complete",
    ]


def test_forms_are_marked_complete(small_dictionary):
    fields = read_data_dictionary(small_dictionary)

    _, rows = generate_records(fields, count=3, seed=1)

    assert {row["admission_complete"] for row in rows} == {"2"}
    assert {row["discharge_complete"] for row in rows} == {"2"}


def test_identifiers_are_synthetic_and_match_the_record(small_dictionary):
    fields = read_data_dictionary(small_dictionary)

    _, rows = generate_records(fields, count=2, seed=1)

    assert [row["ip_number"] for row in rows] == ["SYNTHETIC-000001", "SYNTHETIC-000002"]


def test_same_seed_gives_identical_records(small_dictionary):
    fields = read_data_dictionary(small_dictionary)

    assert generate_records(fields, count=20, seed=3) == generate_records(fields, count=20, seed=3)


def test_different_seeds_give_different_records(small_dictionary):
    fields = read_data_dictionary(small_dictionary)

    assert generate_records(fields, count=20, seed=3) != generate_records(fields, count=20, seed=4)

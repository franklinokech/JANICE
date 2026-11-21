"""Tests for reading a REDCap data dictionary.

A data dictionary describes every field in a REDCap project: its name, form,
type, choices and validation. JANICE reads it to generate synthetic data, and
later to find which fields are flagged as identifiers.
"""

import csv
from pathlib import Path

from janice_pipeline.synthetic.dictionary import Choice, read_data_dictionary

# Headers exactly as in the CSV downloaded from REDCap's Data Dictionary page
DOWNLOAD_HEADERS = [
    "Variable / Field Name",
    "Form Name",
    "Section Header",
    "Field Type",
    "Field Label",
    "Choices, Calculations, OR Slider Labels",
    "Field Note",
    "Text Validation Type OR Show Slider Number",
    "Text Validation Min",
    "Text Validation Max",
    "Identifier?",
    "Branching Logic (Show field only if...)",
    "Required Field?",
]


def write_dictionary(path: Path, headers: list[str], rows: list[list[str]], bom=False) -> Path:
    with path.open("w", newline="", encoding="utf-8-sig" if bom else "utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    return path


def row(name, form, ftype, label="", choices="", validation="", vmin="", vmax="", ident="", req=""):
    return [name, form, "", ftype, label, choices, "", validation, vmin, vmax, ident, "", req]


def test_reads_every_field_in_order(tmp_path):
    path = write_dictionary(
        tmp_path / "dd.csv",
        DOWNLOAD_HEADERS,
        [
            row("record_id", "admission", "text", "Record ID"),
            row("hosp_id", "admission", "dropdown", "Hospital", "1, Hospital A | 2, Hospital B"),
            row("adm_date", "admission", "text", "Date of admission", validation="date_ymd"),
        ],
    )

    fields = read_data_dictionary(path)

    assert [f.name for f in fields] == ["record_id", "hosp_id", "adm_date"]
    assert fields[2].form == "admission"
    assert fields[2].field_type == "text"
    assert fields[2].validation == "date_ymd"


def test_parses_choices_including_labels_that_contain_commas(tmp_path):
    path = write_dictionary(
        tmp_path / "dd.csv",
        DOWNLOAD_HEADERS,
        [
            row(
                "outcome",
                "discharge",
                "radio",
                "Outcome",
                "1, Alive | 2, Died | 3, Absconded, or left",
            )
        ],
    )

    (field,) = read_data_dictionary(path)

    assert field.choices == (
        Choice("1", "Alive"),
        Choice("2", "Died"),
        Choice("3", "Absconded, or left"),
    )


def test_only_choice_fields_get_choices(tmp_path):
    path = write_dictionary(
        tmp_path / "dd.csv",
        DOWNLOAD_HEADERS,
        [row("bmi", "admission", "calc", "BMI", "[weight]/([height]*[height])")],
    )

    (field,) = read_data_dictionary(path)

    assert field.choices == ()


def test_reads_identifier_and_required_flags(tmp_path):
    path = write_dictionary(
        tmp_path / "dd.csv",
        DOWNLOAD_HEADERS,
        [
            row("ip_number", "admission", "text", "Inpatient number", ident="y", req="y"),
            row("weight", "admission", "text", "Weight (kg)", validation="number"),
        ],
    )

    ip_number, weight = read_data_dictionary(path)

    assert ip_number.identifier is True
    assert ip_number.required is True
    assert weight.identifier is False
    assert weight.required is False


def test_reads_validation_limits(tmp_path):
    path = write_dictionary(
        tmp_path / "dd.csv",
        DOWNLOAD_HEADERS,
        [
            row(
                "weight",
                "admission",
                "text",
                "Weight (kg)",
                validation="number",
                vmin="0.3",
                vmax="80",
            )
        ],
    )

    (field,) = read_data_dictionary(path)

    assert (field.minimum, field.maximum) == ("0.3", "80")


def test_accepts_api_metadata_headers(tmp_path):
    # The REDCap API's metadata export (used by redquack) uses short column names
    path = write_dictionary(
        tmp_path / "dd.csv",
        ["field_name", "form_name", "field_type", "field_label", "select_choices_or_calculations"],
        [["sex", "admission", "radio", "Sex", "1, Male | 2, Female"]],
    )

    (field,) = read_data_dictionary(path)

    assert field.name == "sex"
    assert field.choices == (Choice("1", "Male"), Choice("2", "Female"))


def test_handles_a_byte_order_mark_from_excel(tmp_path):
    path = write_dictionary(
        tmp_path / "dd.csv", DOWNLOAD_HEADERS, [row("record_id", "admission", "text")], bom=True
    )

    (field,) = read_data_dictionary(path)

    assert field.name == "record_id"

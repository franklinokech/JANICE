"""Read a REDCap data dictionary into typed Python objects.

The data dictionary describes every field in a REDCap project. It comes in two
shapes with the same content:

- the CSV downloaded from Project Setup -> Data Dictionary, with long
  human-readable headers such as "Variable / Field Name";
- the API metadata export (what redquack stores), with short headers such as
  "field_name".

Both are normalised to the API's short names.
REDCap docs: https://redcap.vumc.org (Help & FAQ -> Data Dictionary)
"""

import csv
from dataclasses import dataclass
from pathlib import Path

# Long CSV headers -> API metadata names
HEADER_ALIASES = {
    "Variable / Field Name": "field_name",
    "Form Name": "form_name",
    "Field Type": "field_type",
    "Field Label": "field_label",
    "Choices, Calculations, OR Slider Labels": "select_choices_or_calculations",
    "Text Validation Type OR Show Slider Number": "text_validation_type_or_show_slider_number",
    "Text Validation Min": "text_validation_min",
    "Text Validation Max": "text_validation_max",
    "Identifier?": "identifier",
    "Branching Logic (Show field only if...)": "branching_logic",
    "Required Field?": "required_field",
}

# Field types whose "choices" column lists coded options
CHOICE_FIELD_TYPES = {"dropdown", "radio", "checkbox"}


@dataclass(frozen=True)
class Choice:
    """One coded option, e.g. code "1" with label "Male"."""

    code: str
    label: str


@dataclass(frozen=True)
class Field:
    """One field (variable) in a REDCap project."""

    name: str
    form: str
    field_type: str
    label: str = ""
    choices: tuple[Choice, ...] = ()
    validation: str = ""
    minimum: str = ""
    maximum: str = ""
    identifier: bool = False
    required: bool = False


def parse_choices(raw: str) -> tuple[Choice, ...]:
    """Parse REDCap's "1, Yes | 0, No" format. Labels may themselves contain commas."""
    choices = []
    for part in raw.split("|"):
        code, _, label = part.strip().partition(",")
        if code.strip():
            choices.append(Choice(code.strip(), label.strip()))
    return tuple(choices)


def read_data_dictionary(path: Path) -> list[Field]:
    """Read a data dictionary CSV (download or API format) into a list of fields, in order."""
    # utf-8-sig also strips the byte order mark Excel adds when saving CSV files
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = [
            {
                HEADER_ALIASES.get(key.strip(), key.strip()): (value or "").strip()
                for key, value in raw_row.items()
            }
            for raw_row in csv.DictReader(f)
        ]

    return [
        Field(
            name=row["field_name"],
            form=row.get("form_name", ""),
            field_type=row["field_type"],
            label=row.get("field_label", ""),
            choices=(
                parse_choices(row.get("select_choices_or_calculations", ""))
                if row["field_type"] in CHOICE_FIELD_TYPES
                else ()
            ),
            validation=row.get("text_validation_type_or_show_slider_number", ""),
            minimum=row.get("text_validation_min", ""),
            maximum=row.get("text_validation_max", ""),
            identifier=row.get("identifier", "").lower() == "y",
            required=row.get("required_field", "").lower() == "y",
        )
        for row in rows
    ]

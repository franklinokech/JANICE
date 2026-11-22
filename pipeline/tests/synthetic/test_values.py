"""Tests for generating synthetic values for REDCap fields.

Every value must be something REDCap itself would accept for that field,
so the pipeline is exercised with realistic, valid data. Identifier fields
must be obviously fake, so synthetic data can never be mistaken for real data.
"""

import random
import re
from datetime import date

from janice_pipeline.synthetic.dictionary import Choice, Field
from janice_pipeline.synthetic.values import generate_values


def rng(seed=1):
    return random.Random(seed)


def values_for(field, *, seed=1, record_number=1, missing_rate=0.0, runs=1):
    generator = rng(seed)
    return [
        generate_values(field, generator, record_number, missing_rate=missing_rate)
        for _ in range(runs)
    ]


def test_dropdown_and_radio_values_come_from_the_choice_codes():
    for field_type in ("dropdown", "radio"):
        field = Field("sex", "admission", field_type, choices=(Choice("1", "M"), Choice("2", "F")))

        seen = {v["sex"] for v in values_for(field, runs=50)}

        assert seen == {"1", "2"}


def test_checkbox_gives_one_zero_or_one_column_per_option():
    field = Field(
        "danger_signs",
        "admission",
        "checkbox",
        choices=(Choice("1", "Convulsions"), Choice("2", "Coma")),
    )

    (values,) = values_for(field)

    assert set(values) == {"danger_signs___1", "danger_signs___2"}
    assert set(values.values()) <= {"0", "1"}


def test_yesno_and_truefalse_are_zero_or_one():
    for field_type in ("yesno", "truefalse"):
        field = Field("oxygen", "admission", field_type)

        seen = {v["oxygen"] for v in values_for(field, runs=50)}

        assert seen == {"0", "1"}


def test_integer_respects_validation_limits():
    field = Field(
        "age_months", "admission", "text", validation="integer", minimum="2", maximum="59"
    )

    ages = [int(v["age_months"]) for v in values_for(field, runs=200)]

    assert min(ages) >= 2
    assert max(ages) <= 59


def test_number_respects_limits_and_uses_one_decimal_place():
    field = Field("weight", "admission", "text", validation="number", minimum="0.5", maximum="80")

    weights = [v["weight"] for v in values_for(field, runs=200)]

    assert all(re.fullmatch(r"\d+\.\d", w) for w in weights)
    assert all(0.5 <= float(w) <= 80 for w in weights)


def test_number_2dp_uses_two_decimal_places():
    field = Field("temp", "admission", "text", validation="number_2dp", minimum="34", maximum="42")

    (values,) = values_for(field)

    assert re.fullmatch(r"\d+\.\d\d", values["temp"])


def test_date_respects_limits_and_uses_redcap_format():
    field = Field(
        "adm_date",
        "admission",
        "text",
        validation="date_ymd",
        minimum="2025-01-01",
        maximum="2025-12-31",
    )

    dates = [date.fromisoformat(v["adm_date"]) for v in values_for(field, runs=200)]

    assert min(dates) >= date(2025, 1, 1)
    assert max(dates) <= date(2025, 12, 31)


def test_datetime_uses_redcap_format():
    field = Field("adm_time", "admission", "text", validation="datetime_ymd")

    (values,) = values_for(field)

    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", values["adm_time"])


def test_identifier_fields_are_obviously_synthetic():
    field = Field("ip_number", "admission", "text", identifier=True)

    (values,) = values_for(field, record_number=42)

    assert values["ip_number"] == "SYNTHETIC-000042"


def test_fields_redcap_fills_itself_produce_no_columns():
    for field_type in ("calc", "descriptive", "file"):
        field = Field("x", "admission", field_type)

        (values,) = values_for(field)

        assert values == {}


def test_same_seed_gives_the_same_values():
    field = Field("weight", "admission", "text", validation="number", minimum="0.5", maximum="80")

    assert values_for(field, seed=7, runs=20) == values_for(field, seed=7, runs=20)


def test_optional_fields_can_be_left_blank():
    field = Field("weight", "admission", "text", validation="number")

    (values,) = values_for(field, missing_rate=1.0)

    assert values == {"weight": ""}


def test_required_fields_are_never_blank():
    field = Field("weight", "admission", "text", validation="number", required=True)

    (values,) = values_for(field, missing_rate=1.0)

    assert values["weight"] != ""


# REDCap fields often set only one limit, e.g. a year of birth with minimum
# 1975 and no maximum. The missing limit must come from the one that is set,
# not from a fixed default that can end up on the wrong side of it.


def test_integer_with_only_a_minimum_above_the_default_range():
    field = Field("birth_year", "mother", "text", validation="integer", minimum="1975")

    years = [int(v["birth_year"]) for v in values_for(field, runs=200)]

    assert min(years) >= 1975


def test_integer_with_only_a_maximum_below_the_default_range():
    field = Field("deficit", "labs", "text", validation="integer", maximum="-10")

    values = [int(v["deficit"]) for v in values_for(field, runs=200)]

    assert max(values) <= -10


def test_integer_with_a_limit_redcap_computes_uses_the_other_limit():
    # "today" and piped values such as [admit_year] are not numbers
    field = Field(
        "birth_year", "mother", "text", validation="integer", minimum="1975", maximum="[year]"
    )

    years = [int(v["birth_year"]) for v in values_for(field, runs=200)]

    assert min(years) >= 1975


def test_number_with_only_a_minimum_above_the_default_range():
    field = Field("weight_g", "baby", "text", validation="number", minimum="500")

    weights = [float(v["weight_g"]) for v in values_for(field, runs=200)]

    assert min(weights) >= 500


def test_date_with_only_a_minimum_after_the_default_range():
    field = Field("follow_up", "visit", "text", validation="date_ymd", minimum="2030-01-01")

    dates = [date.fromisoformat(v["follow_up"]) for v in values_for(field, runs=200)]

    assert min(dates) >= date(2030, 1, 1)


def test_date_with_only_a_maximum_before_the_default_range():
    field = Field("mother_dob", "mother", "text", validation="date_ymd", maximum="2008-12-31")

    dates = [date.fromisoformat(v["mother_dob"]) for v in values_for(field, runs=200)]

    assert max(dates) <= date(2008, 12, 31)

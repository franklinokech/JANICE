"""Tests for identifier hashing.

Identifier values are replaced with HMAC-SHA256 hashes before any data reaches
the warehouse. A secret key makes the hashes impossible to reverse by guessing
(names and phone numbers come from small sets), while the same person still
gets the same hash in every record, so admissions can be linked.
"""

import hashlib
import hmac

import pytest

from janice_pipeline.privacy.hashing import (
    MIN_KEY_BYTES,
    fields_to_protect,
    hash_identifier,
    protect_row,
)
from janice_pipeline.synthetic.dictionary import Choice, Field

KEY = b"k" * MIN_KEY_BYTES
OTHER_KEY = b"x" * MIN_KEY_BYTES


def test_hash_is_keyed_hmac_sha256_of_the_normalised_value():
    # Documents the exact algorithm, so any other tool can reproduce it
    expected = hmac.new(KEY, b"mary wanjiku", hashlib.sha256).hexdigest()

    assert hash_identifier("Mary Wanjiku", KEY) == expected


def test_hash_is_not_a_plain_unkeyed_sha256():
    plain = hashlib.sha256(b"mary wanjiku").hexdigest()

    assert hash_identifier("Mary Wanjiku", KEY) != plain


def test_same_value_gives_the_same_hash():
    assert hash_identifier("IP-2025-0042", KEY) == hash_identifier("IP-2025-0042", KEY)


def test_a_different_key_gives_a_different_hash():
    assert hash_identifier("IP-2025-0042", KEY) != hash_identifier("IP-2025-0042", OTHER_KEY)


def test_spacing_and_capitals_do_not_change_the_hash():
    assert hash_identifier("  Mary   WANJIKU ", KEY) == hash_identifier("mary wanjiku", KEY)


def test_phone_separators_do_not_change_the_hash():
    phone = Field("phone", "admission", "text", validation="phone")

    assert hash_identifier("0712 345-678", KEY, phone) == hash_identifier("0712345678", KEY, phone)


def test_hash_is_64_hex_characters_and_hides_the_value():
    result = hash_identifier("Mary Wanjiku", KEY)

    assert len(result) == 64
    assert set(result) <= set("0123456789abcdef")
    assert "mary" not in result


def test_blank_values_stay_blank():
    assert hash_identifier("", KEY) == ""
    assert hash_identifier("   ", KEY) == ""


def test_short_keys_are_rejected():
    with pytest.raises(ValueError, match="at least"):
        hash_identifier("Mary", b"too-short")


FIELDS = [
    Field("record_id", "admission", "text"),
    Field("hosp_id", "admission", "dropdown", choices=(Choice("101", "A"),), identifier=True),
    Field("in_gis_add", "admission", "text", identifier=True),
    Field("in_gis_notes", "admission", "notes", identifier=True),
    Field(
        "contact_ways", "admission", "checkbox", choices=(Choice("1", "Phone"),), identifier=True
    ),
    Field("wt_now", "admission", "text", validation="number"),
]


def test_protects_fields_redcap_flags_except_those_kept_in_clear():
    protected = fields_to_protect(FIELDS, keep_in_clear={"hosp_id"})

    assert protected == {"in_gis_add", "in_gis_notes", "contact_ways"}


def test_protect_row_hashes_flagged_text_and_leaves_other_fields_unchanged():
    row = {"record_id": "7", "hosp_id": "101", "in_gis_add": "Kilifi Road", "wt_now": "2.4"}

    result = protect_row(row, FIELDS, KEY, keep_in_clear={"hosp_id"})

    assert result["record_id"] == "7"
    assert result["hosp_id"] == "101"
    assert result["wt_now"] == "2.4"
    assert result["in_gis_add"] == hash_identifier("Kilifi Road", KEY)


def test_protect_row_drops_flagged_free_text_fields():
    # A hash of free text is useless for analysis, so the column is removed
    row = {"record_id": "7", "in_gis_notes": "Lives behind the market"}

    result = protect_row(row, FIELDS, KEY)

    assert "in_gis_notes" not in result


def test_protect_row_drops_flagged_checkbox_columns():
    # Checkbox columns hold only 0/1; hashing them would protect nothing
    row = {"record_id": "7", "contact_ways___1": "1"}

    result = protect_row(row, FIELDS, KEY)

    assert "contact_ways___1" not in result


def test_protect_row_never_changes_the_input_row():
    row = {"record_id": "7", "in_gis_add": "Kilifi Road"}

    protect_row(row, FIELDS, KEY)

    assert row["in_gis_add"] == "Kilifi Road"

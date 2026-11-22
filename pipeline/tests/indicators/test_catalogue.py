"""Tests for the indicator catalogue.

Each indicator is defined once, in its dbt model's YAML (config.meta). The
catalogue validates those definitions and renders a readable page per
indicator into docs/indicators/, for the clinical leads to review and sign off.
The pages are generated: a test fails if they fall out of date.
"""

import textwrap

import pytest

from janice_pipeline.indicators.catalogue import (
    DEFAULT_DOCS_DIR,
    DEFAULT_MODELS_DIR,
    CatalogueError,
    load_catalogue,
    render_catalogue,
    stale_pages,
    write_catalogue,
)

VALID_META = """
models:
  - name: qi_test_indicator
    config:
      meta:
        indicator_id: test_indicator
        name: Test indicator
        version: "1.0"
        status: draft
        unit: neonatal
        type: process
        desired_direction: higher
        definition: Share of babies who got the thing.
        numerator: {column: done, description: Babies who got the thing}
        denominator: {column: eligible, description: Babies who should get the thing}
        exclusions: [Babies who died]
        completeness: Share of eligible babies with the question answered.
        fields: [thing_done]
        rationale: Because it matters.
        references:
          - {title: A guideline, url: "https://example.org/guideline"}
    columns:
      - name: done
      - name: eligible
"""


def write_model(tmp_path, text, name="qi_test_indicator.yml"):
    models = tmp_path / "models" / "qi"
    models.mkdir(parents=True, exist_ok=True)
    (models / name).write_text(textwrap.dedent(text))
    return models


def test_definitions_are_loaded_from_model_yaml(tmp_path):
    (indicator,) = load_catalogue(write_model(tmp_path, VALID_META))

    assert indicator.indicator_id == "test_indicator"
    assert indicator.model == "qi_test_indicator"
    assert indicator.numerator.column == "done"


def test_models_without_an_indicator_id_are_ignored(tmp_path):
    models = write_model(tmp_path, VALID_META)
    (models / "helper.yml").write_text("models:\n  - name: some_helper_model\n")

    assert [i.indicator_id for i in load_catalogue(models)] == ["test_indicator"]


def test_a_misspelt_setting_is_refused(tmp_path):
    text = VALID_META.replace("rationale:", "rationalle:")

    with pytest.raises(CatalogueError, match="rationalle"):
        load_catalogue(write_model(tmp_path, text))


def test_an_approved_indicator_must_say_who_approved_it_and_when(tmp_path):
    text = VALID_META.replace("status: draft", "status: approved")

    with pytest.raises(CatalogueError, match="approved_by"):
        load_catalogue(write_model(tmp_path, text))


def test_numerator_and_denominator_must_be_columns_of_the_model(tmp_path):
    text = VALID_META.replace("      - name: eligible\n", "")

    with pytest.raises(CatalogueError, match="eligible"):
        load_catalogue(write_model(tmp_path, text))


def test_indicator_ids_must_be_unique(tmp_path):
    models = write_model(tmp_path, VALID_META)
    write_model(tmp_path, VALID_META.replace("qi_test_indicator", "qi_copy"), name="copy.yml")

    with pytest.raises(CatalogueError, match="test_indicator"):
        load_catalogue(models)


def test_each_indicator_gets_a_page_and_the_catalogue_an_index(tmp_path):
    pages = render_catalogue(load_catalogue(write_model(tmp_path, VALID_META)))

    assert set(pages) == {"catalogue.md", "test_indicator.md"}
    page = pages["test_indicator.md"]
    assert page.startswith("<!-- Generated")
    assert "# Test indicator" in page
    assert "Babies who should get the thing" in page
    assert "Draft" in page
    assert "[Test indicator](test_indicator.md)" in pages["catalogue.md"]


def test_stale_pages_are_detected(tmp_path):
    catalogue = load_catalogue(write_model(tmp_path, VALID_META))
    docs = tmp_path / "docs"
    write_catalogue(catalogue, docs)
    assert stale_pages(catalogue, docs) == []

    (docs / "test_indicator.md").write_text("edited by hand")
    (docs / "old_indicator.md").write_text("<!-- Generated ... -->")

    assert stale_pages(catalogue, docs) == ["old_indicator.md", "test_indicator.md"]


def test_hand_written_pages_are_left_alone(tmp_path):
    catalogue = load_catalogue(write_model(tmp_path, VALID_META))
    docs = tmp_path / "docs"
    write_catalogue(catalogue, docs)
    (docs / "README.md").write_text("# Conventions, written by hand")

    assert stale_pages(catalogue, docs) == []


def test_the_repositorys_indicators_are_valid_and_their_pages_up_to_date():
    # Fails when an indicator's YAML changed but `janice-indicators` was not run
    catalogue = load_catalogue(DEFAULT_MODELS_DIR)

    assert catalogue, "no indicators found"
    assert stale_pages(catalogue, DEFAULT_DOCS_DIR) == [], (
        "Indicator pages are out of date: run `uv run janice-indicators` and commit docs/indicators"
    )

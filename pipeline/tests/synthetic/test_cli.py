"""Tests for the janice-synthetic command-line tool."""

import csv

from janice_pipeline.synthetic.cli import main


def test_writes_a_csv_export_with_the_requested_number_of_records(small_dictionary, tmp_path):
    out = tmp_path / "records.csv"

    exit_code = main(["--dictionary", str(small_dictionary), "--records", "25", "--out", str(out)])

    assert exit_code == 0
    with out.open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 25
    assert rows[0]["record_id"] == "1"
    assert "danger_signs___1" in rows[0]


def test_reports_a_missing_dictionary_clearly(tmp_path, capsys):
    exit_code = main(
        ["--dictionary", str(tmp_path / "nope.csv"), "--out", str(tmp_path / "out.csv")]
    )

    assert exit_code == 1
    assert "nope.csv" in capsys.readouterr().err

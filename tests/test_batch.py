"""Batch fill: one template, many records, one report."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from pypdf import PdfReader

from pdf_autofiller import fill_batch
from pdf_autofiller.cli import main
from pdf_autofiller.errors import PdfAutofillerError

SAMPLE = Path("samples/sample_form.pdf")


def _values(path: Path) -> dict[str, str | None]:
    return {name: field.get("/V") for name, field in PdfReader(path).get_fields().items()}


def test_fill_batch_writes_one_pdf_per_record(tmp_path: Path):
    report = fill_batch(
        SAMPLE,
        [
            {"firstname": "Jane", "lastname": "Doe", "dob": "1990-01-01"},
            {"firstname": "Sam", "lastname": "Lee", "dob": "1988-07-04"},
        ],
        tmp_path,
        filename_key="lastname",
    )
    assert report.written == 2
    assert report.failed == 0
    assert _values(tmp_path / "Doe.pdf")["txtFirstName"] == "Jane"
    assert _values(tmp_path / "Lee.pdf")["txtLastName"] == "Lee"


def test_fill_batch_keeps_going_when_one_record_is_incomplete(tmp_path: Path):
    report = fill_batch(
        SAMPLE,
        [
            {"firstname": "Jane", "lastname": "Doe", "dob": "1990-01-01"},
            {"firstname": "Only"},
            {"firstname": "Sam", "lastname": "Lee", "dob": "1988-07-04"},
        ],
        tmp_path,
    )
    assert report.written == 2
    assert report.failed == 1
    assert report.items[1].error
    assert report.items[1].output is None
    assert list(tmp_path.glob("*.pdf"))
    assert not any("Only" in path.name for path in tmp_path.glob("*.pdf"))


def test_fill_batch_stop_on_error_raises_and_keeps_earlier_pdfs(tmp_path: Path):
    with pytest.raises(PdfAutofillerError):
        fill_batch(
            SAMPLE,
            [
                {"firstname": "Jane", "lastname": "Doe", "dob": "1990-01-01"},
                {"firstname": "Only"},
            ],
            tmp_path,
            on_error="stop",
        )
    assert (tmp_path / "record-0001.pdf").is_file()
    assert not (tmp_path / "record-0002.pdf").exists()


def test_filename_key_cannot_escape_the_output_directory(tmp_path: Path):
    report = fill_batch(
        SAMPLE,
        [{"firstname": "Jane", "lastname": "../../outside", "dob": "1990-01-01"}],
        tmp_path,
        filename_key="lastname",
    )
    assert report.written == 1
    written = Path(report.items[0].output or "")
    assert written.parent == tmp_path
    assert written.is_file()
    assert not (tmp_path.parent / "outside.pdf").exists()


def test_cli_batch_exits_nonzero_when_a_record_fails(tmp_path: Path):
    records = tmp_path / "people.json"
    records.write_text(
        json.dumps(
            [
                {"firstname": "Jane", "lastname": "Doe", "dob": "1990-01-01"},
                {"firstname": "Only"},
            ]
        ),
        encoding="utf-8",
    )
    out = tmp_path / "pdfs"
    result = CliRunner().invoke(main, ["batch", str(SAMPLE), str(records), "-o", str(out)])
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["written"] == 1
    assert payload["failed"] == 1
    assert len(list(out.glob("*.pdf"))) == 1


def test_cli_batch_prints_a_report(tmp_path: Path):
    records = tmp_path / "people.json"
    records.write_text(
        json.dumps(
            [
                {"firstname": "Jane", "lastname": "Doe", "dob": "1990-01-01"},
                {"firstname": "Sam", "lastname": "Lee", "dob": "1991-02-02"},
            ]
        ),
        encoding="utf-8",
    )
    out = tmp_path / "pdfs"
    result = CliRunner().invoke(main, ["batch", str(SAMPLE), str(records), "-o", str(out)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["written"] == 2
    assert len(list(out.glob("*.pdf"))) == 2

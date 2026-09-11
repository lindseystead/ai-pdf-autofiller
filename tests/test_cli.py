"""CLI smoke tests for inspect / preview / fill."""

import json
from pathlib import Path

from click.testing import CliRunner

from pdf_autofiller.cli import main

SAMPLE_PDF = Path("samples/sample_form.pdf")
SAMPLE_DATA = {
    "firstname": "Jane",
    "lastname": "Doe",
    "dob": "1990-01-01",
    "email": "jane@example.com",
}


def test_cli_version():
    runner = CliRunner()
    result = runner.invoke(main, ["version"])
    assert result.exit_code == 0
    assert result.output.strip()


def test_cli_inspect_sample():
    runner = CliRunner()
    result = runner.invoke(main, ["inspect", str(SAMPLE_PDF)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["field_count"] >= 1
    assert isinstance(payload["fields"], list)


def test_cli_preview_and_fill(tmp_path: Path):
    runner = CliRunner()
    data_file = tmp_path / "profile.json"
    data_file.write_text(json.dumps(SAMPLE_DATA), encoding="utf-8")
    out_pdf = tmp_path / "filled.pdf"

    preview = runner.invoke(main, ["preview", str(SAMPLE_PDF), str(data_file)])
    assert preview.exit_code == 0, preview.output
    preview_payload = json.loads(preview.output)
    assert preview_payload["field_count"] >= 1
    assert "mapping" in preview_payload

    fill = runner.invoke(
        main,
        [
            "fill",
            str(SAMPLE_PDF),
            str(data_file),
            "-o",
            str(out_pdf),
            "--json-report",
        ],
    )
    assert fill.exit_code == 0, fill.output
    assert out_pdf.is_file()
    assert out_pdf.read_bytes()[:4] == b"%PDF"
    report = json.loads(fill.output)
    assert report["output"] == str(out_pdf)
    assert len(report["written_fields"]) >= 1


def test_cli_fill_inline_data(tmp_path: Path):
    runner = CliRunner()
    out_pdf = tmp_path / "inline.pdf"
    result = runner.invoke(
        main,
        [
            "fill",
            str(SAMPLE_PDF),
            "--data",
            json.dumps(SAMPLE_DATA),
            "-o",
            str(out_pdf),
        ],
    )
    assert result.exit_code == 0, result.output
    assert out_pdf.is_file()
    assert "Wrote" in result.output


def test_cli_rejects_non_object_json(tmp_path: Path):
    runner = CliRunner()
    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2, 3]", encoding="utf-8")
    result = runner.invoke(main, ["preview", str(SAMPLE_PDF), str(bad)])
    assert result.exit_code != 0
    assert "JSON object" in result.output

"""CLI smoke tests for inspect / preview / fill."""

import json
from pathlib import Path

import pytest
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


def _bad_pdfs(tmp_path: Path) -> dict[str, Path]:
    sample = SAMPLE_PDF.read_bytes()
    files = {
        "text": b"hello, not a pdf",
        "empty": b"",
        "truncated": sample[: len(sample) // 2],
        "header_only": b"%PDF-1.7\n",
    }
    paths = {}
    for name, content in files.items():
        path = tmp_path / f"{name}.pdf"
        path.write_bytes(content)
        paths[name] = path
    return paths


def _assert_clean_error(result, *fragments: str) -> None:
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), result.exception  # not an uncaught error
    assert "Traceback" not in result.output
    assert result.output.startswith("Error: ")
    for fragment in fragments:
        assert fragment in result.output


@pytest.mark.parametrize("kind", ["text", "empty", "truncated", "header_only"])
@pytest.mark.parametrize("command", ["inspect", "preview", "fill"])
def test_cli_reports_unreadable_pdf_without_traceback(tmp_path: Path, kind: str, command: str):
    pdf = _bad_pdfs(tmp_path)[kind]
    args = [command, str(pdf)]
    if command != "inspect":
        args += ["--data", "{}"]
    if command == "fill":
        args += ["-o", str(tmp_path / "out.pdf")]
    _assert_clean_error(CliRunner().invoke(main, args), "Could not parse PDF")
    assert not (tmp_path / "out.pdf").exists()


@pytest.mark.parametrize("command", ["preview", "fill"])
def test_cli_reports_overly_nested_data_without_traceback(tmp_path: Path, command: str):
    nested = "{}"
    for _ in range(40):
        nested = '{"a": ' + nested + "}"
    args = [command, str(SAMPLE_PDF), "--data", nested]
    if command == "fill":
        args += ["-o", str(tmp_path / "out.pdf")]
    _assert_clean_error(CliRunner().invoke(main, args), "nests deeper")


def test_cli_reports_page_limit_without_traceback():
    result = CliRunner().invoke(main, ["inspect", str(SAMPLE_PDF), "--max-pages", "0"])
    _assert_clean_error(result, "page")


def test_cli_reports_unwritable_output_without_traceback(tmp_path: Path):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("a file where a directory should be")
    args = ["fill", str(SAMPLE_PDF), "--data", json.dumps(SAMPLE_DATA), "-o", str(blocker / "out.pdf")]
    _assert_clean_error(CliRunner().invoke(main, args), "File error", "not_a_dir")


@pytest.mark.parametrize("command", ["inspect", "preview", "fill"])
def test_cli_rejects_unreadable_input_file_as_usage_error(tmp_path: Path, command: str):
    pdf = tmp_path / "locked.pdf"
    pdf.write_bytes(SAMPLE_PDF.read_bytes())
    pdf.chmod(0)
    try:
        args = [command, str(pdf)]
        if command != "inspect":
            args += ["--data", "{}"]
        if command == "fill":
            args += ["-o", str(tmp_path / "out.pdf")]
        result = CliRunner().invoke(main, args)
    finally:
        pdf.chmod(0o600)
    assert result.exit_code == 2  # click validates readability before any work
    assert isinstance(result.exception, SystemExit)
    assert "is not readable" in result.output

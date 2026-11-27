"""Starter JSON, CSV batches, dry runs, the on-disk report, and POST /batch."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient
from pypdf import PdfReader

from pdf_autofiller import fill, fill_template, preview_batch
from pdf_autofiller.api import config
from pdf_autofiller.api.security import reset_rate_limit_state
from pdf_autofiller.api_service import app
from pdf_autofiller.cli import main
from pdf_autofiller.records import RecordsError, parse_records

SAMPLE = Path("samples/sample_form.pdf")


def _values(path: Path) -> dict[str, str | None]:
    return {name: field.get("/V") for name, field in PdfReader(path).get_fields().items()}


def test_template_keys_round_trip_into_the_sample_form(tmp_path: Path):
    template = fill_template(SAMPLE)
    assert template.required_keys == ["first_name", "last_name", "date_of_birth"]
    assert set(template.example) >= set(template.required_keys)
    data = {
        "first_name": "Jane",
        "last_name": "Doe",
        "date_of_birth": "1990-01-01",
        "email_address": "jane@example.com",
        "phone_number": "555-0100",
    }
    output = tmp_path / "filled.pdf"
    fill(SAMPLE, data, output)
    values = _values(output)
    assert values["txtFirstName"] == "Jane"
    assert values["txtEmail"] == "jane@example.com"


def test_template_keeps_a_second_widget_when_keys_collide(tmp_path: Path):
    from tests.form_factory import FormBuilder

    pdf = tmp_path / "two.pdf"
    FormBuilder().text("txtFirstName", required=True).text("given_name", required=True).save(pdf)
    template = fill_template(pdf)
    keys = [field.key for field in template.fields]
    assert keys[0] == "first_name"
    assert keys[1] == "given_name"
    assert len(set(keys)) == 2


def test_cli_inspect_template_prints_the_starter_object():
    result = CliRunner().invoke(main, ["inspect", str(SAMPLE), "--template"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["example"]["first_name"] == ""
    assert "first_name" in payload["required_keys"]


def test_records_reject_malformed_json_jsonl_and_headers(monkeypatch):
    with pytest.raises(RecordsError, match="JSON array"):
        parse_records('{"firstname": "Jane"}', fmt="json")
    with pytest.raises(RecordsError, match="Invalid JSON"):
        parse_records("[", fmt="json")
    with pytest.raises(RecordsError, match="JSON object"):
        parse_records('["Jane"]', fmt="json")
    with pytest.raises(RecordsError, match="at least one"):
        parse_records("[]", fmt="json")
    with pytest.raises(RecordsError, match="line 2"):
        parse_records('{"firstname": "Jane"}\nnot-json\n', fmt="jsonl")
    parsed = parse_records('{"firstname": "Jane"}\n\n{"lastname": "Doe"}\n', fmt="jsonl")
    assert parsed == [{"firstname": "Jane"}, {"lastname": "Doe"}]
    with pytest.raises(RecordsError, match="no header"):
        parse_records("\n", fmt="csv")
    with pytest.raises(RecordsError, match="empty column"):
        parse_records("firstname,\nJane,Doe\n", fmt="csv")
    with pytest.raises(RecordsError, match="at least 1"):
        parse_records('[{"a": 1}]', fmt="json", max_records=0)

    nested: dict[str, object] = {"value": "x"}
    for _ in range(20):
        nested = {"child": nested}
    with pytest.raises(RecordsError, match="nested too deeply"):
        parse_records(json.dumps([nested]), fmt="json")

    monkeypatch.setenv("BATCH_MAX_RECORDS", "nope")
    from pdf_autofiller.records import max_batch_records

    assert max_batch_records() == 25
    monkeypatch.setenv("BATCH_MAX_RECORDS", "9000")
    assert max_batch_records() == 500


def test_csv_keeps_formula_text_and_rejects_hostile_tables():
    records = parse_records(
        "firstname,lastname,dob\n=cmd|'/c calc',Doe,1990-01-01\n",
        fmt="csv",
    )
    assert records == [{"firstname": "=cmd|'/c calc'", "lastname": "Doe", "dob": "1990-01-01"}]

    with pytest.raises(RecordsError, match="duplicate"):
        parse_records("firstname,firstname\nA,B\n", fmt="csv")
    with pytest.raises(RecordsError, match="more columns"):
        parse_records('firstname,lastname\n"Jane",Doe,extra\n', fmt="csv")
    with pytest.raises(RecordsError, match="NUL"):
        parse_records("firstname\nJane\x00\n", fmt="csv")
    with pytest.raises(RecordsError, match="limit") as limited:
        parse_records("firstname,lastname,dob\n" + "A,B,1990-01-01\n" * 3, fmt="csv", max_records=2)
    assert limited.value.code == "too_many_records"

    quoted = parse_records('firstname,note\nJane,"line one\nline two"\n', fmt="csv")
    assert quoted[0]["note"] == "line one\nline two"


def test_csv_batch_writes_formula_text_and_a_report(tmp_path: Path):
    sheet = tmp_path / "people.csv"
    sheet.write_text(
        "firstname,lastname,dob\n=Jane,Doe,1990-01-01\nSam,Lee,1988-07-04\n",
        encoding="utf-8",
    )
    out = tmp_path / "pdfs"
    result = CliRunner().invoke(main, ["batch", str(SAMPLE), str(sheet), "-o", str(out)])
    assert result.exit_code == 0, result.output
    report = json.loads((out / "fill-report.json").read_text(encoding="utf-8"))
    assert report["written"] == 2
    assert _values(out / "record-0001.pdf")["txtFirstName"] == "=Jane"
    assert json.loads(result.output)["report_path"].endswith("fill-report.json")


def test_dry_run_writes_nothing_and_flags_the_bad_row(tmp_path: Path):
    records = [
        {"firstname": "Jane", "lastname": "Doe", "dob": "1990-01-01"},
        {"firstname": "Only"},
    ]
    before = set(tmp_path.iterdir())
    report = preview_batch(SAMPLE, records)
    assert set(tmp_path.iterdir()) == before
    assert report.written == 1
    assert report.failed == 1
    assert report.report_path is None
    assert "txtLastName" in (report.items[1].error or "")

    data = tmp_path / "people.json"
    data.write_text(json.dumps(records), encoding="utf-8")
    result = CliRunner().invoke(main, ["batch", str(SAMPLE), str(data), "--dry-run"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["failed"] == 1
    assert list(tmp_path.glob("*.pdf")) == []


def test_api_batch_returns_pdfs_and_rejects_too_many(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(config, "API_AUTH_ENABLED", False)
    reset_rate_limit_state()
    client = TestClient(app)
    pdf = SAMPLE.read_bytes()
    records = [
        {"firstname": "Jane", "lastname": "Doe", "dob": "1990-01-01"},
        {"firstname": "Only"},
    ]
    response = client.post(
        "/batch",
        files={"pdf_file": ("form.pdf", pdf, "application/pdf")},
        data={"records": json.dumps(records), "records_format": "json", "filename_key": "lastname"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["written"] == 1
    assert body["failed"] == 1
    assert body["items"][0]["filename"] == "Doe.pdf"
    assert body["items"][0]["pdf_base64"]
    assert body["items"][1]["pdf_base64"] is None

    dry = client.post(
        "/batch",
        files={"pdf_file": ("form.pdf", pdf, "application/pdf")},
        data={"records": json.dumps(records), "dry_run": "true"},
    )
    assert dry.status_code == 200
    assert dry.json()["dry_run"] is True
    assert dry.json()["items"][0]["pdf_base64"] is None

    crowded = "firstname,lastname,dob\n" + "A,B,1990-01-01\n" * 3
    monkeypatch.setenv("BATCH_MAX_RECORDS", "2")
    too_many = client.post(
        "/batch",
        files={"pdf_file": ("form.pdf", pdf, "application/pdf")},
        data={"records": crowded, "records_format": "csv"},
    )
    assert too_many.status_code == 422
    assert too_many.json()["detail"]["error"]["code"] == "too_many_records"

    denied = TestClient(app)
    monkeypatch.setattr(config, "API_AUTH_ENABLED", True)
    monkeypatch.setattr(config, "API_AUTH_TOKEN", "secret")
    locked = denied.post(
        "/batch",
        files={"pdf_file": ("form.pdf", pdf, "application/pdf")},
        data={"records": "[]"},
    )
    assert locked.status_code == 401
    reset_rate_limit_state()


def test_api_batch_rejects_aggregate_pdf_response_over_limit(monkeypatch):
    monkeypatch.setattr(config, "API_AUTH_ENABLED", False)
    monkeypatch.setattr(config, "BATCH_MAX_RESPONSE_BYTES", 1)
    reset_rate_limit_state()
    response = TestClient(app).post(
        "/batch",
        files={"pdf_file": ("form.pdf", SAMPLE.read_bytes(), "application/pdf")},
        data={"records": json.dumps([{"firstname": "Jane", "lastname": "Doe", "dob": "1990-01-01"}])},
    )
    assert response.status_code == 413
    error = response.json()["detail"]["error"]
    assert error["code"] == "batch_output_too_large"
    assert error["details"]["generated_bytes"] > error["details"]["max_response_bytes"]

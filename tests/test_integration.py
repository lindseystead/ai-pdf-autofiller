"""End-to-end pipeline tests against real sample PDFs."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from pdf_autofiller import api_service
from pdf_autofiller.acroform_fields import get_field_value
from pdf_autofiller.pipeline import run_fill_pipeline

SAMPLE_PDF = Path("samples/sample_form.pdf")


@pytest.mark.skipif(not SAMPLE_PDF.exists(), reason="sample PDF not present")
def test_sample_form_round_trip_writes_required_fields(tmp_path: Path):
    user_data = {
        "firstname": "Jane",
        "lastname": "Doe",
        "dob": "1990-01-01",
        "email": "jane@example.com",
    }
    output_path = tmp_path / "filled.pdf"

    result = run_fill_pipeline(
        SAMPLE_PDF,
        output_path,
        user_data,
        strict=True,
        allow_fallback_mapping=False,
        use_semantic_inference=False,
    )
    report = result.fill_report

    assert result.fields_total >= 3
    assert output_path.exists()
    assert "txtFirstName" in report.written_fields
    assert "txtLastName" in report.written_fields
    assert "txtDOB" in report.written_fields
    assert not report.failed_fields
    assert not result.mapping_result.missing_required
    # The default path must not contact a provider at all.
    assert result.telemetry.provider_calls == 0
    assert result.telemetry.semantic_inference_requested is False

    reader = PdfReader(str(output_path))
    fields = reader.get_fields() or {}
    assert get_field_value(fields["txtFirstName"]) == "Jane"
    assert get_field_value(fields["txtLastName"]) == "Doe"
    assert get_field_value(fields["txtDOB"]) == "1990-01-01"


@pytest.mark.skipif(not SAMPLE_PDF.exists(), reason="sample PDF not present")
def test_fill_endpoint_round_trip_with_sample_pdf():
    client = TestClient(api_service.app)
    original_auth = api_service.API_AUTH_ENABLED
    api_service.API_AUTH_ENABLED = False
    try:
        response = client.post(
            "/fill",
            files={"pdf_file": (SAMPLE_PDF.name, SAMPLE_PDF.read_bytes(), "application/pdf")},
            data={
                "user_data": '{"firstname":"Jane","lastname":"Doe","dob":"1990-01-01"}',
                "strict": "true",
            },
        )
    finally:
        api_service.API_AUTH_ENABLED = original_auth

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert int(response.headers["X-PDF-Fields-Written"]) >= 3


def test_health_reports_alias_packs_and_auth_state(monkeypatch):
    client = TestClient(api_service.app)
    monkeypatch.setattr(api_service, "API_AUTH_ENABLED", True)
    monkeypatch.setattr(api_service, "API_AUTH_TOKEN", "")

    response = client.get("/health")
    payload = response.json()

    assert payload["status"] == "degraded"
    assert payload["checks"]["auth"] == "misconfigured"
    assert int(payload["checks"]["alias_pack_count"]) >= 1

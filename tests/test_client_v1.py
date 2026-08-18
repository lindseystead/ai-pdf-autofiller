"""SDK client coverage for the inspect and report surfaces."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pdf_autofiller import api_service
from pdf_autofiller.client import PDFAutofillerClient, PDFAutofillError
from pdf_autofiller.http_support import reset_rate_limit_state
from pdf_autofiller.settings import Settings, set_settings

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "sample_form.pdf"
COMPLETE = {
    "firstname": "Jane",
    "lastname": "Doe",
    "dob": "1990-01-01",
    "email": "jane@example.com",
    "phone": "555-0100",
}


@pytest.fixture
def sdk(tmp_path):
    """An SDK client wired directly to the app, with no network in between.

    TestClient is itself a sync httpx.Client, so it can be injected straight
    into the SDK; httpx's own ASGITransport is async-only.
    """
    set_settings(
        Settings(auth_enabled=False, rate_limit_per_minute=0, state_dir=tmp_path / "state")
    )
    reset_rate_limit_state()
    http = TestClient(api_service.app, base_url="http://testserver")
    yield PDFAutofillerClient(base_url="http://testserver", http_client=http)
    http.close()
    set_settings(None)


def test_inspect_returns_field_report(sdk):
    report = sdk.inspect(SAMPLE, {"firstname": "Jane"})
    assert len(report["fields"]) == 5
    assert "txtFirstName" in report["would_write"]
    assert report["fingerprint"]


def test_inspect_accepts_raw_bytes(sdk):
    report = sdk.inspect(SAMPLE.read_bytes(), filename="x.pdf")
    assert len(report["fields"]) == 5


def test_fill_returns_pdf_and_headers(sdk):
    content, headers = sdk.fill(SAMPLE, COMPLETE)
    assert content.startswith(b"%PDF")
    assert headers["x-pdf-fields-written"] == "5"


def test_fill_with_flatten_and_overrides(sdk):
    content, headers = sdk.fill(
        SAMPLE, COMPLETE, flatten=True, overrides={"txtFirstName": "Overridden"}
    )
    assert headers["x-pdf-flattened"] == "true"
    assert content.startswith(b"%PDF")


def test_fill_with_report_returns_structured_result(sdk):
    result = sdk.fill_with_report(SAMPLE, COMPLETE)
    assert result["fields_total"] == 5
    assert len(result["report"]["written_fields"]) == 5
    assert result["pdf_base64"]
    assert result["filename"].endswith("_filled.pdf")


def test_fill_to_file_writes_output(sdk, tmp_path):
    target = tmp_path / "out.pdf"
    headers = sdk.fill_to_file(SAMPLE, COMPLETE, target)
    assert target.read_bytes().startswith(b"%PDF")
    assert headers["x-pdf-fields-written"] == "5"


def test_api_errors_surface_with_code_and_details(sdk):
    with pytest.raises(PDFAutofillError) as excinfo:
        sdk.fill(SAMPLE, {"firstname": "Jane"})  # missing required fields
    assert excinfo.value.code == "required_fields_unresolved"
    assert excinfo.value.status_code == 422
    assert "txtLastName" in excinfo.value.details["missing_fields"]


def test_health_exposes_alias_and_cache_state(sdk):
    payload = sdk.health()
    assert payload["service"] == "pdf-autofiller"
    assert "alias_pack_count" in payload["checks"]
    assert "semantics_cache_entries" in payload["checks"]


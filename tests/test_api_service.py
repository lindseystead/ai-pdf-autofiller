"""Tests for FastAPI service wrapper."""

import io

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from pdf_autofiller import api_service
from pdf_autofiller.models import EnrichedFormField, FieldSemantics, FormField, TextRegion


client = TestClient(api_service.app)


@pytest.fixture(autouse=True)
def _isolate_request_guards(monkeypatch):
    """Run tests without auth and with a clean rate-limiter by default.

    Authentication now defaults to enabled in production; the auth-specific
    tests opt back in explicitly.
    """
    monkeypatch.setattr(api_service, "API_AUTH_ENABLED", False)
    api_service._reset_rate_limit_state()
    yield
    api_service._reset_rate_limit_state()


def _minimal_pdf_bytes(pages: int = 1) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "pdf-autofiller"
    assert "X-Request-ID" in response.headers


def test_version_endpoint():
    response = client.get("/version")
    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "pdf-autofiller"
    assert isinstance(payload["version"], str)


def test_page_context_by_number_groups_text_by_page():
    contexts = api_service._page_context_by_number(
        [
            TextRegion(text="First", page_number=1),
            TextRegion(text="Second", page_number=1),
            TextRegion(text="Third", page_number=2),
        ]
    )

    assert contexts == {1: "First\nSecond", 2: "Third"}


def test_enrich_fields_passes_page_context_to_ai(monkeypatch):
    observed: dict[str, str | None] = {"context": None}

    def fake_infer(field, context_text=None):
        observed["context"] = context_text
        return EnrichedFormField(
            field=field,
            semantics=FieldSemantics(
                semantic_meaning="first_name",
                expected_data_type="string",
                confidence_score=0.95,
            ),
        )

    monkeypatch.setattr(api_service, "infer_field_semantics", fake_infer)

    field = FormField(name="txtFirstName", field_type="text", required=True, page_number=1)
    enriched_fields = api_service._enrich_fields(
        [field],
        use_semantic_inference=True,
        page_context={1: "Applicant First Name"},
    )

    assert observed["context"] == "Applicant First Name"
    assert len(enriched_fields) == 1


def test_fill_endpoint_rejects_invalid_json():
    response = client.post(
        "/fill",
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        data={"user_data": "{invalid", "strict": "true"},
    )
    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"]["error"]["code"] == "invalid_user_data_json"
    assert payload["detail"]["error"]["message"] == "Invalid user_data JSON"


def test_fill_endpoint_rejects_non_object_json():
    response = client.post(
        "/fill",
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        data={"user_data": '["not","an","object"]'},
    )
    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"]["error"]["code"] == "invalid_user_data_type"


def test_fill_endpoint_rejects_unsupported_media_type():
    response = client.post(
        "/fill",
        files={"pdf_file": ("input.txt", b"not a pdf", "text/plain")},
        data={"user_data": '{"firstname":"John"}'},
    )
    assert response.status_code == 415
    payload = response.json()
    assert payload["detail"]["error"]["code"] == "unsupported_media_type"


def test_fill_endpoint_rejects_invalid_pdf_signature():
    response = client.post(
        "/fill",
        files={"pdf_file": ("input.pdf", b"not-a-real-pdf", "application/pdf")},
        data={"user_data": '{"firstname":"John"}'},
    )
    assert response.status_code == 415
    payload = response.json()
    assert payload["detail"]["error"]["code"] == "invalid_pdf_signature"


def test_fill_endpoint_returns_pdf():
    response = client.post(
        "/fill",
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        data={
            "user_data": '{"firstname":"John","lastname":"Doe"}',
            "strict": "true",
            "allow_fallback_mapping": "false",
            "use_semantic_inference": "false",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_fill_endpoint_exposes_fill_report_headers():
    response = client.post(
        "/fill",
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        data={
            "user_data": '{"firstname":"John","lastname":"Doe"}',
            "strict": "true",
        },
    )
    assert response.status_code == 200
    assert "X-PDF-Fields-Written" in response.headers
    assert "X-PDF-Fields-Skipped-Review" in response.headers
    assert "X-PDF-Fields-Skipped-Empty" in response.headers


def test_fill_endpoint_rate_limited(monkeypatch):
    monkeypatch.setattr(api_service, "RATE_LIMIT_PER_MINUTE", 1)

    payload = {
        "files": {"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        "data": {"user_data": '{"firstname":"John","lastname":"Doe"}', "strict": "true"},
    }
    first = client.post("/fill", **payload)
    second = client.post("/fill", **payload)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["detail"]["error"]["code"] == "rate_limited"


def test_fill_endpoint_rejects_too_many_pages(monkeypatch):
    monkeypatch.setattr(api_service, "MAX_PDF_PAGES", 1)

    response = client.post(
        "/fill",
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(pages=2), "application/pdf")},
        data={"user_data": '{"firstname":"John"}', "strict": "true"},
    )
    assert response.status_code == 413
    assert response.json()["detail"]["error"]["code"] == "pdf_too_many_pages"


def test_fill_endpoint_times_out_on_slow_read(monkeypatch):
    import time

    def slow_read(_path, *, max_pages=None):
        time.sleep(0.3)
        raise AssertionError("should have timed out before returning")

    monkeypatch.setattr(api_service, "read_pdf", slow_read)
    monkeypatch.setattr(api_service, "PDF_READ_TIMEOUT_SECONDS", 0.01)

    response = client.post(
        "/fill",
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        data={"user_data": '{"firstname":"John"}', "strict": "true"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["error"]["code"] == "pdf_processing_timeout"


def test_fill_endpoint_requires_api_key_when_enabled(monkeypatch):
    monkeypatch.setattr(api_service, "API_AUTH_ENABLED", True)
    monkeypatch.setattr(api_service, "API_AUTH_TOKEN", "secret-token")
    monkeypatch.setattr(api_service, "API_KEY_HEADER", "X-API-Key")

    response = client.post(
        "/fill",
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        data={"user_data": '{"firstname":"John"}'},
    )
    assert response.status_code == 401
    payload = response.json()
    assert payload["detail"]["error"]["code"] == "unauthorized"


def test_fill_endpoint_returns_server_auth_config_error(monkeypatch):
    monkeypatch.setattr(api_service, "API_AUTH_ENABLED", True)
    monkeypatch.setattr(api_service, "API_AUTH_TOKEN", "")
    monkeypatch.setattr(api_service, "API_KEY_HEADER", "X-API-Key")

    response = client.post(
        "/fill",
        headers={"X-API-Key": "any-token"},
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        data={"user_data": '{"firstname":"John"}'},
    )
    assert response.status_code == 500
    payload = response.json()
    assert payload["detail"]["error"]["code"] == "server_auth_config_error"


def test_fill_endpoint_accepts_api_key_when_enabled(monkeypatch):
    monkeypatch.setattr(api_service, "API_AUTH_ENABLED", True)
    monkeypatch.setattr(api_service, "API_AUTH_TOKEN", "secret-token")
    monkeypatch.setattr(api_service, "API_KEY_HEADER", "X-API-Key")

    response = client.post(
        "/fill",
        headers={"X-API-Key": "secret-token"},
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        data={"user_data": '{"firstname":"John","lastname":"Doe"}'},
    )
    assert response.status_code == 200


def test_fill_endpoint_rejects_large_upload(monkeypatch):
    monkeypatch.setattr(api_service, "MAX_UPLOAD_BYTES", 20)

    response = client.post(
        "/fill",
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        data={"user_data": '{"firstname":"John"}'},
    )
    assert response.status_code == 413
    payload = response.json()
    assert payload["detail"]["error"]["code"] == "payload_too_large"


def test_fill_endpoint_returns_required_fields_unresolved_code(monkeypatch):
    def fake_fill_pdf(_in_path, _out_path, _result):
        raise api_service.UnresolvedRequiredFieldsError(
            missing_fields=["txtRequired"],
            skipped_fields=[],
        )

    monkeypatch.setattr(api_service, "fill_pdf", fake_fill_pdf)

    response = client.post(
        "/fill",
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        data={"user_data": '{"firstname":"John"}'},
    )
    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"]["error"]["code"] == "required_fields_unresolved"


def test_fill_endpoint_returns_pdf_fill_failed_code(monkeypatch):
    def fake_read_pdf(_path):
        raise RuntimeError("boom")

    monkeypatch.setattr(api_service, "read_pdf", fake_read_pdf)

    response = client.post(
        "/fill",
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        data={"user_data": '{"firstname":"John"}'},
    )
    assert response.status_code == 500
    payload = response.json()
    assert payload["detail"]["error"]["code"] == "pdf_fill_failed"


def test_fill_endpoint_validation_error_contract_when_missing_user_data():
    response = client.post(
        "/fill",
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
    )
    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"]["error"]["code"] == "request_validation_error"

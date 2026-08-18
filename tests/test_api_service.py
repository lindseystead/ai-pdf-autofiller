"""Tests for FastAPI service wrapper."""

import io

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from pdf_autofiller import api_service
from pdf_autofiller.models import FieldSemantics, FormField, TextRegion
from pdf_autofiller.http_support import reset_rate_limit_state
from pdf_autofiller.settings import Settings, set_settings


client = TestClient(api_service.app)


def configure(**overrides):
    """Install a Settings object for one test.

    Configuration is a validated object rather than module globals, so tests
    build the exact settings they need instead of poking attributes.
    """
    base = {"auth_enabled": False, "rate_limit_per_minute": 0}
    base.update(overrides)
    settings = Settings(**base)
    set_settings(settings)
    return settings


@pytest.fixture(autouse=True)
def _isolate_request_guards():
    """Run tests without auth and with a clean rate-limiter by default.

    Authentication now defaults to enabled in production; the auth-specific
    tests opt back in explicitly.
    """
    configure()
    reset_rate_limit_state()
    yield
    reset_rate_limit_state()
    set_settings(None)


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
    """Inference sees the page text, and runs once for the whole form."""
    observed: dict[str, object] = {}

    def fake_infer_batch(fields, page_context=None, api_key=None):
        observed["page_context"] = page_context
        observed["field_names"] = [f.name for f in fields]
        observed["calls"] = observed.get("calls", 0) + 1
        return {
            f.name: FieldSemantics(
                semantic_meaning="first_name",
                expected_data_type="string",
                confidence_score=0.95,
            )
            for f in fields
        }

    from pdf_autofiller import pipeline as fill_pipeline

    monkeypatch.setattr(fill_pipeline, "infer_fields_semantics", fake_infer_batch)

    fields = [
        FormField(name="txtFirstName", field_type="text", required=True, page_number=1),
        FormField(name="txtLastName", field_type="text", required=True, page_number=1),
    ]
    enriched_fields = api_service._enrich_fields(
        fields,
        use_semantic_inference=True,
        page_context={1: "Applicant First Name"},
    )

    assert observed["page_context"] == {1: "Applicant First Name"}
    assert observed["field_names"] == ["txtFirstName", "txtLastName"]
    # One request for the whole form, not one per field.
    assert observed["calls"] == 1
    assert len(enriched_fields) == 2


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


def test_fill_endpoint_emits_pii_free_audit_log(caplog):
    import logging

    secret_value = "Top-Secret-Applicant-Name"
    with caplog.at_level(logging.INFO, logger="pdf_autofiller.api_service"):
        response = client.post(
            "/fill",
            files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
            data={
                "user_data": f'{{"firstname":"{secret_value}"}}',
                "strict": "true",
            },
        )

    assert response.status_code == 200
    audit_lines = [r.getMessage() for r in caplog.records if "action=fill" in r.getMessage()]
    assert audit_lines, "expected an audit log line"
    # The audit trail must never contain raw user values.
    assert secret_value not in caplog.text


def test_fill_endpoint_rate_limited(monkeypatch):
    configure(rate_limit_per_minute=1)

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
    configure(max_pdf_pages=1)

    response = client.post(
        "/fill",
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(pages=2), "application/pdf")},
        data={"user_data": '{"firstname":"John"}', "strict": "true"},
    )
    assert response.status_code == 413
    assert response.json()["detail"]["error"]["code"] == "pdf_too_many_pages"


def test_fill_endpoint_times_out_on_slow_read(monkeypatch):
    import time

    def slow_pipeline(*_args, **_kwargs):
        time.sleep(0.3)
        raise AssertionError("should have timed out before returning")

    monkeypatch.setattr(api_service, "run_fill_pipeline", slow_pipeline)
    configure(pdf_read_timeout_seconds=0.01)

    response = client.post(
        "/fill",
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        data={"user_data": '{"firstname":"John"}', "strict": "true"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["error"]["code"] == "pdf_processing_timeout"


def test_fill_endpoint_requires_api_key_when_enabled(monkeypatch):
    configure(auth_enabled=True, api_token="secret-token", api_key_header="X-API-Key")

    response = client.post(
        "/fill",
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        data={"user_data": '{"firstname":"John"}'},
    )
    assert response.status_code == 401
    payload = response.json()
    assert payload["detail"]["error"]["code"] == "unauthorized"


def test_fill_endpoint_returns_server_auth_config_error(monkeypatch):
    configure(auth_enabled=True, api_token="", api_key_header="X-API-Key")

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
    configure(auth_enabled=True, api_token="secret-token", api_key_header="X-API-Key")

    response = client.post(
        "/fill",
        headers={"X-API-Key": "secret-token"},
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        data={"user_data": '{"firstname":"John","lastname":"Doe"}'},
    )
    assert response.status_code == 200


def test_fill_endpoint_rejects_large_upload(monkeypatch):
    configure(max_upload_bytes=20)

    response = client.post(
        "/fill",
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        data={"user_data": '{"firstname":"John"}'},
    )
    assert response.status_code == 413
    payload = response.json()
    assert payload["detail"]["error"]["code"] == "payload_too_large"


def test_fill_endpoint_returns_required_fields_unresolved_code(monkeypatch):
    def fake_pipeline(*_args, **_kwargs):
        raise api_service.UnresolvedRequiredFieldsError(
            missing_fields=["txtRequired"],
            skipped_fields=[],
        )

    monkeypatch.setattr(api_service, "run_fill_pipeline", fake_pipeline)

    response = client.post(
        "/fill",
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        data={"user_data": '{"firstname":"John"}'},
    )
    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"]["error"]["code"] == "required_fields_unresolved"


def test_fill_endpoint_returns_pdf_fill_failed_code(monkeypatch):
    def failing_pipeline(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(api_service, "run_fill_pipeline", failing_pipeline)

    response = client.post(
        "/fill",
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        data={"user_data": '{"firstname":"John"}'},
    )
    assert response.status_code == 500
    payload = response.json()
    assert payload["detail"]["error"]["code"] == "pdf_fill_failed"


def test_fill_endpoint_rejects_request_with_no_data_source():
    """user_data is optional (a profile or template can supply it) but not absent.

    Filling with nothing would return an unchanged document that looks like a
    successful fill, so the request is rejected instead.
    """
    response = client.post(
        "/fill",
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
    )
    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"]["error"]["code"] == "no_fill_data"

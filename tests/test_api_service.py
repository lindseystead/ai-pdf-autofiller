"""Tests for FastAPI service wrapper."""

import io

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from pdf_autofiller import api_service

client = TestClient(api_service.app)


@pytest.fixture(autouse=True)
def _isolate_request_guards(monkeypatch):
    """Run tests without auth and with a clean rate-limiter by default.

    Authentication now defaults to enabled in production; the auth-specific
    tests opt back in explicitly.
    """
    monkeypatch.setattr(api_service, "API_AUTH_ENABLED", False)
    api_service._rate_limit_state.clear()
    _wait_for_idle_workers()
    yield
    api_service._rate_limit_state.clear()


def _wait_for_idle_workers(timeout: float = 5.0) -> None:
    """Wait until no PDF job is in flight.

    A timed-out job deliberately keeps its worker slot until it truly finishes,
    so tests that assert on capacity must start from a quiesced pool.
    """
    import time

    deadline = time.monotonic() + timeout
    while api_service._active_pdf_jobs > 0 and time.monotonic() < deadline:
        time.sleep(0.01)


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
    assert "X-PDF-Fields-Failed" in response.headers
    assert "X-PDF-Fields-Skipped-Review" in response.headers
    assert "X-PDF-Fields-Skipped-Empty" in response.headers
    # A run that never asked for the model path reports "off", not silence.
    assert response.headers["X-PDF-Semantic-Inference"] == "off"
    assert response.headers["X-PDF-Provider-Calls"] == "0"


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

    def slow_pipeline(*_args, **_kwargs):
        time.sleep(0.3)
        raise AssertionError("should have timed out before returning")

    monkeypatch.setattr(api_service, "run_fill_pipeline", slow_pipeline)
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


def test_fill_endpoint_validation_error_contract_when_missing_user_data():
    response = client.post(
        "/fill",
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
    )
    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"]["error"]["code"] == "request_validation_error"


def test_fill_endpoint_reports_degraded_semantic_inference():
    """Requesting inference without a provider must be visible, not silent."""
    response = client.post(
        "/fill",
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        data={
            "user_data": '{"firstname":"John","lastname":"Doe"}',
            "strict": "true",
            "use_semantic_inference": "true",
        },
    )
    assert response.status_code == 200
    assert response.headers["X-PDF-Semantic-Inference"] == "degraded"


def test_audit_log_records_actual_model_activity(caplog):
    """The audit line reports what ran, not merely which flag was passed."""
    import logging

    with caplog.at_level(logging.INFO, logger="pdf_autofiller.api_service"):
        response = client.post(
            "/fill",
            files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
            data={
                "user_data": '{"firstname":"John"}',
                "strict": "true",
                "use_semantic_inference": "true",
            },
        )

    assert response.status_code == 200
    audit = next(r.getMessage() for r in caplog.records if "action=fill" in r.getMessage())
    # Requested but not applied: the flag alone never implies the model ran.
    assert "semantic_requested=True" in audit
    assert "semantic_applied=False" in audit
    assert "provider_calls=0" in audit
    assert "model=none" in audit


def test_semantic_request_gets_its_own_time_budget(monkeypatch):
    """Model latency is not charged to the PDF parsing clock."""
    monkeypatch.setattr(api_service, "PDF_READ_TIMEOUT_SECONDS", 20.0)
    monkeypatch.setattr(api_service, "SEMANTIC_TIMEOUT_SECONDS", 45.0)

    assert (
        api_service._request_time_budget(
            use_semantic_inference=False, allow_fallback_mapping=False
        )
        == 20.0
    )
    assert (
        api_service._request_time_budget(
            use_semantic_inference=True, allow_fallback_mapping=False
        )
        == 65.0
    )
    assert (
        api_service._request_time_budget(
            use_semantic_inference=False, allow_fallback_mapping=True
        )
        == 65.0
    )


def test_saturated_worker_pool_sheds_load(monkeypatch):
    """Capacity is bounded, so excess work is refused rather than queued."""
    monkeypatch.setattr(api_service, "PDF_WORKER_THREADS", 1)
    monkeypatch.setattr(api_service, "PDF_QUEUE_DEPTH", 0)
    monkeypatch.setattr(api_service, "_active_pdf_jobs", 1)

    response = client.post(
        "/fill",
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        data={"user_data": '{"firstname":"John"}', "strict": "true"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["error"]["code"] == "server_busy"


def test_timed_out_job_holds_its_slot_until_it_finishes(monkeypatch):
    """A job that outlives its request keeps consuming capacity until done.

    This is what stops timed-out work from silently accumulating: the 503 is
    returned to the client, but the worker slot is not handed back early.
    """
    import threading
    import time

    release = threading.Event()
    started = threading.Event()

    def blocking_pipeline(*_args, **_kwargs):
        started.set()
        release.wait(timeout=5)
        raise RuntimeError("job finished after its request gave up")

    monkeypatch.setattr(api_service, "run_fill_pipeline", blocking_pipeline)
    monkeypatch.setattr(api_service, "PDF_READ_TIMEOUT_SECONDS", 0.05)

    baseline = api_service._active_pdf_jobs
    response = client.post(
        "/fill",
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        data={"user_data": '{"firstname":"John"}', "strict": "true"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["error"]["code"] == "pdf_processing_timeout"
    assert started.is_set()
    # Still occupying a slot while the orphaned thread runs.
    assert api_service._active_pdf_jobs == baseline + 1

    release.set()
    deadline = time.monotonic() + 5
    while api_service._active_pdf_jobs != baseline and time.monotonic() < deadline:
        time.sleep(0.01)
    assert api_service._active_pdf_jobs == baseline


def test_health_reports_model_provider_state():
    payload = client.get("/health").json()
    assert payload["checks"]["model_provider"] in ("configured", "not_configured")
    assert payload["checks"]["model_name"]


def test_header_values_strip_control_characters():
    """Field names come from untrusted PDFs; CR/LF must never reach a header.

    Otherwise a crafted field name breaks response header framing — a 500 on a
    strict ASGI server, response splitting on a permissive one.
    """
    rendered = api_service._safe_header_value(
        ["good_field", "evil\r\nX-Injected: yes", "nul\x00byte", "tab\tfield"]
    )

    for forbidden in ("\r", "\n", "\x00", "\t"):
        assert forbidden not in rendered
    assert "good_field" in rendered
    assert all(32 <= ord(char) < 127 for char in rendered)

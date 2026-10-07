"""Tests for FastAPI service wrapper."""

import io
import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from pdf_autofiller import api_service
from pdf_autofiller.api import config
from pdf_autofiller.api import routes as api_routes
from pdf_autofiller.api.security import reset_rate_limit_state
from pdf_autofiller.models import FieldSemantics, FormField, TextRegion
from pdf_autofiller.pdf_writer import UnresolvedRequiredFieldsError
from pdf_autofiller.pipeline import enrich_fields, page_context_by_number

client = TestClient(api_service.app)


@pytest.fixture(autouse=True)
def _isolate_request_guards(monkeypatch):
    """Run tests without auth and with a clean rate-limiter by default."""
    monkeypatch.setattr(config, "API_AUTH_ENABLED", False)
    reset_rate_limit_state()
    yield
    reset_rate_limit_state()


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
    assert payload["checks"]["semantic_provider"] in {
        "available",
        "unconfigured",
        "sdk_missing",
    }
    assert "X-Request-ID" in response.headers


def test_version_endpoint():
    response = client.get("/version")
    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "pdf-autofiller"
    assert isinstance(payload["version"], str)


def test_page_context_by_number_groups_text_by_page():
    contexts = page_context_by_number(
        [
            TextRegion(text="First", page_number=1),
            TextRegion(text="Second", page_number=1),
            TextRegion(text="Third", page_number=2),
        ]
    )

    assert contexts == {1: "First\nSecond", 2: "Third"}


def test_enrich_fields_passes_page_context_to_ai(monkeypatch):
    observed: dict[str, object] = {"page_context": None}

    def fake_batch(self, fields, *, page_context=None):
        observed["page_context"] = page_context
        return {
            fields[0].name: FieldSemantics(
                semantic_meaning="first_name",
                expected_data_type="string",
                confidence_score=0.95,
            )
        }

    from pdf_autofiller import pipeline as fill_pipeline

    monkeypatch.setattr(fill_pipeline.SemanticClient, "infer_semantics_batch", fake_batch)

    field = FormField(name="txtFirstName", field_type="text", required=True, page_number=1)
    enriched_fields = enrich_fields(
        [field],
        use_semantic_inference=True,
        page_context={1: "Applicant First Name"},
    )

    assert observed["page_context"] == {1: "Applicant First Name"}
    assert len(enriched_fields) == 1
    assert enriched_fields[0].semantics.semantic_meaning == "first_name"


def test_enrich_fields_logs_inference_failure(monkeypatch, caplog):
    import logging

    def boom(self, fields, *, page_context=None):
        raise RuntimeError("provider down")

    from pdf_autofiller import pipeline as fill_pipeline

    monkeypatch.setattr(fill_pipeline.SemanticClient, "infer_semantics_batch", boom)

    field = FormField(name="txtFirstName", field_type="text", required=True, page_number=1)
    with caplog.at_level(logging.WARNING, logger="pdf_autofiller.pipeline"):
        enriched = enrich_fields([field], use_semantic_inference=True)

    assert len(enriched) == 1
    assert enriched[0].semantics.semantic_meaning == "first_name"
    assert "Batch semantic inference failed" in caplog.text


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
    assert "X-PDF-Fields-Skipped-Unwritable" in response.headers


def test_fill_endpoint_json_accept_returns_report_with_pdf_base64():
    sample = Path("samples/sample_form.pdf")
    if not sample.exists():
        pytest.skip("sample PDF not present")

    response = client.post(
        "/fill",
        headers={"Accept": "application/json"},
        files={"pdf_file": (sample.name, sample.read_bytes(), "application/pdf")},
        data={
            "user_data": '{"firstname":"Jane","lastname":"Doe","dob":"1990-01-01"}',
            "strict": "true",
        },
    )
    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"]
    payload = response.json()
    assert "pdf_base64" in payload
    assert payload["field_count"] >= 3
    assert "txtFirstName" in payload["written_fields"]
    import base64

    assert base64.b64decode(payload["pdf_base64"]).startswith(b"%PDF")


def test_fill_endpoint_emits_pii_free_audit_log(caplog):
    import logging

    secret_value = "Top-Secret-Applicant-Name"
    with caplog.at_level(logging.INFO, logger="pdf_autofiller.api.routes"):
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
    assert secret_value not in caplog.text


def test_fill_endpoint_rate_limited(monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MINUTE", 1)

    payload = {
        "files": {"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        "data": {"user_data": '{"firstname":"John","lastname":"Doe"}', "strict": "true"},
    }
    first = client.post("/fill", **payload)
    second = client.post("/fill", **payload)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["detail"]["error"]["code"] == "rate_limited"
    assert second.headers.get("retry-after") == "60"


def test_fill_endpoint_file_rate_limit_shared(monkeypatch, tmp_path):
    store = tmp_path / "rate-limit.json"
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MINUTE", 1)
    monkeypatch.setattr(config, "RATE_LIMIT_BACKEND", "file")
    monkeypatch.setattr(config, "RATE_LIMIT_STORE_PATH", str(store))
    reset_rate_limit_state()

    payload = {
        "files": {"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        "data": {"user_data": '{"firstname":"John","lastname":"Doe"}', "strict": "true"},
    }
    first = client.post("/fill", **payload)
    second = client.post("/fill", **payload)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["detail"]["error"]["details"]["backend"] == "file"
    health = client.get("/health").json()
    assert health["checks"]["rate_limit"] == "shared_file"


def test_unauthorized_does_not_consume_rate_limit(monkeypatch):
    """Auth failures must not burn the per-client fill budget."""
    monkeypatch.setattr(config, "API_AUTH_ENABLED", True)
    monkeypatch.setattr(config, "API_AUTH_TOKEN", "secret-token")
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MINUTE", 1)
    reset_rate_limit_state()

    payload = {
        "files": {"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        "data": {"user_data": '{"firstname":"John","lastname":"Doe"}'},
    }
    denied = client.post("/fill", **payload)
    assert denied.status_code == 401

    allowed = client.post("/fill", headers={"X-API-Key": "secret-token"}, **payload)
    assert allowed.status_code == 200


def test_preview_endpoint_returns_mapping_decisions():
    sample = Path("samples/sample_form.pdf")
    if not sample.exists():
        pytest.skip("sample PDF not present")

    response = client.post(
        "/preview",
        files={"pdf_file": (sample.name, sample.read_bytes(), "application/pdf")},
        data={
            "user_data": '{"firstname":"Jane","lastname":"Doe","dob":"1990-01-01","extra":"x"}',
            "strict": "true",
            "allow_fallback_mapping": "false",
            "use_semantic_inference": "false",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["field_count"] >= 3
    assert payload["pages"] >= 1
    assert isinstance(payload["decisions"], list)
    names = {d["field_name"] for d in payload["decisions"]}
    assert "txtFirstName" in names
    first = next(d for d in payload["decisions"] if d["field_name"] == "txtFirstName")
    assert first["selected_value"] == "Jane"
    assert "confidence" in first and "reason" in first
    assert "extra" in payload["unmapped_user_keys"]


def test_preview_endpoint_rejects_invalid_json():
    response = client.post(
        "/preview",
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        data={"user_data": "{invalid"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"]["code"] == "invalid_user_data_json"


def test_fill_endpoint_accepts_flatten_flag():
    sample = Path("samples/sample_form.pdf")
    if not sample.exists():
        pytest.skip("sample PDF not present")

    response = client.post(
        "/fill",
        files={"pdf_file": (sample.name, sample.read_bytes(), "application/pdf")},
        data={
            "user_data": '{"firstname":"Jane","lastname":"Doe","dob":"1990-01-01"}',
            "strict": "true",
            "flatten": "true",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_security_headers_present_on_health():
    response = client.get("/health")
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert response.headers.get("referrer-policy") == "no-referrer"


def test_fill_endpoint_openapi_documents_pdf_response():
    schema = client.get("/openapi.json").json()
    fill_post = schema["paths"]["/fill"]["post"]
    content = fill_post["responses"]["200"]["content"]
    assert "application/pdf" in content
    assert "application/json" in content
    assert "/preview" in schema["paths"]


def test_inspect_endpoint_lists_sample_fields():
    sample = Path("samples/sample_form.pdf")
    if not sample.exists():
        pytest.skip("sample PDF not present")

    response = client.post(
        "/inspect",
        files={"pdf_file": (sample.name, sample.read_bytes(), "application/pdf")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["field_count"] >= 3
    names = {field["name"] for field in payload["fields"]}
    assert "txtFirstName" in names
    assert payload["opaque_field_count"] == 0
    assert all(field["name_quality"] == "readable" for field in payload["fields"])
    assert payload["mapping_hints"] == []


def test_sample_form_route_serves_pdf():
    response = client.get("/samples/sample_form.pdf")
    if response.status_code == 404:
        pytest.skip("sample PDF not bundled")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")


def test_fill_endpoint_rejects_too_many_pages(monkeypatch):
    monkeypatch.setattr(config, "MAX_PDF_PAGES", 1)

    response = client.post(
        "/fill",
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(pages=2), "application/pdf")},
        data={"user_data": '{"firstname":"John"}', "strict": "true"},
    )
    assert response.status_code == 413
    assert response.json()["detail"]["error"]["code"] == "pdf_too_many_pages"


def test_fill_endpoint_times_out_on_slow_read(monkeypatch):
    def boom(*_args, **_kwargs):
        raise TimeoutError("simulated timeout")

    monkeypatch.setattr(api_routes, "execute_pdf_job", boom)

    response = client.post(
        "/fill",
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        data={"user_data": '{"firstname":"John"}', "strict": "true"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["error"]["code"] == "pdf_processing_timeout"


def test_fill_endpoint_requires_api_key_when_enabled(monkeypatch):
    monkeypatch.setattr(config, "API_AUTH_ENABLED", True)
    monkeypatch.setattr(config, "API_AUTH_TOKEN", "secret-token")
    monkeypatch.setattr(config, "API_KEY_HEADER", "X-API-Key")

    response = client.post(
        "/fill",
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        data={"user_data": '{"firstname":"John"}'},
    )
    assert response.status_code == 401
    payload = response.json()
    assert payload["detail"]["error"]["code"] == "unauthorized"


def test_fill_endpoint_returns_server_auth_config_error(monkeypatch):
    monkeypatch.setattr(config, "API_AUTH_ENABLED", True)
    monkeypatch.setattr(config, "API_AUTH_TOKEN", "")
    monkeypatch.setattr(config, "API_KEY_HEADER", "X-API-Key")

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
    monkeypatch.setattr(config, "API_AUTH_ENABLED", True)
    monkeypatch.setattr(config, "API_AUTH_TOKEN", "secret-token")
    monkeypatch.setattr(config, "API_KEY_HEADER", "X-API-Key")

    response = client.post(
        "/fill",
        headers={"X-API-Key": "secret-token"},
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        data={"user_data": '{"firstname":"John","lastname":"Doe"}'},
    )
    assert response.status_code == 200


def test_fill_endpoint_rejects_large_upload(monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 20)

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
        raise UnresolvedRequiredFieldsError(
            missing_fields=["txtRequired"],
            skipped_fields=[],
        )

    monkeypatch.setattr(api_routes, "run_fill_pipeline", fake_pipeline)

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

    monkeypatch.setattr(api_routes, "run_fill_pipeline", failing_pipeline)

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


@pytest.mark.parametrize("endpoint", ["/fill", "/inspect", "/preview"])
def test_corrupt_pdf_returns_invalid_pdf(endpoint):
    response = client.post(
        endpoint,
        files={"pdf_file": ("input.pdf", b"%PDF-1.7\ngarbage", "application/pdf")},
        data={"user_data": "{}"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"]["code"] == "invalid_pdf"


@pytest.mark.parametrize("depth", [40, 100_000])
def test_deeply_nested_user_data_is_rejected(depth):
    response = client.post(
        "/preview",
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        data={"user_data": '{"a":' * depth + "1" + "}" * depth},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"]["code"] == "user_data_too_deep"


def test_fill_allow_partial_returns_pdf_with_missing_required(tmp_path):
    from .form_factory import FormBuilder

    pdf = FormBuilder().text("first_name").text("last_name", required=True).save(tmp_path / "f.pdf")
    files = {"pdf_file": ("f.pdf", pdf.read_bytes(), "application/pdf")}
    data = {"user_data": '{"first_name":"Jane"}'}

    blocked = client.post("/fill", files=files, data=data)
    assert blocked.status_code == 422

    partial = client.post("/fill", files=files, data={**data, "allow_partial": "true"})
    assert partial.status_code == 200
    assert partial.content.startswith(b"%PDF")
    assert partial.headers["X-PDF-Fields-Missing-Required"] == "last_name"
    assert partial.headers["X-PDF-Fields-Unfilled"] == "1"


def test_safe_header_value_strips_control_characters():
    assert api_routes._safe_header_value(["a\r\nSet-Cookie: x", "b\x00"]) == "aSet-Cookie: x,b"


@pytest.mark.parametrize(
    ("proxy_count", "forwarded", "expected"),
    [
        (1, "6.6.6.6, 203.0.113.9", "203.0.113.9"),  # spoofed left entry ignored
        (2, "6.6.6.6, 203.0.113.9, 10.0.0.2", "203.0.113.9"),
        (2, "203.0.113.9", "203.0.113.9"),  # fewer hops than proxies
    ],
)
def test_client_identifier_uses_trusted_hop(monkeypatch, proxy_count, forwarded, expected):
    from starlette.requests import Request

    from pdf_autofiller.api.security import client_identifier

    monkeypatch.setattr(config, "TRUST_PROXY_HEADERS", True)
    monkeypatch.setattr(config, "TRUSTED_PROXY_COUNT", proxy_count)
    request = Request(
        {
            "type": "http",
            "headers": [(b"x-forwarded-for", forwarded.encode())],
            "client": ("10.0.0.1", 1234),
        }
    )
    assert client_identifier(request) == expected


@pytest.mark.parametrize(
    "presented",
    [
        b"",
        b"wrong",
        b"secret-token ",
        b" secret-token",
        b"SECRET-TOKEN",
        b"secret-tokenX",
        b"secret-toke",
        "café".encode("latin-1"),
        "王".encode(),
        b"secret-token\xff",
        b"x" * 10_000,
    ],
)
@pytest.mark.parametrize("path", ["/fill", "/preview", "/inspect"])
def test_wrong_api_key_is_always_401_never_500(monkeypatch, path, presented):
    monkeypatch.setattr(config, "API_AUTH_ENABLED", True)
    monkeypatch.setattr(config, "API_AUTH_TOKEN", "secret-token")
    monkeypatch.setattr(config, "API_KEY_HEADER", "X-API-Key")

    response = client.post(
        path,
        headers={"X-API-Key": presented},
        files={"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")},
        data={"user_data": "{}"},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "unauthorized"


def test_non_ascii_configured_token_still_authenticates(monkeypatch):
    monkeypatch.setattr(config, "API_AUTH_ENABLED", True)
    monkeypatch.setattr(config, "API_AUTH_TOKEN", "clé-secrète")
    monkeypatch.setattr(config, "API_KEY_HEADER", "X-API-Key")

    files = {"pdf_file": ("input.pdf", _minimal_pdf_bytes(), "application/pdf")}
    ok = client.post("/inspect", headers={"X-API-Key": "clé-secrète".encode()}, files=files)
    assert ok.status_code == 200


@pytest.mark.parametrize("algorithm", ["RC4-128", "AES-256"])
@pytest.mark.parametrize("path", ["/fill", "/preview", "/inspect"])
def test_password_protected_pdf_returns_422_with_reason(tmp_path, path, algorithm):
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader("samples/sample_form.pdf"))
    writer.encrypt(user_password="open-sesame", owner_password="owner", algorithm=algorithm)
    locked = tmp_path / "locked.pdf"
    writer.write(locked)

    response = client.post(
        path,
        files={"pdf_file": ("locked.pdf", locked.read_bytes(), "application/pdf")},
        data={"user_data": '{"firstname": "Jane"}'},
    )
    assert response.status_code == 422
    error = response.json()["detail"]["error"]
    assert error["code"] == "invalid_pdf"
    assert "password-protected" in error["details"]["reason"]


def test_api_request_logs_never_contain_user_values(caplog):
    secret = "SSN-987-65-4321-王"
    user_data = json.dumps({"firstname": secret, "lastname": secret, "dob": secret, "zzz": secret})
    with caplog.at_level(logging.DEBUG):
        for path in ("/preview", "/fill"):
            client.post(
                path,
                files={
                    "pdf_file": ("input.pdf", Path("samples/sample_form.pdf").read_bytes(), "application/pdf")
                },
                data={"user_data": user_data, "allow_partial": "true"},
            )
    assert [r.getMessage() for r in caplog.records if secret in r.getMessage()] == []

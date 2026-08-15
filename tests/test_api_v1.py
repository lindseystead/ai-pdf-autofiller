"""Tests for the v1 API surface: inspect, bounds, templates, metrics, CORS."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pdf_autofiller import api_service, metrics
from pdf_autofiller.settings import Settings, set_settings

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "sample_form.pdf"
COMPLETE = {
    "firstname": "Jane",
    "lastname": "Doe",
    "dob": "1990-01-01",
    "email": "jane@example.com",
    "phone": "555-0100",
}

client = TestClient(api_service.app)


@pytest.fixture(autouse=True)
def _settings(tmp_path):
    set_settings(
        Settings(auth_enabled=False, rate_limit_per_minute=0, state_dir=tmp_path / "state")
    )
    api_service._reset_rate_limit_state()
    metrics.reset()
    yield
    api_service._reset_rate_limit_state()
    set_settings(None)


def _upload():
    return {"pdf_file": ("sample_form.pdf", SAMPLE.read_bytes(), "application/pdf")}


# --- inspect ---------------------------------------------------------------


def test_inspect_reports_fields_without_producing_a_document():
    response = client.post(
        "/v1/inspect", files=_upload(), data={"user_data": json.dumps({"firstname": "Jane"})}
    )
    assert response.status_code == 200
    payload = response.json()

    assert len(payload["fields"]) == 5
    assert payload["fingerprint"]
    assert "txtFirstName" in payload["would_write"]
    # The response is a report, not a PDF.
    assert response.headers["content-type"].startswith("application/json")


def test_inspect_without_user_data_still_lists_fields():
    response = client.post("/v1/inspect", files=_upload())
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["fields"]) == 5
    assert payload["mapping"] is None


def test_inspect_surfaces_required_fields_the_data_misses():
    response = client.post(
        "/v1/inspect", files=_upload(), data={"user_data": json.dumps({"firstname": "Jane"})}
    )
    payload = response.json()
    assert "txtLastName" in payload["mapping"]["missing_required"]
    assert "txtLastName" in payload["would_skip"]


# --- fill ------------------------------------------------------------------


def test_fill_v1_returns_pdf_with_report_headers():
    response = client.post("/v1/fill", files=_upload(), data={"user_data": json.dumps(COMPLETE)})
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
    assert response.headers["X-PDF-Fields-Written"] == "5"
    assert response.headers["X-PDF-Flattened"] == "false"


def test_fill_json_response_carries_the_full_report():
    """The header report is ASCII-stripped and capped; JSON mode is the real one."""
    response = client.post(
        "/v1/fill",
        files=_upload(),
        data={"user_data": json.dumps(COMPLETE), "response_format": "json"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["fields_total"] == 5
    assert len(payload["report"]["written_fields"]) == 5
    assert payload["mapping"]["decisions"]
    assert payload["pdf_base64"].startswith("JVBER")  # base64 of "%PDF"


def test_fill_flatten_flag_reports_flattening():
    response = client.post(
        "/v1/fill",
        files=_upload(),
        data={"user_data": json.dumps(COMPLETE), "flatten": "true"},
    )
    assert response.status_code == 200
    assert response.headers["X-PDF-Flattened"] == "true"


def test_unversioned_alias_still_works():
    """Existing callers must not break when routes gain a /v1 prefix."""
    response = client.post("/fill", files=_upload(), data={"user_data": json.dumps(COMPLETE)})
    assert response.status_code == 200


# --- user_data bounds ------------------------------------------------------


def test_oversized_user_data_is_rejected():
    """The upload was bounded while the JSON beside it was not."""
    set_settings(Settings(auth_enabled=False, rate_limit_per_minute=0, max_user_data_bytes=100))
    response = client.post(
        "/v1/fill",
        files=_upload(),
        data={"user_data": json.dumps({"k": "x" * 5000})},
    )
    assert response.status_code == 413
    assert response.json()["detail"]["error"]["code"] == "user_data_too_large"


def test_deeply_nested_user_data_is_rejected():
    set_settings(Settings(auth_enabled=False, rate_limit_per_minute=0, max_user_data_depth=3))
    nested: object = "leaf"
    for _ in range(25):
        nested = {"k": nested}
    response = client.post(
        "/v1/fill", files=_upload(), data={"user_data": json.dumps(nested)}
    )
    assert response.status_code == 413
    assert "nesting depth" in response.json()["detail"]["error"]["details"]["reason"]


def test_too_many_keys_is_rejected():
    set_settings(Settings(auth_enabled=False, rate_limit_per_minute=0, max_user_data_keys=5))
    response = client.post(
        "/v1/fill",
        files=_upload(),
        data={"user_data": json.dumps({f"k{i}": i for i in range(50)})},
    )
    assert response.status_code == 413


# --- typed errors ----------------------------------------------------------


def test_encrypted_upload_returns_named_error(tmp_path):
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    writer.append(PdfReader(str(SAMPLE)))
    writer.encrypt("pw")
    target = tmp_path / "enc.pdf"
    with target.open("wb") as handle:
        writer.write(handle)

    response = client.post(
        "/v1/fill",
        files={"pdf_file": ("enc.pdf", target.read_bytes(), "application/pdf")},
        data={"user_data": json.dumps(COMPLETE)},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"]["code"] == "pdf_encrypted"


def test_fill_with_no_data_source_is_rejected():
    response = client.post("/v1/fill", files=_upload())
    assert response.status_code == 422
    assert response.json()["detail"]["error"]["code"] == "no_fill_data"


# --- templates and profiles over HTTP --------------------------------------


def test_template_and_profile_endpoints_round_trip():
    assert client.put("/v1/profiles/me", json={"name": "me", "data": COMPLETE}).status_code == 200
    assert client.put(
        "/v1/templates/sample",
        json={"name": "sample", "fingerprint": "abc", "flatten": True},
    ).status_code == 200

    listed = client.get("/v1/profiles").json()["profiles"]
    assert listed[0]["name"] == "me"
    # The index must not hand back personal data wholesale.
    assert "data" not in listed[0]
    assert "firstname" in listed[0]["keys"]

    response = client.post(
        "/v1/fill", files=_upload(), data={"profile": "me", "template": "sample"}
    )
    assert response.status_code == 200
    assert response.headers["X-PDF-Flattened"] == "true"

    assert client.delete("/v1/profiles/me").status_code == 200
    assert client.get("/v1/profiles/me").status_code == 404


def test_unknown_template_returns_404():
    response = client.post("/v1/fill", files=_upload(), data={"template": "nope"})
    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "template_not_found"


# --- metrics ---------------------------------------------------------------


def test_metrics_endpoint_exposes_fill_counters():
    client.post("/v1/fill", files=_upload(), data={"user_data": json.dumps(COMPLETE)})
    body = client.get("/metrics").text
    assert 'pdf_autofiller_fills_total{outcome="success"} 1' in body
    assert "pdf_autofiller_fields_written_total" in body
    assert "pdf_autofiller_request_duration_seconds_count" in body


def test_metrics_can_be_disabled():
    set_settings(Settings(auth_enabled=False, metrics_enabled=False))
    assert client.get("/metrics").status_code == 404


# --- auth ------------------------------------------------------------------


def test_multiple_api_keys_are_accepted_and_attributed(caplog):
    import logging

    set_settings(
        Settings(
            auth_enabled=True,
            rate_limit_per_minute=0,
            api_keys={"ops": "key-ops", "ci": "key-ci"},
        )
    )
    with caplog.at_level(logging.INFO, logger="pdf_autofiller.api_service"):
        response = client.post(
            "/v1/fill",
            files=_upload(),
            data={"user_data": json.dumps(COMPLETE)},
            headers={"X-API-Key": "key-ci"},
        )
    assert response.status_code == 200
    assert "key=ci" in caplog.text

    assert client.post(
        "/v1/fill",
        files=_upload(),
        data={"user_data": json.dumps(COMPLETE)},
        headers={"X-API-Key": "wrong"},
    ).status_code == 401


# --- CORS ------------------------------------------------------------------


def test_cors_is_off_by_default():
    """A wildcard default would let any page drive an authenticated deployment."""
    response = client.get("/v1/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in {k.lower() for k in response.headers}

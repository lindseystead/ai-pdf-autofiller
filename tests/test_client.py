"""Tests for the HTTP client SDK and local fill helper."""

import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from pdf_autofiller import fill
from pdf_autofiller.client import PDFAutofillerClient, PDFAutofillError

SAMPLE_PDF = Path("samples/sample_form.pdf")


def _pdf_response(content: bytes = b"%PDF-1.4 filled") -> Mock:
    response = Mock(spec=httpx.Response)
    response.status_code = 200
    response.content = content
    response.headers = httpx.Headers({"X-PDF-Fields-Written": "2"})
    return response


def test_client_health():
    response = Mock(spec=httpx.Response)
    response.raise_for_status = Mock()
    response.json.return_value = {"status": "ok", "service": "pdf-autofiller"}

    http = Mock(spec=httpx.Client)
    http.get.return_value = response

    sdk = PDFAutofillerClient("http://testserver", http_client=http)
    payload = sdk.health()
    assert payload["status"] == "ok"
    http.get.assert_called_once()


def test_client_fill_bytes():
    http = Mock(spec=httpx.Client)
    http.post.return_value = _pdf_response()

    sdk = PDFAutofillerClient("http://testserver", http_client=http)
    filled, headers = sdk.fill(b"%PDF-1.4", {"firstname": "Jane"}, filename="demo.pdf")
    assert filled.startswith(b"%PDF-")
    assert headers["x-pdf-fields-written"] == "2"
    http.post.assert_called_once()
    call_kwargs = http.post.call_args.kwargs
    assert call_kwargs["data"]["flatten"] == "false"
    assert call_kwargs["data"]["strict"] == "true"
    assert call_kwargs["headers"]["Accept"] == "application/pdf"


def test_client_inspect_and_preview():
    inspect_response = Mock(spec=httpx.Response)
    inspect_response.status_code = 200
    inspect_response.json.return_value = {"pages": 1, "field_count": 2, "fields": []}

    preview_response = Mock(spec=httpx.Response)
    preview_response.status_code = 200
    preview_response.json.return_value = {
        "pages": 1,
        "field_count": 2,
        "decisions": [],
        "missing_required": [],
        "unmapped_user_keys": [],
    }

    http = Mock(spec=httpx.Client)
    http.post.side_effect = [inspect_response, preview_response]

    sdk = PDFAutofillerClient("http://testserver", http_client=http)
    inventory = sdk.inspect(b"%PDF-1.4", filename="demo.pdf")
    assert inventory["field_count"] == 2
    mapping = sdk.preview(b"%PDF-1.4", {"firstname": "Jane"}, filename="demo.pdf")
    assert mapping["missing_required"] == []


def test_client_fill_json_accept():
    response = Mock(spec=httpx.Response)
    response.status_code = 200
    response.headers = httpx.Headers({"content-type": "application/json"})
    response.json.return_value = {
        "pages": 1,
        "field_count": 1,
        "written_fields": ["txtFirstName"],
        "skipped_review_fields": [],
        "skipped_empty_fields": [],
        "missing_required": [],
        "unmapped_user_keys": [],
        "decisions": [],
        "pdf_base64": "JVBERi0=",
    }
    http = Mock(spec=httpx.Client)
    http.post.return_value = response

    sdk = PDFAutofillerClient("http://testserver", http_client=http)
    payload, _headers = sdk.fill(
        b"%PDF-1.4",
        {"firstname": "Jane"},
        filename="demo.pdf",
        accept="application/json",
    )
    assert isinstance(payload, dict)
    assert payload["written_fields"] == ["txtFirstName"]


def test_client_fill_sends_flatten_flag():
    http = Mock(spec=httpx.Client)
    http.post.return_value = _pdf_response()

    sdk = PDFAutofillerClient("http://testserver", http_client=http)
    sdk.fill(b"%PDF-1.4", {"firstname": "Jane"}, flatten=True, filename="demo.pdf")
    call_kwargs = http.post.call_args.kwargs
    assert call_kwargs["data"]["flatten"] == "true"


def test_client_fill_to_file(tmp_path):
    http = Mock(spec=httpx.Client)
    http.post.return_value = _pdf_response(b"%PDF-filled")

    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "filled.pdf"
    input_path.write_bytes(b"%PDF-input")

    sdk = PDFAutofillerClient("http://testserver", http_client=http)
    headers = sdk.fill_to_file(str(input_path), {"firstname": "Jane"}, str(output_path))
    assert output_path.read_bytes() == b"%PDF-filled"
    assert headers["x-pdf-fields-written"] == "2"


def test_client_raises_structured_error():
    response = Mock(spec=httpx.Response)
    response.status_code = 415
    response.json.return_value = {
        "detail": {
            "error": {
                "code": "invalid_pdf_signature",
                "message": "Uploaded file is not a valid PDF",
            }
        }
    }

    http = Mock(spec=httpx.Client)
    http.post.return_value = response

    sdk = PDFAutofillerClient("http://testserver", http_client=http)
    with pytest.raises(PDFAutofillError) as exc:
        sdk.fill(b"not-a-pdf", {"firstname": "Jane"})
    assert exc.value.code == "invalid_pdf_signature"


def test_client_raises_on_non_json_error():
    response = Mock(spec=httpx.Response)
    response.status_code = 500
    response.text = "boom"
    response.json.side_effect = json.JSONDecodeError("not json", "doc", 0)

    http = Mock(spec=httpx.Client)
    http.post.return_value = response

    sdk = PDFAutofillerClient("http://testserver", http_client=http)
    with pytest.raises(PDFAutofillError) as exc:
        sdk.fill(b"%PDF-1.4", {"firstname": "Jane"})
    assert exc.value.code == "invalid_response"


@pytest.mark.skipif(not SAMPLE_PDF.exists(), reason="sample PDF not present")
def test_fill_local_convenience_helper(tmp_path):
    """Local fill() writes a PDF without contacting an HTTP server."""
    output_path = tmp_path / "filled.pdf"
    report = fill(
        SAMPLE_PDF,
        {"firstname": "Jane", "lastname": "Doe", "dob": "1990-01-01"},
        output_path,
    )
    assert output_path.exists()
    assert output_path.read_bytes()[:5] == b"%PDF-"
    assert "txtFirstName" in report.written_fields

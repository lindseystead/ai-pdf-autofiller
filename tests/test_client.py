"""Tests for the HTTP client SDK."""

import json
from unittest.mock import Mock

import httpx
import pytest

from pdf_autofiller.client import PDFAutofillError, PDFAutofillerClient, fill


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


def test_fill_convenience_helper(tmp_path, monkeypatch):
    output_path = tmp_path / "filled.pdf"
    captured: dict[str, object] = {}

    class FakeClient:
        def fill_to_file(self, pdf, user_data, output, **kwargs):
            captured["pdf"] = pdf
            captured["user_data"] = user_data
            Path = __import__("pathlib").Path
            Path(output).write_bytes(b"%PDF-filled")
            return {"X-PDF-Fields-Written": "1"}

    monkeypatch.setattr("pdf_autofiller.client.PDFAutofillerClient", lambda **kwargs: FakeClient())
    headers = fill("form.pdf", {"firstname": "Jane"}, str(output_path), api_key="secret")
    assert output_path.exists()
    assert captured["user_data"] == {"firstname": "Jane"}
    assert headers["X-PDF-Fields-Written"] == "1"

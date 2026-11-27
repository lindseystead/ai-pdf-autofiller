"""Tests for playground routes."""

from fastapi.testclient import TestClient

from pdf_autofiller import api_service

client = TestClient(api_service.app)


def test_root_redirects_to_playground():
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (307, 308)
    assert response.headers["location"] == "/playground"


def test_playground_page_renders_html():
    response = client.get("/playground")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Fill AcroForm PDFs from JSON" in response.text
    assert 'id="fillBtn"' in response.text
    assert 'id="loadSamplePdfBtn"' in response.text
    assert 'id="inspectBtn"' in response.text
    assert 'id="templateBtn"' in response.text
    assert 'id="previewBtn"' in response.text
    assert 'id="flatten"' in response.text
    assert 'id="needAppearances"' in response.text
    assert "disable AI key fallback" in response.text
    assert 'type="password"' in response.text
    assert 'role="status" aria-live="polite"' in response.text
    assert 'for="userData"' in response.text
    assert 'id="pdfPreview"' in response.text
    assert 'id="aiConsent"' in response.text
    assert 'id="fieldMapping"' in response.text
    assert 'id="saveMappingBtn"' in response.text
    assert 'id="mappingEditor"' in response.text
    assert 'id="refreshMappingBtn"' in response.text
    assert '<link rel="stylesheet" href="/assets/playground.css"' in response.text
    assert '<script src="/assets/playground.js" defer>' in response.text
    assert "<style" not in response.text
    assert "style=" not in response.text
    assert "<script>" not in response.text
    assert '<button id="drop"' in response.text
    assert 'role="button"' not in response.text
    assert '<a id="download"' in response.text


def test_playground_assets_are_served_and_csp_disallows_inline_code():
    css = client.get("/assets/playground.css")
    javascript = client.get("/assets/playground.js")
    page = client.get("/playground")

    assert css.status_code == javascript.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    assert javascript.headers["content-type"].startswith("text/javascript")
    assert "crypto.subtle.digest('SHA-256'" in javascript.text
    assert "localStorage.setItem(selectedPdfKey" in javascript.text
    assert "form.append('field_mapping'" in javascript.text
    assert "function renderMappingEditor()" in javascript.text
    assert "document.createElement('select')" in javascript.text
    assert "X-PDF-Fields-Missing-Required" in javascript.text
    assert "URL.revokeObjectURL" in javascript.text
    csp = page.headers["content-security-policy"]
    assert "script-src 'self'" in csp
    assert "style-src 'self'" in csp
    assert "unsafe-inline" not in csp


def test_playground_default_json_is_valid():
    """Default textarea content must parse as a JSON object without edits."""
    import json
    import re

    response = client.get("/playground")
    match = re.search(
        r'<textarea id="userData"[^>]*>(.*?)</textarea>',
        response.text,
        flags=re.DOTALL,
    )
    assert match is not None
    payload = json.loads(match.group(1))
    assert isinstance(payload, dict)
    assert "firstname" in payload


def test_playground_has_no_html_injection_sinks():
    # Status and report text echo server errors that can contain field names
    # taken from the uploaded PDF, so the page must only ever set textContent.
    javascript = client.get("/assets/playground.js").text
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in javascript


def test_playground_download_requires_acknowledgement_for_partial_fill():
    html = client.get("/playground").text
    javascript = client.get("/assets/playground.js").text
    assert 'id="ackIncomplete"' in html
    assert "download.hidden = true" in javascript
    assert "Incomplete PDF — required fields are missing" in javascript
    assert "ackIncomplete.checked && downloadUrl" in javascript

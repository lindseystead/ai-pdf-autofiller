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
    assert "Fill any PDF from JSON" in response.text
    assert 'id="fillBtn"' in response.text
    assert 'id="loadSamplePdfBtn"' in response.text
    assert 'id="inspectBtn"' in response.text
    assert 'id="previewBtn"' in response.text
    assert 'id="flatten"' in response.text
    assert "disable AI fallback" in response.text
    assert 'type="password"' in response.text


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

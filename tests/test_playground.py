"""Tests for playground routes."""

import json
import re

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
    assert "PDF Autofiller" in response.text
    assert 'id="fillBtn"' in response.text


def test_playground_default_user_data_is_valid_json():
    response = client.get("/playground")
    match = re.search(
        r'<textarea id="userData"[^>]*>(.*?)</textarea>',
        response.text,
        re.DOTALL,
    )
    assert match is not None
    payload = json.loads(match.group(1))
    assert isinstance(payload, dict)
    assert payload["firstname"] == "Jane"
    assert payload["lastname"] == "Doe"

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

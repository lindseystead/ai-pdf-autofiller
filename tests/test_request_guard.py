"""The upload routes must reject bad requests before reading the request body.

These tests drive the ASGI app directly with a ``receive`` that counts how many
body chunks the app pulls: TestClient buffers the whole body first, so it cannot
show whether a rejection happened before or after the upload was read.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from pdf_autofiller import api_service
from pdf_autofiller.api import config
from pdf_autofiller.api.security import reset_rate_limit_state

CHUNK = b"x" * 65_536
# Opens a valid multipart file part, so the parser keeps consuming the "x" chunks.
PART_HEADER = (
    b"--x\r\n"
    b'Content-Disposition: form-data; name="pdf_file"; filename="a.pdf"\r\n'
    b"Content-Type: application/pdf\r\n\r\n"
)
PROTECTED = ["/fill", "/preview", "/inspect"]


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.setattr(config, "API_AUTH_ENABLED", False)
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 1_000_000)
    reset_rate_limit_state()
    yield
    reset_rate_limit_state()


def _post(path: str, headers: dict[str, str], chunks: int) -> tuple[int, dict[str, Any], int]:
    """POST ``chunks`` x 64 KiB to ``path``; return (status, json body, chunks pulled)."""
    pulled = 0

    async def receive() -> dict[str, Any]:
        nonlocal pulled
        if pulled < chunks:
            pulled += 1
            body = PART_HEADER + CHUNK if pulled == 1 else CHUNK
            return {"type": "http.request", "body": body, "more_body": pulled < chunks}
        return {"type": "http.disconnect"}

    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": ("203.0.113.9", 50000),
        "server": ("testserver", 80),
    }
    asyncio.run(api_service.app(scope, receive, send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, json.loads(body or b"{}"), pulled


MULTIPART = {"content-type": "multipart/form-data; boundary=x"}


@pytest.mark.parametrize("path", PROTECTED)
@pytest.mark.parametrize("key", [None, "wrong"])
def test_unauthenticated_upload_is_rejected_without_reading_the_body(monkeypatch, path, key):
    monkeypatch.setattr(config, "API_AUTH_ENABLED", True)
    monkeypatch.setattr(config, "API_AUTH_TOKEN", "secret-token")
    headers = {**MULTIPART, "content-length": str(10 * 1024**3)}
    if key is not None:
        headers["x-api-key"] = key

    status, body, pulled = _post(path, headers, chunks=1_000)
    assert status == 401
    assert body["detail"]["error"]["code"] == "unauthorized"
    assert pulled == 0


@pytest.mark.parametrize("path", PROTECTED)
def test_declared_oversize_body_is_rejected_without_reading_it(path):
    headers = {**MULTIPART, "content-length": str(10 * 1024**3)}
    status, body, pulled = _post(path, headers, chunks=1_000)
    assert status == 413
    assert body["detail"]["error"]["code"] == "payload_too_large"
    assert pulled == 0


@pytest.mark.parametrize("path", PROTECTED)
def test_undeclared_oversize_body_stops_once_past_the_limit(path):
    limit = config.MAX_UPLOAD_BYTES + config.FORM_OVERHEAD_BYTES
    status, body, pulled = _post(path, MULTIPART, chunks=1_000)  # ~64 MiB, no content-length
    assert status == 413
    assert body["detail"]["error"]["code"] == "payload_too_large"
    assert pulled == limit // len(CHUNK) + 1


@pytest.mark.parametrize("path", PROTECTED)
def test_lying_content_length_is_still_capped(path):
    headers = {**MULTIPART, "content-length": "10"}
    status, _, pulled = _post(path, headers, chunks=1_000)
    assert status == 413
    assert pulled < 1_000


def test_rate_limited_upload_is_rejected_without_reading_the_body(monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MINUTE", 1)
    headers = {**MULTIPART, "content-length": str(len(CHUNK))}
    _post("/inspect", headers, chunks=1)
    status, body, pulled = _post("/inspect", headers, chunks=1)
    assert status == 429
    assert pulled == 0


def test_unprotected_routes_are_not_guarded(monkeypatch):
    monkeypatch.setattr(config, "API_AUTH_ENABLED", True)
    monkeypatch.setattr(config, "API_AUTH_TOKEN", "secret-token")
    status, _, _ = _post("/not-a-route", {"content-length": str(10 * 1024**3)}, chunks=0)
    assert status in (404, 405)

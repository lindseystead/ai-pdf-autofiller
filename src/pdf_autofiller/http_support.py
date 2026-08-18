"""
HTTP plumbing shared by the API routes.

Everything here is machinery the endpoints need but that is not itself an
endpoint: the error contract, authentication, rate limiting, request-payload
bounds, and staging an upload to disk. Keeping it out of
:mod:`pdf_autofiller.api_service` leaves that module as a readable list of what
the service actually exposes.

This service accepts untrusted uploads from the public, so the guards here are
the security boundary:

- Authentication fails closed: enabled by default, and a missing token is a
  server configuration error rather than an open door.
- Uploads are size-, signature-, and page-count-checked, and the JSON beside
  them is bounded in bytes, key count, and nesting depth.
- PDF parsing runs in a killable child process under a wall-clock timeout, so a
  hostile document cannot permanently consume a worker.

See docs/OPERATIONS.md for rationale and configuration.
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Optional

from fastapi import HTTPException, Request, UploadFile

from .errors import PdfAutofillerError, UserDataTooLargeError
from .execution import run_isolated
from .models import FillReport
from .settings import Settings, get_settings

logger = logging.getLogger(__name__)

UPLOAD_CHUNK_BYTES = 64 * 1024

def _api_error_payload(
    *, code: str, message: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build a consistent API error payload."""
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        payload["error"]["details"] = details
    return payload


def _api_error(
    *, status_code: int, code: str, message: str, details: dict[str, Any] | None = None
) -> HTTPException:
    # Centralize API error formatting so clients can rely on one contract
    # regardless of which endpoint raised the error.
    """Build a consistent API exception payload."""
    return HTTPException(
        status_code=status_code,
        detail=_api_error_payload(code=code, message=message, details=details),
    )


def _domain_error(exc: PdfAutofillerError) -> HTTPException:
    """Translate a typed pipeline error into its HTTP response.

    Every domain error carries its own code and status, so adding an error to
    :mod:`pdf_autofiller.errors` surfaces it here with no change at this layer.
    """
    return _api_error(
        status_code=exc.status_code,
        code=exc.code,
        message=str(exc),
        details=exc.details() or None,
    )


def _safe_header_value(field_names: list[str]) -> str:
    """Render field names as an ASCII-safe, comma-separated HTTP header value."""
    joined = ",".join(field_names)
    return joined.encode("ascii", "ignore").decode("ascii")


def _fill_report_headers(report: FillReport) -> dict[str, str]:
    """Expose fill outcome via response headers.

    Lets clients detect non-required fields that were dropped (for example,
    flagged for review) instead of receiving a silently incomplete PDF. Callers
    that want the full structured report should request ``application/json``.
    """
    return {
        "X-PDF-Fields-Written": str(len(report.written_fields)),
        "X-PDF-Fields-Skipped-Review": _safe_header_value(report.skipped_review_fields),
        "X-PDF-Fields-Skipped-Empty": _safe_header_value(report.skipped_empty_fields),
        "X-PDF-Fields-Skipped-Invalid": _safe_header_value(report.skipped_invalid_fields),
        "X-PDF-Flattened": str(report.flattened).lower(),
    }


# Per-client request timestamps for the sliding-window rate limiter. This is an
# in-process guard suitable for a single worker; multi-worker deployments should
# add a shared limiter (e.g. at the ingress/proxy layer).
_rate_limit_state: dict[str, deque[float]] = defaultdict(deque)


def reset_rate_limit_state() -> None:
    """Clear rate-limiter state.

    Public because it is a testing seam used from outside this module; the
    limiter is process-global, so tests must be able to reset it between cases.
    """
    _rate_limit_state.clear()


def _client_identifier(request: Request) -> str:
    """Resolve the client key used for rate limiting."""
    if get_settings().trust_proxy_headers:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _purge_stale_rate_limit_clients(now: float) -> None:
    """Drop idle client buckets to bound memory use under rotating clients."""
    if len(_rate_limit_state) <= 1000:
        return
    stale_clients = [
        client_id
        for client_id, window in _rate_limit_state.items()
        if not window or now - window[-1] >= 60.0
    ]
    for client_id in stale_clients:
        _rate_limit_state.pop(client_id, None)


async def _read_bounded_upload(upload: UploadFile, max_bytes: int) -> bytes:
    """Read an upload in chunks and reject payloads before they fully buffer."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise _api_error(
                status_code=413,
                code="payload_too_large",
                message="PDF exceeds MAX_UPLOAD_BYTES limit",
                details={"max_upload_bytes": max_bytes},
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _measure_depth(value: Any, depth: int = 0) -> int:
    """Return the maximum nesting depth of a decoded JSON value."""
    if isinstance(value, dict):
        return max((_measure_depth(v, depth + 1) for v in value.values()), default=depth)
    if isinstance(value, list):
        return max((_measure_depth(v, depth + 1) for v in value), default=depth)
    return depth


def _count_keys(value: Any) -> int:
    """Return the total number of keys across a nested JSON value."""
    if isinstance(value, dict):
        return len(value) + sum(_count_keys(v) for v in value.values())
    if isinstance(value, list):
        return sum(_count_keys(v) for v in value)
    return 0


def _parse_user_data(raw: str, settings: Settings) -> dict[str, Any]:
    """Decode and bound the JSON payload accompanying an upload.

    The upload path was carefully bounded while this field beside it was an
    unbounded string handed straight to ``json.loads``. Size is checked before
    decoding; shape is checked after, because a small string can decode into a
    deeply nested structure that is expensive to walk.
    """
    encoded_length = len(raw.encode("utf-8"))
    if encoded_length > settings.max_user_data_bytes:
        raise UserDataTooLargeError(
            f"payload is {encoded_length} bytes", settings.max_user_data_bytes
        )

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _api_error(
            status_code=422,
            code="invalid_user_data_json",
            message="Invalid user_data JSON",
            details={"reason": str(exc)},
        ) from exc

    if not isinstance(parsed, dict):
        raise _api_error(
            status_code=422,
            code="invalid_user_data_type",
            message="user_data must be a JSON object",
        )

    depth = _measure_depth(parsed)
    if depth > settings.max_user_data_depth:
        raise UserDataTooLargeError(f"nesting depth {depth}", settings.max_user_data_depth)

    key_count = _count_keys(parsed)
    if key_count > settings.max_user_data_keys:
        raise UserDataTooLargeError(f"{key_count} keys", settings.max_user_data_keys)

    return parsed


def _parse_optional_json_object(raw: Optional[str], field: str) -> dict[str, Any]:
    """Decode an optional JSON-object form field."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _api_error(
            status_code=422,
            code="invalid_json",
            message=f"Invalid {field} JSON",
            details={"reason": str(exc)},
        ) from exc
    if not isinstance(parsed, dict):
        raise _api_error(
            status_code=422,
            code="invalid_json_type",
            message=f"{field} must be a JSON object",
        )
    return parsed


def _enforce_rate_limit(request: Request) -> None:
    """Apply a per-client sliding-window rate limit, if enabled."""
    limit = get_settings().rate_limit_per_minute
    if limit <= 0:
        return

    client_host = _client_identifier(request)
    now = time.monotonic()
    _purge_stale_rate_limit_clients(now)
    window = _rate_limit_state[client_host]
    while window and now - window[0] >= 60.0:
        window.popleft()

    if len(window) >= limit:
        raise _api_error(
            status_code=429,
            code="rate_limited",
            message="Too many requests",
            details={"limit_per_minute": limit},
        )

    window.append(now)


def _require_api_key(request: Request) -> None:
    """Validate API key auth when enabled."""
    settings = get_settings()
    if not settings.auth_enabled:
        return

    if not settings.auth_configured():
        logger.error("API_AUTH_ENABLED is true but API_AUTH_TOKEN is not configured")
        raise _api_error(
            status_code=500,
            code="server_auth_config_error",
            message="Server authentication configuration error",
        )

    if not settings.token_matches(request.headers.get(settings.api_key_header)):
        raise _api_error(status_code=401, code="unauthorized", message="Unauthorized")


def _guard(request: Request) -> None:
    """Rate-limit then authenticate a mutating request."""
    _enforce_rate_limit(request)
    _require_api_key(request)


async def _run_pipeline(func, *args, **kwargs) -> Any:
    """Run a pipeline entry point in a killable worker, off the event loop."""
    settings = get_settings()
    try:
        return await asyncio.to_thread(
            run_isolated,
            func,
            *args,
            timeout=settings.pdf_read_timeout_seconds,
            **kwargs,
        )
    except PdfAutofillerError as exc:
        raise _domain_error(exc) from exc


async def _stage_upload(pdf_file: UploadFile, settings: Settings):
    """Validate and write an upload to a temp directory, returning both."""

    if pdf_file.content_type not in ("application/pdf", "application/octet-stream"):
        raise _api_error(
            status_code=415, code="unsupported_media_type", message="Expected a PDF upload"
        )

    temp_dir = tempfile.TemporaryDirectory(prefix="pdf-autofiller-")
    try:
        content = await _read_bounded_upload(pdf_file, settings.max_upload_bytes)
        if not content.startswith(b"%PDF-"):
            raise _api_error(
                status_code=415,
                code="invalid_pdf_signature",
                message="Uploaded file is not a valid PDF",
            )
        input_path = Path(temp_dir.name) / "input.pdf"
        input_path.write_bytes(content)
        return temp_dir, input_path
    except Exception:
        temp_dir.cleanup()
        raise



def request_validation_payload(errors: Any) -> dict[str, Any]:
    """Payload for FastAPI's own request-validation failures.

    Routed through the same builder as every other error so clients can rely on
    one response shape regardless of which layer rejected the request.
    """
    return _api_error_payload(
        code="request_validation_error",
        message="Request validation failed",
        details={"errors": errors},
    )

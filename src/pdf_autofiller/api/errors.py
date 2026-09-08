"""Consistent API error payloads and OpenAPI error catalog."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field


class ApiErrorBody(BaseModel):
    """Single error object inside the API envelope."""

    code: str = Field(description="Stable machine-readable error code")
    message: str = Field(description="Human-readable summary")
    details: dict[str, Any] | None = Field(
        default=None,
        description="Optional structured context (never raw user PII values)",
    )


class ApiErrorDetail(BaseModel):
    """FastAPI ``detail`` wrapper used by HTTPException responses."""

    error: ApiErrorBody


class ApiErrorEnvelope(BaseModel):
    """Top-level JSON body returned for API errors."""

    detail: ApiErrorDetail


# Canonical catalog: code → (HTTP status, default message).
# Keep in sync with raises in api.security / api.uploads / api.routes / api.app.
ERROR_CATALOG: dict[str, tuple[int, str]] = {
    "request_validation_error": (422, "Request validation failed"),
    "invalid_user_data_json": (422, "Invalid user_data JSON"),
    "invalid_user_data_type": (422, "user_data must be a JSON object"),
    "unsupported_media_type": (415, "Expected a PDF upload"),
    "invalid_pdf_signature": (415, "Uploaded file is not a valid PDF"),
    "payload_too_large": (413, "PDF exceeds MAX_UPLOAD_BYTES limit"),
    "pdf_too_many_pages": (413, "PDF exceeds the maximum allowed page count"),
    "pdf_processing_timeout": (503, "PDF processing exceeded the time limit"),
    "rate_limited": (429, "Too many requests"),
    "unauthorized": (401, "Unauthorized"),
    "server_auth_config_error": (500, "Server authentication configuration error"),
    "required_fields_unresolved": (422, "Required fields unresolved"),
    "pdf_fill_failed": (500, "PDF fill failed"),
    "pdf_preview_failed": (500, "PDF preview failed"),
    "pdf_inspect_failed": (500, "PDF inspect failed"),
    "sample_not_found": (404, "Sample PDF is not bundled in this deployment"),
}


def api_error_payload(
    *,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a consistent API error payload."""
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        payload["error"]["details"] = details
    return payload


def api_error(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> HTTPException:
    """Build a consistent API exception."""
    return HTTPException(
        status_code=status_code,
        detail=api_error_payload(code=code, message=message, details=details),
        headers=headers,
    )


def openapi_error_responses(*codes: str) -> dict[int | str, dict[str, Any]]:
    """Build OpenAPI ``responses`` entries for the given error codes."""
    by_status: dict[int, list[str]] = {}
    for code in codes:
        if code not in ERROR_CATALOG:
            raise KeyError(f"Unknown API error code: {code}")
        status, _message = ERROR_CATALOG[code]
        by_status.setdefault(status, []).append(code)

    responses: dict[int | str, dict[str, Any]] = {}
    for status, code_list in sorted(by_status.items()):
        descriptions = []
        for code in code_list:
            _status, message = ERROR_CATALOG[code]
            descriptions.append(f"`{code}` — {message}")
        responses[status] = {
            "description": "; ".join(descriptions),
            "model": ApiErrorEnvelope,
        }
    return responses


MUTATING_ERROR_CODES = (
    "unauthorized",
    "server_auth_config_error",
    "rate_limited",
    "unsupported_media_type",
    "invalid_pdf_signature",
    "payload_too_large",
    "pdf_too_many_pages",
    "pdf_processing_timeout",
    "request_validation_error",
)

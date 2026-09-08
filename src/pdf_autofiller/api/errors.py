"""Consistent API error payloads."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException


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

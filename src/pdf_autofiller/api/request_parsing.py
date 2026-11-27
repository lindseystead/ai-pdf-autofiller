"""Validated parsing for multipart JSON fields used by API routes."""

from __future__ import annotations

import json
from typing import Any

from pdf_autofiller.user_data import UserDataTooDeepError, validate_user_data_depth

from .errors import ERROR_CATALOG, api_error


def parse_user_data(user_data: str) -> dict[str, Any]:
    """Parse and depth-check the user-data object without recursing indefinitely."""
    try:
        parsed = json.loads(user_data)
    except RecursionError as exc:
        raise api_error(
            status_code=422,
            code="user_data_too_deep",
            message="user_data is nested too deeply",
        ) from exc
    except json.JSONDecodeError as exc:
        raise api_error(
            status_code=422,
            code="invalid_user_data_json",
            message="Invalid user_data JSON",
            details={"reason": str(exc)},
        ) from exc
    if not isinstance(parsed, dict):
        raise api_error(
            status_code=422,
            code="invalid_user_data_type",
            message="user_data must be a JSON object",
        )
    try:
        validate_user_data_depth(parsed)
    except UserDataTooDeepError as exc:
        raise api_error(
            status_code=422,
            code="user_data_too_deep",
            message="user_data is nested too deeply",
            details={"max_depth": exc.max_depth},
        ) from exc
    return parsed


def parse_field_mapping(field_mapping: str) -> dict[str, str]:
    """Parse an optional exact ``PDF field -> user data key`` mapping."""
    try:
        parsed = json.loads(field_mapping or "{}")
    except (RecursionError, json.JSONDecodeError) as exc:
        raise api_error(
            status_code=422,
            code="invalid_field_mapping",
            message="field_mapping must be valid JSON",
        ) from exc
    if not isinstance(parsed, dict) or any(
        not isinstance(field, str) or not isinstance(key, str) or not field or not key
        for field, key in parsed.items()
    ):
        raise api_error(
            status_code=422,
            code="invalid_field_mapping",
            message=ERROR_CATALOG["invalid_field_mapping"][1],
        )
    return parsed

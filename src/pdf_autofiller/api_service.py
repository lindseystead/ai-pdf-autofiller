"""
HTTP boundary for the PDF autofill service.

This module handles request validation, auth, and response contracts.
Core PDF logic remains in reader/mapping/writer modules.
"""

import json
import logging
import os
import secrets
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import __version__
from .field_semantics import infer_field_semantics
from .mapping import map_user_data_to_fields, normalize_key
from .models import EnrichedFormField, FieldSemantics, FormField, TextRegion
from .pdf_reader import read_pdf
from .pdf_writer import UnresolvedRequiredFieldsError, fill_pdf

LOG_LEVEL_NAME = os.getenv("LOG_LEVEL", "INFO").upper()
API_AUTH_ENABLED = os.getenv("API_AUTH_ENABLED", "false").lower() == "true"
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN", "")
API_KEY_HEADER = os.getenv("API_KEY_HEADER", "X-API-Key")
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(5 * 1024 * 1024)))


def _resolve_log_level() -> int:
    """Resolve the configured log level without mutating global logging state."""
    level = getattr(logging, LOG_LEVEL_NAME, None)
    if not isinstance(level, int):
        level = logging.INFO
    return level


logger = logging.getLogger(__name__)
LOGGER_LEVEL = _resolve_log_level()
logger.setLevel(LOGGER_LEVEL)


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class VersionResponse(BaseModel):
    service: str
    version: str


def _api_error_payload(
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


def _api_error(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> HTTPException:
    # Centralize API error formatting so clients can rely on one contract
    # regardless of which endpoint raised the error.
    """Build a consistent API exception payload."""
    return HTTPException(
        status_code=status_code,
        detail=_api_error_payload(code=code, message=message, details=details),
    )


def _fallback_semantics(field: FormField) -> EnrichedFormField:
    """Build deterministic semantics from field name when inference is disabled/unavailable."""
    normalized = normalize_key(field.name)
    normalized = normalized.removeprefix("txt_")
    normalized = normalized.removeprefix("txt")
    semantic = normalized if normalized else "unknown_field"

    return EnrichedFormField(
        field=field,
        semantics=FieldSemantics(
            semantic_meaning=semantic,
            expected_data_type="string",
            confidence_score=0.5,
        ),
    )


def _page_context_by_number(text_regions: list[TextRegion]) -> dict[int, str]:
    """Group extracted page text so semantic inference can use local context."""
    grouped_regions: dict[int, list[str]] = {}
    for region in text_regions:
        grouped_regions.setdefault(region.page_number, []).append(region.text)
    return {
        page_number: "\n".join(chunks)
        for page_number, chunks in grouped_regions.items()
    }


def _enrich_fields(
    fields: list[FormField],
    *,
    use_semantic_inference: bool,
    page_context: dict[int, str] | None = None,
) -> list[EnrichedFormField]:
    """Enrich extracted fields with semantic inference or deterministic fallback."""
    enriched_fields: list[EnrichedFormField] = []

    for field in fields:
        context_text = page_context.get(field.page_number) if page_context else None
        if use_semantic_inference:
            try:
                enriched_fields.append(infer_field_semantics(field, context_text=context_text))
                continue
            except (RuntimeError, ValueError) as exc:
                logger.warning(
                    "Semantic inference failed for field '%s'; using deterministic fallback: %s",
                    field.name,
                    exc,
                )
        enriched_fields.append(_fallback_semantics(field))

    return enriched_fields


app = FastAPI(
    title="PDF Autofiller API",
    version=__version__,
    description=(
        "HTTP API for deterministic-first PDF form filling with optional semantic inference."
    ),
)


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Normalize FastAPI request validation errors to API contract."""
    del request
    return JSONResponse(
        status_code=422,
        content={
            "detail": _api_error_payload(
                code="request_validation_error",
                message="Request validation failed",
                details={"errors": exc.errors()},
            )
        },
    )


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    """Attach request ID and emit basic request logs."""
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request_id=%s method=%s path=%s status=%s duration_ms=%.2f",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


def _require_api_key(request: Request) -> None:
    """Validate API key auth when enabled."""
    if not API_AUTH_ENABLED:
        return

    if not API_AUTH_TOKEN:
        logger.error("API_AUTH_ENABLED is true but API_AUTH_TOKEN is not configured")
        raise _api_error(
            status_code=500,
            code="server_auth_config_error",
            message="Server authentication configuration error",
        )

    incoming_token = request.headers.get(API_KEY_HEADER)
    if incoming_token is None or not secrets.compare_digest(incoming_token, API_AUTH_TOKEN):
        raise _api_error(
            status_code=401,
            code="unauthorized",
            message="Unauthorized",
        )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="pdf-autofiller",
        version=__version__,
    )


@app.get("/version", response_model=VersionResponse)
def version() -> VersionResponse:
    return VersionResponse(service="pdf-autofiller", version=__version__)


@app.post("/fill")
async def fill(
    request: Request,
    pdf_file: UploadFile = File(...),
    user_data: str = Form(...),
    strict: bool = Form(True),
    allow_fallback_mapping: bool = Form(False),
    use_semantic_inference: bool = Form(False),
) -> FileResponse:
    """
    Fill a PDF form from uploaded file and user data.

    Args:
        request: FastAPI request object
        pdf_file: Uploaded PDF file
        user_data: JSON object encoded as form text
        strict: Disable fallback mapping when true
        allow_fallback_mapping: Enable fallback mapping for unmapped high-value fields
        use_semantic_inference: Enable semantic inference before mapping
    """
    temp_dir = None

    try:
        _require_api_key(request)

        if pdf_file.content_type not in ("application/pdf", "application/octet-stream"):
            raise _api_error(
                status_code=415,
                code="unsupported_media_type",
                message="Expected a PDF upload",
            )

        parsed_user_data: dict[str, Any] = json.loads(user_data)
        if not isinstance(parsed_user_data, dict):
            raise _api_error(
                status_code=422,
                code="invalid_user_data_type",
                message="user_data must be a JSON object",
            )

        temp_dir = tempfile.TemporaryDirectory(prefix="pdf-autofiller-")
        temp_path = Path(temp_dir.name)
        input_path = temp_path / "input.pdf"
        output_path = temp_path / "output_filled.pdf"

        # Read the upload once, then immediately enforce size/signature checks.
        # This keeps validation behavior deterministic before any PDF parsing.
        content = await pdf_file.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise _api_error(
                status_code=413,
                code="payload_too_large",
                message="PDF exceeds MAX_UPLOAD_BYTES limit",
                details={"max_upload_bytes": MAX_UPLOAD_BYTES},
            )
        if not content.startswith(b"%PDF-"):
            raise _api_error(
                status_code=415,
                code="invalid_pdf_signature",
                message="Uploaded file is not a valid PDF",
            )
        input_path.write_bytes(content)

        structure = read_pdf(input_path)
        enriched_fields = _enrich_fields(
            structure.form_fields,
            use_semantic_inference=use_semantic_inference,
            page_context=_page_context_by_number(structure.text_regions),
        )
        mapping_result = map_user_data_to_fields(
            enriched_fields,
            parsed_user_data,
            strict=strict,
            allow_fallback_mapping=allow_fallback_mapping,
        )

        fill_pdf(input_path, output_path, mapping_result)
        return FileResponse(
            path=output_path,
            media_type="application/pdf",
            filename=f"{Path(pdf_file.filename or 'filled').stem}_filled.pdf",
            background=BackgroundTask(temp_dir.cleanup),
        )
    except json.JSONDecodeError as exc:
        if temp_dir is not None:
            temp_dir.cleanup()
        raise _api_error(
            status_code=422,
            code="invalid_user_data_json",
            message="Invalid user_data JSON",
            details={"reason": str(exc)},
        ) from exc
    except UnresolvedRequiredFieldsError as exc:
        if temp_dir is not None:
            temp_dir.cleanup()
        raise _api_error(
            status_code=422,
            code="required_fields_unresolved",
            message="Required fields unresolved",
            details={
                "missing_fields": exc.missing_fields,
                "skipped_fields": exc.skipped_fields,
            },
        ) from exc
    except HTTPException:
        if temp_dir is not None:
            temp_dir.cleanup()
        raise
    except Exception as exc:
        if temp_dir is not None:
            temp_dir.cleanup()
        logger.exception("PDF fill request failed")
        raise _api_error(
            status_code=500,
            code="pdf_fill_failed",
            message="PDF fill failed",
        ) from exc
    finally:
        await pdf_file.close()


def run() -> None:
    """Run local API server."""
    import uvicorn

    if not logging.getLogger().handlers:
        logging.basicConfig(level=LOGGER_LEVEL)
    uvicorn.run(
        "pdf_autofiller.api_service:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level=logging.getLevelName(LOGGER_LEVEL).lower(),
    )

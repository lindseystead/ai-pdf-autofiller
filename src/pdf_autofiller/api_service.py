"""
HTTP boundary for the PDF autofill service.

This module owns request validation, authentication, and response contracts.
Core PDF logic remains in the reader/mapping/writer modules.

Security posture (this service accepts untrusted uploads from the public):
- Authentication on POST /fill is enabled by default and fails closed.
- Per-client rate limiting protects against request floods.
- Uploads are size-, signature-, and page-count-checked, and PDF parsing runs
  off the event loop under a wall-clock timeout to bound DoS from hostile PDFs.
- Temporary files are removed on every code path.
- A structured, PII-free audit line is emitted per fill.
See docs/AUDIT.md and docs/OPERATIONS.md for rationale and configuration.
"""

import asyncio
import json
import logging
import os
import secrets
import tempfile
import time
import uuid
from collections import defaultdict, deque
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
from .models import EnrichedFormField, FieldSemantics, FillReport, FormField, TextRegion
from .pdf_reader import PdfPageLimitError, read_pdf
from .pdf_writer import UnresolvedRequiredFieldsError, fill_pdf

LOG_LEVEL_NAME = os.getenv("LOG_LEVEL", "INFO").upper()
# Fail closed: authentication is enabled unless explicitly disabled. Operators
# running a trusted/local deployment can set API_AUTH_ENABLED=false.
API_AUTH_ENABLED = os.getenv("API_AUTH_ENABLED", "true").lower() == "true"
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN", "")
API_KEY_HEADER = os.getenv("API_KEY_HEADER", "X-API-Key")
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(5 * 1024 * 1024)))
# Reject obviously oversized documents before extraction (cheap DoS guard).
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "200"))
# Wall-clock budget for PDF parsing/extraction, the main CPU/memory DoS vector.
PDF_READ_TIMEOUT_SECONDS = float(os.getenv("PDF_READ_TIMEOUT_SECONDS", "20"))
# Per-client request budget for POST /fill. Set to 0 to disable.
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))


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


def _safe_header_value(field_names: list[str]) -> str:
    """Render field names as an ASCII-safe, comma-separated HTTP header value."""
    joined = ",".join(field_names)
    return joined.encode("ascii", "ignore").decode("ascii")


def _fill_report_headers(report: FillReport) -> dict[str, str]:
    """Expose fill outcome via response headers.

    Lets clients detect non-required fields that were dropped (for example,
    flagged for review) instead of receiving a silently incomplete PDF.
    """
    return {
        "X-PDF-Fields-Written": str(len(report.written_fields)),
        "X-PDF-Fields-Skipped-Review": _safe_header_value(report.skipped_review_fields),
        "X-PDF-Fields-Skipped-Empty": _safe_header_value(report.skipped_empty_fields),
    }


def _audit_log_fill(
    request: Request,
    *,
    fields_total: int,
    report: FillReport,
    missing_required: int,
    use_semantic_inference: bool,
    allow_fallback_mapping: bool,
) -> None:
    """Emit a structured, PII-free audit record for a completed fill.

    This is the application-level audit trail. It deliberately records only
    counts, request identity, and which optional features ran — never field
    names or user values — so the line is safe to ship to a central log store.
    Persistent retention/storage is a deployment responsibility (see
    docs/OPERATIONS.md).
    """
    request_id = getattr(request.state, "request_id", "unknown")
    logger.info(
        "audit action=fill request_id=%s auth=%s fields_total=%d fields_written=%d "
        "fields_review_skipped=%d fields_empty_skipped=%d missing_required=%d "
        "semantic_inference=%s fallback_mapping=%s",
        request_id,
        "enabled" if API_AUTH_ENABLED else "disabled",
        fields_total,
        len(report.written_fields),
        len(report.skipped_review_fields),
        len(report.skipped_empty_fields),
        missing_required,
        use_semantic_inference,
        allow_fallback_mapping,
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


# Per-client request timestamps for the sliding-window rate limiter. This is an
# in-process guard suitable for a single worker; multi-worker deployments should
# add a shared limiter (e.g. at the ingress/proxy layer).
_rate_limit_state: dict[str, deque[float]] = defaultdict(deque)


def _reset_rate_limit_state() -> None:
    """Clear rate-limiter state (used by tests)."""
    _rate_limit_state.clear()


def _enforce_rate_limit(request: Request) -> None:
    """Apply a per-client sliding-window rate limit, if enabled."""
    if RATE_LIMIT_PER_MINUTE <= 0:
        return

    client_host = request.client.host if request.client else "unknown"
    now = time.monotonic()
    window = _rate_limit_state[client_host]
    # Drop timestamps older than the 60s window.
    while window and now - window[0] >= 60.0:
        window.popleft()

    if len(window) >= RATE_LIMIT_PER_MINUTE:
        raise _api_error(
            status_code=429,
            code="rate_limited",
            message="Too many requests",
            details={"limit_per_minute": RATE_LIMIT_PER_MINUTE},
        )

    window.append(now)


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
    # The FileResponse streams the output and cleans up the temp dir via a
    # BackgroundTask. On every other path we must clean up here, so track whether
    # ownership of the temp dir was handed off to a successful response.
    response_started = False

    try:
        _enforce_rate_limit(request)
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

        # Parse/extract off the event loop with a wall-clock budget. Extraction is
        # the main CPU/memory cost and the primary DoS vector for hostile PDFs.
        try:
            structure = await asyncio.wait_for(
                asyncio.to_thread(read_pdf, input_path, max_pages=MAX_PDF_PAGES),
                timeout=PDF_READ_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            raise _api_error(
                status_code=503,
                code="pdf_processing_timeout",
                message="PDF processing exceeded the time limit",
                details={"timeout_seconds": PDF_READ_TIMEOUT_SECONDS},
            ) from exc
        except PdfPageLimitError as exc:
            raise _api_error(
                status_code=413,
                code="pdf_too_many_pages",
                message="PDF exceeds the maximum allowed page count",
                details={"max_pages": exc.max_pages, "num_pages": exc.num_pages},
            ) from exc

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

        fill_report = fill_pdf(input_path, output_path, mapping_result)
        _audit_log_fill(
            request,
            fields_total=len(enriched_fields),
            report=fill_report,
            missing_required=len(mapping_result.missing_required),
            use_semantic_inference=use_semantic_inference,
            allow_fallback_mapping=allow_fallback_mapping,
        )
        response = FileResponse(
            path=output_path,
            media_type="application/pdf",
            filename=f"{Path(pdf_file.filename or 'filled').stem}_filled.pdf",
            headers=_fill_report_headers(fill_report),
            background=BackgroundTask(temp_dir.cleanup),
        )
        response_started = True
        return response
    except json.JSONDecodeError as exc:
        raise _api_error(
            status_code=422,
            code="invalid_user_data_json",
            message="Invalid user_data JSON",
            details={"reason": str(exc)},
        ) from exc
    except UnresolvedRequiredFieldsError as exc:
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
        raise
    except Exception as exc:
        logger.exception("PDF fill request failed")
        raise _api_error(
            status_code=500,
            code="pdf_fill_failed",
            message="PDF fill failed",
        ) from exc
    finally:
        # Clean up unless a successful response took ownership of the temp dir.
        if temp_dir is not None and not response_started:
            temp_dir.cleanup()
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

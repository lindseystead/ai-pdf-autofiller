"""
HTTP boundary for the PDF autofill service.

This module owns request validation, authentication, and response contracts.
Core PDF logic remains in the reader/mapping/writer modules.

Security posture (this service accepts untrusted uploads from the public):
- Authentication on POST /fill, /preview, and /inspect is enabled by default and fails closed.
- Per-client rate limiting protects against request floods.
- Uploads are size-, signature-, and page-count-checked, and PDF parsing runs
  off the event loop under a wall-clock timeout to bound DoS from hostile PDFs.
- Temporary files are removed on every code path.
- A structured, PII-free audit line is emitted per fill.
See docs/OPERATIONS.md for rationale and configuration.
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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from . import __version__
from .mapping import alias_pack_status
from .models import FillReport
from .pdf_reader import PdfPageLimitError, read_pdf
from .pdf_writer import UnresolvedRequiredFieldsError
from .pipeline import (
    enrich_fields,
    page_context_by_number,
    run_fill_pipeline,
    run_preview_pipeline,
)
from .playground import PLAYGROUND_HTML

LOG_LEVEL_NAME = os.getenv("LOG_LEVEL", "INFO").upper()
# Optional structured JSON logs for aggregators (LOG_FORMAT=json).
LOG_FORMAT = os.getenv("LOG_FORMAT", "text").lower()
# Fail closed: authentication is enabled unless explicitly disabled. Operators
# running a trusted/local deployment can set API_AUTH_ENABLED=false.
API_AUTH_ENABLED = os.getenv("API_AUTH_ENABLED", "true").lower() == "true"
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN", "")
API_KEY_HEADER = os.getenv("API_KEY_HEADER", "X-API-Key")
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(5 * 1024 * 1024)))
# Reject obviously oversized documents before extraction (cheap DoS guard).
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "200"))
# Wall-clock budget for full pipeline processing on /fill, /preview, and /inspect
# (not only PDF parsing — covers enrich/map/write as well).
PDF_READ_TIMEOUT_SECONDS = float(os.getenv("PDF_READ_TIMEOUT_SECONDS", "20"))
# Per-client request budget for POST /fill, /preview, and /inspect. Set to 0 to disable.
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
# Trust X-Forwarded-For for per-client rate limiting behind a reverse proxy.
TRUST_PROXY_HEADERS = os.getenv("TRUST_PROXY_HEADERS", "false").lower() == "true"
UPLOAD_CHUNK_BYTES = 64 * 1024


class _JsonLogFormatter(logging.Formatter):
    """Emit one JSON object per log line (no PII beyond the message text)."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "time": self.formatTime(record, self.datefmt),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


def _configure_logging() -> None:
    """Apply text or JSON logging based on LOG_FORMAT."""
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        if LOG_FORMAT == "json":
            handler.setFormatter(_JsonLogFormatter())
        else:
            handler.setFormatter(
                logging.Formatter("%(levelname)s:%(name)s:%(message)s")
            )
        root.addHandler(handler)
    root.setLevel(_resolve_log_level())

# Prefer packaged samples next to the install, then repo-root samples/ for local dev.
_PACKAGE_ROOT = Path(__file__).resolve().parent
_REPO_ROOT = _PACKAGE_ROOT.parents[1]
_SAMPLE_CANDIDATES = (
    _REPO_ROOT / "samples" / "sample_form.pdf",
    Path("/app/samples/sample_form.pdf"),
)

def _resolve_log_level() -> int:
    """Resolve the configured log level without mutating global logging state."""
    level = getattr(logging, LOG_LEVEL_NAME, None)
    if not isinstance(level, int):
        level = logging.INFO
    return level


LOGGER_LEVEL = _resolve_log_level()
logger = logging.getLogger(__name__)
logger.setLevel(LOGGER_LEVEL)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach baseline security headers without breaking the playground HTML."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    checks: dict[str, str] = {}


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
    headers: dict[str, str] | None = None,
) -> HTTPException:
    """Build a consistent API exception payload."""
    # Centralize API error formatting so clients can rely on one contract
    # regardless of which endpoint raised the error.
    return HTTPException(
        status_code=status_code,
        detail=_api_error_payload(code=code, message=message, details=details),
        headers=headers,
    )


def _fallback_semantics(field):
    """Backward-compatible wrapper for tests importing the helper."""
    from .pipeline import fallback_semantics

    return fallback_semantics(field)


def _page_context_by_number(text_regions):
    """Backward-compatible wrapper for tests importing the helper."""
    return page_context_by_number(text_regions)


def _enrich_fields(fields, *, use_semantic_inference, page_context=None):
    """Backward-compatible wrapper for tests importing the helper."""
    return enrich_fields(
        fields,
        use_semantic_inference=use_semantic_inference,
        page_context=page_context,
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


app = FastAPI(
    title="PDF Autofiller API",
    version=__version__,
    description=(
        "HTTP API for deterministic-first PDF form filling with optional semantic inference."
    ),
)
app.add_middleware(SecurityHeadersMiddleware)


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


def _client_identifier(request: Request) -> str:
    """Resolve the client key used for rate limiting."""
    if TRUST_PROXY_HEADERS:
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


def _enforce_rate_limit(request: Request) -> None:
    """Apply a per-client sliding-window rate limit, if enabled."""
    if RATE_LIMIT_PER_MINUTE <= 0:
        return

    client_host = _client_identifier(request)
    now = time.monotonic()
    _purge_stale_rate_limit_clients(now)
    window = _rate_limit_state[client_host]
    while window and now - window[0] >= 60.0:
        window.popleft()

    if len(window) >= RATE_LIMIT_PER_MINUTE:
        raise _api_error(
            status_code=429,
            code="rate_limited",
            message="Too many requests",
            details={"limit_per_minute": RATE_LIMIT_PER_MINUTE},
            headers={"Retry-After": "60"},
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


@app.get("/")
def root() -> RedirectResponse:
    """Redirect browsers to the interactive playground."""
    return RedirectResponse(url="/playground")


@app.get("/playground", response_class=HTMLResponse)
def playground_page() -> HTMLResponse:
    """Serve the browser playground for trying fills without curl."""
    return HTMLResponse(content=PLAYGROUND_HTML)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    checks = {
        "auth": (
            "enabled"
            if API_AUTH_ENABLED and API_AUTH_TOKEN
            else "disabled" if not API_AUTH_ENABLED else "misconfigured"
        ),
        **alias_pack_status(),
    }
    status = "ok" if checks["auth"] != "misconfigured" else "degraded"
    return HealthResponse(
        status=status,
        service="pdf-autofiller",
        version=__version__,
        checks=checks,
    )


@app.get("/version", response_model=VersionResponse)
def version() -> VersionResponse:
    return VersionResponse(service="pdf-autofiller", version=__version__)


def _sample_form_path() -> Path | None:
    for candidate in _SAMPLE_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


@app.get("/samples/sample_form.pdf")
def sample_form_pdf() -> FileResponse:
    """Serve the bundled sample AcroForm for playground one-click demos."""
    sample = _sample_form_path()
    if sample is None:
        raise _api_error(
            status_code=404,
            code="sample_not_found",
            message="Sample PDF is not bundled in this deployment",
        )
    return FileResponse(
        path=sample,
        media_type="application/pdf",
        filename="sample_form.pdf",
    )


class InspectField(BaseModel):
    name: str
    field_type: str
    required: bool
    page_number: int
    current_value: str | None = None


class InspectResponse(BaseModel):
    pages: int
    field_count: int
    fields: list[InspectField]


class PreviewDecision(BaseModel):
    field_name: str
    semantic_meaning: str
    selected_value: str | None = None
    confidence: float
    reason: str
    requires_review: bool = False


class PreviewResponse(BaseModel):
    pages: int
    field_count: int
    decisions: list[PreviewDecision]
    missing_required: list[str]
    unmapped_user_keys: list[str]


@app.post("/inspect", response_model=InspectResponse)
async def inspect_pdf(
    request: Request,
    pdf_file: UploadFile = File(...),
) -> InspectResponse:
    """List AcroForm fields so clients can draft matching JSON without guessing."""
    temp_dir = None
    try:
        _require_api_key(request)
        _enforce_rate_limit(request)

        if pdf_file.content_type not in ("application/pdf", "application/octet-stream"):
            raise _api_error(
                status_code=415,
                code="unsupported_media_type",
                message="Expected a PDF upload",
            )

        content = await _read_bounded_upload(pdf_file, MAX_UPLOAD_BYTES)
        if not content.startswith(b"%PDF-"):
            raise _api_error(
                status_code=415,
                code="invalid_pdf_signature",
                message="Uploaded file is not a valid PDF",
            )

        temp_dir = tempfile.TemporaryDirectory(prefix="pdf-autofiller-inspect-")
        input_path = Path(temp_dir.name) / "input.pdf"
        input_path.write_bytes(content)

        try:
            structure = await asyncio.wait_for(
                asyncio.to_thread(lambda: read_pdf(input_path, max_pages=MAX_PDF_PAGES)),
                timeout=PDF_READ_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
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

        fields = [
            InspectField(
                name=field.name,
                field_type=field.field_type,
                required=field.required,
                page_number=field.page_number,
                current_value=field.value,
            )
            for field in structure.form_fields
        ]
        return InspectResponse(
            pages=structure.metadata.num_pages,
            field_count=len(fields),
            fields=fields,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("PDF inspect request failed")
        raise _api_error(
            status_code=500,
            code="pdf_inspect_failed",
            message="PDF inspect failed",
        ) from exc
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()
        await pdf_file.close()


@app.post("/preview", response_model=PreviewResponse)
async def preview_pdf(
    request: Request,
    pdf_file: UploadFile = File(...),
    user_data: str = Form(...),
    strict: bool = Form(True),
    allow_fallback_mapping: bool = Form(False),
    use_semantic_inference: bool = Form(False),
) -> PreviewResponse:
    """Return mapping decisions without writing a PDF (inspect → map debug loop)."""
    temp_dir = None
    try:
        _require_api_key(request)
        _enforce_rate_limit(request)

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

        content = await _read_bounded_upload(pdf_file, MAX_UPLOAD_BYTES)
        if not content.startswith(b"%PDF-"):
            raise _api_error(
                status_code=415,
                code="invalid_pdf_signature",
                message="Uploaded file is not a valid PDF",
            )

        temp_dir = tempfile.TemporaryDirectory(prefix="pdf-autofiller-preview-")
        input_path = Path(temp_dir.name) / "input.pdf"
        input_path.write_bytes(content)

        try:
            mapping_result, field_count, page_count = await asyncio.wait_for(
                asyncio.to_thread(
                    run_preview_pipeline,
                    input_path,
                    parsed_user_data,
                    strict=strict,
                    allow_fallback_mapping=allow_fallback_mapping,
                    use_semantic_inference=use_semantic_inference,
                    max_pages=MAX_PDF_PAGES,
                ),
                timeout=PDF_READ_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
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

        decisions = [
            PreviewDecision(
                field_name=d.field_name,
                semantic_meaning=d.semantic_meaning,
                selected_value=d.selected_value,
                confidence=d.confidence,
                reason=d.reason,
                requires_review=d.requires_review,
            )
            for d in mapping_result.decisions
        ]
        return PreviewResponse(
            pages=page_count,
            field_count=field_count,
            decisions=decisions,
            missing_required=list(mapping_result.missing_required),
            unmapped_user_keys=list(mapping_result.unmapped_user_keys),
        )
    except json.JSONDecodeError as exc:
        raise _api_error(
            status_code=422,
            code="invalid_user_data_json",
            message="Invalid user_data JSON",
            details={"reason": str(exc)},
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("PDF preview request failed")
        raise _api_error(
            status_code=500,
            code="pdf_preview_failed",
            message="PDF preview failed",
        ) from exc
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()
        await pdf_file.close()


@app.post(
    "/fill",
    responses={
        200: {
            "content": {"application/pdf": {}},
            "description": "Filled PDF binary",
        }
    },
)
async def fill(
    request: Request,
    pdf_file: UploadFile = File(...),
    user_data: str = Form(...),
    strict: bool = Form(True),
    allow_fallback_mapping: bool = Form(False),
    use_semantic_inference: bool = Form(False),
    flatten: bool = Form(False),
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
        flatten: Burn field values into page content and remove widget annotations
    """
    temp_dir = None
    # The FileResponse streams the output and cleans up the temp dir via a
    # BackgroundTask. On every other path we must clean up here, so track whether
    # ownership of the temp dir was handed off to a successful response.
    response_started = False

    try:
        # Authenticate before counting against the rate-limit budget so
        # unauthenticated scans cannot exhaust a client's quota.
        _require_api_key(request)
        _enforce_rate_limit(request)

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

        content = await _read_bounded_upload(pdf_file, MAX_UPLOAD_BYTES)
        if not content.startswith(b"%PDF-"):
            raise _api_error(
                status_code=415,
                code="invalid_pdf_signature",
                message="Uploaded file is not a valid PDF",
            )
        input_path.write_bytes(content)

        try:
            fill_report, mapping_result, fields_total = await asyncio.wait_for(
                asyncio.to_thread(
                    run_fill_pipeline,
                    input_path,
                    output_path,
                    parsed_user_data,
                    strict=strict,
                    allow_fallback_mapping=allow_fallback_mapping,
                    use_semantic_inference=use_semantic_inference,
                    max_pages=MAX_PDF_PAGES,
                    flatten=flatten,
                ),
                timeout=PDF_READ_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
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

        _audit_log_fill(
            request,
            fields_total=fields_total,
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

    _configure_logging()
    uvicorn.run(
        "pdf_autofiller.api_service:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level=logging.getLevelName(LOGGER_LEVEL).lower(),
    )
